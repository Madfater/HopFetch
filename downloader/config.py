"""Runtime settings read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .proxies import parse_proxy_lines

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """Paths and switches shared by the job manager, engine and API.

    - `data_dir` holds `jobs.json`, `proxies.txt`, the optional `proxies.user.txt` and per-job part
      files under `jobs/`.
    - `download_dir` receives assembled files.
    - `web_dist` is the built frontend; it is served at `/` when it exists.
    - `captcha_ocr` enables automatic captcha solving before falling back to the UI.
    - `use_proxies` lets link generation try public proxies when this IP must wait.
    - `proxies` are user proxy URLs, tried before public proxies whatever `use_proxies` says.
    - `max_active_jobs` caps how many jobs run at once; the rest stay queued.
    """

    data_dir: Path
    download_dir: Path
    web_dist: Path = ROOT / "web" / "dist"
    captcha_ocr: bool = True
    ocr_attempts: int = 10
    use_proxies: bool = True
    proxies: list[str] = field(default_factory=list)
    max_active_jobs: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from DATA_DIR, DOWNLOAD_DIR, CAPTCHA_OCR, USE_PROXIES, PROXIES and
        MAX_ACTIVE_JOBS."""
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve(),
            download_dir=Path(os.environ.get("DOWNLOAD_DIR", ROOT / "downloads")).resolve(),
            captcha_ocr=os.environ.get("CAPTCHA_OCR", "1") != "0",
            use_proxies=os.environ.get("USE_PROXIES", "1") != "0",
            proxies=parse_proxy_lines(os.environ.get("PROXIES", "")),
            max_active_jobs=int(os.environ.get("MAX_ACTIVE_JOBS", "2")),
        )
