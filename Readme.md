# Downloader

A local web app that downloads files from file hosting platforms over many connections at once, with pause, resume and automatic captcha solving.

Supported:
- Keep2Share (`k2s.cc`, `keep2share.cc`) free links
- Any direct http(s) link whose server supports ranged downloads

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

## Notes

- Keep2Share free downloads need a captcha. The app reads it automatically. If that fails ten times, the captcha appears in the page for you to type.
- Keep2Share makes an IP wait between free downloads, sometimes about half an hour. The job shows a countdown and continues by itself.
- Stopping the server pauses running downloads. Press Resume to continue where they stopped.
- The server has no login. Keep it on localhost.
