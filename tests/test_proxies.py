"""Proxy URL helpers and pool ordering, using cache files only."""

from __future__ import annotations

import os
import threading
import time

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
            "# comment\n\nnot a proxy\n1.1.1.1:0\n1.1.1.1:70000\n1.1.1.1\n999.1.1.1:80\n"
            "010.001.002.003:0080\n")
    assert parse_source(text, "http") == ["1.2.3.4:80", "5.6.7.8:3128", "9.9.9.9:8080",
                                          "10.0.0.1:1080", "10.1.2.3:80"]
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


def age(path, seconds):
    """Set the mtime of `path` to `seconds` ago."""
    then = time.time() - seconds
    os.utime(path, (then, then))


def scripted_refresh(monkeypatch, candidates, working):
    """Replace fetching and testing; return the list of candidate batches that were tested."""
    tested = []
    monkeypatch.setattr(proxies, "fetch_candidates", lambda: list(candidates))
    monkeypatch.setattr(ProxyPool, "_test", staticmethod(lambda c: tested.append(c) or list(working)))
    return tested


def test_fresh_cache_is_not_refreshed(monkeypatch, tmp_path):
    cache = tmp_path / "proxies.txt"
    cache.write_text("1.1.1.1:80")
    tested = scripted_refresh(monkeypatch, ["2.2.2.2:80"], ["2.2.2.2:80"])
    pool = ProxyPool(cache)
    assert pool.all() == [None, "1.1.1.1:80"]
    assert pool._refresh_thread is None
    assert tested == []


def test_stale_cache_is_served_then_replaced(monkeypatch, tmp_path):
    cache = tmp_path / "proxies.txt"
    cache.write_text("1.1.1.1:80")
    age(cache, proxies.CACHE_MAX_AGE + 60)
    release = threading.Event()
    monkeypatch.setattr(proxies, "fetch_candidates", lambda: release.wait(5) and ["2.2.2.2:80"])
    monkeypatch.setattr(ProxyPool, "_test", staticmethod(list))
    pool = ProxyPool(cache)
    assert pool.all() == [None, "1.1.1.1:80"]
    assert pool._refresh_thread.is_alive()
    assert pool.all() == [None, "1.1.1.1:80"]
    release.set()
    pool._refresh_thread.join(5)
    assert pool.all() == [None, "2.2.2.2:80"]
    assert cache.read_text() == "2.2.2.2:80"
    assert pool._refresh_thread.is_alive() is False


def test_failed_refresh_keeps_the_old_list(monkeypatch, tmp_path):
    cache = tmp_path / "proxies.txt"
    cache.write_text("1.1.1.1:80\nsocks5h://3.3.3.3:1080")
    age(cache, proxies.CACHE_MAX_AGE + 60)
    tested = scripted_refresh(monkeypatch, ["2.2.2.2:80"], [])
    pool = ProxyPool(cache)
    pool.all()
    pool._refresh_thread.join(5)
    assert tested == [["2.2.2.2:80"]]
    assert pool.all() == [None, "1.1.1.1:80", "socks5h://3.3.3.3:1080"]
    assert cache.read_text() == "1.1.1.1:80\nsocks5h://3.3.3.3:1080"
    assert time.time() - cache.stat().st_mtime < 60


def test_disabled_pool_never_refreshes(monkeypatch, tmp_path):
    cache = tmp_path / "proxies.txt"
    cache.write_text("1.1.1.1:80")
    age(cache, proxies.CACHE_MAX_AGE + 60)
    scripted_refresh(monkeypatch, ["2.2.2.2:80"], ["2.2.2.2:80"])
    pool = ProxyPool(cache, enabled=False)
    assert pool.all() == [None]
    assert pool._refresh_thread is None


def test_missing_cache_is_built_from_fetched_candidates(monkeypatch, tmp_path):
    cache = tmp_path / "data" / "proxies.txt"
    tested = scripted_refresh(monkeypatch, ["1.1.1.1:80", "socks5h://2.2.2.2:1080"],
                              ["socks5h://2.2.2.2:1080"])
    pool = ProxyPool(cache)
    assert pool.all() == [None, "socks5h://2.2.2.2:1080"]
    assert tested == [["1.1.1.1:80", "socks5h://2.2.2.2:1080"]]
    assert cache.read_text() == "socks5h://2.2.2.2:1080"
    assert pool._refresh_thread is None


def test_refresh_ends_quietly_when_the_cache_is_gone(monkeypatch, tmp_path, caplog):
    cache = tmp_path / "proxies.txt"
    cache.write_text("1.1.1.1:80")
    age(cache, proxies.CACHE_MAX_AGE + 60)

    def vanish():
        cache.unlink()
        return ["2.2.2.2:80"]

    monkeypatch.setattr(proxies, "fetch_candidates", vanish)
    monkeypatch.setattr(ProxyPool, "_test", staticmethod(lambda candidates: []))
    pool = ProxyPool(cache)
    assert pool.all() == [None, "1.1.1.1:80"]
    pool._refresh_thread.join(5)
    assert pool.all() == [None, "1.1.1.1:80"]
    assert "proxy refresh failed" in caplog.text
