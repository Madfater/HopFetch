import re
import json
import math
import time
import fcntl
import pathlib
import argparse
import threading
import subprocess
from shutil import which
from typing import Dict, List
from contextlib import contextmanager

import requests
from tqdm import tqdm

import k2s
from utils import get_working_proxies

WORKING_PROXY_LIST = []
PROXIES = get_working_proxies()
PROXIES_LOCK = [threading.Lock() for _ in range(len(PROXIES))]

URL_LOCKS = None
START_TIME = time.time()

TMP_DIR = pathlib.Path("tmp")
DOWNLOAD_DIR = pathlib.Path("downloads")
BYTES_PER_SPLIT = 1024 * 1024 * 16
BLOCK_SIZE = 1024 * 32


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


def read_urls_json() -> dict:
    """安全讀取 urls.json（帶檔案鎖）"""
    urls_path = pathlib.Path("urls.json")
    with file_lock("urls.json.lock"):
        if not urls_path.exists():
            return {}
        return json.loads(urls_path.read_text())


def write_urls_json(data: dict) -> None:
    """安全寫入 urls.json（帶檔案鎖）"""
    urls_path = pathlib.Path("urls.json")
    with file_lock("urls.json.lock"):
        urls_path.write_text(json.dumps(data, indent=4))


def parse_size(size: str) -> int:
    """將大小字串轉換為 bytes 數值"""
    units = {
        "B": 1, "KB": 2**10, "MB": 2**20, "GB": 2**30, "TB": 2**40,
        "": 1, "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40,
    }
    m = re.match(r'^([\d\.]+)\s*([a-zA-Z]{0,3})$', str(size).strip())
    if not m:
        raise ValueError(f"無法解析大小: {size}")
    number, unit = float(m.group(1)), m.group(2).upper()
    if unit not in units:
        raise ValueError(f"不支援的單位: {unit}")
    return int(number * units[unit])


def human_readable_bytes(num: int) -> str:
    """將 bytes 數值轉換為人類可讀的格式"""
    for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0 or unit == 'TB':
            return f"{num:.3f} {unit}"
        num /= 1024.0


def build_range(value: int, numsplits: int) -> Dict:
    """將檔案大小分割成多個下載範圍"""
    range_dict = {}
    chunk_size = value // numsplits

    for i in range(numsplits):
        start = i * chunk_size
        # 最後一個分割包含剩餘的所有 bytes
        end = value - 1 if i == numsplits - 1 else (i + 1) * chunk_size - 1
        size = end - start + 1
        range_dict[str(i)] = {
            "inUse": False,
            "downloaded": False,
            "range": f"{start}-{end}",
            "bytes": size,
        }

    return range_dict


def _acquire_proxy() -> tuple:
    """取得可用的 proxy，回傳 (proxy_idx, proxy_dict, prefix)"""
    # 優先嘗試已知可用的 proxy
    for i in WORKING_PROXY_LIST:
        if PROXIES_LOCK[i].acquire(blocking=False):
            break
    else:
        # 嘗試取得任何未鎖定的 proxy
        for i in range(len(PROXIES)):
            if PROXIES_LOCK[i].acquire(blocking=False):
                break
        else:
            # 全部都在使用中，阻塞等待第一個可用的
            PROXIES_LOCK[0].acquire()
            i = 0

    if PROXIES[i]:
        prox = {'https': f'http://{PROXIES[i]}'}
        prefix = f"[{PROXIES[i]}]"
    else:
        prox = None
        prefix = "[LOCAL]"

    return i, prox, prefix


def _part_path(file_id: str, filename: str, idx, total_digits: int) -> pathlib.Path:
    """產生暫存 part 檔案路徑"""
    return TMP_DIR / f"{file_id}_{filename}.part{str(idx).zfill(total_digits)}"


