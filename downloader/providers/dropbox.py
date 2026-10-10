"""Dropbox (dropbox.com) provider for shared file links, `/scl/fi/` and the older `/s/`."""

from __future__ import annotations

import codecs
import logging
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import requests

from .base import PHASE_LINKS, FileInfo, FileRef, LinkContext, Provider, ProviderError

log = logging.getLogger(__name__)

HOSTS = r"(?:www\.|dl\.)?dropbox\.com"
SCL_PATTERN = rf"^https?://{HOSTS}/scl/fi/([A-Za-z0-9]+)(?:[/?#].*)?$"
LEGACY_PATTERN = rf"^https?://{HOSTS}/s/([A-Za-z0-9]+)(?:[/?#].*)?$"
DROPPED_PARAMS = {"dl", "raw", "pwd"}
TITLE_BYTES = 256 * 1024


def download_url(url: str) -> str:
    """The share link as a forced download: host `www.dropbox.com`, `dl=1`, no `raw` or fragment.

    - Every other query parameter, `rlkey` above all, is kept as given; `rlkey` is what grants
      access to a `/scl/fi/` link.
    - `raw=1` would win over `dl=1` and render the file instead, so it is dropped.
    - `pwd`, where share passwords would go, is dropped so it never reaches Dropbox.
    - Raises `ProviderError("invalid_url", "errors.invalid_url_rlkey")` for a `/scl/fi/` link
      without `rlkey`, which Dropbox would answer with its login page.
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in DROPPED_PARAMS]
    if parts.path.startswith("/scl/") and not any(k == "rlkey" and v for k, v in query):
        raise ProviderError("invalid_url", "errors.invalid_url_rlkey")
    return urlunsplit(("https", "www.dropbox.com", parts.path, urlencode(query + [("dl", "1")]), ""))


def filename_from_disposition(value: str) -> str | None:
    """The file name in a Content-Disposition header, preferring the RFC 5987 `filename*`."""
    found = re.search(r"filename\*\s*=\s*([\w-]+)''([^;]+)", value, re.I)
    if found:
        try:
            codecs.lookup(found.group(1))
            return unquote(found.group(2).strip(), encoding=found.group(1), errors="strict")
        except (LookupError, UnicodeDecodeError):
            pass
    found = re.search(r'filename\s*=\s*"([^"]*)"', value, re.I) or re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    return found.group(1).strip() if found and found.group(1).strip() else None


def page_title(resp: requests.Response) -> str:
    """The `<title>` of an HTML answer, read from at most TITLE_BYTES of the body, lower-cased."""
    body = b""
    for block in resp.iter_content(16 * 1024):
        body += block
        if b"</title>" in body.lower() or len(body) >= TITLE_BYTES:
            break
    found = re.search(rb"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    return found.group(1).decode("utf-8", "replace").strip().lower() if found else ""


class DropboxProvider(Provider):
    """Public Dropbox shared file links.

    - `www.dropbox.com/...&dl=1` redirects to a `dl.dropboxusercontent.com` URL that answers
      exactly one request, so the share link itself is the download link: every chunk request
      follows a fresh redirect, and the share link stays valid as long as the share does.
    - Errors come back as `200` HTML pages told apart only by their title: a login page means
      the link is restricted or its `rlkey` is wrong, a password page means a password is set,
      and "Invalid Link" or "Error" means the file is gone.
    """

    name = "dropbox"
    label = "Dropbox"
    icon = "dropbox"
    patterns = (SCL_PATTERN, LEGACY_PATTERN)

    def _fail_for_page(self, resp: requests.Response) -> ProviderError:
        """The error a non-file answer stands for."""
        if resp.status_code == 429:
            return ProviderError("quota_exceeded", provider=self.label)
        if resp.status_code in (404, 410):
            return ProviderError("not_found")
        if resp.status_code != 200:
            return ProviderError("upstream_error", provider=self.label)
        title = page_title(resp)
        log.info("dropbox answered a page titled %r", title)
        if "password" in title:
            return ProviderError("private", "errors.private_password")
        if "log in" in title or "sign in" in title:
            return ProviderError("private")
        if "invalid link" in title or "error" in title:
            return ProviderError("not_found")
        return ProviderError("upstream_error", provider=self.label)

    def get_info(self, ref: FileRef) -> FileInfo:
        """Ask for the first byte: Content-Range carries the size, Content-Disposition the name."""
        url = download_url(ref.url)
        try:
            resp = requests.get(url, headers={**self.headers(), "Range": "bytes=0-0"}, stream=True, timeout=15)
        except requests.RequestException as exc:
            log.warning("dropbox info request failed: %s", exc)
            raise ProviderError("upstream_error", provider=self.label) from exc
        with resp:
            is_html = resp.headers.get("Content-Type", "").lower().startswith("text/html")
            if resp.status_code not in (200, 206) or is_html:
                raise self._fail_for_page(resp)
            size = None
            if resp.status_code == 206:
                found = re.match(r"bytes \d+-\d+/(\d+)", resp.headers.get("Content-Range", ""))
                size = int(found.group(1)) if found else None
            elif resp.headers.get("Content-Length", "").isdigit():
                size = int(resp.headers["Content-Length"])
            name = filename_from_disposition(resp.headers.get("Content-Disposition", ""))
        if not name:
            name = unquote(urlsplit(ref.url).path.rstrip("/").rsplit("/", 1)[-1])
            if name == ref.file_id:
                name = ""
        return FileInfo(name=name or ref.file_id, size=size)

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Return the forced-download share link once per connection."""
        ctx.check_cancelled()
        url = download_url(ref.url)
        ctx.set_status(PHASE_LINKS, "messages.links_generated", done=count, count=count)
        return [url] * count
