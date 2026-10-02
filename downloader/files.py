"""Serving finished files from the download root without following symlinks.

- A file is opened by name relative to an open handle of the root, with O_NOFOLLOW, and checked
  with fstat on the open descriptor. Nothing is looked up by path after the check, so swapping
  the file for a symlink in between cannot redirect the read.
- One byte range per request is honored; If-Range is honored against this module's ETag.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

import anyio.to_thread
from starlette.responses import Response, StreamingResponse

CHUNK = 256 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def open_in_root(root: Path, path: Path) -> tuple[int, os.stat_result] | None:
    """Open `path` for reading when it is a regular file directly inside `root`.

    - Returns the descriptor and its fstat result, or None when the name is not directly under
      `root`, is a symlink, is missing, or is not a regular file.
    """
    if path.parent != root or path.name in ("", ".", ".."):
        return None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
    except OSError:
        return None
    finally:
        os.close(root_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        return None
    return fd, info


def etag_of(info: os.stat_result) -> str:
    """A strong ETag from the file's inode, size and modification time."""
    return f'"{info.st_ino:x}-{info.st_size:x}-{info.st_mtime_ns:x}"'


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """The inclusive byte range a Range header asks for.

    - Returns None to send the whole file (no header, several ranges, an invalid range such as
      `bytes=5-3`, or a form not handled), and "unsatisfiable" when the range starts beyond the
      file.
    """
    if not header:
        return None
    found = _RANGE.match(header.strip())
    if not found or (not found.group(1) and not found.group(2)):
        return None
    first, last = found.group(1), found.group(2)
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        start = max(0, size - int(last))
        end = size - 1
    if first and last and int(last) < start:
        return None
    if start >= size or start > end:
        return "unsatisfiable"
    return start, end


def disposition(name: str) -> str:
    """An attachment Content-Disposition with an ASCII fallback and the RFC 5987 UTF-8 name."""
    fallback = name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"attachment; filename=\"{fallback}\"; filename*=utf-8''{quote(name, safe='')}"


async def _read(fd: int, start: int, length: int) -> AsyncIterator[bytes]:
    """Yield `length` bytes from `fd` starting at `start`; reads run in a worker thread."""
    offset, left = start, length
    while left > 0:
        block = await anyio.to_thread.run_sync(os.pread, fd, min(CHUNK, left), offset)
        if not block:
            break
        offset += len(block)
        left -= len(block)
        yield block


class DescriptorResponse(StreamingResponse):
    """A streaming response that owns an open file descriptor and closes it when it ends.

    - The descriptor is closed in a `finally` around the whole ASGI call, so it is closed on
      every path: completion, an error, or a client that disconnects before or during the body.
      Starlette does not close the body iterator on disconnect, so the iterator cannot own it.
    """

    def __init__(self, fd: int, start: int, length: int, **kwargs):
        self.fd = fd
        super().__init__(_read(fd, start, length), media_type="application/octet-stream", **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            os.close(self.fd)


def file_response(fd: int, info: os.stat_result, name: str, range_header: str | None,
                  if_range: str | None) -> Response:
    """Answer with the whole file, one range of it, or 416, reading from the open `fd`.

    - The returned response owns `fd` and closes it when it has been sent.
    """
    size = info.st_size
    etag = etag_of(info)
    headers = {"Accept-Ranges": "bytes", "ETag": etag, "Content-Disposition": disposition(name),
               "Cache-Control": "no-store"}
    wanted = parse_range(range_header, size) if if_range in (None, etag) else None
    if wanted == "unsatisfiable":
        os.close(fd)
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if wanted is None:
        return DescriptorResponse(fd, 0, size, headers={**headers, "Content-Length": str(size)})
    start, end = wanted
    length = end - start + 1
    return DescriptorResponse(fd, start, length, status_code=206,
                              headers={**headers, "Content-Length": str(length),
                                       "Content-Range": f"bytes {start}-{end}/{size}"})
