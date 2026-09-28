"""FastAPI application: the API plus the built frontend.

Run with `uv run uvicorn downloader.app:app`.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import Settings
from .jobs import JobManager
from .providers import default_registry


def create_app(settings: Settings | None = None, manager: JobManager | None = None,
               preload_proxies: bool = True) -> FastAPI:
    """Build the app.

    - On startup the job manager loads stored jobs; the proxy pool loads in a background thread
      so the first job does not wait for it when possible.
    - On shutdown running jobs are paused, keeping their part files.
    - `web/dist` is served at `/` when it has been built.
    """
    settings = settings or Settings.from_env()
    manager = manager or JobManager(settings, default_registry())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.start()
        if preload_proxies:
            threading.Thread(target=manager.proxies.load, daemon=True, name="proxy-load").start()
        yield
        manager.shutdown()

    app = FastAPI(title="Downloader", lifespan=lifespan)
    app.state.manager = manager
    app.include_router(router)
    if settings.web_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
