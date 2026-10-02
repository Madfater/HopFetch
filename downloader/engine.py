"""Segmented, resumable HTTP download over many links at once."""

from __future__ import annotations

import collections
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

import requests

from .providers.base import Cancelled

log = logging.getLogger(__name__)

BLOCK_SIZE = 32 * 1024
DEAD_LINK_STATUSES = {401, 403, 404, 410}
DEAD_LINK_STRIKES = 3
RETRY_DELAY = 2.0


class LinksExpired(Exception):
    """Every link was refused by the server, so new links are needed."""


class DownloadStalled(Exception):
    """No byte arrived for longer than the stall timeout."""


class RemoteChanged(Exception):
    """The server answered a validated range request with the whole file: the file changed."""


class RangeUnsupported(Exception):
    """The server answered a range request with the whole file, so parts cannot be fetched."""


@dataclass
class Validator:
    """What identifies the remote file version: its ETag and Last-Modified, once seen.

    - `if_range` prefers a strong ETag and falls back to Last-Modified; a weak ETag cannot be
      used with If-Range.
    - `capture` keeps the first values seen and ignores later ones.
    """

    etag: str | None = None
    last_modified: str | None = None

    @property
    def known(self) -> bool:
        """True once either value was seen."""
        return self.etag is not None or self.last_modified is not None

    def if_range(self) -> str | None:
        """The If-Range value to send, or None when nothing usable is known."""
        if self.etag and not self.etag.startswith("W/"):
            return self.etag
        return self.last_modified

    def capture(self, headers) -> None:
        """Record ETag and Last-Modified from a response when none was recorded yet."""
        if not self.known:
            self.etag = headers.get("ETag")
            self.last_modified = headers.get("Last-Modified")

    def matches(self, headers) -> bool:
        """False when a response names a different version than the one recorded.

        - Compares the ETag when both sides have one, else Last-Modified; a response that sends
          neither cannot be told apart and matches.
        """
        etag = headers.get("ETag")
        if self.etag and etag:
            return etag == self.etag
        modified = headers.get("Last-Modified")
        if self.last_modified and modified:
            return modified == self.last_modified
        return True


@dataclass(frozen=True)
class Part:
    """One byte range of the file, `start` and `end` inclusive, stored in its own part file."""

    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        """Number of bytes in the range."""
        return self.end - self.start + 1


@dataclass
class Progress:
    """A progress snapshot passed to the `on_progress` callback."""

    total_bytes: int
    done_bytes: int
    parts_total: int
    parts_done: int
    active: int
    speed: float