def main(urls: List[str], filename: str, file_id: str = "") -> None:

    if not urls:
        print("請提供 URL 以開始下載。")
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36"
    }
    stop = False
    done_count = 0
    done_lock = threading.Lock()

    sizeInBytes = requests.head(
        urls[-1], allow_redirects=True, headers=headers
    ).headers.get('Content-Length', None)
    if not sizeInBytes:
        print("無法取得檔案大小。")
        return

    sizeInBytes = int(sizeInBytes)
    print(f"{human_readable_bytes(sizeInBytes)} 待下載。")

    # 將總 bytes 數分割成多個範圍
    splitBy = math.ceil(sizeInBytes / BYTES_PER_SPLIT)
    ranges = build_range(sizeInBytes, splitBy)
    total_digits = len(str(splitBy))
    total_iter = tqdm(
        desc=f"[{done_count}/{len(ranges)}] Downloaded",
        total=sizeInBytes, unit='iB', unit_scale=True, unit_divisor=1024,
    )

    def download_chunk(idx, irange, th_idx):
        nonlocal done_count

        chunk_start_time = time.time()
        tmp_path = _part_path(file_id, filename, idx, total_digits)
        proxy_idx = None
        downloaded_bytes = 0

        try:
            proxy_idx, prox, _ = _acquire_proxy()

            try:
                req = requests.get(
                    urls[th_idx],
                    headers={"Range": f"bytes={irange}", "User-Agent": headers["User-Agent"]},
                    stream=True,
                    proxies=prox,
                    timeout=20,
                )
                req.raise_for_status()

                # 直接串流寫入磁碟，避免佔用記憶體
                with tmp_path.open("wb") as f:
                    for data in req.iter_content(BLOCK_SIZE):
                        if stop:
                            break
                        # 單個 chunk 超過 20 秒未收到資料則中斷
                        if time.time() - chunk_start_time > 20:
                            break
                        chunk_start_time = time.time()
                        total_iter.update(len(data))
                        downloaded_bytes += len(data)
                        f.write(data)
            except (requests.RequestException, OSError):
                pass  # 下載失敗，交由下方邏輯處理重試

            # 檢查下載完整性
            if not math.isclose(downloaded_bytes, ranges[idx]["bytes"], abs_tol=1):
                total_iter.update(-downloaded_bytes)
                # 清理不完整的暫存檔
                if tmp_path.exists():
                    tmp_path.unlink()
                ranges[idx]["inUse"] = False
            else:
                if proxy_idx is not None and proxy_idx not in WORKING_PROXY_LIST:
                    WORKING_PROXY_LIST.append(proxy_idx)
                ranges[idx]["inUse"] = False
                ranges[idx]["downloaded"] = True
                with done_lock:
                    done_count += 1
                total_iter.desc = f"[{done_count}/{len(ranges)}] Downloaded"
        finally:
            # 確保 lock 一定被釋放
            if proxy_idx is not None:
                try:
                    PROXIES_LOCK[proxy_idx].release()
                except RuntimeError:
                    pass
            try:
                URL_LOCKS[th_idx].release()
            except RuntimeError:
                pass

    try:
        while done_count < len(ranges):
            dispatched = False
            for idx, irange in ranges.items():
                if irange["inUse"] or irange["downloaded"]:
                    continue

                tmp_path = _part_path(file_id, filename, idx, total_digits)
                # 檢查是否已有完整的暫存檔（支援斷點續傳）
                if tmp_path.exists():
                    file_size = tmp_path.stat().st_size
                    if math.isclose(file_size, ranges[idx]["bytes"], abs_tol=1):
                        if not irange["downloaded"]:
                            total_iter.update(ranges[idx]["bytes"])
                            with done_lock:
                                done_count += 1
                            total_iter.desc = f"[{done_count}/{len(ranges)}] Downloaded"
                            irange["downloaded"] = True
                        continue
                    else:
                        tmp_path.unlink()

                for th_idx in range(batch_count):
                    if URL_LOCKS[th_idx].locked():
                        continue

                    URL_LOCKS[th_idx].acquire()
                    irange["inUse"] = True
                    dispatched = True
                    threading.Thread(
                        target=download_chunk,
                        args=(idx, irange["range"], th_idx),
                        daemon=True,
                    ).start()
                    break

            # 避免 CPU 空轉，短暫休眠後再檢查
            if not dispatched:
                time.sleep(0.1)

    except KeyboardInterrupt:
        stop = True
        print("\n正在停止下載中的 thread...")
        # 等待所有執行中的 thread 完成，避免檔案損壞
        for lock in URL_LOCKS:
            lock.acquire(blocking=True)
            lock.release()
        total_iter.close()
        print("下載已中止。")
        return

    # 等待所有下載 thread 完成
    for lock in URL_LOCKS:
        lock.acquire(blocking=True)
        lock.release()

    total_iter.close()
    print(f"--- {int(time.time() - START_TIME)} 秒 ---")

    output_path = DOWNLOAD_DIR / filename
    if output_path.exists():
        output_path.unlink()

    # 按照正確順序組裝檔案
    with output_path.open('wb') as fh:
        for idx in range(len(ranges)):
            tmp_path = _part_path(file_id, filename, idx, total_digits)
            fh.write(tmp_path.read_bytes())
            tmp_path.unlink()

    print(f"檔案寫入完成: {output_path}")
    print(f"檔案大小: {human_readable_bytes(output_path.stat().st_size)}")


