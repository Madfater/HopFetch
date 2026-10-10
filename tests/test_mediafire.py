"""MediaFire info, page parsing and error mapping against a scripted fake site, and the SHA-256
check while assembling."""

from __future__ import annotations

import base64
import hashlib

import pytest
import requests

from downloader.providers import default_registry, mediafire
from downloader.providers.base import FileRef, LinkContext, ProviderError

EXAMPLE = "https://www.mediafire.com/file/ipnyzofjcwri357/test-10mb.bin/file"
DIRECT = ("https://download1514.mediafire.com/3gg3kqsc1vegM9QoPf82XNVUCEWNBq3v5JGF_sCVxnkQBYMz8ga/"
          "ipnyzofjcwri357/test-10mb.bin")
CONTENT = b"mediafire test bytes" * 100


def file_info(**overrides) -> dict:
    info = {"quickkey": "ipnyzofjcwri357", "filename": "test-10mb.bin", "size": "10485760",
            "privacy": "public", "password_protected": "no",
            "hash": hashlib.sha256(CONTENT).hexdigest()}
    info.update(overrides)
    return {"response": {"action": "file/get_info", "file_info": info, "result": "Success"}}


API_INVALID = {"response": {"action": "file/get_info", "message": "Unknown or Invalid QuickKey",
                            "error": 110, "result": "Error"}}


def download_page(button: str) -> str:
    return ('<html><head><title>test-10mb</title></head><body><div class="download_link">'
            '<a class="preparing" href="#"><span>Preparing Download</span></a>'
            f'{button}<a class="retry" href="https://www.mediafire.com/download_repair.php?qkey=x">'
            'Repair</a></div></body></html>')


PAGE = download_page(f'<a class="input popsok"\n   aria-label="Download file"\n   href="{DIRECT}"'
                     '   id="downloadButton"\n   rel="nofollow">Download (10MB)</a>')


class Reply:
    """A `requests` response with a scripted final URL, status and body."""

    def __init__(self, body="", status=200, url="https://www.mediafire.com/file/ipnyzofjcwri357"):
        self.body = body
        self.status_code = status
        self.url = url

    @property
    def text(self) -> str:
        return self.body if isinstance(self.body, str) else ""

    def json(self):
        if isinstance(self.body, str):
            raise ValueError("not json")
        return self.body


class FakeSite:
    """Answers the API and the file page with scripted replies, recording each request."""

    def __init__(self, api=None, page=None):
        self.api = api
        self.page = page
        self.requests = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append((url, params))
        reply = self.api if url == mediafire.API_URL else self.page
        assert reply is not None, url
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, Reply) else Reply(reply)


@pytest.fixture
def site(monkeypatch):
    def install(api=None, page=None):
        fake = FakeSite(api, page)
        monkeypatch.setattr(mediafire.requests, "get", fake.get)
        return fake
    return install


def example_ref() -> FileRef:
    return default_registry().resolve(EXAMPLE)[1]


def context(statuses: list | None = None) -> LinkContext:
    seen = statuses if statuses is not None else []
    return LinkContext(solve_captcha=lambda image, spec: None,
                       set_status=lambda phase, key, **params: seen.append((phase, key)), proxies=None)


@pytest.mark.parametrize("url", [
    EXAMPLE,
    "https://mediafire.com/file/ipnyzofjcwri357",
    "https://www.mediafire.com/download/ipnyzofjcwri357",
    "https://www.mediafire.com/?ipnyzofjcwri357",
    "https://www.mediafire.com/file/ipnyzofjcwri357/test-10mb.bin?pwd=secret",
])
def test_every_link_form_resolves_to_the_quick_key(url):
    provider, ref = default_registry().resolve(url)
    assert (provider.name, ref.file_id) == ("mediafire", "ipnyzofjcwri357")


def test_get_info_reads_the_exact_size_from_the_api(site):
    fake = site(api=file_info())
    info = mediafire.MediaFireProvider().get_info(example_ref())
    assert (info.name, info.size) == ("test-10mb.bin", 10485760)
    assert fake.requests == [(mediafire.API_URL, {"quick_key": "ipnyzofjcwri357", "response_format": "json"})]


