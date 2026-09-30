"""Segmented download engine against a local Range server."""

from __future__ import annotations

import threading
import time

import pytest

from downloader.engine import (
    DownloadStalled,
    LinksExpired,
    SegmentedDownload,
    assemble,
    build_parts,
    part_path,
)
from downloader.providers.base import Cancelled
from downloader.util import claim_staging, parse_size, publish_staging, safe_filename, staging_path

SPLIT = 200_000


def make(server, tmp_path, links=4, **kwargs):
    """Build a download of the server's file into `tmp_path/parts`."""
    return SegmentedDownload(
        links=[server.url] * links, size=len(server.content), part_dir=tmp_path / "parts",
        split_size=SPLIT, headers={}, cancelled=kwargs.pop("cancelled", threading.Event()), **kwargs,
    )


def finish(download, tmp_path):
    """Assemble the parts and return the output bytes."""
    out = tmp_path / "out.bin"
    with out.open("wb") as handle:
        assemble(download.part_dir, download.parts, handle)
    return out.read_bytes()


@pytest.mark.parametrize("size,split,expected", [
    (10, 4, [(0, 2), (3, 5), (6, 9)]),
    (10, 10, [(0, 9)]),
    (10, 100, [(0, 9)]),
    (0, 10, []),
])
def test_build_parts(size, split, expected):
    assert [(p.start, p.end) for p in build_parts(size, split)] == expected


def test_build_parts_covers_every_byte():
    parts = build_parts(2_514_849_678, parse_size("20MB"))
    assert parts[0].start == 0 and parts[-1].end == 2_514_849_677
    assert all(a.end + 1 == b.start for a, b in zip(parts, parts[1:]))


@pytest.mark.parametrize("text,expected", [
    ("20MB", 20 * 2**20), ("20mb", 20 * 2**20), ("1.5 GiB", int(1.5 * 2**30)),
    ("4096", 4096), (1024, 1024), ("512k", 512 * 1024),
])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "10 XB"])
def test_parse_size_rejects(bad):
    with pytest.raises(ValueError):
        parse_size(bad)


@pytest.mark.parametrize("raw,expected", [
    ("Keep the Witch Out of This Inn.rar", "Keep the Witch Out of This Inn.rar"),
    ("../../etc/passwd", "passwd"),
    ("a\\b\\c.txt", "c.txt"),
    ("..hidden", "hidden"),
    ('bad:name?.mp4', "bad_name_.mp4"),
    ("", "download"),
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_download_is_byte_identical(server, content, tmp_path):
    progress = []
    download = make(server, tmp_path, on_progress=progress.append, progress_interval=0)
    download.run()
    assert finish(download, tmp_path) == content
    assert progress[-1].done_bytes == len(content)
    assert progress[-1].parts_done == progress[-1].parts_total == len(download.parts)
    assert len(list((tmp_path / "parts").iterdir())) == len(download.parts)


def test_resume_continues_from_bytes_on_disk(server, content, tmp_path):
    first = make(server, tmp_path)
    first.part_dir.mkdir()
    p0, p1 = first.parts[0], first.parts[1]
    part_path(first.part_dir, 0).write_bytes(content[p0.start:p0.start + 12_345])
    part_path(first.part_dir, 1).write_bytes(content[p1.start:p1.end + 1])

    progress = []
    download = make(server, tmp_path, on_progress=progress.append, progress_interval=0)
    download.run()

    assert f"bytes={p0.start + 12_345}-{p0.end}" in server.ranges
    assert not any(r.startswith(f"bytes={p1.start}-") for r in server.ranges)
    assert progress[0].done_bytes >= 12_345 + p1.size
    assert finish(download, tmp_path) == content


def test_cancel_keeps_consistent_parts_and_resumes(server, content, tmp_path):
    server.delay = 0.05
    cancelled = threading.Event()
    download = make(server, tmp_path, cancelled=cancelled)
    threading.Timer(0.3, cancelled.set).start()
    with pytest.raises(Cancelled):
        download.run()

    stored = 0
    for part in download.parts:
        path = part_path(download.part_dir, part.index)
        if path.exists():
            data = path.read_bytes()
            assert data == content[part.start:part.start + len(data)]
            stored += len(data)
    assert 0 < stored < len(content)

    server.delay = 0
    resumed = make(server, tmp_path)
    resumed.run()
    assert finish(resumed, tmp_path) == content


def test_refused_links_raise_links_expired(server, tmp_path):
    server.refuse = True
    with pytest.raises(LinksExpired):
        make(server, tmp_path, links=2).run()


def test_server_ignoring_range_never_corrupts_parts(server, tmp_path):
    server.ignore_range = True
    download = make(server, tmp_path, links=2, stall_timeout=1)
    started = time.monotonic()
    with pytest.raises(DownloadStalled):
        download.run()
    assert time.monotonic() - started < 10
    assert all(not part_path(download.part_dir, p.index).exists()
               or part_path(download.part_dir, p.index).stat().st_size == 0
               for p in download.parts)


def test_claim_staging_skips_taken_names(tmp_path):
    (tmp_path / "a.bin.part").write_bytes(b"other writer")
    output, handle = claim_staging(tmp_path / "a.bin")
    handle.close()
    assert output == tmp_path / "a (1).bin"
    assert (tmp_path / "a (1).bin.part").exists()
    assert (tmp_path / "a.bin.part").read_bytes() == b"other writer"


def test_publish_staging_never_replaces(tmp_path):
    output, handle = claim_staging(tmp_path / "a.bin")
    with handle:
        handle.write(b"new")
    output.write_bytes(b"appeared meanwhile")
    final = publish_staging(staging_path(output), output)
    assert final == tmp_path / "a (1).bin"
    assert final.read_bytes() == b"new"
    assert output.read_bytes() == b"appeared meanwhile"
    assert not staging_path(output).exists()


def test_publish_staging_without_hard_links(tmp_path, monkeypatch):
    import errno
    import os

    def no_links(*args, **kwargs):
        raise OSError(errno.EPERM, "no links")

    monkeypatch.setattr(os, "link", no_links)
    output, handle = claim_staging(tmp_path / "b.bin")
    with handle:
        handle.write(b"data")
    assert publish_staging(staging_path(output), output).read_bytes() == b"data"
    assert not staging_path(output).exists()
