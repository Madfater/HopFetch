"""REST API under `/api`, a thin layer over `JobManager`."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .jobs import DuplicateJob, JobManager, State
from .providers.base import ProviderError
from .util import parse_size

router = APIRouter(prefix="/api")


class CreateJob(BaseModel):
    """Body of `POST /api/jobs`."""

    url: str
    filename: str | None = None
    connections: int = Field(default=20, ge=1, le=64)
    split_size: str | int = "20MB"


class ResolveRequest(BaseModel):
    """Body of `POST /api/resolve`."""

    url: str


class CaptchaAnswer(BaseModel):
    """Body of `POST /api/jobs/{id}/captcha`."""

    answer: str


def _manager(request: Request) -> JobManager:
    """The app's job manager."""
    return request.app.state.manager


def _job(request: Request, job_id: str):
    """Look up a job or answer 404."""
    try:
        return _manager(request).get(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


@router.get("/providers")
def providers(request: Request) -> list[dict]:
    """List the supported platforms in match order."""
    return [{"name": p.name, "label": p.label, "hosts": list(p.hosts)}
            for p in _manager(request).registry.all()]


@router.post("/resolve")
def resolve(body: ResolveRequest, request: Request) -> dict:
    """Tell which provider would handle a URL, without creating a job."""
    try:
        provider, ref = _manager(request).registry.resolve(body.url)
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"provider": provider.name, "label": provider.label, "file_id": ref.file_id}


@router.get("/jobs")
def list_jobs(request: Request) -> list[dict]:
    """All jobs, newest first."""
    return [job.public() for job in _manager(request).list()]


@router.post("/jobs", status_code=201)
def create_job(body: CreateJob, request: Request) -> dict:
    """Create and start a job."""
    try:
        split_size = parse_size(body.split_size)
        job = _manager(request).create(body.url, body.filename, body.connections, split_size)
    except DuplicateJob as exc:
        raise HTTPException(409, f"This file is already in the list (job {exc.job_id})") from None
    except (ValueError, ProviderError) as exc:
        raise HTTPException(400, str(exc)) from None
    return job.public()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    """One job."""
    return _job(request, job_id).public()


@router.get("/jobs/{job_id}/captcha")
def captcha_image(job_id: str, request: Request) -> Response:
    """The captcha image the job waits on."""
    _job(request, job_id)
    image = _manager(request).captcha_image(job_id)
    if image is None:
        raise HTTPException(404, "This job is not waiting for a captcha")
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/jobs/{job_id}/captcha")
def submit_captcha(job_id: str, body: CaptchaAnswer, request: Request) -> dict:
    """Answer the captcha the job waits on."""
    job = _job(request, job_id)
    try:
        _manager(request).submit_captcha(job_id, body.answer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return job.public()


@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: str, request: Request) -> dict:
    """Stop a running job and keep its progress."""
    _job(request, job_id)
    try:
        return _manager(request).pause(job_id).public()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, request: Request) -> dict:
    """Continue a paused or failed job."""
    _job(request, job_id)
    try:
        return _manager(request).resume(job_id).public()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request) -> Response:
    """Remove a job and its part files; a finished file stays on disk."""
    _job(request, job_id)
    _manager(request).delete(job_id)
    return Response(status_code=204)


@router.get("/jobs/{job_id}/file")
def job_file(job_id: str, request: Request) -> FileResponse:
    """Stream a finished file to the browser."""
    job = _job(request, job_id)
    download_dir = _manager(request).settings.download_dir.resolve()
    path = Path(job.output_path).resolve() if job.output_path else None
    if job.state != State.COMPLETED or path is None or not path.is_file() \
            or download_dir not in path.parents:
        raise HTTPException(404, "The file is not available")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
