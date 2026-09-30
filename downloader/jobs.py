"""Download jobs: their state machine, persistence, and the worker thread that drives each one."""

from __future__ import annotations

import json
import logging
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
from .providers import ProviderRegistry
from .providers.base import Cancelled, FileRef, LinkContext, Provider, ProviderError
from .proxies import ProxyPool
from .util import MIN_SPLIT_SIZE, file_lock, safe_filename, unique_path

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".m4v", ".wmv", ".flv"}
PERSIST_INTERVAL = 5.0


class State(str, Enum):
    """Job states; the first group is active, the second is where a job rests."""

    QUEUED = "queued"
    RESOLVING = "resolving"
    PREPARING = "preparing"
    SOLVING_CAPTCHA = "solving_captcha"
    AWAITING_CAPTCHA = "awaiting_captcha"
    WAITING = "waiting"
    GENERATING_LINKS = "generating_links"
    DOWNLOADING = "downloading"
    ASSEMBLING = "assembling"
    VERIFYING = "verifying"

    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


RESTING = {State.COMPLETED, State.FAILED, State.PAUSED}
RESUMABLE = {State.FAILED, State.PAUSED}


class DuplicateJob(Exception):
    """A job for the same file is already in the list."""

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = job_id


@dataclass
class Job:
    """One download, as stored in `jobs.json` and returned by the API."""

    id: str
    url: str
    provider: str
    file_id: str
    connections: int
    split_size: int
    requested_filename: str | None = None
    filename: str | None = None
    size: int | None = None
    state: State = State.QUEUED
    message: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    links: list[str] = field(default_factory=list)
    links_created_at: float | None = None
    done_bytes: int = 0
    parts_total: int = 0
    parts_done: int = 0
    active_connections: int = 0
    speed: float = 0.0
    output_path: str | None = None
    verified: str | None = None
    captcha_attempts: int = 0

    def public(self) -> dict:
        """Return the fields the API exposes; links stay private."""
        data = asdict(self)
        data.pop("links")
        data["state"] = self.state.value
        data["links_count"] = len(self.links)
        return data

    @classmethod
    def load(cls, data: dict) -> "Job":
        """Rebuild a job from its stored form, ignoring unknown keys."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known["state"] = State(known.get("state", State.PAUSED))
        return cls(**known)


class _Run:
    """Runtime-only companions of a job: its thread, cancel flag and captcha session."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.delete = False
        self.thread: threading.Thread | None = None
        self.captcha: CaptchaSession | None = None
        self.captcha_image: bytes | None = None


