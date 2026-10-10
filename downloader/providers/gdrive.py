"""Google Drive provider for public file links, downloaded from `drive.usercontent.google.com`."""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

import requests

from .base import PHASE_LINKS, FileInfo, FileRef, LinkContext, Provider, ProviderError

log = logging.getLogger(__name__)

DOWNLOAD_URL = "https://drive.usercontent.google.com/download"
FILE_ID = r"([A-Za-z0-9_-]{25,})"
FILE_PATTERN = rf"^https?://drive\.google\.com/file/d/{FILE_ID}(?:[/?#].*)?$"
QUERY_PATTERN = rf"^https?://drive\.google\.com/(?:open|uc)\?(?:[^#]*&)?id={FILE_ID}(?:[&#].*)?$"
USERCONTENT_PATTERN = rf"^https?://drive\.usercontent\.google\.com/download\?(?:[^#]*&)?id={FILE_ID}(?:[&#].*)?$"
DRIVE_HOSTS = {"drive.usercontent.google.com", "drive.google.com"}
SIGN_IN_HOST = "accounts.google.com"
MAX_HOPS = 3
FORM = re.compile(r'(<form\b[^>]*\bid="download-form"[^>]*>)(.*?)</form>', re.S)
INPUT = re.compile(r"<input\b[^>]*>")
ATTRIBUTE = re.compile(r'\b([a-z-]+)="([^"]*)"')
ERROR_CAPTION = re.compile(r'class="uc-error-(?:caption|subcaption)"[^>]*>(.*?)</p>', re.S)
QUOTA_HINTS = ("too many users", "quota exceeded")
DENIED_HINTS = ("access denied", "need access", "need permission", "not have permission", "sign in", "sign-in")
FILENAME_STAR = re.compile(r"filename\*=(?:UTF-8|utf-8)''([^;]+)")
FILENAME = re.compile(r'filename="([^"]*)"')


def attributes(tag: str) -> dict[str, str]:
    """Return the quoted attributes of an HTML tag, unescaped, in any order."""
    return {name: html.unescape(value) for name, value in ATTRIBUTE.findall(tag)}


def content_name(disposition: str) -> str | None:
    """Return the file name from a Content-Disposition header, preferring the RFC 5987 form."""
    found = FILENAME_STAR.search(disposition)
    if found:
        return unquote(found.group(1).strip())
    found = FILENAME.search(disposition)
    return found.group(1) if found else None


def content_size(headers) -> int | None:
    """Return the total size from Content-Range, or from Content-Length on a plain 200."""
    found = re.match(r"bytes \d+-\d+/(\d+)", headers.get("Content-Range", ""))
    if found:
        return int(found.group(1))
    length = headers.get("Content-Length")
    return int(length) if length and length.isdigit() and "Content-Range" not in headers else None


