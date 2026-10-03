"""MEGA (mega.nz) provider for public file links, driven through the public `cs` API."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from itertools import count as counter

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .base import PHASE_LINKS, Decoder, FileInfo, FileRef, LinkContext, Provider, ProviderError

log = logging.getLogger(__name__)

API_URL = "https://g.api.mega.co.nz/cs"
HOSTS = r"(?:www\.)?mega\.(?:nz|co\.nz)"
HANDLE = r"([A-Za-z0-9_-]{8})"
KEY = r"[A-Za-z0-9_-]{43}"
FILE_PATTERN = rf"^https?://{HOSTS}/file/{HANDLE}#{KEY}$"
LEGACY_PATTERN = rf"^https?://{HOSTS}/#!{HANDLE}!{KEY}$"
NOT_FOUND = {-2, -9, -11, -16}
OVER_QUOTA = -17
FIRST_CHUNK = 0x20000
MAX_CHUNK = 0x100000

_sequence = counter(1)


def b64_decode(text: str) -> bytes:
    """Decode MEGA's unpadded base64url."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_key(url: str) -> tuple[bytes, bytes, bytes]:
    """Return (aes_key, nonce, meta_mac) from the 256-bit key at the end of a file link.

    - The link key is 32 bytes: the AES key is its two halves XORed, the nonce is bytes
      16 to 24 and the expected condensed MAC is bytes 24 to 32.
    """
    found = re.search(rf"[#!]({KEY})$", url)
    if not found:
        raise ProviderError("invalid_url", "errors.invalid_url_key")
    raw = b64_decode(found.group(1))
    if len(raw) != 32:
        raise ProviderError("invalid_url", "errors.invalid_url_key")
    aes_key = bytes(a ^ b for a, b in zip(raw[:16], raw[16:]))
    return aes_key, raw[16:24], raw[24:32]


def decrypt_attributes(data: bytes, aes_key: bytes) -> dict:
    """Decrypt a node's `at` blob, AES-CBC with a zero IV, into its attribute object.

    - Raises ValueError when the plaintext is not `MEGA{...}`, which means a wrong key.
    """
    if not data or len(data) % 16:
        raise ValueError("attribute length")
    decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(bytes(16))).decryptor()
    plain = (decryptor.update(data) + decryptor.finalize()).rstrip(b"\0")
    if not plain.startswith(b"MEGA{"):
        raise ValueError("attribute prefix")
    attributes = json.loads(plain[4:].decode("utf-8"))
    if not isinstance(attributes, dict):
        raise ValueError("attribute shape")
    return attributes


class MegaDecoder(Decoder):
    """Decrypts a MEGA file and checks its MAC while the parts are assembled in order.

    - Content is AES-128-CTR with the counter starting at `nonce` followed by eight zero bytes.
    - Integrity is a CBC-MAC per chunk over the plaintext, with IV `nonce + nonce` and the last
      block zero padded. Chunks are 128 KiB, 256 KiB and so on up to 1 MiB, then 1 MiB each.
    - The chunk MACs are chained through AES-CBC from a zero IV; the result, condensed to
      8 bytes by XORing 32-bit words pairwise, must equal `meta_mac`.
    """

    def __init__(self, aes_key: bytes, nonce: bytes, meta_mac: bytes):
        self._aes = algorithms.AES(aes_key)
        self._nonce = nonce
        self._meta_mac = meta_mac
        self._ctr = Cipher(self._aes, modes.CTR(nonce + bytes(8))).decryptor()
        self._file_mac = Cipher(self._aes, modes.CBC(bytes(16))).encryptor()
        self._last_file_block = bytes(16)
        self._chunk_size = FIRST_CHUNK
        self._chunk_left = FIRST_CHUNK
        self._chunk_fed = 0
        self._chunk_mac = self._new_chunk_mac()
        self._last_chunk_block = b""

    def _new_chunk_mac(self):
        """A CBC encryptor whose last output block is the MAC of one chunk."""
        return Cipher(self._aes, modes.CBC(self._nonce + self._nonce)).encryptor()

    def _feed_chunk(self, data: bytes) -> None:
        """Feed plaintext of the current chunk into its MAC, keeping the last output block."""
        out = self._chunk_mac.update(data)
        self._chunk_fed += len(data)
        if out:
            self._last_chunk_block = out[-16:]

    def _close_chunk(self) -> None:
        """Pad the current chunk to a block, fold its MAC into the file MAC, and start the next."""
        pad = -self._chunk_fed % 16
        if pad:
            self._feed_chunk(bytes(pad))
        self._chunk_mac.finalize()
        out = self._file_mac.update(self._last_chunk_block)
        self._last_file_block = out[-16:]
        if self._chunk_size < MAX_CHUNK:
            self._chunk_size += FIRST_CHUNK
        self._chunk_left = self._chunk_size
        self._chunk_fed = 0
        self._chunk_mac = self._new_chunk_mac()
        self._last_chunk_block = b""

    def update(self, data: bytes) -> bytes:
        """Decrypt `data` and feed the plaintext into the chunk MACs."""
        plain = self._ctr.update(data)
        view = memoryview(plain)
        while view:
            take = min(len(view), self._chunk_left)
            self._feed_chunk(bytes(view[:take]))
            self._chunk_left -= take
            view = view[take:]
            if self._chunk_left == 0:
                self._close_chunk()
        return plain

    def finish(self) -> None:
        """Close the last chunk and compare the condensed file MAC with the link's."""
        if self._chunk_fed:
            self._close_chunk()
        mac = self._last_file_block
        condensed = bytes(mac[i] ^ mac[i + 4] for i in range(4)) + bytes(mac[i + 8] ^ mac[i + 12] for i in range(4))
        if condensed != self._meta_mac:
            raise ProviderError("integrity_failed")