def check_vid(video_path: pathlib.Path) -> bool:
    """使用 ffmpeg 檢查影片是否損壞"""
    try:
        output = subprocess.check_output(
            ['ffmpeg', '-i', str(video_path), '-c', 'copy',
             '-f', 'null', '/dev/null', '-v', 'warning'],
            stderr=subprocess.STDOUT,
        )
        return not bool(output)
    except subprocess.CalledProcessError:
        return False


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='K2S Downloader')
    parser.add_argument('url', help='k2s url to download', action='store')
    parser.add_argument('--filename', type=str,
                        help='filename to save as',
                        action='store', dest='filename')
    parser.add_argument('--threads', dest='batch_count', action='store',
                        help='number of connections to use (default 20)', default=20)
    parser.add_argument('--split-size', dest='size', action='store',
                        help='Size to split at (default 20M)', default=1024 * 1024 * 20)

    args = parser.parse_args()

    if "k2s.cc" not in args.url:
        print("無效的 URL")
        exit()

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = re.findall(r"https:\/\/(k2s.cc|keep2share.cc)\/file\/(.*?)(\?|\/|$)", args.url)
    if not file_id:
        print("無效的 URL")
        exit()

    if parse_size(args.size) < 1024 * 1024 * 20:
        print("分割大小必須至少為 20M")
        exit()

    file_id = file_id[0][1]
    if not args.filename:
        file_name = k2s.get_name(file_id)
    else:
        file_name = args.filename
    batch_count = int(args.batch_count)
    BYTES_PER_SPLIT = parse_size(args.size)

    past_urls = read_urls_json()

    urls = []
    if file_id in past_urls:
        urls = past_urls[file_id]

    if len(urls) < batch_count:
        urls = k2s.generate_download_urls(file_id, batch_count)

    past_urls[file_id] = urls
    write_urls_json(past_urls)

    URL_LOCKS = [threading.Lock() for _ in range(batch_count)]
    START_TIME = time.time()
    redownloaded = False

    while True:
        main(urls, file_name, file_id)
        if which("ffmpeg"):
            output_path = DOWNLOAD_DIR / file_name
            if not check_vid(output_path):
                if not redownloaded:
                    print("影片已損壞，正在以較大的 chunk size 重新下載。")
                    redownloaded = True
                    BYTES_PER_SPLIT *= 2
                    continue
                else:
                    print("影片仍然損壞，跳過。")
        break
