"""The provider interface: what a file hosting platform must implement to be downloadable."""

from __future__ import annotations

import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..proxies import ProxyPool

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}


class ProviderError(Exception):
    """A provider-side failure with a stable `code` and a message fit to show to the user.

    - `code` is one of the error codes in docs/refactor-spec.md, such as `not_found`.
    - `message` is zh-Hant text; the frontend shows it only for codes it has no copy for.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Cancelled(Exception):
    """Raised inside a job when the user paused or deleted it."""


@dataclass(frozen=True)
class FileRef:
    """A file on a platform: the URL the user gave and the id the provider extracted from it."""

    url: str
    file_id: str


@dataclass
class FileInfo:
    """Name and size of a remote file; size is None when the platform does not report it."""

    name: str
    size: int | None = None


@dataclass
class CaptchaSpec:
    """Shape of a platform's image captcha, used to reject OCR guesses before submitting them.

    - `length` is the exact number of characters, or None when it varies.
    - `charset` is a regex character class that every character must match.
    - `lowercase` folds the answer to lower case first.
    """

    length: int | None = None
    charset: str = "[a-z0-9]"
    lowercase: bool = True

    def normalize(self, text: str) -> str | None:
        """Return `text` in the accepted shape, or None when it cannot be a valid answer."""
        if self.lowercase:
            text = text.lower()
        text = "".join(re.findall(self.charset, text))
        if not text or (self.length is not None and len(text) != self.length):
            return None
        return text


@dataclass
class LinkContext:
    """Everything a provider may need while generating links, without knowing about jobs or HTTP.

    - `solve_captcha(image, spec)` returns an answer, or None to ask for a fresh captcha image.
    - `set_status(phase, message)` reports progress; phases are the `PHASE_*` constants.
    - `proxies` is the shared proxy pool.
    - `cancelled` is set when the user pauses or deletes the job.
    """

    solve_captcha: Callable[[bytes, CaptchaSpec], str | None]
    set_status: Callable[[str, str], None]
    proxies: ProxyPool
    cancelled: threading.Event = field(default_factory=threading.Event)

    def check_cancelled(self) -> None:
        """Raise `Cancelled` when the job was stopped."""
        if self.cancelled.is_set():
            raise Cancelled()

    def wait(self, seconds: float, message: str) -> None:
        """Sleep for `seconds`, reporting a countdown each second and stopping early on cancel."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            minutes, seconds = divmod(int(left + 0.999), 60)
            countdown = f"{minutes}:{seconds:02d}"
            self.set_status(PHASE_WAITING, f"{message} {countdown}")
            if self.cancelled.wait(min(1.0, left)):
                raise Cancelled()


PHASE_CAPTCHA = "captcha"
PHASE_WAITING = "waiting"
PHASE_LINKS = "links"


class Provider(ABC):
    """A file hosting platform.

    - `name` is the stable id stored in jobs; `label` is shown in the UI; `icon` names the
      frontend icon.
    - `patterns` are regular expressions over the normalized URL, with the file id in group 1.
      They use only syntax that Python and JavaScript read the same way: no named groups,
      no lookbehind, no inline flags.
    - `link_ttl` is how long generated links stay reusable, in seconds.
    """

    name: str = ""
    label: str = ""
    icon: str = ""
    patterns: tuple[str, ...] = ()
    link_ttl: float = float("inf")

    def match(self, url: str) -> str | None:
        """Return the file id when the normalized `url` matches one of `patterns`, else None."""
        normalized = normalize_url(url)
        for pattern in self.patterns:
            found = re.match(pattern, normalized)
            if found:
                return found.group(1)
        return None

    @abstractmethod
    def get_info(self, ref: FileRef) -> FileInfo:
        """Return the file's name and size, raising `ProviderError` when it is unavailable."""

    @abstractmethod
    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Return between 1 and `count` direct links that answer HTTP Range requests."""

    def headers(self) -> dict[str, str]:
        """Return the HTTP headers to send with every chunk request."""
        return dict(DEFAULT_HEADERS)


def normalize_url(url: str) -> str:
    """Trim whitespace and lowercase the scheme and host, leaving path and query as given.

    - The frontend applies the same rule before matching, so both sides see the same string.
    """
    url = url.strip()
    found = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?#]*)(.*)$", url, re.S)
    if not found:
        return url
    return found.group(1).lower() + found.group(2).lower() + found.group(3)