class MegaProvider(Provider):
    """Public MEGA file links, `/file/<handle>#<key>` and the older `/#!<handle>!<key>`.

    - The key travels in the URL fragment and never reaches MEGA; it decrypts the name here
      and the content in `MegaDecoder`.
    - One download URL serves HTTP Range requests over many connections, so it is handed to
      the engine once per connection.
    """

    name = "mega"
    label = "MEGA"
    icon = "mega"
    patterns = (FILE_PATTERN, LEGACY_PATTERN)
    link_ttl = 3600

    def _node(self, ref: FileRef, download: bool) -> dict:
        """Ask the API for a public node; map MEGA's negative error numbers to error codes."""
        command = {"a": "g", "p": ref.file_id, "ssl": 2}
        if download:
            command["g"] = 1
        try:
            reply = requests.post(API_URL, params={"id": next(_sequence)}, json=[command], timeout=15).json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("mega node request failed: %s", exc)
            raise ProviderError("upstream_error", provider=self.label) from exc
        node = reply[0] if isinstance(reply, list) and reply else reply
        if isinstance(node, int):
            log.info("mega node %s: error %s", ref.file_id, node)
            if node in NOT_FOUND:
                raise ProviderError("not_found")
            if node == OVER_QUOTA:
                raise ProviderError("quota_exceeded", provider=self.label)
            raise ProviderError("upstream_error", provider=self.label)
        if not isinstance(node, dict):
            raise ProviderError("upstream_error", provider=self.label)
        return node

    def get_info(self, ref: FileRef) -> FileInfo:
        """Read size `s` and decrypt the name from the attributes `at`."""
        aes_key, _, _ = parse_key(ref.url)
        node = self._node(ref, download=False)
        try:
            attributes = decrypt_attributes(b64_decode(str(node.get("at", ""))), aes_key)
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise ProviderError("invalid_url", "errors.invalid_url_key") from exc
        try:
            size = int(node["s"]) if node.get("s") else None
        except (TypeError, ValueError):
            size = None
        return FileInfo(name=str(attributes.get("n") or ref.file_id), size=size)

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Return the node's download URL once per connection."""
        ctx.check_cancelled()
        node = self._node(ref, download=True)
        url = node.get("g")
        if not isinstance(url, str) or not url.startswith("http"):
            raise ProviderError("upstream_error", "errors.upstream_error_no_links")
        ctx.set_status(PHASE_LINKS, "messages.links_generated", done=count, count=count)
        return [url] * count

    def decoder(self, ref: FileRef) -> Decoder:
        """A `MegaDecoder` for the key in the link."""
        return MegaDecoder(*parse_key(ref.url))
