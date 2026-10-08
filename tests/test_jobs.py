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


def test_restart_resumes_jobs_a_crash_left_active(tmp_path, provider, server, content):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("five"))
    pause_midway(manager, job)
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())
    stored[0].update(status="downloading", phase="downloading")
    (tmp_path / "data" / "jobs.json").write_text(json.dumps(stored))

    server.delay = 0
    again = build_manager(tmp_path, provider).get(job.id)
    assert again.notice_key == "messages.resumed_restart"
    wait_for(lambda: again.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "five.bin").read_bytes() == content
    assert again.notice_key is None


def test_restart_resumes_jobs_the_shutdown_paused(tmp_path, provider, server, content):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("shutdown"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.shutdown()
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())[0]
    assert stored["status"] == "paused" and stored["resume_on_start"] is True

    server.delay = 0
    again = build_manager(tmp_path, provider).get(job.id)
    assert again.status in (Status.QUEUED, Status.DOWNLOADING) and not again.resume_on_start
    assert again.notice_key == "messages.resumed_restart"
    wait_for(lambda: again.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "shutdown.bin").read_bytes() == content
    assert again.notice_key is None


def test_shutdown_does_not_resume_a_job_being_canceled(tmp_path, provider, server):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("leaving"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    with manager._lock:
        manager._runs[job.id].stop("cancel")
    manager.shutdown()
    assert job.status == Status.CANCELED and not job.resume_on_start

    again = build_manager(tmp_path, provider).get(job.id)
    assert again.status == Status.CANCELED and again.notice_key is None


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
    assert manager.open_file(job.id) is None
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


def test_out_of_range_environment_defaults_fall_back(tmp_path):
    from downloader.config import Settings
    from downloader.settings_store import SettingsStore

    settings = Settings(data_dir=tmp_path, download_dir=tmp_path, split_size=2**20, max_active_jobs=0,
                        connections=5, use_proxies=False)
    prefs = SettingsStore(settings).get()
    assert (prefs.split_size, prefs.max_active_jobs) == (20 * 2**20, 2)
    assert (prefs.connections, prefs.use_proxies) == (5, False)


def test_restart_during_verify_keeps_the_published_file(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("verify"))
    wait_for(lambda: job.status == Status.COMPLETED)
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())
    stored[0].update(status="downloading", phase="verifying", completed_at=None)
    (tmp_path / "data" / "jobs.json").write_text(json.dumps(stored))
    (tmp_path / "downloads" / "verify.bin.part").write_bytes(b"leftover")

    again = build_manager(tmp_path, provider).get(job.id)
    assert again.status == Status.COMPLETED and again.completed_at
    assert not (tmp_path / "downloads" / "verify.bin.part").exists()


def test_no_task_event_after_removal(tmp_path, provider):
    seen = []
    bus = EventBus()
    bus.publish_task = lambda task, force=False: seen.append(task["id"])
    manager = build_manager(tmp_path, provider, bus=bus)
    job = manager.create(URL.format("late"))
    wait_for(lambda: job.status == Status.COMPLETED)
    manager.clear_completed()
    seen.clear()
    manager._publish(job, force=True)
    assert seen == []


def test_intents_only_escalate():
    from downloader.jobs import _Run

    run = _Run()
    run.stop("delete")
    run.stop("pause")
    run.stop("cancel")
    assert run.intent == "delete" and run.cancelled.is_set()
    other = _Run()
    other.stop("pause")
    other.stop("cancel")
    assert other.intent == "cancel"


def test_pause_during_pending_delete_keeps_the_delete(tmp_path, provider):
    gate = threading.Event()
    entered = threading.Event()
    original = provider.generate_links

    def blocking(ref, count, ctx):
        entered.set()
        gate.wait(5)
        return original(ref, count, ctx)

    provider.generate_links = blocking
    removed = []
    bus = EventBus()
    bus.publish_removed = removed.append
    manager = build_manager(tmp_path, provider, bus=bus)
    job = manager.create(URL.format("pending"))
    assert entered.wait(5)
    deleting = threading.Thread(target=manager.delete, args=(job.id,))
    deleting.start()
    wait_for(lambda: manager._runs.get(job.id) is not None and manager._runs[job.id].intent == "delete")
    manager.pause(job.id)
    gate.set()
    deleting.join(10)
    assert job.id not in manager.jobs and removed == [job.id]


