"""Keep2Share (k2s.cc) free-tier provider, driven through the public `api/v2` endpoints."""

from __future__ import annotations

import logging
from concurrent.futures import as_completed
from random import choice

import requests
from requests_futures.sessions import FuturesSession

from ..proxies import proxy_dict, proxy_label, redact_credentials
from .base import (
    PHASE_CAPTCHA,
    PHASE_LINKS,
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
URL_PATTERN = r"^https?://(?:www\.)?(?:k2s\.cc|keep2share\.cc)/file/([A-Za-z0-9]+)(?:[/?#].*)?$"
QUOTA_HINTS = ("limit", "quota", "traffic")


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
    icon = "k2s"
    patterns = (URL_PATTERN,)
    link_ttl = 12 * 3600

    def get_info(self, ref: FileRef) -> FileInfo:
        """Read name and size from `getFilesInfo`.

        - A missing or unavailable file is `not_found`; `access` of `private` or `premium`
          maps to `private` and `premium_only`, since a free download cannot get them.
        """
        try:
            data = requests.post(_api("getFilesInfo"), json={"ids": [ref.file_id]}, timeout=15).json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("getFilesInfo failed: %s", exc)
            raise ProviderError("upstream_error", provider=self.label) from exc
        files = data.get("files") if isinstance(data, dict) else None
        info = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else None
        if info is None or not info.get("is_available", True):
            raise ProviderError("not_found")
        access = info.get("access")
        if access == "private":
            raise ProviderError("private")
        if access == "premium":
            raise ProviderError("premium_only")
        try:
            size = int(info["size"]) if info.get("size") else None
        except (TypeError, ValueError):
            size = None
        return FileInfo(name=str(info.get("name") or ref.file_id), size=size)

    def generate_links(self, ref: FileRef, count: int, ctx: LinkContext) -> list[str]:
        """Solve the captcha, get a free download key through some proxy, then mint links.

        - Each proxy is a different IP; k2s makes an IP wait between free downloads.
        - When every IP must wait longer than MAX_WAIT, the job waits for the shortest cooldown,
          up to MAX_COOLDOWN, then tries that IP once more.
        """
        ctx.set_status(PHASE_LINKS, "messages.loading_proxies")
        candidates = ctx.proxies.all()
        captcha = list(self._solve_captcha(ctx))
        links: list[str] = []
        last_error = ProviderError("upstream_error", "errors.upstream_error_no_key", provider=self.label)

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
            ctx.wait(wait + 5, "messages.waiting_cooldown")
            candidates = [proxy]

        if not links:
            raise last_error
        return links[:count]

    def _request_key(self, file_id: str, proxy: str | None, captcha: list[str],
                     ctx: LinkContext) -> tuple[str | None, int | None, ProviderError | None]:
        """Ask for a free download key through `proxy`; return (key, cooldown, error).

        - `captcha` holds [challenge, answer] and is replaced in place when k2s rejects it.
        - A wait up to MAX_WAIT is sat out here; a longer one is returned as the cooldown.
        """
        where = proxy_label(proxy)
        self._report_key_request(proxy, ctx)
        while True:
            try:
                reply = requests.post(_api("getUrl"), json={
                    "file_id": file_id,
                    "captcha_challenge": captcha[0],
                    "captcha_response": captcha[1],
                }, proxies=proxy_dict(proxy), timeout=10).json()
            except (requests.RequestException, ValueError) as exc:
                log.info("key request via %s failed: %s", where, redact_credentials(str(exc)))
                return None, None, None
            log.info("key request via %s: %s %s wait=%s", where, reply.get("status"),
                     reply.get("message"), reply.get("time_wait"))
            if reply.get("status") == "error":
                message = reply.get("message", "")
                if message == "Invalid captcha code":
                    captcha[:] = self._solve_captcha(ctx)
                    self._report_key_request(proxy, ctx)
                    continue
                if message == "File not found":
                    raise ProviderError("not_found")
                if any(hint in message.lower() for hint in QUOTA_HINTS):
                    return None, None, ProviderError("quota_exceeded", provider=self.label)
                return None, None, ProviderError("upstream_error", "errors.upstream_error_refused",
                                                 provider=self.label)
            wait = int(reply.get("time_wait") or 0)
            if wait > MAX_WAIT:
                minutes = -(-wait // 60)
                return None, wait, ProviderError("quota_exceeded", "errors.quota_exceeded_wait",
                                                 provider=self.label, minutes=minutes)
            if "free_download_key" not in reply:
                return None, None, None
            ctx.wait(wait, "messages.waiting_free_slot")
            return reply["free_download_key"], None, None

    @staticmethod
    def _report_key_request(proxy: str | None, ctx: LinkContext) -> None:
        """Report which connection asks for a download key; proxies appear without credentials."""
        if proxy is None:
            ctx.set_status(PHASE_LINKS, "messages.requesting_key_direct")
        else:
            ctx.set_status(PHASE_LINKS, "messages.requesting_key_proxy", proxy=proxy_label(proxy))

    def _solve_captcha(self, ctx: LinkContext) -> tuple[str, str]:
        """Fetch captcha images until the solver commits to an answer; return (challenge, answer)."""
        while True:
            ctx.check_cancelled()
            ctx.set_status(PHASE_CAPTCHA, "messages.captcha_fetching")
            try:
                captcha = requests.post(_api("requestCaptcha"), timeout=15).json()
                image = requests.get(captcha["captcha_url"], timeout=15).content
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("captcha fetch failed: %s", exc)
                raise ProviderError("upstream_error", "errors.upstream_error_captcha",
                                    provider=self.label) from exc
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
                    ctx.set_status(PHASE_LINKS, "messages.links_generated", done=len(links), total=count)
                if len(links) == before:
                    break
        return links
