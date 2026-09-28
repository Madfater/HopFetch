"""Shared fixtures: a local HTTP server that serves one file with Range support."""

from __future__ import annotations

import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class RangeServer:
    """Serves `content` at `/file.bin`, recording each Range header it receives.

    - `refuse` makes every request answer 403, as an expired link does.
    - `ignore_range` answers 200 with the whole body, as a server without range support does.
    - `delay` sleeps between 16 KiB blocks, to make a download slow enough to interrupt.
    """

    def __init__(self, content: bytes):
        self.content = content
        self.ranges: list[str] = []
        self.refuse = False
        self.ignore_range = False
        self.delay = 0.0
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
                found = re.fullmatch(r"bytes=(\d+)-(\d*)", rng or "")
                if found and not server.ignore_range:
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
