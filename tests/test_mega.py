"""MEGA key parsing, node lookups against a scripted fake API, and decryption with MAC checks."""

from __future__ import annotations

import base64
import os

import pytest
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from downloader.providers import default_registry, mega
from downloader.providers.base import FileRef, LinkContext, ProviderError

EXAMPLE = "https://mega.nz/file/C1ZESCBI#jqGukumcAMamH_xx-wixpcafBTBUP9M6Io02akC9ZmE"
EXAMPLE_AT = ("FG0qDWjj1w5EA643_QBJoF6LO6Od7MrIgq0zjSriJ84Cwj8Rez_7Sp3D1qL7y6NxSE-lr4aSsCcbxS970Cup"
              "jKcK_tCh8YFkpsC8Gp8_jJI")


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def aes_block(key: bytes, block: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def chunk_sizes(size: int) -> list[int]:
    sizes, step, at = [], 0x20000, 0
    while at + step < size:
        sizes.append(step)
        at += step
        step = min(step + 0x20000, 0x100000)
    sizes.append(size - at)
    return sizes


def reference_encrypt(plain: bytes, aes_key: bytes, nonce: bytes) -> tuple[bytes, bytes]:
    """Encrypt `plain` the way MEGA does, one block at a time; return (ciphertext, meta_mac)."""
    blocks = len(plain) // 16 + 1
    counters = b"".join(nonce + i.to_bytes(8, "big") for i in range(blocks))
    stream = Cipher(algorithms.AES(aes_key), modes.ECB()).encryptor().update(counters)
    cipher = xor(plain, stream)
    file_mac, at = bytes(16), 0
    for size in chunk_sizes(len(plain)):
        chunk = plain[at:at + size]
        at += size
        chunk += bytes(-len(chunk) % 16)
        mac = nonce + nonce
        for i in range(0, len(chunk), 16):
            mac = aes_block(aes_key, xor(mac, chunk[i:i + 16]))
        file_mac = aes_block(aes_key, xor(file_mac, mac))
    return cipher, xor(file_mac[0:4], file_mac[4:8]) + xor(file_mac[8:12], file_mac[12:16])


def link_for(aes_key: bytes, nonce: bytes, meta_mac: bytes) -> str:
    tail = nonce + meta_mac
    return f"https://mega.nz/file/AbCd_-12#{b64(xor(aes_key, tail) + tail)}"


def decode(link: str, cipher: bytes, step: int) -> bytes:
    decoder = mega.MegaProvider().decoder(FileRef(link, "AbCd_-12"))
    out = b"".join(decoder.update(cipher[i:i + step]) for i in range(0, len(cipher), step))
    decoder.finish()
    return out


@pytest.mark.parametrize("size,step", [
    (1, 1), (15, 4), (16, 16), (17, 5), (0x20000 - 1, 4093), (0x20000, 0x20000), (0x20000 + 1, 7777),
    (5 * 1024 * 1024 + 3, 1024 * 1024),
])
def test_decoder_matches_the_reference(size, step):
    plain, aes_key, nonce = os.urandom(size), os.urandom(16), os.urandom(8)
    cipher, meta_mac = reference_encrypt(plain, aes_key, nonce)
    assert decode(link_for(aes_key, nonce, meta_mac), cipher, step) == plain


def test_decoder_rejects_a_changed_byte_or_a_wrong_mac():
    plain, aes_key, nonce = os.urandom(300_000), os.urandom(16), os.urandom(8)
    cipher, meta_mac = reference_encrypt(plain, aes_key, nonce)
    flipped = bytearray(cipher)
    flipped[200_000] ^= 1
    for link, data in [(link_for(aes_key, nonce, meta_mac), bytes(flipped)),
                       (link_for(aes_key, nonce, xor(meta_mac, b"\1" * 8)), cipher)]:
        with pytest.raises(ProviderError) as info:
            decode(link, data, 65536)
        assert info.value.code == "integrity_failed"


@pytest.mark.parametrize("url", [
    EXAMPLE,
    "https://mega.nz/#!C1ZESCBI!jqGukumcAMamH_xx-wixpcafBTBUP9M6Io02akC9ZmE",
])
def test_both_link_forms_resolve_to_the_same_handle_and_key(url):
    provider, ref = default_registry().resolve(url)
    assert provider.name == "mega" and ref.file_id == "C1ZESCBI"
    assert mega.parse_key(ref.url) == mega.parse_key(EXAMPLE)


class FakeApi:
    """Answers `cs` posts with scripted replies and records the commands."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.commands = []

    def post(self, url, params=None, json=None, timeout=None):
        assert url == mega.API_URL
        self.commands.append(json[0])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply

        class Reply:
            def json(self):
                return reply

        return Reply()


@pytest.fixture
def api(monkeypatch):
    def install(*replies):
        fake = FakeApi(*replies)
        monkeypatch.setattr(mega.requests, "post", fake.post)
        return fake
    return install


def example_ref() -> FileRef:
    return default_registry().resolve(EXAMPLE)[1]


def test_get_info_decrypts_the_name(api):
    fake = api([{"s": 6588195, "at": EXAMPLE_AT}])
    info = mega.MegaProvider().get_info(example_ref())
    assert (info.name, info.size) == ("OriDE_CHT_MOD_v1.0.exe", 6588195)
    assert fake.commands == [{"a": "g", "p": "C1ZESCBI", "ssl": 2}]


def test_a_wrong_key_is_an_invalid_url(api):
    api([{"s": 10, "at": EXAMPLE_AT}])
    ref = FileRef("https://mega.nz/file/C1ZESCBI#" + "A" * 43, "C1ZESCBI")
    with pytest.raises(ProviderError) as info:
        mega.MegaProvider().get_info(ref)
    assert (info.value.code, info.value.key) == ("invalid_url", "errors.invalid_url_key")


@pytest.mark.parametrize("reply,code", [
    ([-9], "not_found"), ([-16], "not_found"), (-2, "not_found"), ([-17], "quota_exceeded"),
    ([-3], "upstream_error"), (["odd"], "upstream_error"), (requests.ConnectionError(), "upstream_error"),
])
def test_api_errors_map_to_codes(api, reply, code):
    api(reply)
    with pytest.raises(ProviderError) as info:
        mega.MegaProvider().get_info(example_ref())
    assert info.value.code == code


def test_generate_links_hands_out_the_url_per_connection(api):
    fake = api([{"s": 1, "at": EXAMPLE_AT, "g": "https://gfs.example.test/dl/x"}])
    statuses = []
    ctx = LinkContext(solve_captcha=lambda image, spec: None,
                      set_status=lambda phase, key, **params: statuses.append((phase, key)), proxies=None)
    links = mega.MegaProvider().generate_links(example_ref(), 4, ctx)
    assert links == ["https://gfs.example.test/dl/x"] * 4
    assert fake.commands[0]["g"] == 1 and statuses == [("links", "messages.links_generated")]


def test_a_node_without_a_download_url_has_no_links(api):
    api([{"s": 1, "at": EXAMPLE_AT}])
    ctx = LinkContext(solve_captcha=lambda image, spec: None,
                      set_status=lambda *args, **params: None, proxies=None)
    with pytest.raises(ProviderError) as info:
        mega.MegaProvider().generate_links(example_ref(), 2, ctx)
    assert info.value.key == "errors.upstream_error_no_links"
