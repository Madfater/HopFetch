# Architecture

Navigation map of the codebase. When this file and the code disagree, the code wins, so fix this file.

## Overview

A web app, meant for a NAS on a LAN, that downloads files from file hosting platforms over many connections at once. A FastAPI backend runs download jobs in background threads, pushes changes to the browser over server-sent events, and serves a React dashboard. Each platform is a provider: it turns a user's URL into file info and a list of direct links. A shared engine then fetches byte ranges over those links in parallel into resumable part files.

Keep2Share (k2s.cc) is the only provider. Its free tier gives each link one rate-limited connection after an image captcha. The app solves the captcha with offline OCR and turns one free download key into many links. The provider patterns are the allowlist: any other URL is rejected, so the backend never fetches addresses a user picks.

The agreed spec for the current refactor, stage by stage, is [refactor-spec.md](refactor-spec.md).

## Layout

| Path | Responsibility |
| --- | --- |
| `downloader/app.py` | App factory and the `app` instance for uvicorn. Starts and stops the job manager, preloads proxies, watches free space, maps errors to `{code, key, params, message}`, serves `web/dist` with an SPA fallback |
| `downloader/api.py` | Routes under `/api`: providers, resolve, tasks and their actions, file, storage, settings, events |
| `downloader/jobs.py` | `JobManager`: status and phase state machine, one worker thread per job, `jobs.json` persistence, events, link reuse and regeneration |
| `downloader/events.py` | `EventBus` from worker threads to asyncio subscribers, per-task throttling, and the SSE generator |
| `downloader/settings_store.py` | `SettingsStore`: the editable settings in `settings.json` |
| `downloader/messages.py` | Translation keys for user-facing text: `CodedError`, and `render` for the zh-Hant fallback |
| `downloader/engine.py` | `SegmentedDownload`: splits the file into ranges, one connection per link, resumable part files, `assemble` |
| `downloader/captcha.py` | `OcrSolver` (ddddocr) and `CaptchaSession`, which tries OCR up to a limit |
| `downloader/proxies.py` | `ProxyPool`: user proxies from `PROXIES` and `proxies.user.txt`, then public proxies fetched from proxyscrape, tested and cached in `proxies.txt`; URL helpers that hide credentials |
| `downloader/providers/base.py` | `Provider` interface, `normalize_url`, `FileRef`, `FileInfo`, `CaptchaSpec`, `LinkContext`, `ProviderError` with its code |
| `downloader/providers/__init__.py` | `ProviderRegistry`, the URL allowlist, and `default_registry()` |
| `downloader/providers/k2s.py` | Keep2Share free tier over `api/v2` |
| `downloader/config.py`, `downloader/util.py` | `Settings` from environment variables; file lock, size parsing, safe file names, symlink-safe file creation and root checks |
| `shared/provider-test-cases.json` | URL matching cases run by both pytest and the frontend tests |
| `shared/i18n/` | Catalogs of backend messages and errors, `zh-Hant-TW.json` and `en.json`, shared with the frontend |
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
| `DATA_DIR` | `./data` | `jobs.json`, `settings.json`, `proxies.txt`, part files |
| `DOWNLOAD_DIR` | `./downloads` | The download root. Finished files only; it cannot be changed from the UI |
| `CAPTCHA_MAX_ATTEMPTS` | `50` | OCR tries per run, across link regenerations, before the job fails with `captcha_failed`; a retry starts a new count. A value below 1 is logged and replaced by 50 |
| `CONNECTIONS` | `20` | Initial connections per job |
| `SPLIT_SIZE` | `20MB` | Initial part size, at least 20 MiB |
| `USE_PROXIES` | `1` | Initial public proxy switch; `0` requests download keys over the direct connection and user proxies only |
| `PROXIES` | empty | User proxy URLs (http, https, socks5, socks5h, with optional credentials), separated by newlines, commas or spaces. Tried after the direct connection and before public proxies, whatever `USE_PROXIES` says |
| `MAX_ACTIVE_JOBS` | `2` | Initial number of jobs running at once; others wait in `queued` |

`CONNECTIONS`, `SPLIT_SIZE`, `USE_PROXIES` and `MAX_ACTIVE_JOBS` are only initial values: once `settings.json` exists, the settings page owns them. An out-of-range value is logged and replaced by the built-in default.

Run exactly one uvicorn worker. Jobs, their threads and the event bus live in that process's memory, so a second worker would run its own jobs and send its own events. The server has no authentication: expose it only to a LAN or VPN, never to the internet.

