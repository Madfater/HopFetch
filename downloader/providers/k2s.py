"""Keep2Share (k2s.cc) free-tier provider, driven through the public `api/v2` endpoints."""

from __future__ import annotations

import logging
import re
from concurrent.futures import as_completed
from random import choice

import requests
from requests_futures.sessions import FuturesSession

from ..proxies import proxy_dict
from .base import (
    STATUS_GENERATING_LINKS,
    STATUS_PREPARING,
    STATUS_SOLVING_CAPTCHA,
    CaptchaSpec,
    FileInfo,
    FileRef,
    LinkContext,
    Provider,
    ProviderError,
)

log = logging.getLogger(__name__)

API_DOMAINS = ["k2s.cc"]
CAPTCHA = CaptchaSpec(length=6, charset="[a-z0-9]", lowercase=True)
MAX_WAIT = 30
MAX_ROUNDS = 3
URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?(?:k2s\.cc|keep2share\.cc)/file/(?P<id>[A-Za-z0-9]+)(?:[/?#].*)?$"
)


def _api(method: str) -> str:
    """Return the URL of an `api/v2` method on one of API_DOMAINS."""
    return f"https://{choice(API_DOMAINS)}/api/v2/{method}"


class K2SProvider(Provider):
    """Free downloads from k2s.cc.

    - One image captcha buys a `free_download_key`; each proxy (a different IP) may have to wait
      up to MAX_WAIT seconds first, and a longer wait moves on to the next proxy.
    - The key is exchanged for many links in parallel, up to MAX_ROUNDS rounds per proxy.
    - Each link allows one connection and is rate limited, so speed comes from many links.
    """

    name = "k2s"
    label = "Keep2Share"
    hosts = ("k2s.cc", "keep2share.cc")
    use_proxies = True
    link_ttl = 12 * 3600

    def match(self, url: str) -> str | None:
        """Return the file id of a `k2s.cc/file/<id>/...` or `keep2share.cc/file/<id>` URL."""
        found = URL_PATTERN.match(url.strip())
        return found.group("id") if found else None

    def get_info(self, ref: FileRef) -> FileInfo:
        """Read name and size from `getFilesInfo`."""
        try:
            data = requests.post(_api("getFilesInfo"), json={"ids": [ref.file_id]}, timeout=15).json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"Could not reach k2s: {exc}") from exc
        files = data.get("files") or []
        if not files or not files[0].get("is_available", True):
            raise ProviderError("File not found or no longer available on k2s")
        return FileInfo(name=files[0]["name"], size=files[0].get("size"))

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Solve the captcha, get a free download key through some proxy, then mint links."""
        file_id = ref.file_id
        ctx.set_status(STATUS_PREPARING, "Loading proxy list")
        proxies = ctx.proxies.all()
        challenge, answer = self._solve_captcha(ctx)
        links: list[str] = []
        last_error = "No proxy could obtain a free download key"

        for proxy in proxies:
            ctx.check_cancelled()
            where = proxy or "direct connection"
            ctx.set_status(STATUS_GENERATING_LINKS, f"Requesting a download key via {where}")
            key = None
            while key is None:
                try:
                    reply = requests.post(_api("getUrl"), json={
                        "file_id": file_id,
                        "captcha_challenge": challenge,
                        "captcha_response": answer,
                    }, proxies=proxy_dict(proxy), timeout=10).json()
                except (requests.RequestException, ValueError):
                    break
                if reply.get("status") == "error":
                    message = reply.get("message", "")
                    if message == "Invalid captcha code":
                        challenge, answer = self._solve_captcha(ctx)
                        continue
                    if message == "File not found":
                        raise ProviderError("File not found on k2s")
                    last_error = f"k2s: {message}"
                    break
                wait = int(reply.get("time_wait") or 0)
                if wait > MAX_WAIT or "free_download_key" not in reply:
                    last_error = f"k2s asked to wait {wait}s" if wait else last_error
                    break
                ctx.wait(wait, "Waiting for the free download slot")
                key = reply["free_download_key"]
            if key is None:
                continue
            links += self._links_from_key(file_id, key, proxy, count - len(links), ctx)
            if len(links) >= count:
                break

        if not links:
            raise ProviderError(last_error)
        return links[:count]

    def _solve_captcha(self, ctx: LinkContext) -> tuple[str, str]:
        """Fetch captcha images until the solver commits to an answer; return (challenge, answer)."""
        while True:
            ctx.check_cancelled()
            ctx.set_status(STATUS_SOLVING_CAPTCHA, "Solving the captcha")
            try:
                captcha = requests.post(_api("requestCaptcha"), timeout=15).json()
                image = requests.get(captcha["captcha_url"], timeout=15).content
            except (requests.RequestException, ValueError, KeyError) as exc:
                raise ProviderError(f"Could not fetch a captcha from k2s: {exc}") from exc
            answer = ctx.solve_captcha(image, CAPTCHA)
            if answer is not None:
                return captcha["challenge"], answer

    @staticmethod
    def _links_from_key(file_id: str, key: str, proxy: str | None, count: int,
                        ctx: LinkContext) -> list[str]:
        """Exchange a free download key for up to `count` links, stopping when a round adds none."""
        links: list[str] = []
        with FuturesSession(max_workers=5) as session:
            for _ in range(MAX_ROUNDS):
                if len(links) >= count:
                    break
                ctx.check_cancelled()
                futures = [
                    session.post(_api("getUrl"), json={"file_id": file_id, "free_download_key": key},
                                 proxies=proxy_dict(proxy), timeout=15)
                    for _ in range(count - len(links))
                ]
                before = len(links)
                for future in as_completed(futures):
                    try:
                        links.append(future.result().json()["url"])
                    except (requests.RequestException, KeyError, ValueError):
                        continue
                    ctx.set_status(STATUS_GENERATING_LINKS, f"Generated {len(links)}/{count} links")
                if len(links) == before:
                    break
        return links
