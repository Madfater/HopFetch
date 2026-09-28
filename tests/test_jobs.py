"""Captcha sessions and the job manager, with a fake provider backed by the local server."""

from __future__ import annotations

import threading
import time

import pytest

from downloader.captcha import CaptchaSession
from downloader.config import Settings
from downloader.jobs import DuplicateJob, JobManager, State
from downloader.providers import ProviderRegistry
from downloader.providers.base import (
    STATUS_SOLVING_CAPTCHA,
    CaptchaSpec,
    Cancelled,
    FileInfo,
    FileRef,
    LinkContext,
    Provider,
)
from downloader.providers.direct import DirectProvider
from downloader.proxies import ProxyPool

SPEC = CaptchaSpec(length=6)
MIB = 2**20


class FakeOcr:
    """Returns queued readings in order."""

    def __init__(self, readings):
        self.readings = list(readings)

    def read(self, image):
        return self.readings.pop(0)


class CaptchaProvider(Provider):
    """Asks for captchas until one is `abc123`, then returns the server URL as every link."""

    name = "fake"
    label = "Fake host"
    hosts = ("fake.test",)

    def __init__(self, server_url: str, size: int):
        self.server_url = server_url
        self.size = size
        self.link_calls = 0
        self.expire_first = False

    def match(self, url):
        return url.rsplit("/", 1)[-1] if url.startswith("https://fake.test/") else None

    def get_info(self, ref: FileRef) -> FileInfo:
        return FileInfo(name=f"{ref.file_id}.bin", size=self.size)

    def generate_links(self, ref, count, ctx: LinkContext):
        self.link_calls += 1
        while True:
            ctx.set_status(STATUS_SOLVING_CAPTCHA, "solving")
            if ctx.solve_captcha(b"png", SPEC) == "abc123":
                break
        if self.expire_first and self.link_calls == 1:
            return [self.server_url.replace("/file.bin", "/gone")] * count
        return [self.server_url] * count


