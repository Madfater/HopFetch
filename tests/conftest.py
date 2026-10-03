"""Shared fixtures: a local HTTP server that serves one file with Range support, and a fake provider over it."""

from __future__ import annotations

import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from downloader.config import Settings
from downloader.jobs import JobManager
from downloader.providers import ProviderRegistry
from downloader.providers.base import (
    PHASE_CAPTCHA,
    CaptchaSpec,
    Decoder,
    FileInfo,
    FileRef,
    LinkContext,
    Provider,
    ProviderError,
)
from downloader.proxies import ProxyPool


class RangeServer:
    """Serves `content` at `/file.bin`, recording each Range header it receives.

    - `refuse` makes every request answer 403, as an expired link does.
    - `ignore_range` answers 200 with the whole body, as a server without range support does.
    - `delay` sleeps between 16 KiB blocks, to make a download slow enough to interrupt.
    - `etag` and `last_modified` are sent with every answer when set. A request whose If-Range
      matches neither gets the whole body with 200, as HTTP requires for a changed file.
    - `if_ranges` records the If-Range header of every request.
    """

    def __init__(self, content: bytes):
        self.content = content
        self.ranges: list[str] = []
        self.refuse = False
        self.ignore_range = False
        self.delay = 0.0
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.if_ranges: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                server.ranges.append(rng or "")
                if server.refuse:
                    self.send_response(403)
                    self.end_headers()
                    return
                body, status, extra = server.content, 200, {}
                if_range = self.headers.get("If-Range")
                server.if_ranges.append(if_range or "")
                current = {v for v in (server.etag, server.last_modified) if v}
                stale = if_range is not None and if_range not in current
                if server.etag:
                    extra["ETag"] = server.etag
                if server.last_modified:
                    extra["Last-Modified"] = server.last_modified
                found = re.fullmatch(r"bytes=(\d+)-(\d*)", rng or "")
                if found and not server.ignore_range and not stale:
                    start = int(found.group(1))
                    end = int(found.group(2)) if found.group(2) else len(server.content) - 1
                    body = server.content[start:end + 1]
                    status = 206
                    extra["Content-Range"] = f"bytes {start}-{end}/{len(server.content)}"
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", 'attachment; filename="sample.bin"')
                for key, value in extra.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    for i in range(0, len(body), 16 * 1024):
                        self.wfile.write(body[i:i + 16 * 1024])
                        if server.delay:
                            time.sleep(server.delay)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/file.bin"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        """Stop the server."""
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def content() -> bytes:
    """About 1.2 MB of random bytes."""
    return os.urandom(1_234_567)


@pytest.fixture
def server(content):
    """A running RangeServer for `content`."""
    srv = RangeServer(content)
    yield srv
    srv.close()


class FakeOcr:
    """Returns queued readings in order, then `default` forever."""

    def __init__(self, readings=(), default="abc123"):
        self.readings = list(readings)
        self.default = default
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return self.readings.pop(0) if self.readings else self.default


class XorDecoder(Decoder):
    """XORs every byte with `key`, counts what it saw, and fails `finish` when `corrupt`."""

    def __init__(self, key: int, corrupt: bool = False):
        self.key = key
        self.corrupt = corrupt
        self.seen = 0
        self.finished = False

    def update(self, data: bytes) -> bytes:
        self.seen += len(data)
        return bytes(b ^ self.key for b in data)

    def finish(self) -> None:
        self.finished = True
        if self.corrupt:
            raise ProviderError("integrity_failed")


class FakeProvider(Provider):
    """A platform at `https://fake.test/f/<id>` whose links all point at a RangeServer.

    - Link generation solves captchas until one reads `abc123`.
    - `names` maps file ids to remote names; others are `<id>.bin`.
    - `info_error` makes `get_info` raise it; `expire_first` makes the first links answer 410.
    - `xor` sets a one-byte `XorDecoder` for assembly; `corrupt` makes its `finish` fail.
    """

    name = "fake"
    label = "Fake host"
    icon = "fake"
    patterns = (r"^https?://fake\.test/f/([a-z0-9]+)$",)

    def __init__(self, server: RangeServer):
        self.server = server
        self.names: dict[str, str] = {}
        self.info_error: Exception | None = None
        self.size: int | None = len(server.content)
        self.link_calls = 0
        self.expire_first = False
        self.xor: int | None = None
        self.corrupt = False

    def decoder(self, ref: FileRef) -> Decoder | None:
        return None if self.xor is None else XorDecoder(self.xor, self.corrupt)

    def get_info(self, ref: FileRef) -> FileInfo:
        if self.info_error:
            raise self.info_error
        return FileInfo(name=self.names.get(ref.file_id, f"{ref.file_id}.bin"), size=self.size)

    def generate_links(self, ref, count, ctx: LinkContext):
        self.link_calls += 1
        while True:
            ctx.set_status(PHASE_CAPTCHA, "messages.captcha_fetching")
            if ctx.solve_captcha(b"png", CaptchaSpec(length=6)) == "abc123":
                break
        if self.expire_first and self.link_calls == 1:
            return [self.server.url.replace("/file.bin", "/gone")] * count
        return [self.server.url] * count


def wait_for(predicate, timeout=15.0):
    """Poll until `predicate()` is truthy or fail."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def build_manager(tmp_path, provider, ocr=None, bus=None, **overrides) -> JobManager:
    """A started JobManager over `provider`, with proxies off and data under `tmp_path`."""
    settings = Settings(data_dir=tmp_path / "data", download_dir=tmp_path / "downloads",
                        use_proxies=False, **overrides)
    manager = JobManager(settings, ProviderRegistry([provider]), bus=bus,
                         proxies=ProxyPool(settings.data_dir / "proxies.txt", enabled=False),
                         ocr=ocr or FakeOcr())
    manager.start()
    return manager


@pytest.fixture
def provider(server):
    """A FakeProvider backed by `server`."""
    return FakeProvider(server)
