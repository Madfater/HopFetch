# Downloader

A self-hosted web app that downloads files from file hosting platforms to a NAS over many connections at once, with pause, resume and automatic captcha solving.

Supported: Keep2Share (`k2s.cc`, `keep2share.cc`) free links. Other URLs are rejected.

## Requirements

- Linux or macOS (on Windows, use WSL)
- [uv](https://docs.astral.sh/uv/) and Node.js 20 or newer
- Optional: `ffmpeg` on PATH, to check downloaded videos

## Install and run

```bash
uv sync
npm --prefix web ci
npm --prefix web run build
uv run uvicorn downloader.app:app
```

Open http://127.0.0.1:8000, paste a file link and press Download.

Finished files go to `downloads/`, and unfinished parts and the job list live in `data/`. Change these with `DOWNLOAD_DIR` and `DATA_DIR`. Other settings are in [docs/architecture.md](docs/architecture.md#running).

Run a single uvicorn worker, which is the default. Jobs and live updates live in one process's memory, so `--workers 2` or more would split them.

## Notes

- Keep2Share free downloads need a captcha. The app reads it automatically; if that fails 50 times in a row, the download fails and can be retried.
- Keep2Share makes an IP wait between free downloads, sometimes about half an hour. The job shows a countdown and continues by itself.
- Stopping the server pauses running downloads. Press Resume to continue where they stopped.
- The server has no login, and everyone who can reach it shares the same list and settings. Expose it only to your LAN or VPN, never to the internet.
