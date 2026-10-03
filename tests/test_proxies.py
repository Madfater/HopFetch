"""Proxy URL helpers and pool ordering, using cache files only."""

from __future__ import annotations

import requests

from downloader import proxies
from downloader.config import Settings
from downloader.proxies import (
    ProxyPool,
    fetch_candidates,
    parse_source,
    parse_proxy_lines,
    proxy_dict,
    proxy_label,
    proxy_url,
    redact_credentials,
)


def test_proxy_url_and_dict():
    assert proxy_url("1.1.1.1:80") == "http://1.1.1.1:80"
    assert proxy_url("socks5h://u:p@host:1080") == "socks5h://u:p@host:1080"
    assert proxy_dict(None) is None
    assert proxy_dict("1.1.1.1:80") == {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}
    assert proxy_dict("socks5h://h:1080")["https"] == "socks5h://h:1080"


def test_proxy_label_hides_credentials():
    assert proxy_label(None) == "direct connection"
    assert proxy_label("1.1.1.1:80") == "http://1.1.1.1:80"
    assert proxy_label("socks5h://user:secret@proxy.example:1080") == "socks5h://proxy.example:1080"
    assert proxy_label("http://user:secret@[::1]:3128") == "http://[::1]:3128"
    assert "secret" not in proxy_label("http://user:secret@host")
    assert proxy_label("http://u:secret@[::1:80") == "http://***@[::1:80"


def test_redact_credentials():
    text = "Cannot connect to proxy socks5h://user:secret@host:1080 and http://a:b@c"
    assert redact_credentials(text) == "Cannot connect to proxy socks5h://***@host:1080 and http://***@c"


def test_parse_proxy_lines_keeps_duplicates():
    text = "# my proxies\nhttp://a:1\n\n  socks5h://b:2 , http://a:1  # rotating\n#http://off:3\n"
    assert parse_proxy_lines(text) == ["http://a:1", "socks5h://b:2", "http://a:1"]
    assert parse_proxy_lines("") == []


def test_pool_order_direct_user_public(tmp_path):
    (tmp_path / "proxies.txt").write_text("1.1.1.1:80\n2.2.2.2:80")
    (tmp_path / "proxies.user.txt").write_text("socks5h://u:p@file:1080\n")
    pool = ProxyPool(tmp_path / "proxies.txt", user_proxies=["http://env:3128"],
                     user_file=tmp_path / "proxies.user.txt")
    assert pool.status() == {"loaded": False, "public_enabled": True, "user": 0, "public": 0}
    assert pool.all() == [None, "http://env:3128", "socks5h://u:p@file:1080", "1.1.1.1:80", "2.2.2.2:80"]
    assert pool.status() == {"loaded": True, "public_enabled": True, "user": 2, "public": 2}
    assert (tmp_path / "proxies.user.txt").read_text() == "socks5h://u:p@file:1080\n"
    assert (tmp_path / "proxies.txt").read_text() == "1.1.1.1:80\n2.2.2.2:80"


def test_disabled_pool_keeps_user_proxies(tmp_path):
    (tmp_path / "proxies.txt").write_text("1.1.1.1:80")
    pool = ProxyPool(tmp_path / "proxies.txt", enabled=False, user_proxies=["http://env:3128"],
                     user_file=tmp_path / "missing.txt")
    assert pool.all() == [None, "http://env:3128"]
    assert pool.status()["public"] == 0


def test_settings_read_proxies_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXIES", "http://a:1, socks5h://u:p@b:2")
    assert Settings.from_env().proxies == ["http://a:1", "socks5h://u:p@b:2"]
    monkeypatch.delenv("PROXIES")
    assert Settings.from_env().proxies == []


def test_public_proxies_follow_the_runtime_switch(tmp_path):
    (tmp_path / "proxies.txt").write_text("9.9.9.9:80")
    pool = ProxyPool(tmp_path / "proxies.txt", enabled=False, user_proxies=["http://u.example:1"])
    assert pool.all() == [None, "http://u.example:1"]
    pool.enabled = True
    assert pool.all() == [None, "http://u.example:1", "9.9.9.9:80"]
    assert pool.status() == {"loaded": True, "public_enabled": True, "user": 1, "public": 1}
    pool.enabled = False
    assert pool.all() == [None, "http://u.example:1"]


class FakeSources:
    """Stands in for `FuturesSession`, answering each source URL with scripted text or an error."""

    def __init__(self, answers: dict):
        self.answers = answers

    def __call__(self, max_workers=None):
        return self

    def get(self, url, timeout=None):
        answer = self.answers[url]

        class Future:
            def result(self):
                if isinstance(answer, Exception):
                    raise answer
                return type("Response", (), {"text": answer})()

        return Future()

    def close(self):
        pass


def test_parse_source_handles_list_formats():
    text = ("1.2.3.4:80\nhttp://5.6.7.8:3128\n9.9.9.9:8080:Indonesia\n  10.0.0.1:1080 US\n"
            "# comment\n\nnot a proxy\n1.1.1.1:0\n1.1.1.1:70000\n1.1.1.1\n")
    assert parse_source(text, "http") == ["1.2.3.4:80", "5.6.7.8:3128", "9.9.9.9:8080",
                                          "10.0.0.1:1080"]
    assert parse_source("socks5://2.2.2.2:1080\n3.3.3.3:9050\n", "socks5h") == [
        "socks5h://2.2.2.2:1080", "socks5h://3.3.3.3:9050"]


def test_fetch_candidates_interleaves_dedupes_and_skips_failures(monkeypatch):
    monkeypatch.setattr(proxies, "PROXY_SOURCES", [("a", "http"), ("b", "http"), ("c", "socks5h"),
                                                   ("d", "http")])
    monkeypatch.setattr(proxies, "FuturesSession", FakeSources({
        "a": "1.1.1.1:80\n2.2.2.2:80\n3.3.3.3:80",
        "b": "2.2.2.2:80\n4.4.4.4:80",
        "c": "5.5.5.5:1080",
        "d": requests.ConnectionError("down"),
    }))
    assert fetch_candidates() == ["1.1.1.1:80", "2.2.2.2:80", "socks5h://5.5.5.5:1080",
                                  "4.4.4.4:80", "3.3.3.3:80"]


def test_fetch_candidates_cap_keeps_every_source(monkeypatch):
    monkeypatch.setattr(proxies, "MAX_CANDIDATES", 4)
    monkeypatch.setattr(proxies, "PROXY_SOURCES", [("a", "http"), ("b", "socks5h")])
    monkeypatch.setattr(proxies, "FuturesSession", FakeSources({
        "a": "\n".join(f"1.1.1.{i}:80" for i in range(10)),
        "b": "\n".join(f"2.2.2.{i}:1080" for i in range(10)),
    }))
    assert fetch_candidates() == ["1.1.1.0:80", "socks5h://2.2.2.0:1080", "1.1.1.1:80",
                                  "socks5h://2.2.2.1:1080"]
