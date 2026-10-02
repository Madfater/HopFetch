"""Serving finished files by descriptor: opening inside the root, ranges and If-Range."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from downloader.files import disposition, etag_of, file_response, open_in_root, parse_range


@pytest.mark.parametrize("header,expected", [
    (None, None),
    ("bytes=0-9", (0, 9)),
    ("bytes=5-", (5, 99)),
    ("bytes=-10", (90, 99)),
    ("bytes=90-500", (90, 99)),
    ("bytes=100-", "unsatisfiable"),
    ("bytes=0-1,5-6", None),
    ("items=0-1", None),
    ("bytes=-", None),
    ("bytes=5-3", None),
])
def test_parse_range(header, expected):
    assert parse_range(header, 100) == expected


def test_open_in_root_refuses_symlinks_and_other_places(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.bin").write_bytes(b"data")
    secret = tmp_path / "secret.txt"
    secret.write_text("proxy credentials")
    (root / "link.bin").symlink_to(secret)
    (root / "inner.bin").symlink_to(root / "real.bin")
    (root / "sub").mkdir()
    os.mkfifo(root / "pipe")

    fd, info = open_in_root(root, root / "real.bin")
    os.close(fd)
    assert info.st_size == 4
    for name in ("link.bin", "inner.bin", "sub", "pipe", "missing.bin"):
        assert open_in_root(root, root / name) is None, name
    assert open_in_root(root, tmp_path / "secret.txt") is None
    assert open_in_root(root, root / "sub" / ".." / "real.bin") is None


def test_disposition_keeps_unicode_and_quotes_safely():
    value = disposition('影片 "1".mkv')
    assert "filename*=utf-8''%E5%BD%B1%E7%89%87%20%221%22.mkv" in value
    assert '"' not in value.split('filename="')[1].split('";')[0]


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(bytes(range(100)))
    app = FastAPI()

    @app.get("/f")
    def serve(request: Request):
        fd, info = open_in_root(tmp_path, path)
        return file_response(fd, info, "f.bin", request.headers.get("range"), request.headers.get("if-range"))

    return TestClient(app), path


def test_ranges_and_if_range(client):
    test_client, path = client
    full = test_client.get("/f")
    assert (full.status_code, full.content, full.headers["accept-ranges"]) == (200, bytes(range(100)), "bytes")
    etag = full.headers["etag"]
    assert etag == etag_of(os.stat(path))

    part = test_client.get("/f", headers={"Range": "bytes=10-19"})
    assert (part.status_code, part.content, part.headers["content-range"]) == (206, bytes(range(10, 20)), "bytes 10-19/100")

    matched = test_client.get("/f", headers={"Range": "bytes=10-19", "If-Range": etag})
    assert matched.status_code == 206
    stale = test_client.get("/f", headers={"Range": "bytes=10-19", "If-Range": '"old"'})
    assert (stale.status_code, len(stale.content)) == (200, 100)

    beyond = test_client.get("/f", headers={"Range": "bytes=200-"})
    assert (beyond.status_code, beyond.headers["content-range"]) == (416, "bytes */100")


def _closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


def _serve(tmp_path, receive, send, spec="2.3"):
    """Run a DescriptorResponse for a 4 MiB file through ASGI; return its descriptor."""
    import asyncio

    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * (4 * 1024 * 1024))
    fd, info = open_in_root(tmp_path, path)
    response = file_response(fd, info, "big.bin", None, None)
    scope = {"type": "http", "asgi": {"spec_version": spec}, "method": "GET", "headers": []}

    async def run():
        try:
            await response(scope, receive, send)
        except Exception:
            pass

    asyncio.run(run())
    return fd


def test_descriptor_closes_when_the_client_is_gone_before_the_body(tmp_path):
    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        raise OSError("client gone")

    assert _closed(_serve(tmp_path, receive, send, spec="2.4"))


def test_descriptor_closes_when_the_client_leaves_mid_stream(tmp_path):
    import asyncio

    sent = []

    async def receive():
        await asyncio.sleep(0.05)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message["type"])
        await asyncio.sleep(0.01)

    fd = _serve(tmp_path, receive, send)
    assert "http.response.start" in sent and _closed(fd)


def test_descriptor_closes_after_a_complete_answer(tmp_path):
    import asyncio

    async def receive():
        await asyncio.sleep(10)
        return {"type": "http.disconnect"}

    body = []

    async def send(message):
        body.append(message.get("body", b""))

    fd = _serve(tmp_path, receive, send)
    assert len(b"".join(body)) == 4 * 1024 * 1024 and _closed(fd)


def test_an_unsent_response_closes_its_descriptor(tmp_path):
    import gc

    path = tmp_path / "f.bin"
    path.write_bytes(b"data")
    fd, info = open_in_root(tmp_path, path)
    response = file_response(fd, info, "f.bin", None, None)
    del response
    gc.collect()
    assert _closed(fd)
