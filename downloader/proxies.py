"""Shared pool of proxies, used to request download keys from different IPs.

- User proxies come from the `PROXIES` setting and `proxies.user.txt`, as full URLs with any of
  the http, https, socks5 and socks5h schemes and optional credentials.
- Public HTTP proxies are fetched from PROXY_SOURCES, tested and cached in `proxies.txt`.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests
from requests_futures.sessions import FuturesSession

from .util import file_lock

log = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://api.proxyscrape.com/?request=getproxies&proxytype=https&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=10000&country=all&ssl=all&anonymity=all",
]
TEST_URL = "https://api.myip.com"


_CREDENTIALS = re.compile(r"://[^/@\s]+@")


def proxy_url(proxy: str) -> str:
    """Return `proxy` as a URL, adding `http://` to a bare `host:port`."""
    return proxy if "://" in proxy else f"http://{proxy}"


def proxy_dict(proxy: str | None) -> dict | None:
    """Return a `requests` proxies mapping for a proxy, or None for a direct connection."""
    if not proxy:
        return None
    url = proxy_url(proxy)
    return {"http": url, "https": url}


def proxy_label(proxy: str | None) -> str:
    """Return `scheme://host:port` without credentials, for logs and status messages."""
    if not proxy:
        return "direct connection"
    parts = urlsplit(proxy_url(proxy))
    host = parts.hostname or "?"
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{parts.scheme}://{host}:{port}" if port else f"{parts.scheme}://{host}"


def redact_credentials(text: str) -> str:
    """Replace `user:pass@` in any URL inside `text` with `***@`."""
    return _CREDENTIALS.sub("://***@", text)


def parse_proxy_lines(text: str) -> list[str]:
    """Split proxies on newlines, commas and spaces, dropping blanks and `#` comments.

    - Duplicates are kept, so a rotating endpoint listed N times is tried N times.
    - A `#`, comma or space inside a password must be percent-encoded, as in any URL.
    """
    proxies = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        proxies += line.replace(",", " ").split()
    return proxies


class ProxyPool:
    """Thread-safe list of proxies: `None` (direct connection), then user proxies, then public ones.

    - User proxies are `user_proxies` followed by the lines of `user_file`, read whenever the pool
      loads; they are neither tested nor written anywhere.
    - `load()` reads the public cache file, or fetches proxy lists and keeps the ones that answer
      TEST_URL.
    - The cache file is read and written under a cross-process lock.
    - `enabled=False` skips public proxies; user proxies still apply.
    """

    def __init__(self, cache_path: Path, enabled: bool = True,
                 user_proxies: list[str] | None = None, user_file: Path | None = None):
        self.cache_path = cache_path
        self.enabled = enabled
        self.user_proxies = list(user_proxies or [])
        self.user_file = user_file
        self._proxies: list[str | None] = [None]
        self._counts = (0, 0)
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
            user = self._read_user()
            public = self._read_or_build(refresh, on_status) if self.enabled else []
            self._proxies = [None, *user, *public]
            self._counts = (len(user), len(public))
            self._loaded.set()
            log.info("proxy pool ready with %d user and %d public proxies", len(user), len(public))

    def all(self) -> list[str | None]:
        """Return the proxy list, loading it first when needed."""
        self.load()
        return list(self._proxies)

    def status(self) -> dict:
        """Return pool counts without proxy addresses and without triggering a load."""
        user, public = self._counts
        return {"loaded": self.loaded, "public_enabled": self.enabled, "user": user, "public": public}

    def _read_user(self) -> list[str]:
        """Return `user_proxies` followed by the proxies listed in `user_file`."""
        proxies = list(self.user_proxies)
        if self.user_file is not None:
            try:
                proxies += parse_proxy_lines(self.user_file.read_text())
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("could not read %s: %s", self.user_file, exc)
        return proxies

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
