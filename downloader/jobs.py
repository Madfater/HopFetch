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
from .engine import DownloadStalled, LinksExpired, Progress, SegmentedDownload, assemble, build_parts
from .events import EventBus
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
LEGACY_ERROR = {"code": "internal_error", "message": "這個任務在服務更新前就已失敗。按重試再試一次。"}
LEGACY_MESSAGES = {
    Status.COMPLETED: "已完成",
    Status.FAILED: LEGACY_ERROR["message"],
    Status.PAUSED: "已暫停。按繼續從中斷處下載。",
}
FINISHING = {Phase.ASSEMBLING, Phase.VERIFYING}


class TaskError(Exception):
    """A request the manager refuses, with a stable `code` and a zh-Hant `message`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DuplicateTask(TaskError):
    """A job for the same file exists; `task_id` and `task_status` point at it."""

    def __init__(self, code: str, message: str, job: "Job"):
        super().__init__(code, message)
        self.task_id = job.id
        self.task_status = job.status.value


class InsufficientSpace(TaskError):
    """The download root lacks room for the file."""


class InvalidState(TaskError):
    """The action does not apply to the job's current status."""

    def __init__(self, message: str):
        super().__init__("invalid_state", message)


@dataclass
class Job:
    """One download, as stored in `jobs.json`.

    - `output_path` is the final file name chosen when assembly starts; while the job is not
      completed, the file at that path plus PART_SUFFIX is the job's staging file.
    - `etag` and `last_modified` are reserved for validating resumed downloads.
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

    def public(self, root: Path) -> dict:
        """Return the task object the API exposes; links and paths stay private.

        - `eta` is known only while downloading with a measured speed.
        - `file_exists` is checked on disk for completed jobs, inside `root` only.
        """
        downloading = self.status == Status.DOWNLOADING and self.phase == Phase.DOWNLOADING
        eta = None
        if downloading and self.speed > 0 and self.size:
            eta = max(0, round((self.size - self.bytes_done) / self.speed))
        file_exists = bool(self.status == Status.COMPLETED and self.output_path
                           and inside(root, Path(self.output_path)))
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
            "message": self.message,
            "resumable": self.resumable,
            "file_exists": file_exists,
            "error": self.error,
            "verified": self.verified,
            "created_at": self.created_at,
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
          replaced with fixed zh-Hant text.
        """
        data = dict(data)
        if "state" in data and "status" not in data:
            status = LEGACY_STATES.get(data.pop("state"), Status.PAUSED)
            data["status"] = status.value
            data["file_name"] = data.get("requested_filename") or data.get("filename")
            data["bytes_done"] = data.get("done_bytes", 0)
            data["phase"] = None
            data["message"] = LEGACY_MESSAGES[status]
            data["error"] = dict(LEGACY_ERROR) if status == Status.FAILED else None
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
    - `delete_file` goes with the `delete` intent.
    - `captcha` is shared by every link generation of the run, so the OCR limit counts per run.
    """

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.intent: str | None = None
        self.delete_file = False
        self.thread: threading.Thread | None = None
        self.captcha: CaptchaSession | None = None


class JobManager:
    """Owns all jobs: creates, runs, pauses, resumes, cancels and deletes them.

    - Each running job has one worker thread; at most `max_active_jobs` download at once.
    - `jobs.json` is rewritten on every status or phase change and at most every
      PERSIST_INTERVAL seconds during progress, under a cross-process lock.
    - Every change is published on `bus`: status and phase changes at once, progress throttled.
    - On start, jobs that were active when the server stopped become `paused`.
    """

    def __init__(self, settings: Settings, registry: ProviderRegistry,
                 store: SettingsStore | None = None, bus: EventBus | None = None,
                 proxies: ProxyPool | None = None, ocr: OcrSolver | None = None):
        self.settings = settings
        self.registry = registry
        self.store = store or SettingsStore(settings)
        self.bus = bus or EventBus()
        prefs = self.store.get()
        self.proxies = proxies or ProxyPool(settings.data_dir / "proxies.txt", prefs.use_proxies)
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
        """Load stored jobs and mark interrupted ones as paused."""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self._lock_path()):
            stored = json.loads(self.jobs_file.read_text()) if self.jobs_file.exists() else []
        with self._lock:
            for data in stored:
                job = Job.load(data)
                if job.status in ACTIVE:
                    job.status = Status.PAUSED
                    job.phase = None
                    job.message = "服務重新啟動，下載已暫停。按繼續從中斷處下載。"
                job.active_connections = 0
                job.speed = 0.0
                self.jobs[job.id] = job
        self._persist(force=True)

    def shutdown(self, timeout: float = 30) -> None:
        """Pause every running job and wait for the workers to stop."""
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.intent = run.intent or "pause"
            run.cancelled.set()
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
            raise InsufficientSpace("insufficient_space", "NAS 剩餘空間不足以存放這個檔案。清出空間後再試一次。")

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
            job.message = "等待空閒的下載名額"
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
            raise DuplicateTask("duplicate_active", "這個檔案已經在下載清單中。", dup)
        if not force:
            raise DuplicateTask("duplicate_completed", "這個檔案已經下載過。", dup)

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
                raise InvalidState("只有排隊中或下載中的任務可以暫停。")
            if job.phase in FINISHING:
                raise InvalidState("檔案正在合併或檢查，完成前無法暫停。")
            run.intent = "pause"
            run.cancelled.set()
        return job

    def resume(self, job_id: str) -> Job:
        """Queue a paused job again; it continues from the bytes on disk."""
        return self._requeue(job_id, {Status.PAUSED}, "只有已暫停的任務可以繼續。")

    def retry(self, job_id: str) -> Job:
        """Queue a failed or canceled job again."""
        return self._requeue(job_id, {Status.FAILED, Status.CANCELED}, "只有失敗或已取消的任務可以重試。")

    def _requeue(self, job_id: str, allowed: set[Status], refusal: str) -> Job:
        """Start a new worker for a resting job whose status is in `allowed`.

        - The check, the new run and the `queued` status happen under one lock hold, so a
          concurrent cancel or delete sees either the old state or the new run.
        """
        with self._lock:
            job = self.get(job_id)
            if job.status not in allowed or job_id in self._runs:
                raise InvalidState(refusal)
            job.error = None
            run = self._register(job)
            changed = self._apply(job, Status.QUEUED, None, "等待空閒的下載名額")
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
                raise InvalidState("只有未完成的任務可以取消。")
            if job.phase in FINISHING:
                raise InvalidState("檔案正在合併或檢查，完成前無法取消。")
            run = self._runs.get(job_id)
            if run is not None:
                run.intent = "cancel"
                run.cancelled.set()
            else:
                self._discard_partial(job)
                changed = self._apply(job, Status.CANCELED, None, "已取消")
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
                raise InvalidState("檔案正在合併或檢查，完成後再刪除。")
            run = self._runs.get(job_id)
            if run is not None:
                run.intent = "delete"
                run.delete_file = delete_file
                run.cancelled.set()
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
            Path(job.output_path).unlink()
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

    def file_path(self, job_id: str) -> Path | None:
        """The finished file of a completed job, or None when it is missing or outside the root.

        - A missing file publishes the job again so clients see `file_exists` turn false.
        """
        job = self.get(job_id)
        if job.status != Status.COMPLETED or not job.output_path:
            return None
        path = Path(job.output_path)
        if inside(self.root, path):
            return path
        self._publish(job, force=True)
        return None

    def _join(self, run: _Run | None) -> None:
        """Wait for a stopped run's worker to finish."""
        if run is not None and run.thread is not None and run.thread is not threading.current_thread():
            run.thread.join(30)

    def _discard_partial(self, job: Job) -> None:
        """Delete the part files and staging file of an unfinished job and reset its progress."""
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        self._remove_staging(job)
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
                staging.unlink()

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
        outcome: tuple[Status, str] | None = None
        try:
            while not (acquired := self._slots.acquire(timeout=0.5)):
                if run.cancelled.is_set():
                    raise Cancelled()
            self._execute(job, run)
        except Cancelled:
            outcome = (Status.PAUSED, "已暫停")
        except ProviderError as exc:
            outcome = self._fail(job, exc.code, exc.message)
        except LinksExpired:
            outcome = self._fail(job, "links_expired", "下載連結已失效，重新產生後仍被拒絕。按重試再試一次。")
        except DownloadStalled:
            outcome = self._fail(job, "stalled", "下載停滯太久而中斷。按重試從中斷處繼續。")
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                log.exception("job %s crashed", job.id)
                outcome = self._fail(job, "internal_error", "發生未預期的錯誤，詳細內容已寫入伺服器記錄。按重試再試一次。")
            else:
                outcome = self._fail(job, "disk_full", "NAS 空間不足，下載中斷。清出空間後按重試。")
        except Exception:
            log.exception("job %s crashed", job.id)
            outcome = self._fail(job, "internal_error", "發生未預期的錯誤，詳細內容已寫入伺服器記錄。按重試再試一次。")
        finally:
            if acquired:
                self._slots.release()
            job.active_connections = 0
            job.speed = 0.0
            self._finish_run(job, run, outcome)

    def _finish_run(self, job: Job, run: _Run, outcome: tuple[Status, str] | None) -> None:
        """Apply how a run ended, honoring a pending cancel or delete, and retire the run.

        - The status change and the removal from `_runs` happen under one lock hold, so no
          control action sees a retired run or a stale status.
        - A job that completed before it saw a cancel stays completed.
        """
        removed = False
        with self._lock:
            if run.intent == "delete":
                self.jobs.pop(job.id, None)
                removed = True
            elif run.intent == "cancel" and job.status != Status.COMPLETED:
                self._discard_partial(job)
                self._apply(job, Status.CANCELED, None, "已取消")
            elif outcome is not None:
                self._apply(job, outcome[0], None, outcome[1])
            if self._runs.get(job.id) is run:
                self._runs.pop(job.id)
        if removed:
            self._finish_removal(job, run.delete_file)
        else:
            self._persist(force=True)
            self._publish(job, force=True)

    @staticmethod
    def _fail(job: Job, code: str, message: str) -> tuple[Status, str]:
        """Record an error on `job` and return the failed outcome."""
        job.error = {"code": code, "message": message}
        return Status.FAILED, message

    def _execute(self, job: Job, run: _Run) -> None:
        """Resolve, get links, download, assemble and verify one job."""
        provider = self.registry.get(job.provider)
        ref = FileRef(url=job.url, file_id=job.file_id)

        if job.file_name is None or job.size is None:
            self._set(job, Status.DOWNLOADING, Phase.RESOLVING, "讀取檔案資訊")
            info = provider.get_info(ref)
            job.file_name = job.file_name or safe_filename(info.name)
            job.size = info.size
            self._persist(force=True)
        if not job.size:
            raise ProviderError("upstream_error", "雲端沒有提供檔案大小，無法分段下載。")

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
                self._set(job, Status.DOWNLOADING, Phase.LINKS, "下載連結已失效，重新產生")

        self._set(job, Status.DOWNLOADING, Phase.ASSEMBLING, "合併分段")
        self._remove_staging(job)
        output, handle = claim_staging(self.root / job.file_name)
        job.output_path = str(output)
        self._persist(force=True)
        with handle:
            assemble(self._part_dir(job), build_parts(job.size, job.split_size), handle)
        output = publish_staging(staging_path(output), output)
        job.output_path = str(output)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        job.bytes_done = job.size
        job.parts_done = job.parts_total

        if output.suffix.lower() in VIDEO_SUFFIXES and shutil.which("ffmpeg"):
            self._set(job, Status.DOWNLOADING, Phase.VERIFYING, "以 ffmpeg 檢查影片")
            job.verified = "ok" if _ffmpeg_ok(output) else "corrupt"
        self._set(job, Status.COMPLETED, None, f"已儲存為 {output.name}")

    def _links_fresh(self, job: Job, provider: Provider) -> bool:
        """True when stored links exist and are younger than the provider's link TTL."""
        if not job.links or job.links_created_at is None:
            return False
        return time.time() - job.links_created_at < provider.link_ttl

    def _generate_links(self, job: Job, run: _Run, provider: Provider, ref: FileRef) -> None:
        """Ask the provider for links, wiring captcha and status reporting to the job."""

        def on_attempt(attempt: int) -> None:
            self._set(job, Status.DOWNLOADING, Phase.CAPTCHA, f"辨識驗證碼（第 {attempt} 次）")

        if run.captcha is None:
            run.captcha = CaptchaSession(self.ocr, self.settings.captcha_max_attempts, run.cancelled, on_attempt)
        ctx = LinkContext(
            solve_captcha=run.captcha.solve,
            set_status=lambda phase, message: self._set(job, Status.DOWNLOADING, Phase(phase), message),
            proxies=self.proxies,
            cancelled=run.cancelled,
        )
        links = provider.generate_links(ref, job.connections, ctx)
        if not links:
            raise ProviderError("upstream_error", "雲端沒有提供下載連結。稍後再試一次。")
        job.links = links
        job.links_created_at = time.time()
        self._persist(force=True)

    def _download(self, job: Job, run: _Run, provider: Provider) -> None:
        """Run the segmented download over the job's links."""

        def on_progress(p: Progress) -> None:
            job.bytes_done = p.done_bytes
            job.parts_total = p.parts_total
            job.parts_done = p.parts_done
            job.active_connections = p.active
            job.speed = p.speed
            job.updated_at = time.time()
            self._publish(job)
            self._persist()

        self._set(job, Status.DOWNLOADING, Phase.DOWNLOADING, f"透過 {len(job.links)} 條連線下載")
        SegmentedDownload(
            links=job.links, size=job.size, part_dir=self._part_dir(job),
            split_size=job.split_size, headers=provider.headers(), cancelled=run.cancelled,
            on_progress=on_progress,
        ).run()

    def _part_dir(self, job: Job) -> Path:
        """Directory holding the part files of `job`."""
        return self.settings.data_dir / "jobs" / job.id

    def _set(self, job: Job, status: Status, phase: Phase | None, message: str) -> None:
        """Change a job's status, phase and message, then persist and publish."""
        self._commit(job, self._apply(job, status, phase, message))

    def _apply(self, job: Job, status: Status, phase: Phase | None, message: str) -> bool:
        """Change a job's status, phase and message in memory; return whether status or phase changed.

        - Safe to call under `self._lock`; it neither persists nor publishes.
        """
        changed = job.status != status or job.phase != phase
        job.status = status
        job.phase = phase
        job.message = message
        job.updated_at = time.time()
        if status == Status.COMPLETED and changed:
            job.completed_at = job.updated_at
        if changed:
            log.info("job %s -> %s/%s: %s", job.id, status.value, phase.value if phase else "-", message)
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
        """Send the job's current task object on the bus."""
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
