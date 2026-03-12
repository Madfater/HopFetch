import os
import sys
import fcntl
import pathlib
from contextlib import contextmanager
from concurrent.futures import as_completed

import requests
from requests_futures.sessions import FuturesSession
from tqdm import tqdm

PROXIES_PATH = pathlib.Path("proxies.txt")


@contextmanager
def file_lock(lock_path: str):
    """跨 process 的檔案鎖，防止多個 process 同時讀寫同一檔案"""
    lock_file = open(lock_path, "a")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def get_working_proxies(refresh: bool = False):
    """取得可用的 proxy 清單，優先從快取檔案讀取"""
    with file_lock("proxies.txt.lock"):
        if PROXIES_PATH.exists() and not refresh:
            proxy_urls = [None] + PROXIES_PATH.read_text().splitlines()
            return proxy_urls

        proxies = []

        print("找不到 proxy 快取，從 api.proxyscrape.com 取得中...")
        try:
            r = requests.get(
                "https://api.proxyscrape.com/?request=getproxies"
                "&proxytype=https&timeout=10000&country=all&ssl=all&anonymity=all",
                timeout=15,
            )
            proxies += r.text.splitlines()
            r = requests.get(
                "https://api.proxyscrape.com/?request=getproxies"
                "&proxytype=http&timeout=10000&country=all&ssl=all&anonymity=all",
                timeout=15,
            )
            proxies += r.text.splitlines()
        except requests.RequestException as e:
            print(f"取得 proxy 清單失敗: {e}")
            return [None]

        working_proxies = []
        print(f"正在檢查 {len(proxies)} 個 proxy...")

        session = FuturesSession(max_workers=100)
        futures = []

        for proxy in proxies:
            future = session.get(
                'https://api.myip.com',
                proxies={'https': f'http://{proxy}'},
                timeout=5,
            )
            future.proxy = proxy
            futures.append(future)

        for future in tqdm(as_completed(futures), total=len(futures)):
            try:
                future.result()
                working_proxies.append(future.proxy)
            except KeyboardInterrupt:
                sys.exit()
            except (requests.RequestException, OSError):
                continue

        PROXIES_PATH.write_text("\n".join(working_proxies))

        # 跨平台清除螢幕
        os.system("cls" if os.name == "nt" else "clear")

        return [None] + working_proxies
