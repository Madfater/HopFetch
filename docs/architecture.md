# Architecture

Navigation map of the codebase. When this file and the code disagree, the code wins, so fix this file.

## Overview

A web app, meant for a NAS on a LAN, that downloads files from file hosting platforms over many connections at once. A FastAPI backend runs download jobs in background threads, pushes changes to the browser over server-sent events, and serves a React dashboard. Each platform is a provider: it turns a user's URL into file info and a list of direct links. A shared engine then fetches byte ranges over those links in parallel into resumable part files.

There are two providers:
- **Keep2Share (k2s.cc):** its free tier gives each link one rate-limited connection after an image captcha. The app solves the captcha with offline OCR and turns one free download key into many links.
- **MEGA (mega.nz):** public file links. Content is encrypted with the key in the link, so the app decrypts it while assembling.

The provider patterns are the allowlist: any other URL is rejected, so the backend never fetches addresses a user picks.

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
| `downloader/files.py` | Serving finished files: opening inside the root without following symlinks, single-range answers from the open descriptor, RFC 5987 file names |
| `downloader/engine.py` | `SegmentedDownload`: splits the file into ranges, one connection per link, resumable part files, `assemble` |
| `downloader/captcha.py` | `OcrSolver` (ddddocr) and `CaptchaSession`, which tries OCR up to a limit |
| `downloader/proxies.py` | `ProxyPool`: user proxies from `PROXIES` and `proxies.user.txt`, then public proxies fetched from proxyscrape, tested and cached in `proxies.txt`; URL helpers that hide credentials |
| `downloader/providers/base.py` | `Provider` interface, `normalize_url`, `FileRef`, `FileInfo`, `CaptchaSpec`, `LinkContext`, `Decoder`, `ProviderError` with its code |
| `downloader/providers/__init__.py` | `ProviderRegistry`, the URL allowlist, and `default_registry()` |
| `downloader/providers/k2s.py` | Keep2Share free tier over `api/v2` |
| `downloader/providers/mega.py` | MEGA public file links over the `cs` API, and `MegaDecoder` for decryption and the MAC check |
| `downloader/config.py`, `downloader/util.py` | `Settings` from environment variables; file lock, size parsing, safe file names, symlink-safe file creation and root checks |
| `shared/provider-test-cases.json` | URL matching cases run by both pytest and the frontend tests |
| `shared/i18n/` | Catalogs of backend messages and errors, `zh-Hant-TW.json` and `en.json`, shared with the frontend |
| `web/` | Vite, React and TypeScript dashboard, see [Frontend](#frontend) |
| `shared/providers.json` | Snapshot of `GET /api/providers` for the frontend tests, kept equal to the registry by pytest |
| `tests/` | pytest suite. `conftest.py` has a local Range server used by the engine, job and API tests |
| `script/` | Harness scripts: checks, GitHub client, apply |
| `docs/` | Knowledge |
| `Dockerfile`, `compose.yaml` | Container image and service, see [Docker](#docker) |
| `.github/workflows/harness.yml` | Pull request checks: conventions and `script/check.py` |
| `.github/workflows/deploy.yml`, `deploy/arcane/compose.yaml` | Image publishing and the Arcane service, see [Deployment](#deployment) |

## Running

```bash
uv sync                                   # backend dependencies
npm --prefix web ci                       # frontend dependencies
npm --prefix web run build                # build web/dist, served by the backend
uv run uvicorn downloader.app:app --timeout-graceful-shutdown 5   # http://127.0.0.1:8000
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

`Dockerfile` builds `web/dist` in a Node stage, then installs the locked backend dependencies and `ffmpeg` into a Python image. Both stages copy `shared/`, which holds the translation catalogs and the provider test cases. `compose.yaml` runs it:

- `DATA_DIR=/data` and `DOWNLOAD_DIR=/downloads` inside the container, mounted from `./data` and `./downloads`.
- Runs as `${UID}:${GID}`, read from `.env` next to `compose.yaml`, so files on the host belong to the user. Without `.env` it runs as `1000:1000`. Bash does not export `UID` and marks it read-only, so the file is the way to set it.
- Create `data/` and `downloads/` before the first start, or Docker creates them owned by root.
- uvicorn runs with `--timeout-graceful-shutdown 5`. An open event stream never ends by itself, so without the limit uvicorn would wait for browsers forever and never reach the app's shutdown. After 5 seconds the streams are cancelled, browsers reconnect later, and running jobs are paused.
- `stop_grace_period` (40 seconds) covers those 5 seconds plus the 30 second job shutdown, so `docker compose down` pauses jobs cleanly.
- uvicorn listens on `0.0.0.0` inside the container. The port is published on `${BIND_ADDR}:8000`, where `BIND_ADDR` comes from `.env` and defaults to `127.0.0.1`. Set it to the NAS's LAN address, or `0.0.0.0`, to reach the app from other machines on the LAN or VPN.
- The variables in the table above are set under `environment:` of the service.

### Deployment

`.github/workflows/deploy.yml` runs on every push to `main`:

- Job `image` builds the `Dockerfile` for `linux/amd64` and pushes `ghcr.io/madfater/hop-fetch` tagged `latest` and `sha-<short commit>`.
- Job `deploy` runs after `image` succeeds. It POSTs to the Arcane project redeploy webhook in the `ARCANE_WEBHOOK_URL` repository secret, and fails when the secret is missing.
- Runs never overlap: a newer push waits for the running deploy. Only one run waits; a later push replaces it, and the replaced run shows as cancelled.

An Arcane project runs `deploy/arcane/compose.yaml`:

- Pulls `ghcr.io/madfater/hop-fetch:latest` on every redeploy. The package is public, since the Arcane host has no registry credentials.
- Uses `network_mode: host`, so uvicorn listens on port 8000 on every host interface. The app has no authentication: the host must not expose port 8000 to the internet.
- Reads `UID`, `GID`, `DATA_PATH` and `DOWNLOAD_PATH` from the project's `.env`. The paths default to `./data` and `./downloads` next to the compose file. Create them before the first start, or Docker creates them owned by root.
- Keeps the user, grace period and restart policy of the root `compose.yaml`.

One-time setup:

1. In Arcane, create a project, for example `hop-fetch`, from `deploy/arcane/compose.yaml` and fill in its `.env`.
2. In Arcane, create a webhook targeting that project with action `redeploy`, and copy its trigger URL.
3. In the GitHub repository settings, add the Actions secret `ARCANE_WEBHOOK_URL` with that URL.
4. After the first `deploy.yml` run, set the `hop-fetch` package visibility to public in its GitHub package settings.

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
   - The first 206 answer records the file version, a strong ETag or else Last-Modified, in the job's `etag` and `last_modified`. Every later request sends it as `If-Range`.
   - The remote file changed when a 206 answer names another ETag or Last-Modified than the recorded one, or reports a total size in `Content-Range` other than the job's size. That also catches parallel first requests served by different versions and servers that ignore `If-Range`. A non-HTML 200 answer to a request with `If-Range` means the same.
   - On a change the job drops its part files, reads the file info again for the new size, checks free space, starts over once, and keeps the notice `messages.remote_changed`. A second change in the same run fails it with `remote_changed`. The recorded version is saved to `jobs.json` as soon as it is first seen.
   - A 200 answer to a plain range request with the file's size, or no length, means the upstream ignores ranges. The job fails with `range_unsupported` and `resumable` turns false until a retry judges it again.
   - An HTML 200 answer, or a plain one of another length, is an error page and counts as a failed request. Nothing of a 200 body is ever written.
4. When every link is refused (401, 403, 404 or 410, three times in a row each), the job regenerates links once and continues from the bytes on disk.
5. `assembling`: a free final name is chosen and `<name>.part` is created exclusively, never through a symlink. Parts are joined into it in order, through the provider's `Decoder` when it has one. A decoder that fails its integrity check fails the job with `integrity_failed` and drops the part files and staging file, so a retry downloads again. It is then hard-linked to the final name, which never replaces an existing file, and unlinked; a name taken meanwhile moves to the next ` (N)`. On filesystems without hard links the final name is first reserved by creating an empty file exclusively, and the staging file is renamed over that reservation. The final name is persisted at once, then the part directory is removed.
6. `verifying`: for video extensions, when `ffmpeg` is on PATH, the result is recorded in `verified` as `ok` or `corrupt`.

Pause, cancel and delete set the job's cancel event with an intent. Workers stop at the next block, and the worker applies the intent as it ends, under the manager lock: `pause` keeps the parts and marks the job `paused`; `cancel` deletes the parts and staging file and marks it `canceled`; `delete` removes the record and partial data, and with `delete_file` a finished file that is a regular file inside the root. Intents only escalate, pause < cancel < delete, so a later weaker request never undoes a pending stronger one. A job that completes before it sees a cancel stays completed. All three are refused during `assembling` and `verifying`. A job with no worker is handled by the caller directly.

Stopping the server pauses running jobs the same way. A server start marks any job left active as `paused` when it can resume, and as `failed` with `interrupted` when it cannot. A job stopped while assembling or verifying whose published file is at its persisted final name with the job's size becomes `completed`. Resume queues a paused job; retry queues a failed or canceled one. Both read the file info again and generate new links, since direct links expire; a size that changed meanwhile starts the job over after checking free space again. Cancel forgets the recorded file version along with the part files. A job that cannot resume refuses to pause. The OCR limit counts across every link generation of one run, and a retry starts a new count.

## Events

`GET /api/events` streams `task` (the full task object), `task_removed` (`{id}`) and `storage` (`{free_bytes, total_bytes}`).

- Worker threads publish on `EventBus`, which hands each event to every subscriber's asyncio loop with `call_soon_threadsafe`.
- Status and phase changes go out at once. Progress and countdowns of one task go out at most twice a second.
- A subscriber whose queue fills up is dropped; the browser reconnects and refetches the task list.
- A `: ping` comment goes out after 15 seconds without events, and the response sets `X-Accel-Buffering: no` so a reverse proxy does not buffer it.
- Free space is checked every 5 seconds and published when it changes.

## Frontend

`web/src/` is a React app on React Router, TanStack Query, Radix UI primitives and i18next. Styles are plain CSS: color tokens named by role in `styles/tokens.css`, element defaults inside `:where()` in `styles/base.css`, and CSS Modules per component.

| Path | Responsibility |
| --- | --- |
| `app-name.ts` | `APP_NAME`, the only place the product name is written. `vite.config.ts` puts it in `<title>` and preloads the Archivo font |
| `App.tsx` | Providers, routes (`/`, `/tasks`, `/settings`), the single event stream, completion toasts, and the `(n) APP_NAME` tab title |
| `api/` | Typed client for `/api`. Errors become `ApiError` holding the backend's `{code, key, params, message}` |
| `lib/events.ts` | Opens the `EventSource` and writes `task`, `task_removed` and `storage` events into the query cache. Each open, including reconnects, cancels any task-list fetch in flight, refetches the task list, storage and providers, and replays events that arrived during the refetch. A status change or removal invalidates cached resolve answers |
| `hooks/useTasks.ts` | The task list and provider queries shared by all pages. They never refetch on mount, since a mount-time fetch could land an older snapshot over a newer event |
| `hooks/useResolve.ts` | Local URL check against the provider patterns, then `/api/resolve`: 400 ms after typing stops, at once after a paste. Results are keyed by normalized URL, and outdated requests are aborted |
| `lib/url.ts`, `lib/format.ts`, `lib/messages.ts`, `lib/tasks.ts` | URL extraction and matching, `Intl` formatting, translation of backend keys, and pure task-list helpers |
| `routes/` | The download, files and settings pages |
| `components/` | Navigation bar, lamps, icon buttons with tooltips, delete dialog, toasts |
| `i18n.ts`, `locales/` | i18next setup. Interface text in `locales/<lang>.json`, merged one section deep with `shared/i18n/<lang>.json`. The language is chosen per browser in `localStorage`, then from `navigator.language` |

Vitest runs `src/**/*.test.ts(x)` in jsdom: URL matching against `shared/provider-test-cases.json`, resolve timing and stale answers, cache updates from events, formatting, and catalog parity.

## Messages

The backend sends translation keys, and the frontend translates them.

- Step descriptions are `messages.*` keys and failures are `errors.*` keys, each with a params object. The catalogs are `shared/i18n/zh-Hant-TW.json` and `shared/i18n/en.json`, using i18next's `{{name}}` interpolation.
- An error's `code` is stable for program logic. Its `key` is usually `errors.<code>`; a variant of the same code has its own key, such as `errors.quota_exceeded_wait`.
- Every answer also carries `message`, the zh-Hant text rendered from the catalog, for clients without the key.
- Times and counts are sent as numbers, never as formatted text, so the frontend formats them for its locale. A countdown uses `{{seconds, duration}}`: the `duration` formatter, defined in both `downloader/messages.py` and `web/src/i18n.ts`, shows `m:ss` or `h:mm:ss`. A number that changes the wording is always the `count` param, so English can use i18next's `_one` and `_other` plural keys.
- `tests/test_messages.py` checks that both catalogs have the same keys and placeholders, and that every key and error code the backend uses exists.

## Keep2Share flow

1. `requestCaptcha` gives a challenge and a PNG. `CaptchaSession.solve` runs OCR. An answer that is not 6 lowercase letters or digits is dropped without being submitted, and a fresh image is fetched. After `CAPTCHA_MAX_ATTEMPTS` tries the job fails with `captcha_failed`.
2. `getUrl` with the captcha is tried from each IP in the proxy pool, starting with the direct connection.
   - A wait up to 30 seconds is sat out, and yields a `free_download_key`.
   - A longer wait is the IP's cooldown between free downloads. When every IP is cooling down, the job waits for the shortest cooldown, up to one hour, then tries that IP again.
3. The key is exchanged for links with parallel `getUrl` calls, up to three rounds per IP.
4. Chunks are downloaded over the direct connection. Each link allows one connection, is rate limited, and binds to the first IP that fetches it, so speed comes from the number of links.

## MEGA flow

1. A link is `https://mega.nz/file/<handle>#<key>` or the older `https://mega.nz/#!<handle>!<key>`, also on `mega.co.nz`. The handle is the file id. The 256-bit key stays in the fragment, which MEGA never sees: its halves XORed give the AES key, bytes 16 to 24 the CTR nonce, bytes 24 to 32 the expected MAC.
2. `get_info` posts `{"a": "g", "p": <handle>, "ssl": 2}` to `https://g.api.mega.co.nz/cs`. The size is `s`. The name is `n` in the attributes `at`, which are decrypted with AES-CBC and a zero IV. Attributes that do not decrypt to `MEGA{...}` mean a wrong key: `invalid_url` with `errors.invalid_url_key`. A negative number in the reply is a MEGA error: `-2`, `-9`, `-11` and `-16` are `not_found`, `-17` is `quota_exceeded`, others are `upstream_error`.
3. `generate_links` asks for the same node with `"g": 1` and hands its download URL to the engine once per connection. That URL answers Range requests on many connections at once and sends no ETag or Last-Modified.
4. Part files hold the ciphertext. While assembling, `MegaDecoder` decrypts with AES-128-CTR from counter `nonce + 0` and computes MEGA's MAC: a CBC-MAC per chunk (128 KiB, 256 KiB and so on up to 1 MiB, then 1 MiB each) chained into one file MAC, condensed to 8 bytes and compared with the key's.
5. MEGA limits anonymous transfer per IP. Over the limit the download server answers `509`, which the engine counts as a failed request, so the job ends with `stalled`.

## Adding a provider

1. Subclass `Provider` in a new module under `downloader/providers/`. Set `name`, `label`, `icon` and `patterns`, and implement `get_info` and `generate_links`. Raise `ProviderError` with one of the error codes in [refactor-spec.md](refactor-spec.md). Override `headers` and `link_ttl` when needed.
2. Patterns match the normalized URL and hold the file id in group 1. They use only regex syntax that Python and JavaScript share: no named groups, no lookbehind, no inline flags.
3. Add an instance to `default_registry()`, and add URLs to `shared/provider-test-cases.json`.
4. Add tests in the style of `tests/test_k2s.py`.

The engine, jobs and API need no changes. A captcha is solved through `ctx.solve_captcha(image, CaptchaSpec(...))`, which runs OCR. A platform that serves encoded content overrides `decoder` to return a fresh `Decoder`. Assembly feeds it the file in order from offset 0, and part files keep the bytes as downloaded.

## Invariants

- A part file's size equals the bytes received for its range. The engine only appends, rejects a response whose `Content-Range` start does not match, and never writes past the range end. Resuming depends on this.
- A job's split size is fixed when it is created, so resumed parts always line up with their ranges.
- `jobs.json`, `settings.json` and `proxies.txt` are only written under `file_lock`. `fcntl` is POSIX only, so the backend runs on Linux and macOS but not on native Windows.
- Index 0 of the proxy list is `None`, meaning the direct connection.
- Split sizes under 20 MiB and connection counts outside 1 to 64 are rejected.
- Job links and file paths never leave the backend. Task routes take only an id of 12 hex digits, and every file deleted is checked to be a regular file, not a symlink, whose real path is inside the download root. A file is served by opening its name relative to an open handle of the root with `O_NOFOLLOW`, checking it with `fstat`, and reading from that descriptor (`downloader/files.py`), so swapping it for a symlink after the check cannot redirect the read. The response owns the descriptor and closes it however the request ends, including a client that disconnects.
- Only URLs matching a provider pattern reach the network. Error answers carry a code, a translation key with its params, and fallback text, never raw exception text.
- Tests never touch the network. They use the local Range server in `tests/conftest.py` and scripted fakes.
