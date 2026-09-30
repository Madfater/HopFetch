"""Runtime settings read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .util import parse_size

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Paths and switches shared by the job manager, engine and API.

    - `data_dir` holds `jobs.json`, `settings.json`, `proxies.txt` and per-job part files under `jobs/`.
    - `download_dir` is the root that receives assembled files; nothing is written outside it.
    - `web_dist` is the built frontend; it is served at `/` when it exists.
    - `captcha_max_attempts` caps OCR tries per link generation before a job fails.
    - `connections`, `split_size`, `use_proxies` and `max_active_jobs` are the initial values of
      the editable settings in `settings.json`.
    """

    data_dir: Path
    download_dir: Path
    web_dist: Path = ROOT / "web" / "dist"
    captcha_max_attempts: int = 50
    connections: int = 20
    split_size: int = 20 * 2**20
    use_proxies: bool = True
    max_active_jobs: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from DATA_DIR, DOWNLOAD_DIR, CAPTCHA_MAX_ATTEMPTS, CONNECTIONS,
        SPLIT_SIZE, USE_PROXIES and MAX_ACTIVE_JOBS."""
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve(),
            download_dir=Path(os.environ.get("DOWNLOAD_DIR", ROOT / "downloads")).resolve(),
            captcha_max_attempts=int(os.environ.get("CAPTCHA_MAX_ATTEMPTS", "50")),
            connections=int(os.environ.get("CONNECTIONS", "20")),
            split_size=parse_size(os.environ.get("SPLIT_SIZE", "20MB")),
            use_proxies=os.environ.get("USE_PROXIES", "1") != "0",
            max_active_jobs=int(os.environ.get("MAX_ACTIVE_JOBS", "2")),
        )
