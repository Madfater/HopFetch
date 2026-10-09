"""Download jobs: their state machine, persistence, events, and the worker thread that drives each one."""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from .captcha import CaptchaSession, OcrSolver
from .config import Settings
from .engine import (
    DownloadStalled,
    LinksExpired,
    Progress,
    RangeUnsupported,
    RemoteChanged,
    SegmentedDownload,
    Validator,
    assemble,
    build_parts,
)
from .events import EventBus
from .files import open_in_root
from .messages import CodedError, is_permanent, render
from .providers import ProviderRegistry
from .providers.base import Cancelled, FileRef, LinkContext, Provider, ProviderError
from .proxies import ProxyPool
from .settings_store import Preferences, SettingsStore
from .util import claim_staging, file_lock, inside, publish_staging, safe_filename, staging_path

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".m4v", ".wmv", ".flv"}
PERSIST_INTERVAL = 5.0


class Status(str, Enum):
    """Where a job is in its life, as the API reports it."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class Phase(str, Enum):
    """The step a `downloading` job is on."""

    RESOLVING = "resolving"
    CAPTCHA = "captcha"
    WAITING = "waiting"
    LINKS = "links"
    DOWNLOADING = "downloading"
    ASSEMBLING = "assembling"
    VERIFYING = "verifying"


ACTIVE = {Status.QUEUED, Status.DOWNLOADING}
LEGACY_STATES = {"completed": Status.COMPLETED, "failed": Status.FAILED, "paused": Status.PAUSED}
LEGACY_MESSAGES = {
    Status.COMPLETED: "messages.completed",
    Status.FAILED: "errors.internal_error_legacy",
    Status.PAUSED: "messages.paused_legacy",
}
FINISHING = {Phase.ASSEMBLING, Phase.VERIFYING}
INTENT_RANK = {None: 0, "pause": 1, "cancel": 2, "delete": 3}


class TaskError(CodedError):
    """A request the manager refuses."""


class DuplicateTask(TaskError):
    """A job for the same file exists; `task_id` and `task_status` point at it."""

    def __init__(self, code: str, job: "Job"):
        super().__init__(code)
        self.task_id = job.id
        self.task_status = job.status.value


class InsufficientSpace(TaskError):
    """The download root lacks room for the file."""

    def __init__(self) -> None:
        super().__init__("insufficient_space")


class InvalidState(TaskError):
    """The action does not apply to the job's current status; `key` says which rule applies."""

    def __init__(self, key: str):
        super().__init__("invalid_state", key)