def build_parts(size: int, split_size: int) -> list[Part]:
    """Split `size` bytes into ranges of about `split_size`; the last range takes the remainder."""
    if size <= 0:
        return []
    count = max(1, -(-size // split_size))
    chunk = size // count
    return [
        Part(i, i * chunk, size - 1 if i == count - 1 else (i + 1) * chunk - 1)
        for i in range(count)
    ]


def part_path(part_dir: Path, index: int) -> Path:
    """Return the part file for range `index`."""
    return part_dir / f"part{index:05d}"


def assemble(part_dir: Path, parts: list[Part], out: BinaryIO) -> None:
    """Write the part files in order into `out`.

    - `out` is the job's staging file; the caller gives it its final name afterwards, so the
      final name never holds a partial file. Part files are left for the caller to remove.
    """
    for part in parts:
        with part_path(part_dir, part.index).open("rb") as src:
            while block := src.read(1024 * 1024):
                out.write(block)


def _whole_file(headers, size: int, validated: bool) -> bool:
    """True when a 200 answer to a range request carries a whole file rather than an error page.

    - An HTML body is an error page.
    - A plain range request expects the known size, or no length at all.
    - A validated request may get a replaced file of another size, so any non-HTML body counts.
    """
    if headers.get("Content-Type", "").lower().startswith("text/html"):
        return False
    length = headers.get("Content-Length")
    return validated or length is None or length == str(size)


class SegmentedDownload:
    """Downloads `size` bytes from `links` into part files under `part_dir`.

    - Each part file holds exactly the bytes already received for its range, so a later run
      resumes every range where it stopped. Bytes are only appended, never rewritten.
    - Each link carries at most one connection at a time.
    - A link answering 401/403/404/410 three times in a row is dropped; when every link is
      dropped, `run` raises `LinksExpired`.
    - `run` raises `Cancelled` when `cancelled` is set, and `DownloadStalled` when no byte arrives
      for `stall_timeout` seconds.
    - Every request carries `If-Range` once `validator` knows the file version; the first 206
      answer fills it in and calls `on_validator` once. A 206 naming another version, or a
      Content-Range total other than `size`, raises `RemoteChanged` before anything is written;
      this also covers the first parallel requests and servers ignoring If-Range.
    - A 200 answer carrying a whole file raises `RemoteChanged` when the request had If-Range,
      and `RangeUnsupported` otherwise; see `_whole_file`. Any other 200 answer, such as an error
      page, counts as a failed request. Nothing of a 200 body is written.
    """

    def __init__(self, links: list[str], size: int, part_dir: Path, split_size: int,
                 headers: dict[str, str], cancelled: threading.Event,
                 on_progress: Callable[[Progress], None] | None = None,
                 read_timeout: float = 20, stall_timeout: float = 600,
                 progress_interval: float = 0.5, validator: Validator | None = None,
                 on_validator: Callable[[Validator], None] | None = None):
        self.links = list(links)
        self.size = size
        self.part_dir = part_dir
        self.parts = build_parts(size, split_size)
        self.headers = headers
        self.cancelled = cancelled
        self.on_progress = on_progress
        self.read_timeout = read_timeout
        self.stall_timeout = stall_timeout
        self.progress_interval = progress_interval
        self.validator = validator if validator is not None else Validator()
        self.on_validator = on_validator
        self._fatal: Exception | None = None

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._done_bytes = 0
        self._last_byte_at = time.monotonic()
        self._samples: collections.deque[tuple[float, int]] = collections.deque(maxlen=20)
        self._strikes = [0] * len(self.links)
        self._busy: set[int] = set()
        self._threads: list[threading.Thread] = []

    def run(self) -> None:
        """Download every missing byte; return when all ranges are complete."""
        self.part_dir.mkdir(parents=True, exist_ok=True)
        pending = collections.deque(p for p in self.parts if not self._prepare(p))
        self._done_bytes = sum(self._on_disk(p) for p in self.parts)
        self._last_byte_at = time.monotonic()
        last_report = 0.0
        try:
            while pending or self._busy:
                if self._fatal is not None:
                    raise self._fatal
                if self.cancelled.is_set():
                    raise Cancelled()
                if not self._busy and pending and self._alive_links() == []:
                    raise LinksExpired()
                if time.monotonic() - self._last_byte_at > self.stall_timeout:
                    raise DownloadStalled(f"No data received for {int(self.stall_timeout)}s")
                with self._lock:
                    free = [i for i in self._alive_links() if i not in self._busy]
                    while free and pending:
                        link = free.pop(0)
                        part = pending.popleft()
                        self._busy.add(link)
                        thread = threading.Thread(target=self._worker, args=(part, link, pending),
                                                  daemon=True)
                        self._threads.append(thread)
                        thread.start()
                now = time.monotonic()
                if now - last_report >= self.progress_interval:
                    self._report()
                    last_report = now
                self._wake.wait(0.2)
                self._wake.clear()
        finally:
            self._stop.set()
            for thread in self._threads:
                thread.join()
            self._report()
        if self._fatal is not None:
            raise self._fatal

    def _alive_links(self) -> list[int]:
        """Indexes of links that have not been dropped."""
        return [i for i, strikes in enumerate(self._strikes) if strikes < DEAD_LINK_STRIKES]

    def _on_disk(self, part: Part) -> int:
        """Bytes already stored for `part`."""
        path = part_path(self.part_dir, part.index)
        return path.stat().st_size if path.exists() else 0

    def _prepare(self, part: Part) -> bool:
        """Return True when `part` is complete; discard a part file longer than its range."""
        have = self._on_disk(part)
        if have > part.size:
            log.warning("part %d holds %d bytes for a %d-byte range, restarting it",
                        part.index, have, part.size)
            part_path(self.part_dir, part.index).unlink()
            return False
        return have == part.size

    def _worker(self, part: Part, link: int, pending: collections.deque) -> None:
        """Fetch the rest of `part` over `link`, then requeue the part when it is incomplete.

        - After a failed request the link stays busy for RETRY_DELAY seconds before the part
          is requeued, so a refusing server is not hammered.
        """
        try:
            status = self._fetch(part, link)
            with self._lock:
                if status in DEAD_LINK_STATUSES:
                    self._strikes[link] += 1
                elif status == 206:
                    self._strikes[link] = 0
                incomplete = self._on_disk(part) < part.size
            if incomplete:
                if status != 206:
                    self._stop.wait(RETRY_DELAY)
                pending.append(part)
        finally:
            with self._lock:
                self._busy.discard(link)
            self._wake.set()

    def _fetch(self, part: Part, link: int) -> int | None:
        """Stream the missing tail of `part`; return the HTTP status, or None on a network error."""
        path = part_path(self.part_dir, part.index)
        have = self._on_disk(part)
        if have >= part.size:
            return 206
        start = part.start + have
        headers = {**self.headers, "Range": f"bytes={start}-{part.end}"}
        with self._lock:
            if_range = self.validator.if_range()
        if if_range:
            headers["If-Range"] = if_range
        try:
            resp = requests.get(self.links[link], headers=headers, stream=True,
                                timeout=(10, self.read_timeout))
            with resp:
                if resp.status_code == 200:
                    if _whole_file(resp.headers, self.size, validated=bool(if_range)):
                        self._fail(RemoteChanged() if if_range else RangeUnsupported())
                    return 200
                if resp.status_code != 206:
                    return resp.status_code
                served = re.match(r"bytes (\d+)-\d+/(\d+|\*)", resp.headers.get("Content-Range", ""))
                if not served or int(served.group(1)) != start:
                    return None
                if served.group(2) != "*" and int(served.group(2)) != self.size:
                    self._fail(RemoteChanged())
                    return 206
                with self._lock:
                    was_known = self.validator.known
                    self.validator.capture(resp.headers)
                    learned = self.validator.known and not was_known
                    same = self.validator.matches(resp.headers)
                if learned and self.on_validator:
                    self.on_validator(self.validator)
                if not same:
                    self._fail(RemoteChanged())
                    return 206
                remaining = part.size - have
                with path.open("ab") as out:
                    for block in resp.iter_content(BLOCK_SIZE):
                        if self._stop.is_set() or self.cancelled.is_set():
                            break
                        block = block[:remaining]
                        out.write(block)
                        remaining -= len(block)
                        with self._lock:
                            self._done_bytes += len(block)
                            self._last_byte_at = time.monotonic()
                        if remaining <= 0:
                            break
            return 206
        except (requests.RequestException, OSError):
            return None

    def _fail(self, error: Exception) -> None:
        """Record the first fatal error and stop every worker."""
        with self._lock:
            if self._fatal is None:
                self._fatal = error
        self._stop.set()
        self._wake.set()

    def _report(self) -> None:
        """Send a progress snapshot to `on_progress`."""
        if not self.on_progress:
            return
        now = time.monotonic()
        with self._lock:
            done = self._done_bytes
            active = len(self._busy)
        self._samples.append((now, done))
        first_t, first_done = self._samples[0]
        speed = (done - first_done) / (now - first_t) if now - first_t >= 1 else 0.0
        parts_done = sum(1 for p in self.parts if self._on_disk(p) == p.size)
        self.on_progress(Progress(self.size, done, len(self.parts), parts_done, active, speed))
