# Architecture

Navigation map of the codebase. When this file and the code disagree, the code wins, so fix this file.

## Overview

k2s-downloader is a command line tool that downloads files from k2s.cc over the free tier. It solves one captcha by hand, then turns the resulting free download key into many download links. It fetches byte ranges of the file in parallel through a pool of public proxies. Unfinished downloads are kept as part files and can be resumed later.

## Layout

| Path | Responsibility |
| --- | --- |
| `main.py` | CLI entry point with the `dl`, `ls` and `continue` subcommands. Splits the file into ranges, runs one download thread per link, resumes part files, assembles the output, and checks it with ffmpeg |
| `k2s.py` | k2s.cc API client: `get_name` for file info, and `generate_download_urls`, which handles the captcha, the free download key and link generation across proxies |
| `utils.py` | `get_working_proxies`: fetches a proxy list from proxyscrape, tests each proxy, and caches the working ones in `proxies.txt` |
| `pyproject.toml`, `uv.lock` | Dependencies managed by uv: pillow, requests, requests-futures, tqdm |
| `script/` | Harness scripts: checks, GitHub client, apply |
| `docs/` | Knowledge |

Runtime files, all gitignored and created in the working directory:

| Path | Contents |
| --- | --- |
| `urls.json` | Map from file id to its generated download links, reused by later runs |
| `proxies.txt` | Cached working proxies, one `host:port` per line. Delete it to force a refresh |
| `urls.json.lock`, `proxies.txt.lock` | Lock files for cross-process `fcntl.flock` |
| `tmp/` | Part files named `{file_id}_{filename}.part{NN}` |
| `downloads/` | Assembled output files |
| `img/captcha.png` | The captcha image the user reads and answers on stdin |

## Data flow

1. `uv run main.py dl <url>`: importing `main.py` loads the proxy list through `get_working_proxies()`, which reads `proxies.txt` or builds it from the network.
2. `cmd_download` extracts the file id from the URL, reads the name through `k2s.get_name` unless `--filename` is given, and looks for cached links in `urls.json`.
3. If fewer than `--threads` links are cached, `k2s.generate_download_urls` requests a captcha, saves it to `img/captcha.png`, and reads the answer from stdin. It then tries proxies in order until one yields a `free_download_key`, and posts to `getUrl` concurrently until it has enough links. The links are written back to `urls.json`.
4. `main()` reads the file size with a HEAD request, splits it into ranges of `--split-size` bytes, and counts part files already in `tmp/`. It then dispatches one thread per free link. Each thread takes a proxy, streams its `Range` request in append mode, and marks the range done when the part reaches the expected size.
5. When every range is done, the parts are concatenated in order into `downloads/<filename>` and deleted.
6. If `ffmpeg` is on PATH, `check_vid` checks the output. A corrupt file is downloaded once more with double the split size.

`ls` lists incomplete downloads found in `tmp/`. `continue [file_id]` resumes them, and generates new links when the cached ones are too few.

## Invariants

- `urls.json` and `proxies.txt` are only read and written under `file_lock`, so several processes can run at once. `fcntl` is POSIX only, so the tool runs on Linux and macOS but not on native Windows.
- Importing `main.py` has side effects: it fetches and tests proxies over the network. Checks therefore compile the sources with `py_compile` rather than importing them.
- Index 0 of the proxy list is `None`, meaning a direct connection with no proxy.
- A part file's size equals the bytes already downloaded for its range. Resuming depends on this, so a failed chunk keeps its partial file and never truncates it.
- The part file name encodes the file id before the first `_`. `ls` and `continue` parse it back, so file ids must not contain `_`.
- `dl` rejects a split size under 20 MiB.
- The downloader needs a terminal. Link generation blocks on `input()` for the captcha.