### Docker

`Dockerfile` builds `web/dist` in a Node stage, then installs the locked backend dependencies and `ffmpeg` into a Python image. `compose.yaml` runs it:

- `DATA_DIR=/data` and `DOWNLOAD_DIR=/downloads` inside the container, mounted from `./data` and `./downloads`.
- Runs as `${UID}:${GID}`, read from `.env` next to `compose.yaml`, so files on the host belong to the user. Without `.env` it runs as `1000:1000`. Bash does not export `UID` and marks it read-only, so the file is the way to set it.
- Create `data/` and `downloads/` before the first start, or Docker creates them owned by root.
- `stop_grace_period` is longer than the 30 second job shutdown, so `docker compose down` pauses jobs cleanly.
- uvicorn listens on `0.0.0.0` inside the container. The port is published on `${BIND_ADDR}:8000`, where `BIND_ADDR` comes from `.env` and defaults to `127.0.0.1`. Set it to the NAS's LAN address, or `0.0.0.0`, to reach the app from other machines on the LAN or VPN.
- The variables in the table above are set under `environment:` of the service.

## Runtime files

| Path | Contents |
| --- | --- |
| `DATA_DIR/jobs.json` | Every job, including its generated links. Rewritten on each status or phase change, and every 5 seconds while downloading |
| `DATA_DIR/settings.json` | The editable settings |
| `DATA_DIR/proxies.user.txt` | Optional user proxies, one URL per line, `#` starts a comment. Read whenever the pool loads, never written |
| `DATA_DIR/proxies.txt` | Working proxies, one `host:port` per line. Delete it to force a refresh |
| `DATA_DIR/*.lock` | Lock files for cross-process `fcntl.flock` |
| `DATA_DIR/jobs/<job_id>/partNNNNN` | Part files of an unfinished job |
| `DOWNLOAD_DIR/<filename>.part` | A file being assembled. Renamed to its final name when complete, so SMB users never see a partial file under the real name |
| `DOWNLOAD_DIR/<filename>` | Finished files. A name that exists, or whose `.part` sibling exists, gets ` (N)` appended |

## Job flow

A job's `status` is one of `queued`, `downloading`, `paused`, `completed`, `failed` and `canceled`. While `downloading`, `phase` names the step: `resolving`, `captcha`, `waiting`, `links`, `downloading`, `assembling` or `verifying`, and `message_key` with `message_params` describe the step, such as a countdown in seconds. Failures are `{code, key, params, message}`. See [Messages](#messages).

1. `POST /api/tasks` checks the URL against the allowlist, refuses a duplicate (an unfinished job of the same file, or a completed one without `force`), reads name and size with `get_info`, checks free space, and starts a worker thread. At most `max_active_jobs` workers download at once. Names are reduced to one safe path component of at most 200 UTF-8 bytes, so ` (N)` and `.part` still fit the filesystem's limit.
2. Link generation runs when the job has no links, or they are older than the provider's `link_ttl`. The provider reports through `LinkContext`, and the phase follows: `captcha`, `waiting` and `links`.
3. `downloading`: `SegmentedDownload` splits the size into ranges of the split size. It then runs one thread per link, each streaming one pending range into its part file in append mode.
4. When every link is refused (401, 403, 404 or 410, three times in a row each), the job regenerates links once and continues from the bytes on disk.
5. `assembling`: a free final name is chosen and `<name>.part` is created exclusively, never through a symlink. Parts are joined into it in order. It is then hard-linked to the final name, which never replaces an existing file, and unlinked; a name taken meanwhile moves to the next ` (N)`. On filesystems without hard links the final name is first reserved by creating an empty file exclusively, and the staging file is renamed over that reservation. The final name is persisted at once, then the part directory is removed.
6. `verifying`: for video extensions, when `ffmpeg` is on PATH, the result is recorded in `verified` as `ok` or `corrupt`.

Pause, cancel and delete set the job's cancel event with an intent. Workers stop at the next block, and the worker applies the intent as it ends, under the manager lock: `pause` keeps the parts and marks the job `paused`; `cancel` deletes the parts and staging file and marks it `canceled`; `delete` removes the record and partial data, and with `delete_file` a finished file that is a regular file inside the root. Intents only escalate, pause < cancel < delete, so a later weaker request never undoes a pending stronger one. A job that completes before it sees a cancel stays completed. All three are refused during `assembling` and `verifying`. A job with no worker is handled by the caller directly.