def wait_for(predicate, timeout=15.0):
    """Poll until `predicate()` is truthy or fail."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def make_manager(tmp_path, server, content, ocr=None, **overrides):
    settings = Settings(data_dir=tmp_path / "data", download_dir=tmp_path / "downloads",
                        use_proxies=False, **overrides)
    provider = CaptchaProvider(server.url, len(content))
    manager = JobManager(settings, ProviderRegistry([provider, DirectProvider()]),
                         proxies=ProxyPool(settings.data_dir / "proxies.txt", enabled=False),
                         ocr=ocr)
    manager.start()
    return manager, provider


def test_captcha_session_ocr_then_manual():
    cancelled = threading.Event()
    shown = []
    session = CaptchaSession(FakeOcr(["ab12", "XYZ789"]), 2, cancelled, shown.append)
    assert session.solve(b"img1", SPEC) is None
    assert session.solve(b"img2", SPEC) == "xyz789"

    threading.Timer(0.1, session.submit, args=(" QWE456 ",)).start()
    assert session.solve(b"img3", SPEC) == "qwe456"
    assert shown == [b"img3"]


def test_captcha_session_cancel_while_waiting():
    cancelled = threading.Event()
    session = CaptchaSession(None, 5, cancelled, lambda image: None)
    threading.Timer(0.1, cancelled.set).start()
    with pytest.raises(Cancelled):
        session.solve(b"img", SPEC)


def test_job_completes_with_ocr(tmp_path, server, content):
    manager, _ = make_manager(tmp_path, server, content, ocr=FakeOcr(["zz", "ABC123"]))
    job = manager.create("https://fake.test/one", None, 3, 20 * MIB)
    wait_for(lambda: job.state == State.COMPLETED)
    assert job.captcha_attempts == 2
    assert (tmp_path / "downloads" / "one.bin").read_bytes() == content
    assert not (tmp_path / "data" / "jobs" / job.id).exists()


def test_job_manual_captcha_path(tmp_path, server, content):
    manager, _ = make_manager(tmp_path, server, content, captcha_ocr=False)
    job = manager.create("https://fake.test/two", "renamed.bin", 2, 20 * MIB)
    wait_for(lambda: job.state == State.AWAITING_CAPTCHA)
    assert manager.captcha_image(job.id) == b"png"

    manager.submit_captcha(job.id, "wrong1")
    wait_for(lambda: job.state == State.AWAITING_CAPTCHA and manager.captcha_image(job.id))
    manager.submit_captcha(job.id, "abc123")
    wait_for(lambda: job.state == State.COMPLETED)
    assert (tmp_path / "downloads" / "renamed.bin").read_bytes() == content


def test_expired_links_are_regenerated(tmp_path, server, content):
    manager, provider = make_manager(tmp_path, server, content, ocr=FakeOcr(["abc123"] * 2))
    provider.expire_first = True
    server.refuse = False
    original = server.httpd.RequestHandlerClass.do_GET

    def do_get(handler):
        if handler.path == "/gone":
            handler.send_response(410)
            handler.end_headers()
            return
        original(handler)

    server.httpd.RequestHandlerClass.do_GET = do_get
    job = manager.create("https://fake.test/three", None, 2, 20 * MIB)
    wait_for(lambda: job.state in (State.COMPLETED, State.FAILED))
    assert job.state == State.COMPLETED, job.error
    assert provider.link_calls == 2


def test_pause_resume_and_restart(tmp_path, server, content):
    server.delay = 0.05
    manager, _ = make_manager(tmp_path, server, content, ocr=FakeOcr(["abc123"]))
    job = manager.create("https://fake.test/four", None, 2, 20 * MIB)
    wait_for(lambda: job.state == State.DOWNLOADING and job.done_bytes > 0)
    manager.pause(job.id)
    wait_for(lambda: job.state == State.PAUSED)
    saved = job.done_bytes
    assert 0 < saved < len(content)

    restarted, _ = make_manager(tmp_path, server, content, ocr=FakeOcr([]))
    again = restarted.get(job.id)
    assert again.state == State.PAUSED and again.links
    server.delay = 0
    restarted.resume(job.id)
    wait_for(lambda: again.state == State.COMPLETED)
    assert (tmp_path / "downloads" / "four.bin").read_bytes() == content


def test_restart_marks_active_jobs_paused(tmp_path, server, content):
    manager, _ = make_manager(tmp_path, server, content, captcha_ocr=False)
    job = manager.create("https://fake.test/five", None, 2, 20 * MIB)
    wait_for(lambda: job.state == State.AWAITING_CAPTCHA)
    restarted, _ = make_manager(tmp_path, server, content)
    assert restarted.get(job.id).state == State.PAUSED
    manager.delete(job.id)


def test_duplicate_and_validation(tmp_path, server, content):
    manager, _ = make_manager(tmp_path, server, content, captcha_ocr=False)
    job = manager.create("https://fake.test/six", None, 2, 20 * MIB)
    with pytest.raises(DuplicateJob):
        manager.create("https://fake.test/six", None, 2, 20 * MIB)
    with pytest.raises(ValueError, match="20 MiB"):
        manager.create("https://fake.test/seven", None, 2, MIB)
    with pytest.raises(ValueError, match="Connections"):
        manager.create("https://fake.test/seven", None, 0, 20 * MIB)
    manager.delete(job.id)
    assert job.id not in manager.jobs


def test_delete_running_job_removes_parts(tmp_path, server, content):
    server.delay = 0.05
    manager, _ = make_manager(tmp_path, server, content, ocr=FakeOcr(["abc123"]))
    job = manager.create("https://fake.test/eight", None, 2, 20 * MIB)
    wait_for(lambda: job.state == State.DOWNLOADING and job.done_bytes > 0)
    manager.delete(job.id)
    assert not (tmp_path / "data" / "jobs" / job.id).exists()
    assert manager.list() == []


def test_resume_right_after_pause(tmp_path, server, content):
    server.delay = 0.05
    manager, _ = make_manager(tmp_path, server, content, ocr=FakeOcr(["abc123"]))
    job = manager.create("https://fake.test/nine", None, 2, 20 * MIB)
    wait_for(lambda: job.state == State.DOWNLOADING and job.done_bytes > 0)
    manager.pause(job.id)
    wait_for(lambda: job.state == State.PAUSED)
    server.delay = 0
    manager.resume(job.id)
    with pytest.raises(ValueError):
        manager.resume(job.id)
    wait_for(lambda: job.state == State.COMPLETED)
    assert (tmp_path / "downloads" / "nine.bin").read_bytes() == content
