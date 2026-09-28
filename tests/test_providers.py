"""URL matching and the registry."""

from __future__ import annotations

import pytest

from downloader.providers import ProviderRegistry, default_registry
from downloader.providers.base import CaptchaSpec, FileRef, ProviderError
from downloader.providers.direct import DirectProvider
from downloader.providers.k2s import K2SProvider

TARGET = "https://k2s.cc/file/8d028cc29f08b/Keep%20the%20Witch%20Out%20of%20This%20Inn.rar"


@pytest.mark.parametrize("url", [
    TARGET,
    "https://k2s.cc/file/8d028cc29f08b",
    "https://k2s.cc/file/8d028cc29f08b/",
    "http://k2s.cc/file/8d028cc29f08b?site=x",
    "https://keep2share.cc/file/8d028cc29f08b/name.rar",
    "  https://www.k2s.cc/file/8d028cc29f08b#top  ",
])
def test_k2s_matches_file_links(url):
    assert K2SProvider().match(url) == "8d028cc29f08b"


@pytest.mark.parametrize("url", [
    "https://k2s.cc/folder/abc",
    "https://example.com/file/8d028cc29f08b",
    "k2s.cc/file/8d028cc29f08b",
])
def test_k2s_rejects_other_urls(url):
    assert K2SProvider().match(url) is None


def test_registry_prefers_platform_over_direct():
    provider, ref = default_registry().resolve(TARGET)
    assert provider.name == "k2s"
    assert ref == FileRef(url=TARGET, file_id="8d028cc29f08b")


def test_registry_falls_back_to_direct():
    provider, ref = default_registry().resolve("https://example.com/a/b.zip")
    assert provider.name == "direct"
    assert len(ref.file_id) == 16


def test_registry_rejects_unsupported_page_on_owned_host():
    with pytest.raises(ProviderError, match="not a file link"):
        default_registry().resolve("https://k2s.cc/folder/abc")


@pytest.mark.parametrize("url", ["ftp://example.com/x", "not a url", ""])
def test_registry_rejects_non_http(url):
    with pytest.raises(ProviderError):
        default_registry().resolve(url)


def test_register_adds_provider_first():
    class Fake(DirectProvider):
        name = "fake"

        def match(self, url):
            return "id" if "fake.test" in url else None

    registry = ProviderRegistry([DirectProvider()])
    registry.register(Fake())
    assert registry.resolve("https://fake.test/x")[0].name == "fake"
    assert registry.get("fake").name == "fake"


def test_direct_get_info(server, content):
    info = DirectProvider().get_info(FileRef(server.url, "x"))
    assert info.name == "sample.bin"
    assert info.size == len(content)


def test_direct_get_info_requires_ranges(server):
    server.ignore_range = True
    with pytest.raises(ProviderError, match="ranged"):
        DirectProvider().get_info(FileRef(server.url, "x"))


@pytest.mark.parametrize("raw,expected", [
    ("s7g3bO", "s7g3bo"),
    ("gS5hrn", "gs5hrn"),
    ("35g2u", None),
    ("ab-cd12", "abcd12"),
    ("ab_c12", None),
    ("", None),
])
def test_captcha_spec_normalize(raw, expected):
    assert CaptchaSpec(length=6).normalize(raw) == expected