@pytest.mark.parametrize("api,code,key", [
    (API_INVALID, "not_found", "errors.not_found"),
    (file_info(privacy="private"), "private", "errors.private"),
    (file_info(password_protected="yes"), "private", "errors.private_password"),
    ({"response": {"result": "Error", "error": 105}}, "upstream_error", "errors.upstream_error"),
    ({"unexpected": True}, "upstream_error", "errors.upstream_error"),
    ("<html>maintenance</html>", "upstream_error", "errors.upstream_error"),
    (requests.ConnectionError(), "upstream_error", "errors.upstream_error"),
])
def test_api_answers_map_to_codes(site, api, code, key):
    site(api=api)
    with pytest.raises(ProviderError) as info:
        mediafire.MediaFireProvider().get_info(example_ref())
    assert (info.value.code, info.value.key) == (code, key)


def test_generate_links_parses_the_button_and_hands_it_out_per_connection(site):
    fake = site(page=PAGE)
    statuses = []
    links = mediafire.MediaFireProvider().generate_links(example_ref(), 4, context(statuses))
    assert links == [DIRECT] * 4
    assert fake.requests[0][0] == "https://www.mediafire.com/file/ipnyzofjcwri357"
    assert statuses == [("links", "messages.links_generated")]


def test_a_scrambled_button_link_is_decoded(site):
    scrambled = base64.b64encode(DIRECT.encode()).decode()
    site(page=download_page(f'<a href="javascript:void(0)" data-scrambled-url="{scrambled}" '
                            'id="downloadButton">Download</a>'))
    assert mediafire.MediaFireProvider().generate_links(example_ref(), 1, context()) == [DIRECT]


def test_an_escaped_href_is_unescaped(site):
    site(page=download_page(f'<a href="{DIRECT}?a=1&amp;b=2" id="downloadButton">Download</a>'))
    assert mediafire.MediaFireProvider().generate_links(example_ref(), 1, context()) == [DIRECT + "?a=1&b=2"]


CAPTCHA_PAGE = ('<html><head><title>MediaFire</title><script src="https://www.google.com/recaptcha/api.js">'
                '</script></head><body><form method="post"><div class="g-recaptcha" data-sitekey="x"></div>'
                '</form></body></html>')
PASSWORD_PAGE = ('<html><body><form name="form_password" method="post"><input type="password" name="downloadp">'
                 '</form></body></html>')


@pytest.mark.parametrize("reply,code,key", [
    (CAPTCHA_PAGE, "upstream_error", "errors.upstream_error_captcha_wall"),
    ('<html><div class="cf-turnstile"></div></html>', "upstream_error", "errors.upstream_error_captcha_wall"),
    (PASSWORD_PAGE, "private", "errors.private_password"),
    (download_page('<a href="https://evil.test/x.bin" id="downloadButton">Download</a>'),
     "upstream_error", "errors.upstream_error_no_links"),
    ("<html><body>nothing here</body></html>", "upstream_error", "errors.upstream_error_no_links"),
    (Reply("", url="https://www.mediafire.com/error.php?errno=320&origin=download"), "not_found", "errors.not_found"),
    (Reply("", url="https://www.mediafire.com/error.php?errno=378"), "not_found", "errors.not_found"),
    (Reply("", url="https://www.mediafire.com/error.php?errno=999"), "upstream_error", "errors.upstream_error"),
    (Reply("busy", status=429), "quota_exceeded", "errors.quota_exceeded"),
    (Reply("down", status=503), "upstream_error", "errors.upstream_error"),
    (requests.Timeout(), "upstream_error", "errors.upstream_error"),
])
def test_pages_without_a_link_fail_with_a_code_instead_of_a_download(site, reply, code, key):
    site(page=reply)
    with pytest.raises(ProviderError) as info:
        mediafire.MediaFireProvider().generate_links(example_ref(), 2, context())
    assert (info.value.code, info.value.key) == (code, key)


def run_decoder(data: bytes, step: int = 7) -> bytes:
    decoder = mediafire.MediaFireProvider().decoder(example_ref())
    out = b"".join(decoder.update(data[i:i + step]) for i in range(0, len(data), step))
    decoder.finish()
    return out


def test_the_decoder_passes_bytes_through_and_checks_the_hash(site):
    fake = site(api=file_info())
    assert run_decoder(CONTENT) == CONTENT
    assert [url for url, _ in fake.requests] == [mediafire.API_URL]


def test_a_changed_byte_fails_the_integrity_check(site):
    site(api=file_info())
    with pytest.raises(ProviderError) as info:
        run_decoder(CONTENT[:-1] + b"?")
    assert info.value.code == "integrity_failed"


@pytest.mark.parametrize("api", [requests.ConnectionError(), file_info(hash=""), file_info(hash="md5-ish")])
def test_an_unknown_hash_skips_the_check(site, api):
    site(api=api)
    assert run_decoder(b"anything") == b"anything"
