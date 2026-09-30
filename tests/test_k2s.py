"""K2S link generation against a scripted fake of the k2s API."""

from __future__ import annotations

import pytest

from downloader.providers import k2s
from downloader.providers.base import FileRef, LinkContext, ProviderError
from downloader.proxies import ProxyPool

REF = FileRef("https://k2s.cc/file/abc123/x.rar", "abc123")


class Reply:
    def __init__(self, data):
        self.data = data
        self.content = b"png"

    def json(self):
        return self.data


class FakeK2S:
    """Answers requestCaptcha, captcha images and getUrl from scripted key replies."""

    def __init__(self, key_replies):
        self.key_replies = list(key_replies)
        self.key_calls: list[tuple[str | None, str]] = []
        self.captchas = 0

    def post(self, url, json=None, proxies=None, timeout=None):
        if url.endswith("requestCaptcha"):
            self.captchas += 1
            return Reply({"challenge": f"c{self.captchas}", "captcha_url": "https://k2s.cc/captcha"})
        proxy = proxies["https"] if proxies else None
        self.key_calls.append((proxy, json["captcha_response"]))
        return Reply(self.key_replies.pop(0))

    def get(self, url, timeout=None):
        return Reply({})


@pytest.fixture
def ctx(tmp_path):
    pool = ProxyPool(tmp_path / "proxies.txt")
    (tmp_path / "proxies.txt").write_text("1.1.1.1:80\n2.2.2.2:80")
    context = LinkContext(solve_captcha=lambda image, spec: "abc123",
                          set_status=lambda state, message: None, proxies=pool)
    context.waits = []
    context.wait = lambda seconds, message: context.waits.append(seconds)
    return context


def install(monkeypatch, fake):
    monkeypatch.setattr(k2s.requests, "post", fake.post)
    monkeypatch.setattr(k2s.requests, "get", fake.get)
    monkeypatch.setattr(k2s.K2SProvider, "_links_from_key",
                        staticmethod(lambda file_id, key, proxy, count, ctx: [f"{key}-{i}" for i in range(count)]))


def test_short_wait_then_links(monkeypatch, ctx):
    fake = FakeK2S([{"status": "success", "time_wait": 30, "free_download_key": "K"}])
    install(monkeypatch, fake)
    assert k2s.K2SProvider().generate_links(REF, 3, ctx) == ["K-0", "K-1", "K-2"]
    assert ctx.waits == [30]


def test_invalid_captcha_is_resolved_again(monkeypatch, ctx):
    fake = FakeK2S([
        {"status": "error", "message": "Invalid captcha code"},
        {"status": "success", "time_wait": 0, "free_download_key": "K"},
    ])
    install(monkeypatch, fake)
    assert k2s.K2SProvider().generate_links(REF, 1, ctx) == ["K-0"]
    assert fake.captchas == 2


def test_waits_for_shortest_cooldown_then_retries(monkeypatch, ctx):
    fake = FakeK2S([
        {"status": "success", "time_wait": 2201},
        {"status": "success", "time_wait": 900},
        {"status": "success", "time_wait": 1500},
        {"status": "success", "time_wait": 0, "free_download_key": "K"},
    ])
    install(monkeypatch, fake)
    assert k2s.K2SProvider().generate_links(REF, 2, ctx) == ["K-0", "K-1"]
    assert ctx.waits == [905, 0]
    assert fake.key_calls[-1][0] == "http://1.1.1.1:80"


def test_cooldown_beyond_limit_fails_fast(monkeypatch, ctx):
    fake = FakeK2S([{"status": "success", "time_wait": 9999}] * 3)
    install(monkeypatch, fake)
    with pytest.raises(ProviderError, match="wait 9999s"):
        k2s.K2SProvider().generate_links(REF, 2, ctx)
    assert ctx.waits == []


def test_user_proxy_tried_second_without_leaking_credentials(monkeypatch, tmp_path):
    pool = ProxyPool(tmp_path / "proxies.txt", enabled=False,
                     user_proxies=["socks5h://user:secret@proxy.example:1080"])
    messages = []
    context = LinkContext(solve_captcha=lambda image, spec: "abc123",
                          set_status=lambda state, message: messages.append(message), proxies=pool)
    context.wait = lambda seconds, message: None
    fake = FakeK2S([
        {"status": "success", "time_wait": 2201},
        {"status": "success", "time_wait": 0, "free_download_key": "K"},
    ])
    install(monkeypatch, fake)
    assert k2s.K2SProvider().generate_links(REF, 1, context) == ["K-0"]
    assert [call[0] for call in fake.key_calls] == [None, "socks5h://user:secret@proxy.example:1080"]
    assert "Requesting a download key via socks5h://proxy.example:1080" in messages
    assert not any("secret" in message for message in messages)


def test_failed_key_request_log_hides_credentials(monkeypatch, tmp_path, caplog):
    proxy = "socks5h://user:secret@proxy.example:1080"
    pool = ProxyPool(tmp_path / "proxies.txt", enabled=False, user_proxies=[proxy])
    context = LinkContext(solve_captcha=lambda image, spec: "abc123",
                          set_status=lambda state, message: None, proxies=pool)
    fake = FakeK2S([{"status": "error", "message": "Download limit"}])
    install(monkeypatch, fake)

    def post(url, json=None, proxies=None, timeout=None):
        if proxies:
            raise k2s.requests.ConnectionError(f"Cannot connect to proxy {proxies['https']}")
        return fake.post(url, json=json, proxies=proxies, timeout=timeout)

    monkeypatch.setattr(k2s.requests, "post", post)
    with caplog.at_level("INFO", logger=k2s.log.name), pytest.raises(ProviderError):
        k2s.K2SProvider().generate_links(REF, 1, context)
    assert "socks5h://***@proxy.example:1080" in caplog.text
    assert "secret" not in caplog.text


def test_file_not_found(monkeypatch, ctx):
    install(monkeypatch, FakeK2S([{"status": "error", "message": "File not found"}]))
    with pytest.raises(ProviderError, match="not found"):
        k2s.K2SProvider().generate_links(REF, 2, ctx)
