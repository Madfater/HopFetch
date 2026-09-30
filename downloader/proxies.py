"""Shared pool of public HTTP proxies, used to request download keys from different IPs."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import as_completed
from pathlib import Path
from typing import Callable

import requests
from requests_futures.sessions import FuturesSession

from .util import file_lock

log = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://api.proxyscrape.com/?request=getproxies&proxytype=https&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=10000&country=all&ssl=all&anonymity=all",
]
TEST_URL = "https://api.myip.com"


def proxy_dict(proxy: str | None) -> dict | None:
    """Return a `requests` proxies mapping for `host:port`, or None for a direct connection."""
    return {"https": f"http://{proxy}"} if proxy else None


class ProxyPool:
    """Thread-safe list of proxies, where index 0 is always `None` (direct connection).

    - `load()` reads the cache file, or fetches proxy lists and keeps the ones that answer TEST_URL.
    - The cache file is read and written under a cross-process lock.
    - While `enabled` is False, `all()` returns only the direct connection and loads nothing.
      The flag may change at runtime.
    """

    def __init__(self, cache_path: Path, enabled: bool = True):
        self.cache_path = cache_path
        self.enabled = enabled
        self._proxies: list[str | None] = [None]
        self._loaded = threading.Event()
        self._load_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        """True once `load()` has finished."""
        return self._loaded.is_set()

    def load(self, refresh: bool = False, on_status: Callable[[str], None] | None = None) -> None:
        """Populate the pool once; later calls return at once unless `refresh` is set."""
        with self._load_lock:
            if self._loaded.is_set() and not refresh:
                return
            proxies = self._read_or_build(refresh, on_status)
            self._proxies = [None, *proxies]
            self._loaded.set()
            log.info("proxy pool ready with %d proxies", len(proxies))

    def all(self) -> list[str | None]:
        """Return the proxy list, loading it first when needed; only `[None]` while disabled."""
        if not self.enabled:
            return [None]
        self.load()
        return list(self._proxies)

    def _read_or_build(self, refresh: bool, on_status: Callable[[str], None] | None) -> list[str]:
        """Read the cache file, or fetch and test proxies and write the cache."""
        with file_lock(self.cache_path.with_name(self.cache_path.name + ".lock")):
            if self.cache_path.exists() and not refresh:
                return [p for p in self.cache_path.read_text().splitlines() if p.strip()]
            candidates: list[str] = []
            for source in PROXY_SOURCES:
                try:
                    candidates += requests.get(source, timeout=15).text.split()
                except requests.RequestException as exc:
                    log.warning("proxy source failed: %s", exc)
            if on_status:
                on_status(f"Testing {len(candidates)} public proxies")
            working = self._test(candidates)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text("\n".join(working))
            return working

    @staticmethod
    def _test(candidates: list[str]) -> list[str]:
        """Return the candidates that can reach TEST_URL within 5 seconds."""
        if not candidates:
            return []
        session = FuturesSession(max_workers=100)
        futures = {}
        for proxy in candidates:
            futures[session.get(TEST_URL, proxies=proxy_dict(proxy), timeout=5)] = proxy
        working = []
        for future in as_completed(futures):
            try:
                future.result()
                working.append(futures[future])
            except (requests.RequestException, OSError):
                continue
        session.close()
        return working