class JobManager:
    """Owns all jobs: creates, runs, pauses, resumes and deletes them, and persists the list.

    - Each running job has one worker thread; at most `settings.max_active_jobs` download at once.
    - `jobs.json` is rewritten on every state change and at most every PERSIST_INTERVAL seconds
      during progress, under a cross-process lock.
    - On start, jobs that were active when the server stopped become `paused`.
    """

    def __init__(self, settings: Settings, registry: ProviderRegistry,
                 proxies: ProxyPool | None = None, ocr: OcrSolver | None = None):
        self.settings = settings
        self.registry = registry
        self.proxies = proxies or ProxyPool(settings.data_dir / "proxies.txt", settings.use_proxies,
                                            user_proxies=settings.proxies,
                                            user_file=settings.data_dir / "proxies.user.txt")
        self.ocr = ocr if ocr is not None else (OcrSolver() if settings.captcha_ocr else None)
        self.jobs: dict[str, Job] = {}
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()
        self._slots = threading.Semaphore(settings.max_active_jobs)
        self._last_persist = 0.0
        self._persist_lock = threading.Lock()
        self.jobs_file = settings.data_dir / "jobs.json"

    def start(self) -> None:
        """Load stored jobs and mark interrupted ones as paused."""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self._lock_path()):
            stored = json.loads(self.jobs_file.read_text()) if self.jobs_file.exists() else []
        with self._lock:
            for data in stored:
                job = Job.load(data)
                if job.state not in RESTING:
                    job.state = State.PAUSED
                    job.message = "Interrupted by a server restart"
                job.active_connections = 0
                job.speed = 0.0
                self.jobs[job.id] = job
        self._persist(force=True)

    def shutdown(self, timeout: float = 30) -> None:
        """Pause every running job and wait for the workers to stop."""
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.cancelled.set()
        for run in runs:
            if run.thread:
                run.thread.join(timeout)
        self._persist(force=True)

    def create(self, url: str, filename: str | None, connections: int, split_size: int) -> Job:
        """Validate the request, add a job and start it."""
        if split_size < MIN_SPLIT_SIZE:
            raise ValueError("Split size must be at least 20 MiB")
        if not 1 <= connections <= 64:
            raise ValueError("Connections must be between 1 and 64")
        provider, ref = self.registry.resolve(url)
        with self._lock:
            for job in self.jobs.values():
                if job.provider == provider.name and job.file_id == ref.file_id \
                        and job.state != State.COMPLETED:
                    raise DuplicateJob(job.id)
            job = Job(
                id=uuid.uuid4().hex[:12], url=ref.url, provider=provider.name, file_id=ref.file_id,
                connections=connections, split_size=split_size,
                requested_filename=safe_filename(filename) if filename and filename.strip() else None,
            )
            self.jobs[job.id] = job
        self._launch(job)
        return job

    def get(self, job_id: str) -> Job:
        """Return a job, raising KeyError when it does not exist."""
        return self.jobs[job_id]

    def list(self) -> list[Job]:
        """Return all jobs, newest first."""
        with self._lock:
            return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def captcha_image(self, job_id: str) -> bytes | None:
        """Return the captcha image a job waits on, if any."""
        run = self._runs.get(job_id)
        return run.captcha_image if run else None

    def submit_captcha(self, job_id: str, answer: str) -> None:
        """Pass the user's captcha answer to the waiting job."""
        job = self.get(job_id)
        run = self._runs.get(job_id)
        if job.state != State.AWAITING_CAPTCHA or not run or not run.captcha:
            raise ValueError("This job is not waiting for a captcha")
        if not answer.strip():
            raise ValueError("Enter the captcha text")
        run.captcha_image = None
        self._set(job, State.SOLVING_CAPTCHA, "Submitting the captcha answer")
        run.captcha.submit(answer)

    def pause(self, job_id: str) -> Job:
        """Stop a running job, keeping its part files."""
        job = self.get(job_id)
        run = self._runs.get(job_id)
        if run is None or job.state in RESTING:
            raise ValueError("This job is not running")
        run.cancelled.set()
        return job

    def resume(self, job_id: str) -> Job:
        """Restart a paused or failed job from the bytes already on disk."""
        with self._lock:
            job = self.get(job_id)
            if job.state not in RESUMABLE or job_id in self._runs:
                raise ValueError("Only paused or failed jobs can be resumed")
            job.error = None
            run = self._register(job)
        self._set(job, State.QUEUED, "Queued")
        self._start(job, run)
        return job

    def delete(self, job_id: str) -> None:
        """Stop a job if needed, then remove it and its part files; finished files stay."""
        job = self.get(job_id)
        run = self._runs.get(job_id)
        if run is not None:
            run.delete = True
            run.cancelled.set()
            if run.thread:
                run.thread.join(30)
        with self._lock:
            self.jobs.pop(job.id, None)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        self._persist(force=True)

    def _launch(self, job: Job) -> None:
        """Register and start the worker thread of `job`."""
        with self._lock:
            run = self._register(job)
        self._start(job, run)

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
        """Worker body: wait for a slot, run the job, and record how it ended."""
        self._set(job, State.QUEUED, "Waiting for a free slot")
        acquired = False
        outcome: tuple[State, str] | None = None
        try:
            while not (acquired := self._slots.acquire(timeout=0.5)):
                if run.cancelled.is_set():
                    raise Cancelled()
            self._execute(job, run)
        except Cancelled:
            outcome = (State.PAUSED, "Paused")
        except (ProviderError, LinksExpired, DownloadStalled, ValueError) as exc:
            job.error = str(exc) or type(exc).__name__
            outcome = (State.FAILED, job.error)
        except Exception as exc:
            log.exception("job %s crashed", job.id)
            job.error = f"Unexpected error: {exc!r}"
            outcome = (State.FAILED, job.error)
        finally:
            if acquired:
                self._slots.release()
            job.active_connections = 0
            job.speed = 0.0
            with self._lock:
                self._runs.pop(job.id, None)
            if outcome is not None and not run.delete:
                self._set(job, *outcome)
            if not run.delete:
                self._persist(force=True)

    def _execute(self, job: Job, run: _Run) -> None:
        """Resolve, get links, download, assemble and verify one job."""
        provider = self.registry.get(job.provider)
        ref = FileRef(url=job.url, file_id=job.file_id)

        if job.filename is None or job.size is None:
            self._set(job, State.RESOLVING, "Reading file information")
            info = provider.get_info(ref)
            job.filename = job.requested_filename or safe_filename(info.name)
            job.size = info.size
            self._persist(force=True)
        if not job.size:
            raise ProviderError("The platform did not report the file size")

        retried = False
        while True:
            if not self._links_fresh(job, provider):
                self._generate_links(job, run, provider, ref)
            try:
                self._download(job, run, provider)
                break
            except LinksExpired:
                if retried:
                    raise LinksExpired("Newly generated links were refused by the server")
                retried = True
                job.links = []
                self._set(job, State.GENERATING_LINKS, "Links expired, generating new ones")

        self._set(job, State.ASSEMBLING, "Joining parts")
        output = unique_path(self.settings.download_dir / job.filename)
        assemble(self._part_dir(job), build_parts(job.size, job.split_size), output)
        shutil.rmtree(self._part_dir(job), ignore_errors=True)
        job.output_path = str(output)
        job.done_bytes = job.size
        job.parts_done = job.parts_total

        if output.suffix.lower() in VIDEO_SUFFIXES and shutil.which("ffmpeg"):
            self._set(job, State.VERIFYING, "Checking the video with ffmpeg")
            job.verified = "ok" if _ffmpeg_ok(output) else "corrupt"
        self._set(job, State.COMPLETED, f"Saved to {output.name}")

    def _links_fresh(self, job: Job, provider: Provider) -> bool:
        """True when stored links exist and are younger than the provider's link TTL."""
        if not job.links or job.links_created_at is None:
            return False
        return time.time() - job.links_created_at < provider.link_ttl

    def _generate_links(self, job: Job, run: _Run, provider: Provider, ref: FileRef) -> None:
        """Ask the provider for links, wiring captcha and status reporting to the job."""

        def on_manual(image: bytes) -> None:
            run.captcha_image = image
            self._set(job, State.AWAITING_CAPTCHA, "Type the captcha shown below")

        def on_ocr(attempt: int) -> None:
            job.captcha_attempts = attempt
            self._set(job, State.SOLVING_CAPTCHA, f"Reading the captcha automatically (try {attempt})")

        run.captcha = CaptchaSession(self.ocr, self.settings.ocr_attempts, run.cancelled,
                                     on_manual, on_ocr)
        ctx = LinkContext(
            solve_captcha=run.captcha.solve,
            set_status=lambda state, message: self._set(job, State(state), message),
            proxies=self.proxies,
            cancelled=run.cancelled,
        )
        links = provider.generate_links(ref, job.connections, ctx)
        run.captcha = None
        run.captcha_image = None
        if not links:
            raise ProviderError("The platform returned no download links")
        job.links = links
        job.links_created_at = time.time()
        self._persist(force=True)

    def _download(self, job: Job, run: _Run, provider: Provider) -> None:
        """Run the segmented download over the job's links."""

        def on_progress(p: Progress) -> None:
            job.done_bytes = p.done_bytes
            job.parts_total = p.parts_total
            job.parts_done = p.parts_done
            job.active_connections = p.active
            job.speed = p.speed
            job.updated_at = time.time()
            self._persist()

        count = len(job.links)
        note = f" (only {count} of {job.connections} links)" if count < job.connections else ""
        self._set(job, State.DOWNLOADING, f"Downloading over {count} connections{note}")
        SegmentedDownload(
            links=job.links, size=job.size, part_dir=self._part_dir(job),
            split_size=job.split_size, headers=provider.headers(), cancelled=run.cancelled,
            on_progress=on_progress,
        ).run()

    def _part_dir(self, job: Job) -> Path:
        """Directory holding the part files of `job`."""
        return self.settings.data_dir / "jobs" / job.id

    def _set(self, job: Job, state: State, message: str) -> None:
        """Change a job's state and message, persisting when the state changed."""
        changed = job.state != state
        job.state = state
        job.message = message
        job.updated_at = time.time()
        if changed:
            log.info("job %s -> %s: %s", job.id, state.value, message)
            self._persist(force=True)

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
                payload = [asdict(job) | {"state": job.state.value} for job in self.jobs.values()]
            with file_lock(self._lock_path()):
                tmp.write_text(json.dumps(payload, indent=2))
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
