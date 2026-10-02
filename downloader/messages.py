"""User-facing text as translation keys, rendered in zh-Hant-TW only as a fallback.

- The catalogs live in `shared/i18n/<locale>.json`, split into `messages` and `errors`, and use
  i18next's `{{name}}` interpolation, or `{{name, format}}` with a formatter from FORMATTERS. The frontend translates keys itself; the backend renders
  FALLBACK_LOCALE so every answer still carries readable text.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent.parent / "shared" / "i18n"
FALLBACK_LOCALE = "zh-Hant-TW"
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*(?:,\s*(\w+)\s*)?\}\}")


def _duration(seconds: float) -> str:
    """Whole seconds as `m:ss`, or `h:mm:ss` from one hour up."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


FORMATTERS = {"duration": _duration}


@lru_cache(maxsize=None)
def catalog(locale: str = FALLBACK_LOCALE) -> dict:
    """The parsed catalog of `locale`."""
    return json.loads((CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def render(key: str, params: dict | None = None) -> str:
    """The fallback text for `key` with `params` filled in; the key itself when it is unknown."""
    node: object = catalog()
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if not isinstance(node, str):
        return key
    values = params or {}

    def fill(found: re.Match) -> str:
        name, fmt = found.group(1), found.group(2)
        if name not in values:
            return found.group(0)
        return FORMATTERS[fmt](values[name]) if fmt in FORMATTERS else str(values[name])

    return _PLACEHOLDER.sub(fill, node)


class CodedError(Exception):
    """A failure with a stable `code`, a translation `key`, its `params` and fallback `message`.

    - `key` defaults to `errors.<code>`; a variant of the same code passes its own key, such as
      `errors.quota_exceeded_wait`.
    """

    def __init__(self, code: str, key: str | None = None, **params):
        self.code = code
        self.key = key or f"errors.{code}"
        self.params = params
        self.message = render(self.key, params)
        super().__init__(self.message)

    def as_error(self) -> dict:
        """The `{code, key, params, message}` object sent to clients."""
        return {"code": self.code, "key": self.key, "params": self.params, "message": self.message}
