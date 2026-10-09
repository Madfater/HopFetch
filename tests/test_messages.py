"""Translation catalogs in shared/i18n and the keys the backend sends."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from downloader.messages import CATALOG_DIR, FORMATTERS, PERMANENT_ERRORS, CodedError, catalog, render, is_permanent

LOCALES = ["zh-Hant-TW", "en"]
SOURCE = Path(__file__).resolve().parent.parent / "downloader"
KEY_LITERAL = re.compile(r'"((?:messages|errors)\.[a-z0-9_]+)"')
CODE_LITERAL = re.compile(r'(?:Error|DuplicateTask|InvalidState|__init__)\(\s*"([a-z_]+)"'
                          r'|_error\([^,()]+(?:\.\w+)*,\s*"([a-z_]+)"')
PLURAL_SUFFIX = re.compile(r"_(?:zero|one|two|few|many|other)$")
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*(?:,\s*(\w+)\s*)?\}\}")


def flat(locale: str) -> dict[str, str]:
    """Every `namespace.key` of a catalog with its text, plural forms folded into the base key.

    - i18next plural variants such as `downloading_one` and `downloading_other` count as
      `downloading`; their placeholders are merged.
    """
    keys: dict[str, str] = {}
    for ns, entries in catalog(locale).items():
        for key, text in entries.items():
            base = f"{ns}.{PLURAL_SUFFIX.sub('', key)}"
            keys[base] = keys.get(base, "") + text
    return keys


def codes_in_source() -> set[str]:
    """Every error code passed as a string literal to an error constructor or `_error`."""
    return {a or b for a, b in CODE_LITERAL.findall(source_text())}


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


def test_plural_variants_are_complete():
    for locale in LOCALES:
        keys = {f"{ns}.{key}" for ns, entries in catalog(locale).items() for key in entries}
        for key in keys:
            if key.endswith("_one"):
                assert key[:-4] + "_other" in keys, (locale, key)


def test_every_key_the_backend_uses_exists():
    keys = flat(LOCALES[0])
    used = set(KEY_LITERAL.findall(source_text()))
    assert used and used <= keys.keys(), sorted(used - keys.keys())


def test_every_error_code_has_a_default_key():
    keys = flat(LOCALES[0])
    codes = codes_in_source()
    expected = {"not_found", "invalid_state", "captcha_failed", "duplicate_active",
                "duplicate_completed", "http_error", "insufficient_space", "invalid_settings",
                "task_not_found", "file_missing", "invalid_request", "method_not_allowed"}
    assert expected <= codes, sorted(expected - codes)
    missing = sorted(code for code in codes if f"errors.{code}" not in keys)
    assert missing == []


def test_formats_are_known_and_render():
    for locale in LOCALES:
        for key, text in flat(locale).items():
            for _, fmt in PLACEHOLDER.findall(text):
                assert not fmt or fmt in FORMATTERS, (locale, key, fmt)
    assert render("messages.waiting_cooldown", {"seconds": 750}) == "等待冷卻 12:30"
    assert render("messages.waiting_cooldown", {"seconds": 3725}) == "等待冷卻 1:02:05"


def test_render_fills_params_and_keeps_unknown_keys():
    assert render("messages.captcha_attempt", {"n": 3}) == "辨識驗證碼（第 3 次）"
    assert render("messages.nope") == "messages.nope"
    error = CodedError("quota_exceeded", "errors.quota_exceeded_wait", provider="K", count=5)
    assert error.as_error() == {"code": "quota_exceeded", "key": "errors.quota_exceeded_wait",
                                "params": {"provider": "K", "count": 5},
                                "message": "K 要求等待約 5 分鐘才能再次免費下載。稍後再試一次。"}


@pytest.mark.parametrize("code", ["not_found", "internal_error"])
def test_coded_error_defaults_to_errors_namespace(code):
    assert CodedError(code).key == f"errors.{code}"


def test_permanent_errors_exist_and_others_are_retryable():
    for key in PERMANENT_ERRORS:
        assert render(key) != key
    assert is_permanent("errors.range_unsupported")
    assert not is_permanent("errors.stalled")
    assert not is_permanent("errors.captcha_failed_ocr")
    assert not is_permanent(None)
