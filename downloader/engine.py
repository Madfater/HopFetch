"""Segmented, resumable HTTP download over many links at once."""

from __future__ import annotations

import collections
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


def assemble(part_dir: Path, parts: list[Part], output: Path) -> None:
    """Concatenate the part files in order into `output`, then delete them.

    - Writes to a temporary sibling first and renames it, so `output` never holds a partial file.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + ".assembling")
    with staging.open("wb") as out:
        for part in parts:
            with part_path(part_dir, part.index).open("rb") as src:
                while block := src.read(1024 * 1024):
                    out.write(block)
    staging.replace(output)
    for part in parts:
        part_path(part_dir, part.index).unlink(missing_ok=True)


class SegmentedDownload:
    """Downloads `size` bytes from `links` into part files under `part_dir`.

    - Each part file holds exactly the bytes already received for its range, so a later run
      resumes every range where it stopped. Bytes are only appended, never rewritten.
    - Each link carries at most one connection at a time.
    - A link answering 401/403/404/410 three times in a row is dropped; when every link is
      dropped, `run` raises `LinksExpired`.
    - `run` raises `Cancelled` when `cancelled` is set, and `DownloadStalled` when no byte arrives
      for `stall_timeout` seconds.
    """

    def __init__(self, links: list[str], size: int, part_dir: Path, split_size: int,
                 headers: dict[str, str], cancelled: threading.Event,
                 on_progress: Callable[[Progress], None] | None = None,
                 read_timeout: float = 20, stall_timeout: float = 600,
                 progress_interval: float = 0.5):
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
        try:
            resp = requests.get(
                self.links[link],
                headers={**self.headers, "Range": f"bytes={start}-{part.end}"},
                stream=True, timeout=(10, self.read_timeout),
            )
            with resp:
                if resp.status_code != 206:
                    return resp.status_code
                served = re.match(r"bytes (\d+)-", resp.headers.get("Content-Range", ""))
                if not served or int(served.group(1)) != start:
                    return None
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
