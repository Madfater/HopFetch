"""Small helpers shared across modules."""

from __future__ import annotations

import errno
import fcntl
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

MIN_SPLIT_SIZE = 20 * 2**20
PART_SUFFIX = ".part"
MAX_NAME_BYTES = 200
NO_LINK_ERRORS = {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EXDEV, errno.EMLINK}

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


def safe_filename(name: str, fallback: str = "download", max_bytes: int = MAX_NAME_BYTES) -> str:
    """Reduce a remote file name to a single safe path component.

    - Drops any directory part, control characters and characters Windows rejects.
    - Strips leading dots and surrounding whitespace so the result is never hidden or empty.
    - Keeps the UTF-8 length within `max_bytes`, cutting the stem and keeping a short extension,
      so ` (N)` and the staging suffix still fit the filesystem's name limit.
    """
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip().lstrip(".")
    if len(name.encode()) > max_bytes:
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem or len(ext.encode()) > 16:
            stem, ext = name, ""
        suffix = f".{ext}" if ext else ""
        budget = max_bytes - len(suffix.encode())
        stem = stem.encode()[:budget].decode(errors="ignore").rstrip()
        name = stem + suffix
    return name or fallback


def occupied(path: Path) -> bool:
    """True when anything is at `path`, including a symlink whose target does not exist."""
    return path.is_symlink() or path.exists()


def unique_path(path: Path, staging_suffix: str = PART_SUFFIX) -> Path:
    """Return `path`, or `name (N).ext` with the lowest N, such that neither the name nor its
    staging sibling (`name + staging_suffix`) is occupied."""
    for n in range(0, 10_000):
        candidate = path if n == 0 else path.with_name(f"{path.stem} ({n}){path.suffix}")
        staging = candidate.with_name(candidate.name + staging_suffix)
        if not occupied(candidate) and not occupied(staging):
            return candidate
    raise FileExistsError(path)


def create_new(path: Path) -> BinaryIO:
    """Open a new file for binary writing, failing when anything, even a symlink, is at `path`."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    return os.fdopen(fd, "wb")


def staging_path(output: Path) -> Path:
    """The staging file that holds `output` while it is being written."""
    return output.with_name(output.name + PART_SUFFIX)


def claim_staging(path: Path) -> tuple[Path, BinaryIO]:
    """Pick a free final name for `path` and create its staging file exclusively.

    - Returns the final name and the open staging file.
    - When another writer takes the same staging name first, the next free name is tried.
    """
    for _ in range(100):
        output = unique_path(path)
        try:
            return output, create_new(staging_path(output))
        except FileExistsError:
            continue
    raise FileExistsError(path)


def publish_staging(staging: Path, output: Path) -> Path:
    """Give `staging` its final name without replacing anything, and return that name.

    - Hard-links `staging` to the name and then unlinks `staging`; a name taken in the
      meantime moves on to the next ` (N)` name.
    - On filesystems without hard links, first reserves the name by creating an empty file
      exclusively, then renames `staging` over that reservation, so only our own placeholder
      is ever replaced.
    """
    target = output
    for _ in range(100):
        try:
            os.link(staging, target, follow_symlinks=False)
        except FileExistsError:
            target = unique_path(output)
            continue
        except OSError as exc:
            if exc.errno not in NO_LINK_ERRORS:
                raise
            try:
                create_new(target).close()
            except FileExistsError:
                target = unique_path(output)
                continue
            os.replace(staging, target)
            return target
        staging.unlink()
        return target
    raise FileExistsError(output)


def inside(root: Path, path: Path) -> bool:
    """True when `path` is a regular file, not a symlink, whose real path is under `root`."""
    if path.is_symlink() or not path.is_file():
        return False
    return path.resolve().is_relative_to(root.resolve())
