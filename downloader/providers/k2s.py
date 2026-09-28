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
MAX_COOLDOWN = 3600
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
    - Each link allows one connection, is rate limited, and binds to the first IP that fetches it,
      so speed comes from many links downloaded over the direct connection.
    """

    name = "k2s"
    label = "Keep2Share"
    hosts = ("k2s.cc", "keep2share.cc")
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
        """Solve the captcha, get a free download key through some proxy, then mint links.

        - Each proxy is a different IP; k2s makes an IP wait between free downloads.
        - When every IP must wait longer than MAX_WAIT, the job waits for the shortest cooldown,
          up to MAX_COOLDOWN, then tries that IP once more.
        """
        ctx.set_status(STATUS_PREPARING, "Loading proxy list")
        candidates = ctx.proxies.all()
        captcha = list(self._solve_captcha(ctx))
        links: list[str] = []
        last_error = "No proxy could obtain a free download key"

        for attempt in range(2):
            cooldowns: dict[str | None, int] = {}
            for proxy in candidates:
                ctx.check_cancelled()
                key, wait, error = self._request_key(ref.file_id, proxy, captcha, ctx)
                if wait is not None:
                    cooldowns[proxy] = wait
                last_error = error or last_error
                if key is None:
                    continue
                links += self._links_from_key(ref.file_id, key, proxy, count - len(links), ctx)
                if len(links) >= count:
                    break
            if links or not cooldowns or attempt == 1:
                break
            proxy, wait = min(cooldowns.items(), key=lambda item: item[1])
            if wait > MAX_COOLDOWN:
                break
            ctx.wait(wait + 5, "k2s allows the next free download in")
            candidates = [proxy]

        if not links:
            raise ProviderError(last_error)
        return links[:count]

    def _request_key(self, file_id: str, proxy: str | None, captcha: list[str],
                     ctx: LinkContext) -> tuple[str | None, int | None, str | None]:
        """Ask for a free download key through `proxy`; return (key, cooldown, error).

        - `captcha` holds [challenge, answer] and is replaced in place when k2s rejects it.
        - A wait up to MAX_WAIT is sat out here; a longer one is returned as the cooldown.
        """
        where = proxy or "direct connection"
        ctx.set_status(STATUS_GENERATING_LINKS, f"Requesting a download key via {where}")
        while True:
            try:
                reply = requests.post(_api("getUrl"), json={
                    "file_id": file_id,
                    "captcha_challenge": captcha[0],
                    "captcha_response": captcha[1],
                }, proxies=proxy_dict(proxy), timeout=10).json()
            except (requests.RequestException, ValueError) as exc:
                log.info("key request via %s failed: %s", where, exc)
                return None, None, None
            log.info("key request via %s: %s %s wait=%s", where, reply.get("status"),
                     reply.get("message"), reply.get("time_wait"))
            if reply.get("status") == "error":
                message = reply.get("message", "")
                if message == "Invalid captcha code":
                    captcha[:] = self._solve_captcha(ctx)
                    ctx.set_status(STATUS_GENERATING_LINKS, f"Requesting a download key via {where}")
                    continue
                if message == "File not found":
                    raise ProviderError("File not found on k2s")
                return None, None, f"k2s: {message}"
            wait = int(reply.get("time_wait") or 0)
            if wait > MAX_WAIT:
                return None, wait, f"k2s asked to wait {wait}s before the next free download"
            if "free_download_key" not in reply:
                return None, None, None
            ctx.wait(wait, "Waiting for the free download slot")
            return reply["free_download_key"], None, None

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
