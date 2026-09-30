"""Captcha sessions and the job manager, with a fake provider backed by the local server."""

from __future__ import annotations

import json
import threading
import time

import pytest
from conftest import FakeOcr, build_manager, wait_for

from downloader.captcha import CaptchaSession
from downloader.events import EventBus
from downloader.jobs import DuplicateTask, InsufficientSpace, InvalidState, Job, Phase, Status
from downloader.providers.base import Cancelled, CaptchaSpec, ProviderError

SPEC = CaptchaSpec(length=6)
URL = "https://fake.test/f/{}"


def test_captcha_session_reads_until_limit():
    session = CaptchaSession(FakeOcr(["ab12", "XYZ789"]), 3, threading.Event())
    assert session.solve(b"img1", SPEC) is None
    assert session.solve(b"img2", SPEC) == "xyz789"
    assert session.solve(b"img3", SPEC) == "abc123"
    with pytest.raises(ProviderError) as info:
        session.solve(b"img4", SPEC)
    assert info.value.code == "captcha_failed"


def test_captcha_session_stops_when_cancelled():
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Cancelled):
        CaptchaSession(FakeOcr(), 5, cancelled).solve(b"img", SPEC)


def test_job_completes(tmp_path, provider, content):
    manager = build_manager(tmp_path, provider, ocr=FakeOcr(["zz"]))
    job = manager.create(URL.format("one"))
    wait_for(lambda: job.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "one.bin").read_bytes() == content
    assert not (tmp_path / "downloads" / "one.bin.part").exists()
    assert not (tmp_path / "data" / "jobs" / job.id).exists()
    public = manager.public(job)
    assert public["file_exists"] is True and public["completed_at"] and public["eta"] is None
    assert public["bytes_done"] == public["size"] == len(content)
    assert "links" not in public and "output_path" not in public


def test_ocr_limit_fails_the_job(tmp_path, provider):
    manager = build_manager(tmp_path, provider, ocr=FakeOcr(default="nope00"), captcha_max_attempts=3)
    job = manager.create(URL.format("ocr"))
    wait_for(lambda: job.status == Status.FAILED)
    assert job.error["code"] == "captcha_failed"


def test_expired_links_are_regenerated(tmp_path, provider, server):
    provider.expire_first = True
    original = server.httpd.RequestHandlerClass.do_GET

    def do_get(handler):
        if handler.path == "/gone":
            handler.send_response(410)
            handler.end_headers()
            return
        original(handler)

    server.httpd.RequestHandlerClass.do_GET = do_get
    manager = build_manager(tmp_path, provider, connections=2)
    job = manager.create(URL.format("three"))
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    assert job.status == Status.COMPLETED, job.error
    assert provider.link_calls == 2


def test_pause_resume_and_restart(tmp_path, provider, server, content):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("four"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.pause(job.id)
    wait_for(lambda: job.status == Status.PAUSED)
    assert 0 < job.bytes_done < len(content)
    with pytest.raises(InvalidState):
        manager.pause(job.id)

    restarted = build_manager(tmp_path, provider)
    again = restarted.get(job.id)
    assert again.status == Status.PAUSED and again.links
    server.delay = 0
    restarted.resume(job.id)
    with pytest.raises(InvalidState):
        restarted.resume(job.id)
    wait_for(lambda: again.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "four.bin").read_bytes() == content


def test_restart_marks_active_jobs_paused(tmp_path, provider, server):
    server.delay = 0.2
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("five"))
    wait_for(lambda: job.status == Status.DOWNLOADING)
    restarted = build_manager(tmp_path, provider)
    stored = restarted.get(job.id)
    assert stored.status == Status.PAUSED and stored.phase is None
    assert "重新啟動" in stored.message
    manager.delete(job.id)


