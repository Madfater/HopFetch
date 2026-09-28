"""Generic provider for plain HTTP(S) file URLs whose server answers Range requests."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote, urlsplit

import requests

from .base import DEFAULT_HEADERS, FileInfo, FileRef, LinkContext, Provider, ProviderError


class DirectProvider(Provider):
    """Any `http://` or `https://` URL not claimed by a platform provider.

    - The file id is a hash of the URL, so the same URL maps to the same job.
    - Every connection uses the same URL with a different byte range.
    """

    name = "direct"
    label = "Direct link"

    def match(self, url: str) -> str | None:
        """Accept any absolute http(s) URL with a host."""
        parts = urlsplit(url.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        return hashlib.sha1(url.strip().encode()).hexdigest()[:16]

    def get_info(self, ref: FileRef) -> FileInfo:
        """Probe the URL with a one-byte Range request to learn its size and name."""
        try:
            resp = requests.get(ref.url, headers={**DEFAULT_HEADERS, "Range": "bytes=0-0"},
                                stream=True, timeout=15, allow_redirects=True)
            resp.close()
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach the server: {exc}") from exc
        if resp.status_code != 206:
            raise ProviderError(f"The server does not support ranged downloads (HTTP {resp.status_code})")
        total = re.search(r"/(\d+)$", resp.headers.get("Content-Range", ""))
        if not total:
            raise ProviderError("The server did not report the file size")
        return FileInfo(name=self._filename(resp), size=int(total.group(1)))

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Return the URL itself once per connection."""
        return [ref.url.strip()] * count

    @staticmethod
    def _filename(resp: requests.Response) -> str:
        """Take the name from Content-Disposition, or else from the last path segment."""
        disposition = resp.headers.get("Content-Disposition", "")
        found = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I) or \
            re.search(r'filename="?([^";]+)"?', disposition, re.I)
        if found:
            return unquote(found.group(1))
        return unquote(urlsplit(resp.url).path.rsplit("/", 1)[-1]) or "download"
