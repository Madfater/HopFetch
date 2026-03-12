import sys
import time
import requests
import contextlib
from io import BytesIO
from random import choice
from concurrent.futures import as_completed

from PIL import Image
from pathlib import Path
from tqdm import tqdm
from requests_futures.sessions import FuturesSession

from utils import get_working_proxies

DOMAINS = [
    # "keep2share.cc",
    "k2s.cc",
    # "tezfiles.com",
    # "fboom.me",
    # "fast-download.me"
]


def generate_from_key(url: str, key: str, proxy: str, max_retries: int = 5) -> str:
    """使用 free_download_key 產生下載連結"""
    if proxy:
        prox = {'https': f'http://{proxy}'}
    else:
        prox = None

    for attempt in range(max_retries):
        try:
            r = requests.post(f"https://{choice(DOMAINS)}/api/v2/getUrl", json={
                "file_id": url,
                "free_download_key": key
            }, proxies=prox, timeout=10).json()
            return r['url']
        except (requests.RequestException, KeyError, ValueError):
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 10))
            continue

    raise RuntimeError(f"嘗試 {max_retries} 次後仍無法產生下載連結")


def generate_download_urls(file_id: str, count: int = 1, skip: int = 0) -> list:
    """產生多個下載連結"""
    if skip > 0:
        proxy_urls = get_working_proxies()[skip:]
    else:
        proxy_urls = get_working_proxies()
    working_link = False
    free_download_key = ""
    urls = []
    captcha = requests.post(f"https://{choice(DOMAINS)}/api/v2/requestCaptcha").json()
    r = requests.get(captcha["captcha_url"])
    im = Image.open(BytesIO(r.content))

    path = Path("img")
    path.mkdir(parents=True, exist_ok=True)
    im.save(path / "captcha.png")
    response = input("Enter captcha response: ")

    for url in proxy_urls:
        print(f"\033[KTrying {url}", end='\r')
        prox = {'https': f'http://{url}'}
        if not url:
            prox = None
        while not working_link:
            try:
                free_r = requests.post(f"https://{choice(DOMAINS)}/api/v2/getUrl", json={
                    "file_id": file_id,
                    "captcha_challenge": captcha["challenge"],
                    "captcha_response": response
                }, proxies=prox, timeout=5).json()
            except KeyboardInterrupt:
                sys.exit()
            except (requests.RequestException, ValueError):
                break

            if free_r['status'] == "error":
                if free_r["message"] == "Invalid captcha code":
                    r = requests.get(captcha["captcha_url"])
                    im = Image.open(BytesIO(r.content))
                    im.save(path / "captcha.png")
                    response = input("Enter captcha response: ")
                    continue
                elif free_r["message"] == "File not found":
                    sys.exit("File not found")

            if "time_wait" not in free_r:
                working_link = True
                break

            if free_r['time_wait'] > 30:
                break

            for i in range(free_r['time_wait'] - 1):
                print(f"\033[K[{url}] Waiting {free_r['time_wait'] - i} seconds...", end='\r')
                time.sleep(1)

            free_download_key = free_r['free_download_key']
            working_link = True

        if working_link:

            session = FuturesSession(max_workers=5)

            # 產生下載連結
            while len(urls) < count:
                futures = []
                to_generate = count - len(urls)
                for _ in range(to_generate):
                    future = session.post(f"https://{choice(DOMAINS)}/api/v2/getUrl", json={
                        "file_id": file_id,
                        "free_download_key": free_download_key
                    }, proxies=prox)
                    futures.append(future)

                for future in tqdm(as_completed(futures), total=len(futures), leave=False):
                    try:
                        result = future.result()
                        urls.append(result.json()['url'])
                    except KeyboardInterrupt:
                        sys.exit()
                    except (requests.RequestException, KeyError, ValueError):
                        continue

    if not working_link:
        raise Exception("找不到可用的連結")

    return urls[:count]


def get_name(file_id: str) -> str:
    """取得檔案名稱"""
    r = requests.post(f"https://{choice(DOMAINS)}/api/v2/getFilesInfo", json={
        "ids": [file_id]
    }).json()
    return r['files'][0]['name']