def test_cancel_deletes_partial_data_and_retry_restarts(tmp_path, provider, server, content):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("six"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.cancel(job.id)
    assert job.status == Status.CANCELED and job.bytes_done == 0
    assert not (tmp_path / "data" / "jobs" / job.id).exists()
    with pytest.raises(InvalidState):
        manager.cancel(job.id)

    server.delay = 0
    manager.retry(job.id)
    wait_for(lambda: job.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "six.bin").read_bytes() == content


def test_cancel_paused_job(tmp_path, provider, server):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("seven"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.pause(job.id)
    wait_for(lambda: job.status == Status.PAUSED)
    manager.cancel(job.id)
    assert job.status == Status.CANCELED
    assert not (tmp_path / "data" / "jobs" / job.id).exists()


def test_failed_job_can_be_retried(tmp_path, provider, content):
    manager = build_manager(tmp_path, provider, ocr=FakeOcr(default="nope00"), captcha_max_attempts=1)
    job = manager.create(URL.format("eight"))
    wait_for(lambda: job.status == Status.FAILED)
    with pytest.raises(InvalidState):
        manager.resume(job.id)
    manager.ocr.default = "abc123"
    manager.settings.captcha_max_attempts = 5
    manager.retry(job.id)
    wait_for(lambda: job.status == Status.COMPLETED)
    assert job.error is None


def test_duplicates(tmp_path, provider, server):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("nine"))
    with pytest.raises(DuplicateTask) as info:
        manager.create(URL.format("nine"))
    assert info.value.code == "duplicate_active" and info.value.task_id == job.id

    server.delay = 0
    wait_for(lambda: job.status == Status.COMPLETED)
    with pytest.raises(DuplicateTask) as info:
        manager.create(URL.format("nine"))
    assert info.value.code == "duplicate_completed"
    second = manager.create(URL.format("nine"), force=True)
    wait_for(lambda: second.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "nine (1).bin").exists()
    assert manager.find_duplicate("fake", "nine").id == second.id


def test_insufficient_space(tmp_path, provider):
    provider.size = 10**18
    manager = build_manager(tmp_path, provider)
    with pytest.raises(InsufficientSpace):
        manager.create(URL.format("huge"))
    assert manager.list() == []


def test_same_filesystem_needs_double_space(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    assert manager.required_bytes(100) == 200
    assert manager.required_bytes(None) is None


def test_delete_running_job_removes_parts(tmp_path, provider, server):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("ten"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.delete(job.id)
    assert not (tmp_path / "data" / "jobs" / job.id).exists()
    assert manager.list() == []


def test_delete_with_and_without_file(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    kept = manager.create(URL.format("keep"))
    gone = manager.create(URL.format("gone"))
    wait_for(lambda: kept.status == gone.status == Status.COMPLETED)
    manager.delete(kept.id)
    manager.delete(gone.id, delete_file=True)
    assert (tmp_path / "downloads" / "keep.bin").exists()
    assert not (tmp_path / "downloads" / "gone.bin").exists()


def test_delete_file_refuses_symlinks(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("link"))
    wait_for(lambda: job.status == Status.COMPLETED)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"precious")
    target = tmp_path / "downloads" / "link.bin"
    target.unlink()
    target.symlink_to(outside)
    assert manager.file_path(job.id) is None
    manager.delete(job.id, delete_file=True)
    assert outside.read_bytes() == b"precious"


def test_clear_completed(tmp_path, provider, server):
    manager = build_manager(tmp_path, provider)
    done = manager.create(URL.format("done"))
    wait_for(lambda: done.status == Status.COMPLETED)
    server.delay = 0.05
    running = manager.create(URL.format("running"))
    assert manager.clear_completed() == 1
    assert [j.id for j in manager.list()] == [running.id]
    assert (tmp_path / "downloads" / "done.bin").exists()
    manager.delete(running.id)


def test_status_and_phase_changes_are_published(tmp_path, provider):
    bus = EventBus()
    seen = []
    bus.publish_task = lambda task, force=False: seen.append((task["status"], task["phase"], force))
    manager = build_manager(tmp_path, provider, bus=bus)
    job = manager.create(URL.format("events"))
    wait_for(lambda: job.status == Status.COMPLETED)
    forced = [(s, p) for s, p, force in seen if force]
    assert forced[0] == ("queued", None)
    assert ("downloading", "captcha") in forced and ("downloading", "downloading") in forced
    assert forced[-1] == ("completed", None)


def test_settings_apply_to_new_jobs(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    manager.update_preferences({"connections": 3, "max_active_jobs": 1})
    job = manager.create(URL.format("prefs"))
    assert job.connections == 3
    wait_for(lambda: job.status == Status.COMPLETED)
    assert build_manager(tmp_path, provider).preferences().connections == 3


def test_load_older_job_layout():
    old = {"id": "abcdef012345", "url": "u", "provider": "k2s", "file_id": "f", "connections": 2,
           "split_size": 20, "filename": "a.bin", "done_bytes": 7, "links_count": 3}
    job = Job.load(old | {"state": "generating_links", "message": "Generated 3/20 links", "error": None})
    assert (job.status, job.phase, job.file_name, job.bytes_done) == (Status.PAUSED, None, "a.bin", 7)
    assert job.error is None and "Generated" not in job.message
    assert Job.load(json.loads(json.dumps(job.stored()))) == job

    raw = "Unexpected error: ConnectionError(HTTPSConnectionPool(host='k2s.cc'))"
    failed = Job.load(old | {"state": "failed", "message": raw, "error": raw})
    assert failed.status == Status.FAILED and failed.error["code"] == "internal_error"
    assert "ConnectionError" not in failed.message + failed.error["message"]


def slow_assembly(monkeypatch, seconds=1.0):
    """Make assembly take `seconds` longer."""
    import downloader.jobs as jobs_module

    original = jobs_module.assemble

    def slow(*args):
        time.sleep(seconds)
        original(*args)

    monkeypatch.setattr(jobs_module, "assemble", slow)


def test_cancel_and_delete_are_refused_while_assembling(tmp_path, provider, monkeypatch, content):
    slow_assembly(monkeypatch)
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("asm"))
    wait_for(lambda: job.phase == Phase.ASSEMBLING)
    for action in (manager.cancel, manager.delete, manager.pause):
        with pytest.raises(InvalidState):
            action(job.id)
    wait_for(lambda: job.status == Status.COMPLETED)
    assert manager.public(job)["file_exists"] is True
    assert (tmp_path / "downloads" / "asm.bin").read_bytes() == content


def test_cancel_racing_completion_keeps_the_file_tracked(tmp_path, provider, monkeypatch):
    slow_assembly(monkeypatch)
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("race"))
    wait_for(lambda: job.phase == Phase.ASSEMBLING)
    with manager._lock:
        run = manager._runs[job.id]
        run.intent = "cancel"
        run.cancelled.set()
    wait_for(lambda: job.id not in manager._runs)
    assert job.status == Status.COMPLETED
    assert manager.public(job)["file_exists"] is True


def test_delete_intent_is_applied_by_the_worker(tmp_path, provider, server):
    server.delay = 0.05
    removed = []
    bus = EventBus()
    bus.publish_removed = removed.append
    manager = build_manager(tmp_path, provider, bus=bus)
    job = manager.create(URL.format("gone"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.delete(job.id)
    assert job.id not in manager.jobs and removed == [job.id]
    assert not (tmp_path / "data" / "jobs" / job.id).exists()


def test_captcha_limit_counts_per_run(tmp_path, provider, server):
    provider.expire_first = True
    original = server.httpd.RequestHandlerClass.do_GET

    def do_get(handler):
        if handler.path == "/gone":
            handler.send_response(410)
            handler.end_headers()
            return
        original(handler)

    server.httpd.RequestHandlerClass.do_GET = do_get
    manager = build_manager(tmp_path, provider, connections=1, captcha_max_attempts=1)
    job = manager.create(URL.format("limit"))
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    assert job.error["code"] == "captcha_failed"
