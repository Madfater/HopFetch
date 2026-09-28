"""Runtime settings read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Paths and switches shared by the job manager, engine and API.

    - `data_dir` holds `jobs.json`, `proxies.txt` and per-job part files under `jobs/`.
    - `download_dir` receives assembled files.
    - `web_dist` is the built frontend; it is served at `/` when it exists.
    - `captcha_ocr` enables automatic captcha solving before falling back to the UI.
    - `use_proxies` routes link generation and chunk downloads through the public proxy pool.
    - `max_active_jobs` caps how many jobs run at once; the rest stay queued.
    """

    data_dir: Path
    download_dir: Path
    web_dist: Path = ROOT / "web" / "dist"
    captcha_ocr: bool = True
    ocr_attempts: int = 10
    use_proxies: bool = True
    max_active_jobs: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from DATA_DIR, DOWNLOAD_DIR, CAPTCHA_OCR, USE_PROXIES and MAX_ACTIVE_JOBS."""
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve(),
            download_dir=Path(os.environ.get("DOWNLOAD_DIR", ROOT / "downloads")).resolve(),
            captcha_ocr=os.environ.get("CAPTCHA_OCR", "1") != "0",
            use_proxies=os.environ.get("USE_PROXIES", "1") != "0",
            max_active_jobs=int(os.environ.get("MAX_ACTIVE_JOBS", "2")),
        )
