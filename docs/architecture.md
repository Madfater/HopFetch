# Architecture

Navigation map of the codebase. When this file and the code disagree, the code wins, so fix this file.

## Overview

A web app that downloads files from file hosting platforms over many connections at once. A FastAPI backend runs download jobs in background threads and serves a React dashboard. Each platform is a provider: it turns a user's URL into file info and a list of direct links. A shared engine then fetches byte ranges over those links in parallel into resumable part files.

Keep2Share (k2s.cc) is the main provider. Its free tier gives each link one rate-limited connection after an image captcha. The app solves the captcha with offline OCR, falls back to asking the user in the browser, and turns one free download key into many links.

## Layout

| Path | Responsibility |
| --- | --- |
| `downloader/app.py` | App factory and the `app` instance for uvicorn. Starts and stops the job manager, preloads proxies, serves `web/dist` at `/` |
| `downloader/api.py` | REST routes under `/api`: providers, resolve, jobs, captcha, pause, resume, delete, file |
| `downloader/jobs.py` | `JobManager`: job state machine, one worker thread per job, `jobs.json` persistence, link reuse and regeneration |
| `downloader/engine.py` | `SegmentedDownload`: splits the file into ranges, one connection per link, resumable part files, `assemble` |
| `downloader/captcha.py` | `OcrSolver` (ddddocr) and `CaptchaSession`, which tries OCR and then hands the image to the UI |
| `downloader/proxies.py` | `ProxyPool`: public proxies fetched from proxyscrape, tested, cached in `proxies.txt` |
| `downloader/providers/base.py` | `Provider` interface, `FileRef`, `FileInfo`, `CaptchaSpec`, `LinkContext`, `ProviderError` |
| `downloader/providers/__init__.py` | `ProviderRegistry` and `default_registry()` |
| `downloader/providers/k2s.py` | Keep2Share free tier over `api/v2` |
| `downloader/providers/direct.py` | Any http(s) URL whose server answers Range requests |
| `downloader/config.py`, `downloader/util.py` | `Settings` from environment variables; file lock, size parsing, safe file names |
| `web/` | Vite, React and TypeScript dashboard. `src/api.ts` is the typed API client |
| `tests/` | pytest suite. `conftest.py` has a local Range server used by the engine, job and API tests |
| `script/` | Harness scripts: checks, GitHub client, apply |
| `docs/` | Knowledge |
| `Dockerfile`, `compose.yaml` | Container image and service, see [Docker](#docker) |

## Running

```bash
uv sync                                   # backend dependencies
npm --prefix web ci                       # frontend dependencies
npm --prefix web run build                # build web/dist, served by the backend
uv run uvicorn downloader.app:app         # http://127.0.0.1:8000
npm --prefix web run dev                  # optional: Vite dev server, proxies /api to :8000
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_DIR` | `./data` | `jobs.json`, `proxies.txt`, part files |
| `DOWNLOAD_DIR` | `./downloads` | Finished files |
| `CAPTCHA_OCR` | `1` | `0` skips OCR and always asks in the browser |
| `USE_PROXIES` | `1` | `0` requests download keys over the direct connection only |
| `MAX_ACTIVE_JOBS` | `2` | Jobs running at once; others wait in `queued` |

The server binds to localhost by default and has no authentication. Do not expose it to a network.

### Docker

`Dockerfile` builds `web/dist` in a Node stage, then installs the locked backend dependencies and `ffmpeg` into a Python image. `compose.yaml` runs it:

- `DATA_DIR=/data` and `DOWNLOAD_DIR=/downloads` inside the container, mounted from `./data` and `./downloads`.
- Runs as `${UID}:${GID}`, read from `.env` next to `compose.yaml`, so files on the host belong to the user. Without `.env` it runs as `1000:1000`. Bash does not export `UID` and marks it read-only, so the file is the way to set it.
- Create `data/` and `downloads/` before the first start, or Docker creates them owned by root.
- `stop_grace_period` is longer than the 30 second job shutdown, so `docker compose down` pauses jobs cleanly.
- uvicorn listens on `0.0.0.0` inside the container, and the port is published on `127.0.0.1:8000` only.
- The variables in the table above are set under `environment:` of the service.

## Runtime files

| Path | Contents |
| --- | --- |
| `DATA_DIR/jobs.json` | Every job, including its generated links. Rewritten on each state change, and every 5 seconds while downloading |
| `DATA_DIR/proxies.txt` | Working proxies, one `host:port` per line. Delete it to force a refresh |
| `DATA_DIR/*.lock` | Lock files for cross-process `fcntl.flock` |
| `DATA_DIR/jobs/<job_id>/partNNNNN` | Part files of an unfinished job |
| `DOWNLOAD_DIR/<filename>` | Finished files. A name that exists gets ` (N)` appended |

## Job flow

1. `POST /api/jobs` resolves the URL through the registry, checks the options and starts a worker thread. At most `MAX_ACTIVE_JOBS` workers run at once.
2. `resolving`: the provider's `get_info` gives the name and size. A user-supplied name wins. Names are reduced to one safe path component.
3. Link generation runs when the job has no links, or they are older than the provider's `link_ttl`. The provider reports through `LinkContext`, and the state follows: `preparing`, `solving_captcha`, `awaiting_captcha`, `waiting` and `generating_links`.
4. `downloading`: `SegmentedDownload` splits the size into ranges of the split size. It then runs one thread per link, each streaming one pending range into its part file in append mode.
5. When every link is refused (401, 403, 404 or 410, three times in a row each), the job regenerates links once and continues from the bytes on disk.
6. `assembling`: parts are joined in order into a temporary file, which is renamed into `DOWNLOAD_DIR`. The part directory is removed.
7. `verifying`: for video extensions, when `ffmpeg` is on PATH, the result is recorded in `verified` as `ok` or `corrupt`.

Pause sets the job's cancel event. Workers stop at the next block, and the job becomes `paused` with its parts kept. Stopping the server pauses running jobs the same way, and a server start marks any job left active as `paused`. Resume starts a new worker on the same job. Delete stops the job and removes its parts, but never a finished file.

## Keep2Share flow

1. `requestCaptcha` gives a challenge and a PNG. `CaptchaSession.solve` runs OCR. An answer that is not 6 lowercase letters or digits is dropped without being submitted, and a fresh image is fetched. After 10 OCR tries, the image goes to the browser.
2. `getUrl` with the captcha is tried from each IP in the proxy pool, starting with the direct connection.
   - A wait up to 30 seconds is sat out, and yields a `free_download_key`.
   - A longer wait is the IP's cooldown between free downloads. When every IP is cooling down, the job waits for the shortest cooldown, up to one hour, then tries that IP again.
3. The key is exchanged for links with parallel `getUrl` calls, up to three rounds per IP.
4. Chunks are downloaded over the direct connection. Each link allows one connection, is rate limited, and binds to the first IP that fetches it, so speed comes from the number of links.

## Adding a provider

1. Subclass `Provider` in a new module under `downloader/providers/`. Set `name`, `label` and `hosts`, and implement `match`, `get_info` and `generate_links`. Override `headers` and `link_ttl` when needed.
2. Add an instance to `default_registry()` before `DirectProvider`.
3. Add tests in the style of `tests/test_k2s.py`.

The engine, jobs, API and UI need no changes. A captcha is solved through `ctx.solve_captcha(image, CaptchaSpec(...))`, which handles OCR and the browser fallback.

## Invariants

- A part file's size equals the bytes received for its range. The engine only appends, rejects a response whose `Content-Range` start does not match, and never writes past the range end. Resuming depends on this.
- A job's split size is fixed when it is created, so resumed parts always line up with their ranges.
- `jobs.json` and `proxies.txt` are only written under `file_lock`. `fcntl` is POSIX only, so the backend runs on Linux and macOS but not on native Windows.
- Index 0 of the proxy list is `None`, meaning the direct connection.
- Split sizes under 20 MiB and connection counts outside 1 to 64 are rejected.
- Job links never leave the backend. The API exposes only `links_count`.
- Tests never touch the network. They use the local Range server in `tests/conftest.py` and scripted fakes.