class GoogleDriveProvider(Provider):
    """Public Google Drive file links: `/file/d/<id>/...`, `open?id=`, `uc?id=` and the
    `drive.usercontent.google.com/download?id=` URL they lead to.

    - Every request goes straight to the usercontent download URL with `Range: bytes=0-0`, so
      the answer is either one byte of the file, with its name and total size, or an HTML page.
    - A file too large for the virus scan answers with a page holding `download-form`; its
      hidden inputs (`confirm`, `uuid`) make the URL that serves the file.
    - The final URL serves Range requests over many connections, so it is handed to the engine
      once per connection.
    - A sign-in redirect or a 401/403 means the file is not shared publicly: `private`.
    - The "too many users" page is Drive's download quota: `quota_exceeded`.
    """

    name = "gdrive"
    label = "Google Drive"
    icon = "gdrive"
    patterns = (FILE_PATTERN, QUERY_PATTERN, USERCONTENT_PATTERN)
    link_ttl = 3600

    def _start_url(self, ref: FileRef) -> str:
        """The usercontent download URL for the file, keeping a `resourcekey` from the user's URL."""
        params = {"id": ref.file_id, "export": "download"}
        resource_key = parse_qs(urlsplit(ref.url).query).get("resourcekey")
        if resource_key:
            params["resourcekey"] = resource_key[0]
        return f"{DOWNLOAD_URL}?{urlencode(params)}"

    def _get(self, url: str) -> requests.Response:
        """Ask `url` for its first byte, following redirects only between Drive hosts."""
        for _ in range(MAX_HOPS + 1):
            try:
                resp = requests.get(url, headers={**self.headers(), "Range": "bytes=0-0"},
                                    allow_redirects=False, stream=True, timeout=15)
            except requests.RequestException as exc:
                log.warning("gdrive request failed: %s", exc)
                raise ProviderError("upstream_error", provider=self.label) from exc
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp
            resp.close()
            url = urljoin(url, resp.headers.get("Location", ""))
            host = urlsplit(url).hostname or ""
            if host == SIGN_IN_HOST:
                raise ProviderError("private")
            if host not in DRIVE_HOSTS:
                log.info("gdrive redirect to an unexpected host: %s", host)
                raise ProviderError("upstream_error", provider=self.label)
        raise ProviderError("upstream_error", provider=self.label)

    def _page_error(self, page: str) -> ProviderError:
        """Map an HTML page that is not the confirm form to an error."""
        text = " ".join(html.unescape(m) for m in ERROR_CAPTION.findall(page)).lower()
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        text += " " + html.unescape(title.group(1)).lower() if title else ""
        if any(hint in text for hint in QUOTA_HINTS):
            return ProviderError("quota_exceeded", provider=self.label)
        if any(hint in text for hint in DENIED_HINTS):
            return ProviderError("private")
        log.info("gdrive page not understood: %s", text.strip()[:200])
        return ProviderError("upstream_error", provider=self.label)

    def _confirm_url(self, page: str, start_url: str) -> str | None:
        """Build the URL the virus scan warning's `download-form` submits to, or None.

        - The query is the form's hidden inputs, plus the `resourcekey` of the user's URL when
          the form leaves it out.
        """
        form = FORM.search(page)
        if not form:
            return None
        target = attributes(form.group(1)).get("action") or DOWNLOAD_URL
        if urlsplit(target).hostname not in DRIVE_HOSTS:
            return None
        params = parse_qs(urlsplit(start_url).query)
        params = {"resourcekey": params["resourcekey"][0]} if "resourcekey" in params else {}
        for tag in INPUT.findall(form.group(2)):
            found = attributes(tag)
            if found.get("type") == "hidden" and found.get("name"):
                params[found["name"]] = found.get("value", "")
        return f"{target}?{urlencode(params)}" if params.get("id") else None

    def _resolve(self, ref: FileRef) -> tuple[str, requests.Response]:
        """Return the URL that serves the file and the response to its first-byte request.

        - Raises `not_found` on 404, `private` on 401/403 or a sign-in page, `quota_exceeded`
          on the quota page and `upstream_error` otherwise.
        """
        url = start_url = self._start_url(ref)
        confirmed = False
        while True:
            resp = self._get(url)
            if resp.status_code == 404:
                resp.close()
                raise ProviderError("not_found")
            if resp.status_code == 206:
                return url, resp
            denied = resp.status_code in (401, 403)
            if resp.headers.get("Content-Type", "").lower().startswith("text/html"):
                with resp:
                    page = resp.text
                next_url = None if confirmed else self._confirm_url(page, start_url)
                if next_url:
                    url, confirmed = next_url, True
                    continue
                error = self._page_error(page)
                raise ProviderError("private") if denied and error.code != "quota_exceeded" else error
            if denied:
                resp.close()
                raise ProviderError("private")
            if resp.status_code != 200:
                resp.close()
                log.info("gdrive %s: status %s", ref.file_id, resp.status_code)
                raise ProviderError("upstream_error", provider=self.label)
            return url, resp

    def get_info(self, ref: FileRef) -> FileInfo:
        """Read the name from Content-Disposition and the size from Content-Range."""
        _, resp = self._resolve(ref)
        with resp:
            name = content_name(resp.headers.get("Content-Disposition", ""))
            size = content_size(resp.headers)
        return FileInfo(name=name or ref.file_id, size=size)

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Return the confirmed download URL once per connection."""
        ctx.check_cancelled()
        url, resp = self._resolve(ref)
        resp.close()
        ctx.set_status(PHASE_LINKS, "messages.links_generated", done=count, count=count)
        return [url] * count
