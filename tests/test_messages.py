"""Translation catalogs in shared/i18n and the keys the backend sends."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from downloader.messages import CATALOG_DIR, CodedError, catalog, render

LOCALES = ["zh-Hant-TW", "en"]
SOURCE = Path(__file__).resolve().parent.parent / "downloader"
KEY_LITERAL = re.compile(r'"((?:messages|errors)\.[a-z_]+)"')
CODE_LITERAL = re.compile(r'(?:Error|__init__|_error\(\d+,)\s*\(?\s*"([a-z_]+)"')
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def flat(locale: str) -> dict[str, str]:
    """Every `namespace.key` of a catalog with its text."""
    return {f"{ns}.{key}": text for ns, entries in catalog(locale).items() for key, text in entries.items()}


def source_text() -> str:
    return "\n".join(p.read_text() for p in SOURCE.rglob("*.py"))


def test_catalog_files_are_the_supported_locales():
    assert sorted(p.stem for p in CATALOG_DIR.glob("*.json")) == sorted(LOCALES)


def test_locales_share_keys_and_placeholders():
    base = flat(LOCALES[0])
    for locale in LOCALES[1:]:
        other = flat(locale)
        assert other.keys() == base.keys(), locale
        for key, text in base.items():
            assert set(PLACEHOLDER.findall(other[key])) == set(PLACEHOLDER.findall(text)), (locale, key)


def test_every_key_the_backend_uses_exists():
    keys = flat(LOCALES[0])
    used = set(KEY_LITERAL.findall(source_text()))
    assert used and used <= keys.keys(), sorted(used - keys.keys())


def test_every_error_code_has_a_default_key():
    keys = flat(LOCALES[0])
    codes = set(CODE_LITERAL.findall(source_text()))
    assert {"not_found", "invalid_state", "captcha_failed"} <= codes
    missing = sorted(code for code in codes if f"errors.{code}" not in keys)
    assert missing == []


def test_render_fills_params_and_keeps_unknown_keys():
    assert render("messages.captcha_attempt", {"n": 3}) == "辨識驗證碼（第 3 次）"
    assert render("messages.nope") == "messages.nope"
    error = CodedError("quota_exceeded", "errors.quota_exceeded_wait", provider="K", minutes=5)
    assert error.as_error() == {"code": "quota_exceeded", "key": "errors.quota_exceeded_wait",
                                "params": {"provider": "K", "minutes": 5},
                                "message": "K 要求等待約 5 分鐘才能再次免費下載。稍後再試一次。"}


@pytest.mark.parametrize("code", ["not_found", "internal_error"])
def test_coded_error_defaults_to_errors_namespace(code):
    assert CodedError(code).key == f"errors.{code}"
