"""URL matching and the registry, driven by the test cases shared with the frontend."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from downloader.providers import default_registry
from downloader.providers.base import CaptchaSpec, ProviderError, normalize_url

CASES = json.loads((Path(__file__).parent.parent / "shared" / "provider-test-cases.json").read_text())
PORTABLE_REGEX = re.compile(r"\(\?P?<|\(\?[aiLmsux]")


@pytest.mark.parametrize("case", CASES, ids=[c["url"] or "<empty>" for c in CASES])
def test_shared_cases(case):
    registry = default_registry()
    if case["provider"] is None:
        with pytest.raises(ProviderError) as info:
            registry.resolve(case["url"])
        assert info.value.code in ("invalid_url", "unsupported")
    else:
        provider, ref = registry.resolve(case["url"])
        assert (provider.name, ref.file_id) == (case["provider"], case["file_id"])


def test_patterns_use_the_portable_subset():
    for provider in default_registry().all():
        assert provider.patterns
        for pattern in provider.patterns:
            assert not PORTABLE_REGEX.search(pattern), pattern
            assert re.compile(pattern).groups >= 1


@pytest.mark.parametrize("url,code", [
    ("not a url", "invalid_url"),
    ("ftp://k2s.cc/file/abc", "invalid_url"),
    ("https://example.com/a.zip", "unsupported"),
    ("https://k2s.cc/folder/abc", "unsupported"),
])
def test_registry_error_codes(url, code):
    with pytest.raises(ProviderError) as info:
        default_registry().resolve(url)
    assert info.value.code == code


def test_normalize_url_lowercases_scheme_and_host_only():
    assert normalize_url("  HTTPS://K2S.CC/file/AbC?Q=X  ") == "https://k2s.cc/file/AbC?Q=X"


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


def test_providers_snapshot_matches_the_registry():
    snapshot = json.loads((Path(__file__).resolve().parent.parent / "shared" / "providers.json").read_text())
    live = [{"id": p.name, "name": p.label, "icon": p.icon, "patterns": list(p.patterns)}
            for p in default_registry().all()]
    assert snapshot == live, "refresh shared/providers.json from GET /api/providers"