@dataclass
class Job:
    """One download, as stored in `jobs.json`.

    - `output_path` is the final file name chosen when assembly starts; while the job is not
      completed, the file at that path plus PART_SUFFIX is the job's staging file.
    - `message_key` and `message_params` describe the current state as a translation key:
      `messages.*` for a step, or the error's `errors.*` key once the job has failed;
      `message` is its fallback text.
    - `error` is a `{code, key, params, message}` object while the job has failed.
    - `etag` and `last_modified` identify the remote file version the part files belong to; they
      are sent as If-Range so a changed file is never mixed into existing parts.
    - `resumable` turns false once the upstream ignored a range request.
    - `notice_key` is a lasting `messages.*` note shown beside the status, such as a restart
      after the remote file changed, or `messages.resumed_restart` until the job completes.
    - `resume_on_start` marks a job the server paused while shutting down, or one a crash left
      active; it stays set until the job is queued again on start.
    """

    id: str
    url: str
    provider: str
    file_id: str
    connections: int
    split_size: int
    file_name: str | None = None
    size: int | None = None
    status: Status = Status.QUEUED
    phase: Phase | None = None
    message_key: str | None = None
    message_params: dict = field(default_factory=dict)
    message: str = ""
    error: dict | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    links: list[str] = field(default_factory=list)
    links_created_at: float | None = None
    bytes_done: int = 0
    parts_total: int = 0
    parts_done: int = 0
    active_connections: int = 0
    speed: float = 0.0
    output_path: str | None = None
    verified: str | None = None
    resumable: bool = True
    etag: str | None = None
    last_modified: str | None = None
    notice_key: str | None = None
    resume_on_start: bool = False

    def public(self, root: Path) -> dict:
        """Return the task object the API exposes; links and paths stay private.

        - `eta` is known only while downloading with a measured speed.
        - `file_exists` is checked on disk for completed jobs, inside `root` only.
        - `retryable` says whether a retry can help: true for a canceled job and for a failed
          one whose error key is not permanent, false otherwise.
        """
        downloading = self.status == Status.DOWNLOADING and self.phase == Phase.DOWNLOADING
        eta = None
        if downloading and self.speed > 0 and self.size:
            eta = max(0, round((self.size - self.bytes_done) / self.speed))
        file_exists = bool(self.status == Status.COMPLETED and self.output_path
                           and inside(root, Path(self.output_path)))
        retryable = self.status == Status.CANCELED or (
            self.status == Status.FAILED and not is_permanent((self.error or {}).get("key")))
        return {
            "id": self.id,
            "provider": self.provider,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "size": self.size,
            "bytes_done": self.bytes_done,
            "speed": self.speed if downloading else 0.0,
            "eta": eta,
            "status": self.status.value,
            "phase": self.phase.value if self.phase else None,
            "message_key": self.message_key,
            "message_params": self.message_params,
            "message": self.message,
            "resumable": self.resumable,
            "notice_key": self.notice_key,
            "file_exists": file_exists,
            "error": self.error,
            "retryable": retryable,
            "verified": self.verified,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    def stored(self) -> dict:
        """Return the form written to `jobs.json`."""
        data = asdict(self)
        data["status"] = self.status.value
        data["phase"] = self.phase.value if self.phase else None
        return data

    @classmethod
    def load(cls, data: dict) -> "Job":
        """Rebuild a job from its stored form, including the older `state` layout; unknown keys are ignored.

        - Messages and errors of the older layout may hold raw exception text, so they are
          replaced with fixed translation keys and their fallback text.
        """
        data = dict(data)
        if "state" in data and "status" not in data:
            status = LEGACY_STATES.get(data.pop("state"), Status.PAUSED)
            data["status"] = status.value
            data["file_name"] = data.get("requested_filename") or data.get("filename")
            data["bytes_done"] = data.get("done_bytes", 0)
            data["phase"] = None
            data["message_key"] = LEGACY_MESSAGES[status]
            data["message_params"] = {}
            data["message"] = render(LEGACY_MESSAGES[status])
            legacy = CodedError("internal_error", "errors.internal_error_legacy")
            data["error"] = legacy.as_error() if status == Status.FAILED else None
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known["status"] = Status(known.get("status", Status.PAUSED))
        known["phase"] = Phase(known["phase"]) if known.get("phase") else None
        return cls(**known)


class Slots:
    """Counting limit on running jobs whose size can change at runtime."""

    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0
        self._cond = threading.Condition()

    def acquire(self, timeout: float) -> bool:
        """Take a slot, waiting up to `timeout` seconds; return whether one was taken."""
        with self._cond:
            if self.active >= self.limit:
                self._cond.wait(timeout)
            if self.active < self.limit:
                self.active += 1
                return True
            return False

    def release(self) -> None:
        """Give a slot back."""
        with self._cond:
            self.active -= 1
            self._cond.notify_all()

    def resize(self, limit: int) -> None:
        """Change the limit; running jobs above a lower limit finish normally."""
        with self._cond:
            self.limit = limit
            self._cond.notify_all()


class _Run:
    """Runtime-only companions of a job: its thread, cancel flag, and why it was stopped.

    - `intent` is `pause`, `cancel` or `delete` once someone stops the job; the worker applies
      it when it ends, so the outcome never depends on how long the caller waits.
    - Intents only escalate, pause < cancel < delete, so a later weaker request never undoes a
      pending stronger one.
    - `delete_file` goes with the `delete` intent and, once requested, stays requested.
    - `captcha` is shared by every link generation of the run, so the OCR limit counts per run.
    - `refresh` makes the run read the file info again and generate new links, as a resume or
      retry does, since direct links expire.
    - `restarted` is set once the run started over after the remote file changed.
    """

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.intent: str | None = None
        self.delete_file = False
        self.thread: threading.Thread | None = None
        self.captcha: CaptchaSession | None = None
        self.refresh = False
        self.restarted = False

    def stop(self, intent: str) -> None:
        """Raise the intent to `intent` unless a stronger one is pending, and signal the worker."""
        if INTENT_RANK[intent] > INTENT_RANK[self.intent]:
            self.intent = intent
        self.cancelled.set()


class JobManager:
    """Owns all jobs: creates, runs, pauses, resumes, cancels and deletes them.

    - Each running job has one worker thread; at most `max_active_jobs` download at once.
    - `jobs.json` is rewritten on every status or phase change and at most every
      PERSIST_INTERVAL seconds during progress, under a cross-process lock.
    - Every change is published on `bus`: status and phase changes at once, progress throttled.
    - On start, jobs the last run left active or paused while shutting down are queued again
      with a note; jobs the user paused stay paused.
    """

    def __init__(self, settings: Settings, registry: ProviderRegistry,
                 store: SettingsStore | None = None, bus: EventBus | None = None,
                 proxies: ProxyPool | None = None, ocr: OcrSolver | None = None):
        self.settings = settings
        self.registry = registry
        self.store = store or SettingsStore(settings)
        self.bus = bus or EventBus()
        prefs = self.store.get()
        self.proxies = proxies or ProxyPool(settings.data_dir / "proxies.txt", prefs.use_proxies,
                                            user_proxies=settings.proxies,
                                            user_file=settings.data_dir / "proxies.user.txt")
        self.proxies.enabled = prefs.use_proxies
        self.ocr = ocr or OcrSolver()
        self.jobs: dict[str, Job] = {}
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()
        self._slots = Slots(prefs.max_active_jobs)
        self._last_persist = 0.0
        self._persist_lock = threading.Lock()
        self.jobs_file = settings.data_dir / "jobs.json"

    @property
    def root(self) -> Path:
        """The download root."""
        return self.settings.download_dir

    def start(self) -> None:
        """Load stored jobs and settle the ones the last run left active.

        - A job stopped while assembling or verifying whose file was already published is
          marked completed, and a leftover staging file is removed.
        - Any other active job becomes paused, keeping its part files, when it can resume; one
          whose upstream cannot serve ranges fails with `interrupted` and can be retried.
        - Jobs paused that way, and jobs the last shutdown paused, are queued again with the
          `messages.resumed_restart` note; jobs paused by the user stay paused.
        - `resume_on_start` stays set in `jobs.json` until the job is queued, so a crash in
          between still resumes it on the next start.
        """
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self._lock_path()):
            stored = json.loads(self.jobs_file.read_text()) if self.jobs_file.exists() else []
        resume: list[str] = []
        with self._lock:
            for data in stored:
                job = Job.load(data)
                if job.status in ACTIVE and job.phase in FINISHING and self._published(job):
                    self._remove_staging(job)
                    shutil.rmtree(self._part_dir(job), ignore_errors=True)
                    job.bytes_done = job.size or job.bytes_done
                    self._apply(job, Status.COMPLETED, None, "messages.saved_as",
                                name=Path(job.output_path).name)
                elif job.status in ACTIVE and job.resumable:
                    self._apply(job, Status.PAUSED, None, "messages.paused_restart")
                    job.resume_on_start = True
                    resume.append(job.id)
                elif job.status == Status.PAUSED and job.resume_on_start:
                    resume.append(job.id)
                elif job.status in ACTIVE:
                    error = CodedError("interrupted")
                    job.error = error.as_error()
                    self._apply(job, Status.FAILED, None, error.key)
                job.resume_on_start = job.id in resume
                job.active_connections = 0
                job.speed = 0.0
                self.jobs[job.id] = job
        self._persist(force=True)
        for job_id in resume:
            self._requeue(job_id, {Status.PAUSED}, "errors.invalid_state_resume",
                          notice_key="messages.resumed_restart")

    def shutdown(self, timeout: float = 30) -> None:
        """Pause every running job and wait for the workers to stop.

        - Intents are raised under the manager lock, the same lock control actions hold, so a
          concurrent delete or cancel is never lowered to a pause.
        - A job with no pending intent is marked `resume_on_start`, so the next start continues
          it; one the user is pausing, canceling or deleting is not.
        """
        with self._lock:
            runs = list(self._runs.values())
            for job_id, run in self._runs.items():
                if run.intent is None and job_id in self.jobs:
                    self.jobs[job_id].resume_on_start = True
                run.stop("pause")
        for run in runs:
            if run.thread:
                run.thread.join(timeout)
        self._persist(force=True)

    def preferences(self) -> Preferences:
        """The current editable settings."""
        return self.store.get()

    def update_preferences(self, changes: dict) -> Preferences:
        """Save new settings and apply the ones that act on running parts at once."""
        prefs = self.store.update(changes)
        self._slots.resize(prefs.max_active_jobs)
        self.proxies.enabled = prefs.use_proxies
        return prefs

    def storage(self) -> dict:
        """Free and total bytes of the filesystem holding the download root."""
        usage = shutil.disk_usage(self.root)
        return {"free_bytes": usage.free, "total_bytes": usage.total}

    def required_bytes(self, size: int | None) -> int | None:
        """Space a download of `size` needs on the download root's filesystem.

        - When part files and the root share a filesystem, assembly holds both copies at once.
        """
        if size is None:
            return None
        same = os.stat(self.settings.data_dir).st_dev == os.stat(self.root).st_dev
        return size * 2 if same else size

    def check_space(self, size: int | None) -> None:
        """Raise InsufficientSpace when the file cannot fit; unknown sizes pass."""
        needed = self.required_bytes(size)
        if needed is None:
            return
        free = shutil.disk_usage(self.root).free
        if needed > free or (size is not None and size > shutil.disk_usage(self.settings.data_dir).free):
            raise InsufficientSpace()

    def find_duplicate(self, provider: str, file_id: str) -> Job | None:
        """The job for the same file, preferring an unfinished one over completed ones."""
        with self._lock:
            same = [j for j in self.jobs.values() if j.provider == provider and j.file_id == file_id]
        same.sort(key=lambda j: (j.status != Status.COMPLETED, j.created_at), reverse=True)
        return same[0] if same else None

    def resolve(self, url: str) -> dict:
        """Look up a share link without creating a job; raises ProviderError on failure."""
        provider, ref = self.registry.resolve(url)
        info = provider.get_info(ref)
        duplicate = self.find_duplicate(provider.name, ref.file_id)
        return {
            "provider": provider.name,
            "file_id": ref.file_id,
            "file_name": safe_filename(info.name),
            "size": info.size,
            "resumable": True,
            "duplicate": {"task_id": duplicate.id, "status": duplicate.status.value} if duplicate else None,
            "free_bytes": self.storage()["free_bytes"],
            "required_bytes": self.required_bytes(info.size),
        }

    def create(self, url: str, force: bool = False) -> Job:
        """Validate the link, check duplicates and space, then add a job and start it."""
        provider, ref = self.registry.resolve(url)
        self._check_duplicate(provider.name, ref.file_id, force)
        info = provider.get_info(ref)
        self.check_space(info.size)
        prefs = self.store.get()
        with self._lock:
            self._check_duplicate(provider.name, ref.file_id, force)
            job = Job(
                id=uuid.uuid4().hex[:12], url=ref.url, provider=provider.name, file_id=ref.file_id,
                connections=prefs.connections, split_size=prefs.split_size,
                file_name=safe_filename(info.name), size=info.size,
            )
            self._apply(job, Status.QUEUED, None, "messages.waiting_slot")
            self.jobs[job.id] = job
            run = self._register(job)
        self._commit(job, True)
        self._start(job, run)
        return job

    def _check_duplicate(self, provider: str, file_id: str, force: bool) -> None:
        """Raise DuplicateTask for an unfinished job of the file, or a completed one without `force`."""
        dup = self.find_duplicate(provider, file_id)
        if dup is None:
            return
        if dup.status != Status.COMPLETED:
            raise DuplicateTask("duplicate_active", dup)
        if not force:
            raise DuplicateTask("duplicate_completed", dup)

    def get(self, job_id: str) -> Job:
        """Return a job, raising KeyError when it does not exist."""
        return self.jobs[job_id]

    def list(self) -> list[Job]:
        """Return all jobs, newest first."""
        with self._lock:
            return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def public(self, job: Job) -> dict:
        """The API form of `job`."""
        return job.public(self.root)

    def pause(self, job_id: str) -> Job:
        """Stop a queued or downloading job, keeping its part files."""
        with self._lock:
            job = self.get(job_id)
            run = self._runs.get(job_id)
            if job.status not in ACTIVE or run is None:
                raise InvalidState("errors.invalid_state_pause")
            if job.phase in FINISHING:
                raise InvalidState("errors.invalid_state_finishing")
            if not job.resumable:
                raise InvalidState("errors.invalid_state_not_resumable")
            run.stop("pause")
        return job

    def resume(self, job_id: str) -> Job:
        """Queue a paused job again; it continues from the bytes on disk."""
        return self._requeue(job_id, {Status.PAUSED}, "errors.invalid_state_resume")

    def retry(self, job_id: str) -> Job:
        """Queue a failed or canceled job again."""
        return self._requeue(job_id, {Status.FAILED, Status.CANCELED}, "errors.invalid_state_retry")

    def _requeue(self, job_id: str, allowed: set[Status], refusal: str,
                 notice_key: str | None = None) -> Job:
        """Start a new worker for a resting job whose status is in `allowed`.

        - The check, the new run and the `queued` status happen under one lock hold, so a
          concurrent cancel or delete sees either the old state or the new run.
        - `notice_key` replaces the job's note; none clears it.
        """
        with self._lock:
            job = self.get(job_id)
            if job.status not in allowed or job_id in self._runs:
                raise InvalidState(refusal)
            job.error = None
            job.notice_key = notice_key
            job.resume_on_start = False
            job.resumable = True
            run = self._register(job)
            run.refresh = True
            changed = self._apply(job, Status.QUEUED, None, "messages.waiting_slot")
        self._commit(job, changed)
        self._start(job, run)
        return job

    def cancel(self, job_id: str) -> Job:
        """Stop a queued, downloading or paused job and delete its partial data.

        - A running job is canceled by its worker when it stops; this waits up to 30 seconds
          for that and returns the job as it is then.
        - Refused while the file is being assembled or verified.
        """
        with self._lock:
            job = self.get(job_id)
            if job.status not in ACTIVE | {Status.PAUSED}:
                raise InvalidState("errors.invalid_state_cancel")
            if job.phase in FINISHING:
                raise InvalidState("errors.invalid_state_finishing")
            run = self._runs.get(job_id)
            if run is not None:
                run.stop("cancel")
            else:
                self._discard_partial(job)
                changed = self._apply(job, Status.CANCELED, None, "messages.canceled")
        if run is None:
            self._commit(job, changed)
        else:
            self._join(run)
        return job

    def delete(self, job_id: str, delete_file: bool = False) -> None:
        """Remove a job with its partial data; a running job is removed by its worker when it stops.

        - With `delete_file`, the finished file is deleted too, when it is a regular file inside
          the download root.
        - Refused while the file is being assembled or verified.
        """
        with self._lock:
            job = self.get(job_id)
            if job.phase in FINISHING and job.status == Status.DOWNLOADING:
                raise InvalidState("errors.invalid_state_finishing")
            run = self._runs.get(job_id)
            if run is not None:
                run.delete_file = run.delete_file or delete_file
                run.stop("delete")
            else:
                self.jobs.pop(job.id, None)
        if run is None:
            self._finish_removal(job, delete_file)
        else:
            self._join(run)

    def _finish_removal(self, job: Job, delete_file: bool) -> None:
        """Delete the files of a job already dropped from the list, then persist and publish."""
        if job.status != Status.COMPLETED:
            self._discard_partial(job)
        elif delete_file and job.output_path and inside(self.root, Path(job.output_path)):
            Path(job.output_path).unlink(missing_ok=True)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        self._persist(force=True)
        self.bus.publish_removed(job.id)

    def clear_completed(self) -> int:
        """Remove every completed job from the list, keeping their files; return how many."""
        with self._lock:
            done = [j.id for j in self.jobs.values() if j.status == Status.COMPLETED]
            for job_id in done:
                self.jobs.pop(job_id)
        self._persist(force=True)
        for job_id in done:
            self.bus.publish_removed(job_id)
        return len(done)

    def open_file(self, job_id: str) -> tuple[int, os.stat_result, str] | None:
        """Open the finished file of a completed job; return its descriptor, fstat and name.

        - The file must be a regular file directly inside the root and is opened without
          following symlinks (see `files.open_in_root`); the caller closes the descriptor.
        - A missing file publishes the job again so clients see `file_exists` turn false.
        """
        job = self.get(job_id)
        if job.status != Status.COMPLETED or not job.output_path:
            return None
        path = Path(job.output_path)
        opened = open_in_root(self.root, path)
        if opened is None:
            self._publish(job, force=True)
            return None
        return opened[0], opened[1], path.name

    def _join(self, run: _Run | None) -> None:
        """Wait for a stopped run's worker to finish."""
        if run is not None and run.thread is not None and run.thread is not threading.current_thread():
            run.thread.join(30)

    def _discard_partial(self, job: Job) -> None:
        """Delete the part files and staging file of an unfinished job and reset its progress."""
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        self._remove_staging(job)
        job.etag = None
        job.last_modified = None
        job.notice_key = None
        job.bytes_done = 0
        job.parts_done = 0
        job.parts_total = 0
        job.links = []
        job.links_created_at = None
        job.output_path = None

    def _remove_staging(self, job: Job) -> None:
        """Delete the job's staging file when it is a regular file inside the root."""
        if job.output_path:
            staging = staging_path(Path(job.output_path))
            if inside(self.root, staging):
                staging.unlink(missing_ok=True)

    def _published(self, job: Job) -> bool:
        """True when the job's final file is a regular file inside the root with the job's size.

        - The final name is persisted right after publishing, so a matching file at it is the
          job's own; the size check guards against a file someone else put there.
        """
        if not job.output_path or not job.size:
            return False
        path = Path(job.output_path)
        return inside(self.root, path) and path.stat().st_size == job.size

    def _register(self, job: Job) -> _Run:
        """Record a new run for `job`; the caller holds `self._lock`."""
        run = _Run()
        self._runs[job.id] = run
        return run

    def _start(self, job: Job, run: _Run) -> None:
        """Start the worker thread of a registered run."""
        run.thread = threading.Thread(target=self._work, args=(job, run), daemon=True,
                                      name=f"job-{job.id}")
        run.thread.start()

    def _work(self, job: Job, run: _Run) -> None:
        """Worker body: wait for a slot, run the job, and record how it ended.

        - How the run ended, including a pending pause, cancel or delete, is applied by `_finish_run`.
        """
        acquired = False
        outcome: tuple[Status, str, dict] | None = None
        try:
            while not (acquired := self._slots.acquire(timeout=0.5)):
                if run.cancelled.is_set():
                    raise Cancelled()
            self._execute(job, run)
        except Cancelled:
            outcome = (Status.PAUSED, "messages.paused", {})
        except CodedError as exc:
            outcome = self._fail(job, exc)
        except LinksExpired:
            outcome = self._fail(job, CodedError("links_expired"))
        except DownloadStalled:
            outcome = self._fail(job, CodedError("stalled"))
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                log.exception("job %s crashed", job.id)
                outcome = self._fail(job, CodedError("internal_error"))
            else:
                outcome = self._fail(job, CodedError("disk_full"))
        except Exception:
            log.exception("job %s crashed", job.id)
            outcome = self._fail(job, CodedError("internal_error"))
        finally:
            if acquired:
                self._slots.release()
            job.active_connections = 0
            job.speed = 0.0
            self._finish_run(job, run, outcome)

    def _finish_run(self, job: Job, run: _Run, outcome: tuple[Status, str, dict] | None) -> None:
        """Apply how a run ended, honoring a pending cancel or delete, and retire the run.

        - The status change and the removal from `_runs` happen under one lock hold, so no
          control action sees a retired run or a stale status.
        - A job that completed before it saw a cancel stays completed.
        """
        removed = False
        with self._lock:
            try:
                if run.intent == "delete":
                    self.jobs.pop(job.id, None)
                    removed = True
                elif run.intent == "cancel" and job.status != Status.COMPLETED:
                    job.error = None
                    self._apply(job, Status.CANCELED, None, "messages.canceled")
                    self._discard_partial(job)
                elif outcome is not None:
                    self._apply(job, outcome[0], None, outcome[1], **outcome[2])
            finally:
                if self._runs.get(job.id) is run:
                    self._runs.pop(job.id)
        if removed:
            self._finish_removal(job, run.delete_file)
        else:
            self._persist(force=True)
            self._publish(job, force=True)

    @staticmethod
    def _fail(job: Job, error: CodedError) -> tuple[Status, str, dict]:
        """Record `error` on `job` and return the failed outcome."""
        job.error = error.as_error()
        return Status.FAILED, error.key, error.params

    def _execute(self, job: Job, run: _Run) -> None:
        """Resolve, get links, download, assemble and verify one job."""
        provider = self.registry.get(job.provider)
        ref = FileRef(url=job.url, file_id=job.file_id)

        if run.refresh:
            job.links = []
            job.links_created_at = None
        if run.refresh or job.file_name is None or job.size is None:
            self._set(job, Status.DOWNLOADING, Phase.RESOLVING, "messages.resolving")
            info = provider.get_info(ref)
            job.file_name = job.file_name or safe_filename(info.name)
            changed = job.size is not None and info.size is not None and info.size != job.size
            job.size = info.size
            if changed:
                self._start_over(job, run, Phase.RESOLVING)
                self.check_space(job.size)
            self._persist(force=True)
        if not job.size:
            raise ProviderError("upstream_error", "errors.upstream_error_no_size")

        retried = False
        while True:
            if not self._links_fresh(job, provider):
                self._generate_links(job, run, provider, ref)
            try:
                self._download(job, run, provider)
                break
            except LinksExpired:
                if retried:
                    raise
                retried = True
                job.links = []
                self._set(job, Status.DOWNLOADING, Phase.LINKS, "messages.links_regenerating")
            except RemoteChanged:
                self._start_over(job, run)
                self._reread_size(job, provider, ref)
            except RangeUnsupported:
                job.resumable = False
                raise CodedError("range_unsupported") from None

        self._set(job, Status.DOWNLOADING, Phase.ASSEMBLING, "messages.assembling")
        self._remove_staging(job)
        output, handle = claim_staging(self.root / job.file_name)
        job.output_path = str(output)
        self._persist(force=True)
        try:
            with handle:
                assemble(self._part_dir(job), build_parts(job.size, job.split_size), handle,
                         provider.decoder(ref))
        except ProviderError as exc:
            if exc.code == "integrity_failed":
                self._discard_partial(job)
                self._persist(force=True)
            raise
        output = publish_staging(staging_path(output), output)
        job.output_path = str(output)
        self._persist(force=True)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        job.bytes_done = job.size
        job.parts_done = job.parts_total

        if output.suffix.lower() in VIDEO_SUFFIXES and shutil.which("ffmpeg"):
            self._set(job, Status.DOWNLOADING, Phase.VERIFYING, "messages.verifying")
            job.verified = "ok" if _ffmpeg_ok(output) else "corrupt"
        if job.notice_key == "messages.resumed_restart":
            job.notice_key = None
        self._set(job, Status.COMPLETED, None, "messages.saved_as", name=output.name)

    def _reread_size(self, job: Job, provider: Provider, ref: FileRef) -> None:
        """Read the size of a changed remote file again and check that it still fits."""
        info = provider.get_info(ref)
        if not info.size:
            raise ProviderError("upstream_error", "errors.upstream_error_no_size")
        job.size = info.size
        self.check_space(job.size)
        self._persist(force=True)

    def _start_over(self, job: Job, run: _Run, phase: Phase = Phase.DOWNLOADING) -> None:
        """Drop the part files of an older remote version and download again from the start.

        - Happens at most once per run; a second change fails the job with `remote_changed`.
        - The job keeps the notice `messages.remote_changed` once it starts over.
        """
        if run.restarted:
            raise CodedError("remote_changed")
        run.restarted = True
        log.info("job %s: remote file changed, starting over", job.id)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        job.etag = None
        job.last_modified = None
        job.bytes_done = 0
        job.parts_done = 0
        job.parts_total = 0
        job.notice_key = "messages.remote_changed"
        self._set(job, Status.DOWNLOADING, phase, "messages.remote_changed_restarting")

    def _links_fresh(self, job: Job, provider: Provider) -> bool:
        """True when stored links exist and are younger than the provider's link TTL."""
        if not job.links or job.links_created_at is None:
            return False
        return time.time() - job.links_created_at < provider.link_ttl

    def _generate_links(self, job: Job, run: _Run, provider: Provider, ref: FileRef) -> None:
        """Ask the provider for links, wiring captcha and status reporting to the job."""

        def on_attempt(attempt: int) -> None:
            self._set(job, Status.DOWNLOADING, Phase.CAPTCHA, "messages.captcha_attempt", n=attempt)

        if run.captcha is None:
            run.captcha = CaptchaSession(self.ocr, self.settings.captcha_max_attempts, run.cancelled, on_attempt)
        ctx = LinkContext(
            solve_captcha=run.captcha.solve,
            set_status=lambda phase, key, **params: self._set(job, Status.DOWNLOADING, Phase(phase), key, **params),
            proxies=self.proxies,
            cancelled=run.cancelled,
        )
        links = provider.generate_links(ref, job.connections, ctx)
        if not links:
            raise ProviderError("upstream_error", "errors.upstream_error_no_links")
        job.links = links
        job.links_created_at = time.time()
        self._persist(force=True)

    def _download(self, job: Job, run: _Run, provider: Provider) -> None:
        """Run the segmented download over the job's links."""

        def record(p: Progress) -> None:
            job.bytes_done = p.done_bytes
            job.parts_total = p.parts_total
            job.parts_done = p.parts_done
            job.active_connections = p.active
            job.speed = p.speed
            job.updated_at = time.time()
            self._publish(job)
            self._persist()

        validator = Validator(job.etag, job.last_modified)

        def on_progress(p: Progress) -> None:
            job.etag, job.last_modified = validator.etag, validator.last_modified
            record(p)

        def on_validator(seen: Validator) -> None:
            job.etag, job.last_modified = seen.etag, seen.last_modified
            self._persist(force=True)

        self._set(job, Status.DOWNLOADING, Phase.DOWNLOADING, "messages.downloading",
                  count=len(job.links))
        try:
            SegmentedDownload(
                links=job.links, size=job.size, part_dir=self._part_dir(job),
                split_size=job.split_size, headers=provider.headers(), cancelled=run.cancelled,
                on_progress=on_progress, validator=validator, on_validator=on_validator,
            ).run()
        finally:
            job.etag, job.last_modified = validator.etag, validator.last_modified

    def _part_dir(self, job: Job) -> Path:
        """Directory holding the part files of `job`."""
        return self.settings.data_dir / "jobs" / job.id

    def _set(self, job: Job, status: Status, phase: Phase | None, key: str, **params) -> None:
        """Change a job's status, phase and message, then persist and publish."""
        self._commit(job, self._apply(job, status, phase, key, **params))

    def _apply(self, job: Job, status: Status, phase: Phase | None, key: str, **params) -> bool:
        """Change a job's status, phase and message in memory; return whether status or phase changed.

        - `key` is a translation key and `params` its values; `message` gets the fallback text.
        - Safe to call under `self._lock`; it neither persists nor publishes.
        """
        changed = job.status != status or job.phase != phase
        job.status = status
        job.phase = phase
        job.message_key = key
        job.message_params = params
        job.message = render(key, params)
        job.updated_at = time.time()
        if status == Status.COMPLETED and changed:
            job.completed_at = job.updated_at
        if changed:
            log.info("job %s -> %s/%s: %s", job.id, status.value, phase.value if phase else "-", key)
        return changed

    def _commit(self, job: Job, changed: bool) -> None:
        """Persist and publish a job after `_apply`.

        - A status or phase change is persisted and published at once; a message-only change,
          such as a countdown, is published throttled.
        - Never called under `self._lock`, since persisting takes that lock after its own.
        """
        if changed:
            self._persist(force=True)
        self._publish(job, force=changed)

    def _publish(self, job: Job, force: bool = False) -> None:
        """Send the job's current task object on the bus, unless it has left the list.

        - The membership check and the send share one lock hold, and removals publish
          `task_removed` only after dropping the job, so no `task` event follows `task_removed`.
        """
        with self._lock:
            if self.jobs.get(job.id) is job:
                self.bus.publish_task(self.public(job), force=force)

    def _lock_path(self) -> Path:
        """Cross-process lock file guarding `jobs.json`."""
        return self.jobs_file.with_name(self.jobs_file.name + ".lock")

    def _persist(self, force: bool = False) -> None:
        """Write all jobs to `jobs.json`, at most every PERSIST_INTERVAL seconds unless forced.

        - Snapshot and write happen under one lock, so an older snapshot never lands last.
        """
        now = time.monotonic()
        if not force and now - self._last_persist < PERSIST_INTERVAL:
            return
        self._last_persist = now
        tmp = self.jobs_file.with_name(self.jobs_file.name + ".tmp")
        with self._persist_lock:
            with self._lock:
                payload = [job.stored() for job in self.jobs.values()]
            with file_lock(self._lock_path()):
                tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
                tmp.replace(self.jobs_file)


def _ffmpeg_ok(path: Path) -> bool:
    """True when ffmpeg decodes the container of `path` without warnings."""
    try:
        output = subprocess.check_output(
            ["ffmpeg", "-v", "warning", "-i", str(path), "-c", "copy", "-f", "null", "-"],
            stderr=subprocess.STDOUT, timeout=3600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return not output