def test_restart_does_not_adopt_a_foreign_file(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("foreign"))
    wait_for(lambda: job.status == Status.COMPLETED)
    (tmp_path / "downloads" / "foreign.bin").write_bytes(b"not ours")
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())
    stored[0].update(status="downloading", phase="assembling", completed_at=None)
    (tmp_path / "data" / "jobs.json").write_text(json.dumps(stored))
    again = build_manager(tmp_path, provider).get(job.id)
    assert again.notice_key == "messages.resumed_restart"
    wait_for(lambda: again.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "foreign.bin").read_bytes() == b"not ours"
    assert again.output_path != str(tmp_path / "downloads" / "foreign.bin")


def test_captcha_attempts_env_must_be_positive(monkeypatch):
    from downloader.config import Settings

    monkeypatch.setenv("CAPTCHA_MAX_ATTEMPTS", "0")
    assert Settings.from_env().captcha_max_attempts == 50
    monkeypatch.setenv("CAPTCHA_MAX_ATTEMPTS", "7")
    assert Settings.from_env().captcha_max_attempts == 7


def pause_midway(manager, job):
    """Wait until `job` has some bytes, pause it, and wait for the pause."""
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    manager.pause(job.id)
    wait_for(lambda: job.status == Status.PAUSED)


def test_upstream_without_ranges_fails_and_cannot_pause(tmp_path, provider, server):
    server.ignore_range = True
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("norange"))
    wait_for(lambda: job.status == Status.FAILED)
    assert job.error["code"] == "range_unsupported" and job.resumable is False
    assert manager.public(job)["resumable"] is False
    assert not list((tmp_path / "downloads").iterdir())


def test_resume_regenerates_links_and_sends_if_range(tmp_path, provider, server, content):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("refresh"))
    pause_midway(manager, job)
    assert job.etag == '"v1"'
    calls = provider.link_calls
    server.delay = 0
    server.if_ranges.clear()
    manager.resume(job.id)
    wait_for(lambda: job.status == Status.COMPLETED)
    assert provider.link_calls == calls + 1
    assert server.if_ranges and set(server.if_ranges) == {'"v1"'}
    assert job.notice_key is None
    assert (tmp_path / "downloads" / "refresh.bin").read_bytes() == content


def test_changed_remote_file_is_downloaded_again_once(tmp_path, provider, server, content):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("changed"))
    pause_midway(manager, job)

    new_content = bytes(reversed(content))
    server.content = new_content
    server.etag = '"v2"'
    server.delay = 0
    manager.resume(job.id)
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    assert job.status == Status.COMPLETED, job.error
    assert job.notice_key == "messages.remote_changed"
    assert manager.public(job)["notice_key"] == "messages.remote_changed"
    assert (tmp_path / "downloads" / "changed.bin").read_bytes() == new_content


def test_remote_file_changing_again_fails(tmp_path, provider):
    from downloader.jobs import _Run
    from downloader.messages import CodedError

    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("flappy"))
    wait_for(lambda: job.status == Status.COMPLETED)
    run = _Run()
    manager._start_over(job, run)
    assert run.restarted and job.notice_key == "messages.remote_changed" and job.bytes_done == 0
    with pytest.raises(CodedError) as info:
        manager._start_over(job, run)
    assert info.value.code == "remote_changed"


def test_restart_while_paused_keeps_the_pause(tmp_path, provider, server, content):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("restart"))
    pause_midway(manager, job)
    saved = job.bytes_done
    manager.shutdown()

    again = build_manager(tmp_path, provider).get(job.id)
    assert (again.status, again.etag, again.bytes_done) == (Status.PAUSED, '"v1"', saved)
    assert again.notice_key is None and not again.resume_on_start


def test_restart_fails_active_jobs_that_cannot_resume(tmp_path, provider):
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("fixed"))
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())
    stored[0].update(status="downloading", phase="downloading", resumable=False)
    (tmp_path / "data" / "jobs.json").write_text(json.dumps(stored))
    again = build_manager(tmp_path, provider).get(job.id)
    assert again.status == Status.FAILED and again.error["code"] == "interrupted"


def test_pause_is_refused_for_a_job_that_cannot_resume(tmp_path, provider, server):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("nopause"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    job.resumable = False
    with pytest.raises(InvalidState) as info:
        manager.pause(job.id)
    assert info.value.key == "errors.invalid_state_not_resumable"
    job.resumable = True
    manager.cancel(job.id)


def test_retry_judges_range_support_again(tmp_path, provider, server, content):
    server.ignore_range = True
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("again"))
    wait_for(lambda: job.status == Status.FAILED)
    assert job.resumable is False
    server.ignore_range = False
    manager.retry(job.id)
    assert job.resumable is True
    wait_for(lambda: job.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "again.bin").read_bytes() == content


