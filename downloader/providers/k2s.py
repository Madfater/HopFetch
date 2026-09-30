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
            raise ProviderError("upstream_error", "暫時無法連線到 Keep2Share。稍後再試一次。") from exc
        files = data.get("files") if isinstance(data, dict) else None
        info = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else None
        if info is None or not info.get("is_available", True):
            raise ProviderError("not_found", "找不到這個檔案，可能已被刪除。")
        access = info.get("access")
        if access == "private":
            raise ProviderError("private", "這個檔案是私人檔案，需要擁有者開放分享後才能下載。")
        if access == "premium":
            raise ProviderError("premium_only", "這個檔案只開放付費會員下載。")
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
        ctx.set_status(PHASE_LINKS, "載入代理清單")
        candidates = ctx.proxies.all()
        captcha = list(self._solve_captcha(ctx))
        links: list[str] = []
        last_error = ProviderError("upstream_error", "無法取得免費下載的授權。稍後再試一次。")

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
            ctx.wait(wait + 5, "等待冷卻")
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
        where = "直接連線" if proxy is None else proxy_label(proxy)
        ctx.set_status(PHASE_LINKS, f"透過 {where} 取得下載授權")
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
                    ctx.set_status(PHASE_LINKS, f"透過 {where} 取得下載授權")
                    continue
                if message == "File not found":
                    raise ProviderError("not_found", "找不到這個檔案，可能已被刪除。")
                if any(hint in message.lower() for hint in QUOTA_HINTS):
                    return None, None, ProviderError(
                        "quota_exceeded", "Keep2Share 的免費下載額度已用完。稍後再試一次。")
                return None, None, ProviderError("upstream_error", "Keep2Share 拒絕了下載要求。稍後再試一次。")
            wait = int(reply.get("time_wait") or 0)
            if wait > MAX_WAIT:
                minutes = -(-wait // 60)
                return None, wait, ProviderError(
                    "quota_exceeded", f"Keep2Share 要求等待約 {minutes} 分鐘才能再次免費下載。稍後再試一次。")
            if "free_download_key" not in reply:
                return None, None, None
            ctx.wait(wait, "等待下載名額")
            return reply["free_download_key"], None, None

    def _solve_captcha(self, ctx: LinkContext) -> tuple[str, str]:
        """Fetch captcha images until the solver commits to an answer; return (challenge, answer)."""
        while True:
            ctx.check_cancelled()
            ctx.set_status(PHASE_CAPTCHA, "辨識驗證碼")
            try:
                captcha = requests.post(_api("requestCaptcha"), timeout=15).json()
                image = requests.get(captcha["captcha_url"], timeout=15).content
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("captcha fetch failed: %s", exc)
                raise ProviderError("upstream_error", "暫時無法從 Keep2Share 取得驗證碼。稍後再試一次。") from exc
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
                    ctx.set_status(PHASE_LINKS, f"已取得 {len(links)}/{count} 條連結")
                if len(links) == before:
                    break
        return links
