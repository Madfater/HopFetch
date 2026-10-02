"""REST and SSE API under `/api`, a thin layer over `JobManager`.

- Every error answers `{code, key, params, message}`: a stable code, a translation key with
  its values, and zh-Hant fallback text. Raw exception text never leaves the server.
- Task routes take only a task id, checked against ID_PATTERN; no route accepts a path.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .events import HEARTBEAT_SECONDS, event_stream
from .jobs import DuplicateTask, JobManager, TaskError
from .messages import CodedError
from .providers.base import ProviderError
from .settings_store import InvalidSettings

router = APIRouter(prefix="/api")

ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
PROVIDER_STATUS = {"invalid_url": 400, "unsupported": 400, "not_found": 404, "private": 403,
                   "premium_only": 403, "quota_exceeded": 429, "captcha_failed": 502,
                   "upstream_error": 502}


class ApiError(Exception):
    """An error answer: HTTP status, a coded error and optional extra fields."""

    def __init__(self, status: int, error: CodedError, **extra):
        super().__init__(error.message)
        self.status = status
        self.error = error
        self.extra = extra

    def body(self) -> dict:
        """The JSON answer: `{code, key, params, message}` plus the extra fields."""
        return self.error.as_error() | self.extra


class UrlBody(BaseModel):
    """Body of `POST /api/resolve`."""

    url: str


class CreateTask(BaseModel):
    """Body of `POST /api/tasks`."""

    url: str
    force: bool = False


class SettingsBody(BaseModel):
    """Body of `PUT /api/settings`; omitted fields keep their value."""

    connections: int | None = None
    split_size: int | None = None
    use_proxies: bool | None = None
    max_active_jobs: int | None = None


def _manager(request: Request) -> JobManager:
    """The app's job manager."""
    return request.app.state.manager


def _job(request: Request, task_id: str):
    """Look up a task or answer 404; ids that are not 12 hex digits are never looked up."""
    if not ID_PATTERN.match(task_id):
        raise ApiError(404, CodedError("task_not_found"))
    try:
        return _manager(request).get(task_id)
    except KeyError:
        raise ApiError(404, CodedError("task_not_found")) from None


def _provider_error(exc: ProviderError) -> ApiError:
    """Map a provider failure to an API error."""
    return ApiError(PROVIDER_STATUS.get(exc.code, 502), exc)


def _task_error(exc: TaskError) -> ApiError:
    """Map a refused task action to an API error."""
    if isinstance(exc, DuplicateTask):
        return ApiError(409, exc, task_id=exc.task_id, task_status=exc.task_status)
    status = 507 if exc.code == "insufficient_space" else 409
    return ApiError(status, exc)


@router.get("/providers")
def providers(request: Request) -> list[dict]:
    """The supported platforms and their URL patterns, in match order."""
    return [{"id": p.name, "name": p.label, "icon": p.icon, "patterns": list(p.patterns)}
            for p in _manager(request).registry.all()]


@router.get("/proxies")
def proxies(request: Request) -> dict:
    """Proxy pool counts; never lists addresses and never waits for the pool to load."""
    return _manager(request).proxies.status()


@router.post("/resolve")
def resolve(body: UrlBody, request: Request) -> dict:
    """Look up a share link without creating a task."""
    try:
        return _manager(request).resolve(body.url)
    except ProviderError as exc:
        raise _provider_error(exc) from None


@router.get("/tasks")
def list_tasks(request: Request) -> list[dict]:
    """All tasks, newest first."""
    manager = _manager(request)
    return [manager.public(job) for job in manager.list()]


@router.post("/tasks", status_code=201)
def create_task(body: CreateTask, request: Request) -> dict:
    """Create and start a task."""
    manager = _manager(request)
    try:
        return manager.public(manager.create(body.url, body.force))
    except ProviderError as exc:
        raise _provider_error(exc) from None
    except TaskError as exc:
        raise _task_error(exc) from None


@router.post("/tasks/clear-completed")
def clear_completed(request: Request) -> dict:
    """Remove every completed task from the list; files stay on disk."""
    return {"removed": _manager(request).clear_completed()}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request) -> dict:
    """One task."""
    return _manager(request).public(_job(request, task_id))


def _action(request: Request, task_id: str, name: str) -> dict:
    """Run a manager action on one task and return the task."""
    _job(request, task_id)
    manager = _manager(request)
    try:
        return manager.public(getattr(manager, name)(task_id))
    except TaskError as exc:
        raise _task_error(exc) from None
    except KeyError:
        raise ApiError(404, CodedError("task_not_found")) from None


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: str, request: Request) -> dict:
    """Stop a running task and keep its progress."""
    return _action(request, task_id, "pause")


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, request: Request) -> dict:
    """Continue a paused task."""
    return _action(request, task_id, "resume")


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request) -> dict:
    """Stop a task and delete its partial data."""
    return _action(request, task_id, "cancel")


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str, request: Request) -> dict:
    """Queue a failed or canceled task again."""
    return _action(request, task_id, "retry")


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request, delete_file: bool = False) -> None:
    """Remove a task; with `delete_file`, delete its finished file on the NAS too."""
    _job(request, task_id)
    try:
        _manager(request).delete(task_id, delete_file)
    except TaskError as exc:
        raise _task_error(exc) from None
    except KeyError:
        raise ApiError(404, CodedError("task_not_found")) from None


@router.get("/tasks/{task_id}/file")
def task_file(task_id: str, request: Request) -> FileResponse:
    """Send a finished file to the browser, with Range support and an RFC 5987 file name."""
    _job(request, task_id)
    try:
        path = _manager(request).file_path(task_id)
    except KeyError:
        raise ApiError(404, CodedError("task_not_found")) from None
    if path is None:
        raise ApiError(404, CodedError("file_missing"))
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/storage")
def storage(request: Request) -> dict:
    """Free and total bytes of the download root's filesystem."""
    return _manager(request).storage()


def _settings(manager: JobManager) -> dict:
    """The settings object, with the read-only download root."""
    prefs = manager.preferences()
    return {"connections": prefs.connections, "split_size": prefs.split_size,
            "use_proxies": prefs.use_proxies, "max_active_jobs": prefs.max_active_jobs,
            "download_root": str(manager.root)}


@router.get("/settings")
def get_settings(request: Request) -> dict:
    """Current settings."""
    return _settings(_manager(request))


@router.put("/settings")
def put_settings(body: SettingsBody, request: Request) -> dict:
    """Change settings; the download root cannot be changed here."""
    manager = _manager(request)
    try:
        manager.update_preferences(body.model_dump(exclude_none=True))
    except InvalidSettings as exc:
        raise ApiError(400, exc) from None
    return _settings(manager)


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: `task`, `task_removed` and `storage`."""
    heartbeat = getattr(request.app.state, "heartbeat", HEARTBEAT_SECONDS)
    stream = event_stream(_manager(request).bus, heartbeat)
    return StreamingResponse(stream, media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
