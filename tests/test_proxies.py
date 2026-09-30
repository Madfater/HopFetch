"""Proxy URL helpers and pool ordering, using cache files only."""

from __future__ import annotations

from downloader.config import Settings
from downloader.proxies import (
    ProxyPool,
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
