"""Dropbox link rewriting, info and error mapping against scripted answers, and a parallel
download through single-use redirects on a local server."""

from __future__ import annotations

import itertools
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from downloader.engine import SegmentedDownload, assemble, build_parts
from downloader.providers import default_registry, dropbox
from downloader.providers.base import FileRef, LinkContext, ProviderError

SCL = "https://www.dropbox.com/scl/fi/r2jlil9lj0ypo2fpl3fxa/massw_metadata_v1.jsonl?rlkey=ohnriak63x4ekyli25naajp0q&dl=0"
LEGACY = "https://www.dropbox.com/s/d1kjpkqklf0uw77/celeba.zip?dl=0"


@pytest.mark.parametrize("url,expected", [
    (SCL, "https://www.dropbox.com/scl/fi/r2jlil9lj0ypo2fpl3fxa/massw_metadata_v1.jsonl"
          "?rlkey=ohnriak63x4ekyli25naajp0q&dl=1"),
    ("https://dropbox.com/scl/fi/abc/x.zip?st=s1&rlkey=k1&raw=1&pwd=secret#frag",
     "https://www.dropbox.com/scl/fi/abc/x.zip?st=s1&rlkey=k1&dl=1"),
    (LEGACY, "https://www.dropbox.com/s/d1kjpkqklf0uw77/celeba.zip?dl=1"),
    ("https://dl.dropbox.com/s/d1kjpkqklf0uw77/celeba.zip", "https://www.dropbox.com/s/d1kjpkqklf0uw77/celeba.zip?dl=1"),
])
def test_download_url_forces_dl_and_keeps_rlkey(url, expected):
    assert dropbox.download_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.dropbox.com/scl/fi/abc/x.zip?dl=0",
    "https://www.dropbox.com/scl/fi/abc/x.zip?rlkey=&dl=0",
])
def test_an_scl_link_without_rlkey_is_an_invalid_url(url):
    with pytest.raises(ProviderError) as info:
        dropbox.download_url(url)
    assert (info.value.code, info.value.key) == ("invalid_url", "errors.invalid_url_rlkey")


@pytest.mark.parametrize("value,name", [
    ("attachment; filename=\"a.zip\"; filename*=UTF-8''%E6%AA%94%E6%A1%88%20a.zip", "檔案 a.zip"),
    ('attachment; filename="plain name.bin"', "plain name.bin"),
    ("attachment; filename=bare.bin", "bare.bin"),
    ("attachment; filename*=bogus''x.bin; filename=\"fallback.bin\"", "fallback.bin"),
    ("inline", None),
    ("", None),
])
def test_filename_from_disposition(value, name):
    assert dropbox.filename_from_disposition(value) == name


class Answer:
    """A streamed `requests` response with scripted status, headers and body."""

    def __init__(self, status=206, headers=None, body=b""):
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.body = body

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def answer(monkeypatch):
    """Install one scripted answer for `requests.get`; returns the list of requests made."""
    calls = []

    def install(reply):
        def get(url, headers=None, stream=False, timeout=None):
            calls.append((url, headers))
            if isinstance(reply, Exception):
                raise reply
            return reply
        monkeypatch.setattr(dropbox.requests, "get", get)
        return calls
    return install


def ref_for(url: str) -> FileRef:
    return default_registry().resolve(url)[1]


def test_get_info_reads_size_and_name_from_the_first_byte(answer):
    calls = answer(Answer(206, {"Content-Range": "bytes 0-0/896241496", "Content-Type": "application/binary",
                                "Content-Disposition": "attachment; filename=\"m.jsonl\"; "
                                                       "filename*=UTF-8''massw_metadata_v1.jsonl"}))
    info = dropbox.DropboxProvider().get_info(ref_for(SCL))
    assert (info.name, info.size) == ("massw_metadata_v1.jsonl", 896241496)
    url, headers = calls[0]
    assert url.endswith("rlkey=ohnriak63x4ekyli25naajp0q&dl=1") and headers["Range"] == "bytes=0-0"