Stopping the server pauses running jobs the same way, and a server start marks any job left active as `paused`, except one stopped while assembling or verifying whose published file is at its persisted final name with the job's size, which becomes `completed`. Resume queues a paused job; retry queues a failed or canceled one. The OCR limit counts across every link generation of one run, and a retry starts a new count.

## Events

`GET /api/events` streams `task` (the full task object), `task_removed` (`{id}`) and `storage` (`{free_bytes, total_bytes}`).

- Worker threads publish on `EventBus`, which hands each event to every subscriber's asyncio loop with `call_soon_threadsafe`.
- Status and phase changes go out at once. Progress and countdowns of one task go out at most twice a second.
- A subscriber whose queue fills up is dropped; the browser reconnects and refetches the task list.
- A `: ping` comment goes out after 15 seconds without events, and the response sets `X-Accel-Buffering: no` so a reverse proxy does not buffer it.
- Free space is checked every 5 seconds and published when it changes.

## Messages

The backend sends translation keys, and the frontend translates them.

- Step descriptions are `messages.*` keys and failures are `errors.*` keys, each with a params object. The catalogs are `shared/i18n/zh-Hant-TW.json` and `shared/i18n/en.json`, using i18next's `{{name}}` interpolation.
- An error's `code` is stable for program logic. Its `key` is usually `errors.<code>`; a variant of the same code has its own key, such as `errors.quota_exceeded_wait`.
- Every answer also carries `message`, the zh-Hant text rendered from the catalog, for clients without the key.
- Times and counts are sent as numbers, never as formatted text, so the frontend formats them for its locale.
- `tests/test_messages.py` checks that both catalogs have the same keys and placeholders, and that every key and error code the backend uses exists.

## Keep2Share flow

1. `requestCaptcha` gives a challenge and a PNG. `CaptchaSession.solve` runs OCR. An answer that is not 6 lowercase letters or digits is dropped without being submitted, and a fresh image is fetched. After `CAPTCHA_MAX_ATTEMPTS` tries the job fails with `captcha_failed`.
2. `getUrl` with the captcha is tried from each IP in the proxy pool, starting with the direct connection.
   - A wait up to 30 seconds is sat out, and yields a `free_download_key`.
   - A longer wait is the IP's cooldown between free downloads. When every IP is cooling down, the job waits for the shortest cooldown, up to one hour, then tries that IP again.
3. The key is exchanged for links with parallel `getUrl` calls, up to three rounds per IP.
4. Chunks are downloaded over the direct connection. Each link allows one connection, is rate limited, and binds to the first IP that fetches it, so speed comes from the number of links.

## Adding a provider

1. Subclass `Provider` in a new module under `downloader/providers/`. Set `name`, `label`, `icon` and `patterns`, and implement `get_info` and `generate_links`. Raise `ProviderError` with one of the error codes in [refactor-spec.md](refactor-spec.md). Override `headers` and `link_ttl` when needed.
2. Patterns match the normalized URL and hold the file id in group 1. They use only regex syntax that Python and JavaScript share: no named groups, no lookbehind, no inline flags.
3. Add an instance to `default_registry()`, and add URLs to `shared/provider-test-cases.json`.
4. Add tests in the style of `tests/test_k2s.py`.

The engine, jobs and API need no changes. A captcha is solved through `ctx.solve_captcha(image, CaptchaSpec(...))`, which runs OCR.

## Invariants

- A part file's size equals the bytes received for its range. The engine only appends, rejects a response whose `Content-Range` start does not match, and never writes past the range end. Resuming depends on this.
- A job's split size is fixed when it is created, so resumed parts always line up with their ranges.
- `jobs.json`, `settings.json` and `proxies.txt` are only written under `file_lock`. `fcntl` is POSIX only, so the backend runs on Linux and macOS but not on native Windows.
- Index 0 of the proxy list is `None`, meaning the direct connection.
- Split sizes under 20 MiB and connection counts outside 1 to 64 are rejected.
- Job links and file paths never leave the backend. Task routes take only an id of 12 hex digits, and every file served or deleted is checked to be a regular file, not a symlink, whose real path is inside the download root.
- Only URLs matching a provider pattern reach the network. Error answers carry a code, a translation key with its params, and fallback text, never raw exception text.
- Tests never touch the network. They use the local Range server in `tests/conftest.py` and scripted fakes.
