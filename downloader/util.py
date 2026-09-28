"""Small helpers shared across modules."""

from __future__ import annotations

import fcntl
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIN_SPLIT_SIZE = 20 * 2**20

_UNITS = {
    "": 1, "B": 1,
    "K": 2**10, "KB": 2**10, "KIB": 2**10,
    "M": 2**20, "MB": 2**20, "MIB": 2**20,
    "G": 2**30, "GB": 2**30, "GIB": 2**30,
    "T": 2**40, "TB": 2**40, "TIB": 2**40,
}


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive cross-process `fcntl.flock` on `lock_path` for the block."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def parse_size(size: str | int) -> int:
    """Convert a size such as `20MB`, `1.5 GiB` or `4096` into bytes, using powers of 1024."""
    if isinstance(size, int):
        return size
    match = re.fullmatch(r"\s*([\d.]+)\s*([a-zA-Z]{0,3})\s*", str(size))
    if not match:
        raise ValueError(f"Cannot parse size: {size!r}")
    unit = match.group(2).upper()
    if unit not in _UNITS:
        raise ValueError(f"Unknown size unit: {match.group(2)!r}")
    return int(float(match.group(1)) * _UNITS[unit])


def safe_filename(name: str, fallback: str = "download") -> str:
    """Reduce a remote file name to a single safe path component.

    - Drops any directory part, control characters and characters Windows rejects.
    - Strips leading dots and surrounding whitespace so the result is never hidden or empty.
    """
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip().lstrip(".")
    return name[:240] or fallback


def unique_path(path: Path) -> Path:
    """Return `path`, or `name (N).ext` with the lowest N that does not exist yet."""
    if not path.exists():
        return path
    for n in range(1, 10_000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(path)
