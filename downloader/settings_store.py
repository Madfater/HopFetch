"""Editable settings shared by every user, stored in `DATA_DIR/settings.json`."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .util import MIN_SPLIT_SIZE, file_lock

log = logging.getLogger(__name__)


@dataclass
class Preferences:
    """The settings the UI may change; the download root is not among them."""

    connections: int
    split_size: int
    use_proxies: bool
    max_active_jobs: int

    def validate(self) -> None:
        """Raise ValueError with a zh-Hant message when a value is out of range."""
        if not 1 <= self.connections <= 64:
            raise ValueError("連線數必須介於 1 到 64 之間。")
        if self.split_size < MIN_SPLIT_SIZE:
            raise ValueError("分段大小至少要 20 MiB。")
        if not 1 <= self.max_active_jobs <= 10:
            raise ValueError("同時下載數必須介於 1 到 10 之間。")


FALLBACK = Preferences(connections=20, split_size=20 * 2**20, use_proxies=True, max_active_jobs=2)


def _defaults(settings: Settings) -> Preferences:
    """The environment's initial values, each replaced by FALLBACK when it is out of range."""
    prefs = Preferences(settings.connections, settings.split_size, settings.use_proxies,
                        settings.max_active_jobs)
    for name in ("connections", "split_size", "max_active_jobs"):
        try:
            Preferences(**(asdict(FALLBACK) | {name: getattr(prefs, name)})).validate()
        except ValueError:
            log.warning("ignoring out-of-range %s=%r from the environment", name, getattr(prefs, name))
            setattr(prefs, name, getattr(FALLBACK, name))
    return prefs


class SettingsStore:
    """Reads and writes `settings.json`.

    - Missing or unreadable values fall back to the environment defaults in `Settings`, and
      out-of-range environment values fall back to FALLBACK.
    - Writes go to a temporary sibling that replaces the file, under a cross-process lock.
    """

    def __init__(self, settings: Settings):
        self.path = settings.data_dir / "settings.json"
        self._defaults = _defaults(settings)
        self._lock = threading.Lock()
        self._current = self._load()

    def get(self) -> Preferences:
        """Return a copy of the current settings."""
        with self._lock:
            return Preferences(**asdict(self._current))

    def update(self, changes: dict) -> Preferences:
        """Apply `changes` over the current settings, validate, save and return the result."""
        with self._lock:
            merged = Preferences(**(asdict(self._current) | changes))
            merged.validate()
            self._write(merged)
            self._current = merged
            return Preferences(**asdict(merged))

    def _load(self) -> Preferences:
        """Read the file over the defaults, ignoring unknown keys and invalid content."""
        base = asdict(self._defaults)
        try:
            with file_lock(self._lock_path()):
                stored = json.loads(self.path.read_text()) if self.path.exists() else {}
            prefs = Preferences(**(base | {k: v for k, v in stored.items() if k in base}))
            prefs.validate()
            return prefs
        except (OSError, ValueError, TypeError) as exc:
            log.warning("ignoring %s: %s", self.path, exc)
            return Preferences(**base)

    def _write(self, prefs: Preferences) -> None:
        """Replace the file with `prefs`."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        with file_lock(self._lock_path()):
            tmp.write_text(json.dumps(asdict(prefs), indent=2))
            tmp.replace(self.path)

    def _lock_path(self) -> Path:
        """Cross-process lock file guarding `settings.json`."""
        return self.path.with_name(self.path.name + ".lock")