def test_get_info_falls_back_to_the_name_in_the_link(answer):
    answer(Answer(200, {"Content-Length": "42", "Content-Type": "application/zip"}))
    info = dropbox.DropboxProvider().get_info(ref_for("https://www.dropbox.com/s/d1kjpkqklf0uw77/my%20file.zip"))
    assert (info.name, info.size) == ("my file.zip", 42)


def test_get_info_falls_back_to_the_id_without_a_name(answer):
    answer(Answer(206, {"Content-Range": "bytes 0-0/7"}))
    info = dropbox.DropboxProvider().get_info(ref_for("https://www.dropbox.com/s/d1kjpkqklf0uw77"))
    assert (info.name, info.size) == ("d1kjpkqklf0uw77", 7)


def page(title: str) -> Answer:
    body = f"<!DOCTYPE html><html><head><title>{title}</title></head><body>{'x' * 40000}</body></html>"
    return Answer(200, {"Content-Type": "text/html; charset=utf-8"}, body.encode())


@pytest.mark.parametrize("reply,code,key", [
    (page("Log in to Dropbox"), "private", "errors.private"),
    (page("Dropbox - Password required"), "private", "errors.private_password"),
    (page("Dropbox - Invalid Link - Simplify your life"), "not_found", "errors.not_found"),
    (page("Dropbox - Error - Simplify your life"), "not_found", "errors.not_found"),
    (page("Dropbox"), "upstream_error", "errors.upstream_error"),
    (Answer(429, {"Content-Type": "text/html"}), "quota_exceeded", "errors.quota_exceeded"),
    (Answer(404), "not_found", "errors.not_found"),
    (Answer(500), "upstream_error", "errors.upstream_error"),
    (requests.ConnectionError(), "upstream_error", "errors.upstream_error"),
])
def test_pages_and_statuses_map_to_codes(answer, reply, code, key):
    answer(reply)
    with pytest.raises(ProviderError) as info:
        dropbox.DropboxProvider().get_info(ref_for(SCL))
    assert (info.value.code, info.value.key) == (code, key)


def test_generate_links_hands_out_the_share_link_per_connection(answer):
    calls = answer(AssertionError("no request is needed"))
    statuses = []
    ctx = LinkContext(solve_captcha=lambda image, spec: None,
                      set_status=lambda phase, key, **params: statuses.append((phase, key)), proxies=None)
    links = dropbox.DropboxProvider().generate_links(ref_for(LEGACY), 3, ctx)
    assert links == ["https://www.dropbox.com/s/d1kjpkqklf0uw77/celeba.zip?dl=1"] * 3
    assert statuses == [("links", "messages.links_generated")] and calls == []


class SingleUseRedirects:
    """`/share` redirects to a fresh `/blob/<n>`, which serves one ranged answer and then 403."""

    def __init__(self, content: bytes):
        self.content = content
        self.issued = itertools.count(1)
        self.used: set[str] = set()
        self.refused = 0
        lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/share?dl=1":
                    self.send_response(302)
                    self.send_header("Location", f"/blob/{next(server.issued)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                with lock:
                    reused = self.path in server.used
                    server.used.add(self.path)
                    server.refused += reused
                found = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
                if reused or not found:
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start, end = int(found.group(1)), int(found.group(2))
                body = server.content[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(server.content)}")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", "1717556154680691d")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/share?dl=1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def test_the_share_link_downloads_in_parallel_through_single_use_redirects(content, tmp_path):
    server = SingleUseRedirects(content)
    try:
        part_dir = tmp_path / "parts"
        part_dir.mkdir()
        split = 100_000
        SegmentedDownload([server.url] * 4, len(content), part_dir, split, headers={},
                          cancelled=threading.Event()).run()
        out = tmp_path / "out.bin"
        with out.open("wb") as handle:
            assemble(part_dir, build_parts(len(content), split), handle)
        assert out.read_bytes() == content
        assert server.refused == 0 and len(server.used) == len(build_parts(len(content), split))
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