def test_size_change_found_at_resume_starts_over(tmp_path, provider, server, content):
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("grown"))
    pause_midway(manager, job)
    shorter = content[:-1000]
    server.content = shorter
    provider.size = len(shorter)
    server.delay = 0
    manager.resume(job.id)
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    assert job.status == Status.COMPLETED, job.error
    assert job.size == len(shorter) and job.notice_key == "messages.remote_changed"
    assert (tmp_path / "downloads" / "grown.bin").read_bytes() == shorter


def test_cancel_forgets_the_file_version(tmp_path, provider, server):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("forget"))
    pause_midway(manager, job)
    assert job.etag == '"v1"'
    job.notice_key = "messages.remote_changed"
    manager.cancel(job.id)
    assert (job.etag, job.last_modified, job.notice_key) == (None, None, None)


def test_a_grown_file_found_mid_run_is_downloaded_whole(tmp_path, provider, server, content):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("grow"))
    pause_midway(manager, job)

    grown = content + b"z" * 5000
    original_info = provider.get_info
    reads = []

    def stale_then_fresh(ref):
        reads.append(ref)
        info = original_info(ref)
        info.size = len(content) if len(reads) == 1 else len(grown)
        return info

    provider.get_info = stale_then_fresh
    server.content = grown
    server.etag = '"v2"'
    server.delay = 0
    manager.resume(job.id)
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    assert job.status == Status.COMPLETED, job.error
    assert job.size == len(grown) and len(reads) == 2
    assert (tmp_path / "downloads" / "grow.bin").read_bytes() == grown


def test_the_file_version_is_saved_as_soon_as_it_is_seen(tmp_path, provider, server):
    server.etag = '"v1"'
    server.delay = 0.05
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("saved"))
    wait_for(lambda: job.phase == Phase.DOWNLOADING and job.bytes_done > 0)
    stored = json.loads((tmp_path / "data" / "jobs.json").read_text())
    assert next(j for j in stored if j["id"] == job.id)["etag"] == '"v1"'
    manager.cancel(job.id)


def test_a_second_change_in_one_run_fails_the_job(tmp_path, provider, server, content):
    gate = threading.Event()
    entered = threading.Event()
    original_links = provider.generate_links

    def held(ref, count, ctx):
        entered.set()
        gate.wait(5)
        return original_links(ref, count, ctx)

    provider.generate_links = held
    manager = build_manager(tmp_path, provider, connections=2)
    job = manager.create(URL.format("twice"))
    assert entered.wait(5)
    job.split_size = 100_000

    versions = iter(['"v1"'] * 2 + ['"v2"'] * 3 + ['"v3"'] * 1000)
    original_get = server.httpd.RequestHandlerClass.do_GET

    def changing(handler):
        server.etag = next(versions)
        original_get(handler)

    server.httpd.RequestHandlerClass.do_GET = changing
    server.delay = 0.01
    gate.set()
    wait_for(lambda: job.status in (Status.COMPLETED, Status.FAILED))
    server.httpd.RequestHandlerClass.do_GET = original_get
    assert job.status == Status.FAILED and job.error["code"] == "remote_changed"


def test_the_provider_decoder_turns_parts_into_the_saved_file(tmp_path, provider, content):
    provider.xor = 0x5A
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("decoded"))
    wait_for(lambda: job.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "decoded.bin").read_bytes() == bytes(b ^ 0x5A for b in content)


def test_a_failed_integrity_check_drops_the_download(tmp_path, provider, content):
    provider.xor = 0x5A
    provider.corrupt = True
    manager = build_manager(tmp_path, provider)
    job = manager.create(URL.format("broken"))
    wait_for(lambda: job.status == Status.FAILED)
    assert job.error["code"] == "integrity_failed"
    assert job.bytes_done == 0 and job.output_path is None
    assert not (tmp_path / "data" / "jobs" / job.id).exists()
    assert list((tmp_path / "downloads").iterdir()) == []
    provider.corrupt = False
    manager.retry(job.id)
    wait_for(lambda: job.status == Status.COMPLETED)
    assert (tmp_path / "downloads" / "broken.bin").read_bytes() == bytes(b ^ 0x5A for b in content)
