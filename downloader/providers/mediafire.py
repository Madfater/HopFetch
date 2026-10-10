"""MediaFire (mediafire.com) provider for public file links."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import logging
import re
from typing import Callable
from urllib.parse import parse_qs, urlsplit

import requests

from .base import PHASE_LINKS, Decoder, FileInfo, FileRef, LinkContext, Provider, ProviderError

log = logging.getLogger(__name__)

API_URL = "https://www.mediafire.com/api/1.5/file/get_info.php"
PAGE_URL = "https://www.mediafire.com/file/{key}"
HOSTS = r"(?:www\.)?mediafire\.com"
FILE_PATTERN = rf"^https?://{HOSTS}/(?:file|download)/([A-Za-z0-9]+)(?:[/?#].*)?$"
LEGACY_PATTERN = rf"^https?://{HOSTS}/\?([A-Za-z0-9]+)(?:[&#].*)?$"
INVALID_KEY = 110
GONE_ERRNOS = {320, 378, 380, 386, 388}
DIRECT_LINK = re.compile(r"^https://download\d*\.mediafire\.com/\S+$")
BUTTON = re.compile(r"<a\b[^>]*\bid=\"downloadButton\"[^>]*>", re.S)
CAPTCHA_HINTS = ("g-recaptcha", "recaptcha/api", "hcaptcha", "cf-turnstile", "challenges.cloudflare.com")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def button_link(page: str) -> str | None:
    """The direct link of the page's download button, from `href` or a base64 `data-scrambled-url`."""
    found = BUTTON.search(page)
    if not found:
        return None
    tag = found.group(0)
    candidates = [html.unescape(m) for m in re.findall(r'\bhref="([^"]*)"', tag)]
    for scrambled in re.findall(r'\bdata-scrambled-url="([^"]*)"', tag):
        try:
            candidates.append(base64.b64decode(scrambled, validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError):
            pass
    return next((url for url in candidates if DIRECT_LINK.match(url)), None)


class Sha256Decoder(Decoder):
    """Passes the bytes through unchanged and compares their SHA-256 with the platform's.

    - `expected()` runs once in `finish`, so the hash is the one of the file as it is now; it
      returns None when the hash is unknown, which skips the check.
    """

    def __init__(self, expected: Callable[[], str | None]):
        self._expected = expected
        self._hash = hashlib.sha256()

    def update(self, data: bytes) -> bytes:
        """Hash `data` and return it as is."""
        self._hash.update(data)
        return data

    def finish(self) -> None:
        """Raise `integrity_failed` when a known hash differs from the content's."""
        expected = self._expected()
        if expected and self._hash.hexdigest() != expected:
            raise ProviderError("integrity_failed")


class MediaFireProvider(Provider):
    """Public MediaFire file links: `/file/<key>/...`, `/download/<key>` and the older `/?<key>`.

    - Name, exact size, privacy and SHA-256 come from the public `file/get_info` API.
    - The direct link is the `downloadButton` href of the file page. It answers HTTP Range on
      many connections at once and serves repeated requests, so it is handed to the engine once
      per connection. It is bound to the IP that loaded the page.
    - A removed or invalid file redirects the page to `error.php?errno=<n>`.
    - A page without the button but with captcha markup is MediaFire's human check, which
      fails with `errors.upstream_error_captcha_wall` instead of downloading the page.
    """

    name = "mediafire"
    label = "MediaFire"
    icon = "mediafire"
    patterns = (FILE_PATTERN, LEGACY_PATTERN)
    link_ttl = 1800

    def _file_info(self, ref: FileRef) -> dict:
        """Ask the API about the file; map its errors, privacy and password flag to error codes."""
        try:
            reply = requests.get(API_URL, params={"quick_key": ref.file_id, "response_format": "json"},
                                 headers=self.headers(), timeout=15).json()
            response = reply["response"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            log.warning("mediafire info request failed: %s", exc)
            raise ProviderError("upstream_error", provider=self.label) from exc
        if not isinstance(response, dict):
            raise ProviderError("upstream_error", provider=self.label)
        if response.get("result") != "Success":
            log.info("mediafire file %s: error %s", ref.file_id, response.get("error"))
            if str(response.get("error")) == str(INVALID_KEY):
                raise ProviderError("not_found")
            raise ProviderError("upstream_error", provider=self.label)
        info = response.get("file_info")
        if not isinstance(info, dict):
            raise ProviderError("upstream_error", provider=self.label)
        if info.get("password_protected") == "yes":
            raise ProviderError("private", "errors.private_password")
        if info.get("privacy") == "private":
            raise ProviderError("private")
        return info

    def get_info(self, ref: FileRef) -> FileInfo:
        """Name and exact size from the API."""
        info = self._file_info(ref)
        size = str(info.get("size", ""))
        return FileInfo(name=str(info.get("filename") or ref.file_id), size=int(size) if size.isdigit() else None)

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Load the file page and return its button link once per connection."""
        ctx.check_cancelled()
        try:
            resp = requests.get(PAGE_URL.format(key=ref.file_id), headers=self.headers(), timeout=15)
        except requests.RequestException as exc:
            log.warning("mediafire page request failed: %s", exc)
            raise ProviderError("upstream_error", provider=self.label) from exc
        final = urlsplit(resp.url)
        if final.path.endswith("/error.php"):
            errno = parse_qs(final.query).get("errno", [""])[0]
            log.info("mediafire file %s: errno %s", ref.file_id, errno)
            if errno.isdigit() and int(errno) in GONE_ERRNOS:
                raise ProviderError("not_found")
            raise ProviderError("upstream_error", provider=self.label)
        if resp.status_code == 429:
            raise ProviderError("quota_exceeded", provider=self.label)
        if resp.status_code != 200:
            raise ProviderError("upstream_error", provider=self.label)
        page = resp.text
        url = button_link(page)
        if url is None:
            lowered = page.lower()
            if 'name="downloadp"' in lowered:
                raise ProviderError("private", "errors.private_password")
            if any(hint in lowered for hint in CAPTCHA_HINTS):
                raise ProviderError("upstream_error", "errors.upstream_error_captcha_wall", provider=self.label)
            raise ProviderError("upstream_error", "errors.upstream_error_no_links")
        ctx.set_status(PHASE_LINKS, "messages.links_generated", done=count, count=count)
        return [url] * count

    def _expected_hash(self, ref: FileRef) -> str | None:
        """The API's SHA-256 of the file, or None when the API cannot be asked or has none."""
        try:
            value = str(self._file_info(ref).get("hash", "")).lower()
        except ProviderError as exc:
            log.warning("mediafire file %s: hash unavailable (%s), skipping the check", ref.file_id, exc.code)
            return None
        return value if SHA256.match(value) else None

    def decoder(self, ref: FileRef) -> Decoder:
        """A `Sha256Decoder` checking against the API's hash."""
        return Sha256Decoder(lambda: self._expected_hash(ref))
