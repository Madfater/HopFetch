"""FastAPI application: the API plus the built frontend.

Run with `uv run uvicorn downloader.app:app`, as a single process: jobs, their threads and the
event bus live in that process's memory.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import ApiError, router
from .config import Settings
from .jobs import JobManager
from .messages import CodedError
from .providers import default_registry

STORAGE_INTERVAL = 5.0


def _error(status: int, code: str, key: str | None = None) -> JSONResponse:
    """A `{code, key, params, message}` error answer without parameters."""
    return JSONResponse(CodedError(code, key).as_error(), status_code=status)


def _watch_storage(manager: JobManager, stop: threading.Event, interval: float) -> None:
    """Publish a `storage` event whenever free space on the download root changes."""
    last = None
    while not stop.wait(interval):
        try:
            current = manager.storage()
        except OSError:
            continue
        if current != last:
            manager.bus.publish("storage", current)
            last = current


def create_app(settings: Settings | None = None, manager: JobManager | None = None,
               preload_proxies: bool = True, storage_interval: float = STORAGE_INTERVAL) -> FastAPI:
    """Build the app.

    - On startup the job manager loads stored jobs; when proxies are enabled they load in a
      background thread, so the first job does not wait for them when possible.
    - A background thread watches free space and publishes `storage` events.
    - On shutdown running jobs are paused, keeping their part files.
    - `web/dist` is served at `/` when it has been built. Unknown paths outside `/api` get
      `index.html`, so client-side routes survive a reload; unknown `/api` paths get a JSON 404.
    """
    settings = settings or Settings.from_env()
    manager = manager or JobManager(settings, default_registry())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.start()
        if preload_proxies and manager.proxies.enabled:
            threading.Thread(target=manager.proxies.load, daemon=True, name="proxy-load").start()
        stop = threading.Event()
        threading.Thread(target=_watch_storage, args=(manager, stop, storage_interval),
                         daemon=True, name="storage-watch").start()
        yield
        stop.set()
        manager.shutdown()

    app = FastAPI(title="Hop fetch", lifespan=lifespan)
    app.state.manager = manager

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid_request")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).error("unhandled error on %s", request.url.path, exc_info=exc)
        return _error(500, "internal_error")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error(404, "not_found", "errors.page_not_found")
        if exc.status_code == 405:
            return _error(405, "method_not_allowed")
        return _error(exc.status_code, "http_error")

    app.include_router(router)

    @app.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def api_not_found(rest: str = "") -> JSONResponse:
        return _error(404, "not_found", "errors.route_not_found")

    if settings.web_dist.is_dir():
        dist = settings.web_dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(dist):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


def _configure_logging() -> None:
    """Log to stderr with timestamps."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()
app = create_app()
