# Downloader

A self-hosted web app that downloads files from file hosting platforms to a NAS over many connections at once, with pause, resume and automatic captcha solving.

Supported: Keep2Share (`k2s.cc`, `keep2share.cc`) free links. Other URLs are rejected.

## Run

Needs [Docker](https://docs.docker.com/get-docker/) with Compose.

```bash
mkdir -p data downloads
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose up -d --build
```

Open http://127.0.0.1:8000, paste a file link and press Download. To use it from other machines on your LAN or VPN, add `BIND_ADDR=0.0.0.0` (or the NAS's LAN address) to `.env` before starting.

Finished files go to `downloads/`, and unfinished parts and the job list live in `data/`. `docker compose down` pauses running downloads; start it again and press Resume. Other settings go under `environment:` in `compose.yaml` and are listed in [docs/architecture.md](docs/architecture.md#running).

## Develop

Needs Linux or macOS (on Windows, use WSL), [uv](https://docs.astral.sh/uv/) and Node.js 20 or newer. `ffmpeg` on PATH is optional, to check downloaded videos.

```bash
uv sync
npm --prefix web ci
npm --prefix web run build
uv run uvicorn downloader.app:app      # http://127.0.0.1:8000
npm --prefix web run dev               # optional: Vite dev server with hot reload
uv run pytest -q                       # backend tests
python3 script/check.py                # all checks, run before every commit
```

Change the `downloads/` and `data/` locations with `DOWNLOAD_DIR` and `DATA_DIR`.

Run a single uvicorn worker, which is the default. Jobs and live updates live in one process's memory, so `--workers 2` or more would split them.

## Notes

- Keep2Share free downloads need a captcha. The app reads it automatically; if that fails 50 times in a row, the download fails and can be retried.
- Keep2Share makes an IP wait between free downloads, sometimes about half an hour. The job shows a countdown and continues by itself.
- Stopping the server pauses running downloads. Press Resume to continue where they stopped.
- The server has no login, and everyone who can reach it shares the same list and settings. Expose it only to your LAN or VPN, never to the internet.
