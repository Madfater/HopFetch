"""HTTP API through FastAPI's test client, and SSE through a real local uvicorn."""

from __future__ import annotations

import socket
import threading
import time
from urllib.parse import quote

import pytest
import requests
import uvicorn
from conftest import build_manager, wait_for
from fastapi.testclient import TestClient

from downloader.app import create_app
from downloader.providers.base import ProviderError

URL = "https://fake.test/f/{}"


def make_client(tmp_path, provider, web_dist=None, **overrides):
    """A TestClient over a manager for `provider`."""
    manager = build_manager(tmp_path, provider, **overrides)
    manager.settings.web_dist = web_dist or tmp_path / "no-dist"
    return TestClient(create_app(manager.settings, manager, preload_proxies=False))


@pytest.fixture
def client(tmp_path, provider):
    with make_client(tmp_path, provider) as test_client:
        yield test_client


def finish(client, task_id):
    """Wait for a task to complete and return it."""
    wait_for(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "completed")
    return client.get(f"/api/tasks/{task_id}").json()


def test_providers(client):
    assert client.get("/api/providers").json() == [
        {"id": "fake", "name": "Fake host", "icon": "fake", "patterns": [r"^https?://fake\.test/f/([a-z0-9]+)$"]},
    ]


def test_resolve(client, content):
    ok = client.post("/api/resolve", json={"url": "  HTTPS://FAKE.TEST/f/one "})
    assert ok.status_code == 200
    body = ok.json()
    assert body["provider"] == "fake" and body["file_id"] == "one" and body["file_name"] == "one.bin"
    assert body["size"] == len(content) and body["resumable"] is True and body["duplicate"] is None
    assert body["free_bytes"] > 0 and body["required_bytes"] >= len(content)


@pytest.mark.parametrize("url,status,code", [
    ("not a url", 400, "invalid_url"),
    ("http://192.168.1.1/admin", 400, "unsupported"),
    ("https://example.com/a.zip", 400, "unsupported"),
])
def test_resolve_rejects_unsupported(client, url, status, code):
    resp = client.post("/api/resolve", json={"url": url})
    assert (resp.status_code, resp.json()["code"]) == (status, code)
    assert resp.json()["message"]


@pytest.mark.parametrize("code,status", [
    ("not_found", 404), ("private", 403), ("premium_only", 403),
    ("quota_exceeded", 429), ("upstream_error", 502),
])
def test_resolve_maps_upstream_errors(client, provider, code, status):
    provider.info_error = ProviderError(code, "說明")
    resp = client.post("/api/resolve", json={"url": URL.format("x")})
    assert resp.status_code == status
    assert resp.json() == {"code": code, "message": "說明"}


def test_unexpected_errors_answer_json(tmp_path, provider):
    provider.info_error = RuntimeError("secret internals")
    manager = build_manager(tmp_path, provider)
    manager.settings.web_dist = tmp_path / "no-dist"
    app = create_app(manager.settings, manager, preload_proxies=False)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        resp = test_client.post("/api/resolve", json={"url": URL.format("x")})
    assert resp.status_code == 500
    assert resp.json()["code"] == "internal_error" and "secret" not in resp.text


def test_unsupported_urls_never_create_tasks(client, server):
    resp = client.post("/api/tasks", json={"url": server.url})
    assert (resp.status_code, resp.json()["code"]) == (400, "unsupported")
    assert server.ranges == []
    assert client.get("/api/tasks").json() == []


def test_invalid_body(client):
    resp = client.post("/api/tasks", json={"nope": 1})
    assert (resp.status_code, resp.json()["code"]) == (422, "invalid_request")


def test_task_lifecycle(client, content, tmp_path):
    created = client.post("/api/tasks", json={"url": URL.format("one")})
    assert created.status_code == 201
    task = created.json()
    assert set(task) >= {"id", "provider", "file_id", "file_name", "size", "bytes_done", "speed", "eta",
                         "status", "resumable", "file_exists", "error", "created_at", "completed_at"}

    duplicate = client.post("/api/tasks", json={"url": URL.format("one")})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_active" and duplicate.json()["task_id"] == task["id"]
    resolved = client.post("/api/resolve", json={"url": URL.format("one")}).json()
    assert resolved["duplicate"]["task_id"] == task["id"]

    done = finish(client, task["id"])
    assert done["file_exists"] is True and done["completed_at"]
    assert client.post("/api/tasks", json={"url": URL.format("one")}).json()["code"] == "duplicate_completed"
    assert client.post(f"/api/tasks/{task['id']}/pause").json()["code"] == "invalid_state"
    assert client.post(f"/api/tasks/{task['id']}/cancel").status_code == 409

    again = client.post("/api/tasks", json={"url": URL.format("one"), "force": True})
    assert again.status_code == 201
    finish(client, again.json()["id"])
    assert (tmp_path / "downloads" / "one (1).bin").read_bytes() == content

    assert client.post("/api/tasks/clear-completed").json() == {"removed": 2}
    assert client.get("/api/tasks").json() == []
    assert (tmp_path / "downloads" / "one.bin").exists()


def test_pause_resume_cancel_retry_delete(client, server, tmp_path):
    server.delay = 0.05
    task_id = client.post("/api/tasks", json={"url": URL.format("two")}).json()["id"]
    wait_for(lambda: client.get(f"/api/tasks/{task_id}").json()["bytes_done"] > 0)
    assert client.post(f"/api/tasks/{task_id}/pause").status_code == 200
    wait_for(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "paused")
    assert client.post(f"/api/tasks/{task_id}/resume").json()["status"] in ("queued", "downloading")
    canceled = client.post(f"/api/tasks/{task_id}/cancel").json()
    assert canceled["status"] == "canceled" and canceled["bytes_done"] == 0
    assert client.post(f"/api/tasks/{task_id}/retry").json()["status"] in ("queued", "downloading")
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert not (tmp_path / "data" / "jobs" / task_id).exists()


def test_actions_during_assembly_answer_invalid_state(tmp_path, provider, monkeypatch):
    import downloader.jobs as jobs_module

    original = jobs_module.assemble
    monkeypatch.setattr(jobs_module, "assemble", lambda *args: (time.sleep(1), original(*args)))
    with make_client(tmp_path, provider) as test_client:
        task_id = test_client.post("/api/tasks", json={"url": URL.format("asm")}).json()["id"]
        wait_for(lambda: test_client.get(f"/api/tasks/{task_id}").json()["phase"] == "assembling")
        for method, path in [("POST", "/pause"), ("POST", "/cancel"), ("DELETE", "")]:
            resp = test_client.request(method, f"/api/tasks/{task_id}{path}")
            assert (resp.status_code, resp.json()["code"]) == (409, "invalid_state"), (method, path)
        finish(test_client, task_id)


def test_insufficient_space(client, provider):
    provider.size = 10**18
    resp = client.post("/api/tasks", json={"url": URL.format("huge")})
    assert (resp.status_code, resp.json()["code"]) == (507, "insufficient_space")


def test_delete_file_flag(client, tmp_path):
    keep = client.post("/api/tasks", json={"url": URL.format("keep")}).json()["id"]
    gone = client.post("/api/tasks", json={"url": URL.format("gone")}).json()["id"]
    finish(client, keep)
    finish(client, gone)
    assert client.delete(f"/api/tasks/{keep}?delete_file=false").status_code == 204
    assert client.delete(f"/api/tasks/{gone}?delete_file=true").status_code == 204
    assert (tmp_path / "downloads" / "keep.bin").exists()
    assert not (tmp_path / "downloads" / "gone.bin").exists()


def test_file_supports_range_and_chinese_names(client, provider, content):
    provider.names["zh"] = "測試 影片.bin"
    task_id = client.post("/api/tasks", json={"url": URL.format("zh")}).json()["id"]
    finish(client, task_id)

    whole = client.get(f"/api/tasks/{task_id}/file")
    assert whole.status_code == 200 and whole.content == content
    disposition = whole.headers["content-disposition"]
    assert f"filename*=utf-8''{quote('測試 影片.bin')}" in disposition
    assert whole.headers["accept-ranges"] == "bytes"

    part = client.get(f"/api/tasks/{task_id}/file", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(content)}"


def test_missing_file_answers_404_and_file_exists_false(client, tmp_path):
    task_id = client.post("/api/tasks", json={"url": URL.format("lost")}).json()["id"]
    finish(client, task_id)
    (tmp_path / "downloads" / "lost.bin").unlink()
    resp = client.get(f"/api/tasks/{task_id}/file")
    assert (resp.status_code, resp.json()["code"]) == (404, "file_missing")
    assert client.get(f"/api/tasks/{task_id}").json()["file_exists"] is False


def test_file_refuses_symlink_out_of_root(client, tmp_path):
    task_id = client.post("/api/tasks", json={"url": URL.format("sym")}).json()["id"]
    finish(client, task_id)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    target = tmp_path / "downloads" / "sym.bin"
    target.unlink()
    target.symlink_to(secret)
    resp = client.get(f"/api/tasks/{task_id}/file")
    assert resp.status_code == 404 and b"secret" not in resp.content


def test_dangling_symlink_is_never_written_through(client, tmp_path, content):
    outside = tmp_path / "outside.bin"
    (tmp_path / "downloads" / "dang.bin").symlink_to(outside)
    (tmp_path / "downloads" / "dang.bin.part").symlink_to(tmp_path / "outside.part")
    task_id = client.post("/api/tasks", json={"url": URL.format("dang")}).json()["id"]
    finish(client, task_id)
    assert not outside.exists() and not (tmp_path / "outside.part").exists()
    assert (tmp_path / "downloads" / "dang (1).bin").read_bytes() == content


@pytest.mark.parametrize("task_id", ["..", "..%2F..%2Fetc", "ABCDEF012345", "abc", "0" * 13])
def test_task_ids_are_validated(client, task_id):
    for method, path in [("GET", ""), ("GET", "/file"), ("POST", "/cancel"), ("DELETE", "")]:
        resp = client.request(method, f"/api/tasks/{task_id}{path}")
        assert resp.status_code in (404, 405), (method, path, resp.status_code)
        assert resp.json()["code"] in ("task_not_found", "not_found", "method_not_allowed")


def test_storage(client):
    body = client.get("/api/storage").json()
    assert 0 < body["free_bytes"] <= body["total_bytes"]


def test_settings(client, tmp_path):
    body = client.get("/api/settings").json()
    assert body["download_root"] == str(tmp_path / "downloads")
    updated = client.put("/api/settings", json={"connections": 4, "download_root": "/etc"}).json()
    assert updated["connections"] == 4 and updated["download_root"] == str(tmp_path / "downloads")
    bad = client.put("/api/settings", json={"split_size": 1024})
    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_settings")
    assert client.get("/api/settings").json()["split_size"] == body["split_size"]


def test_unknown_api_path_is_json_404(client):
    for method in ("GET", "POST"):
        resp = client.request(method, "/api/nope")
        assert (resp.status_code, resp.json()["code"]) == (404, "not_found")


def test_spa_fallback(tmp_path, provider):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("js")
    (tmp_path / "secret.txt").write_text("secret")
    with make_client(tmp_path, provider, web_dist=dist) as test_client:
        assert test_client.get("/").text == "<html>app</html>"
        assert test_client.get("/tasks").text == "<html>app</html>"
        assert test_client.get("/settings?x=1").text == "<html>app</html>"
        assert test_client.get("/assets/app.js").text == "js"
        assert "secret" not in test_client.get("/%2e%2e/secret.txt").text
        assert test_client.get("/api/nope").json()["code"] == "not_found"
        assert test_client.get("/api/providers").status_code == 200


@pytest.fixture
def live(tmp_path, provider):
    """The app served by uvicorn on a free local port, with a short heartbeat."""
    manager = build_manager(tmp_path, provider)
    manager.settings.web_dist = tmp_path / "no-dist"
    app = create_app(manager.settings, manager, preload_proxies=False, storage_interval=0.1)
    app.state.heartbeat = 0.3
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    wait_for(lambda: server.started)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(10)


def read_events(lines, until, timeout=15.0):
    """Collect SSE lines grouped into (event, data) or comments until `until(items)` is true."""
    items, event = [], None
    deadline = time.monotonic() + timeout
    for raw in lines:
        assert time.monotonic() < deadline
        if raw.startswith(":"):
            items.append(("comment", raw))
        elif raw.startswith("event: "):
            event = raw[7:]
        elif raw.startswith("data: "):
            items.append((event, raw[6:]))
        if until(items):
            return items
    raise AssertionError("stream ended early")


def test_sse_stream(live):
    with requests.get(f"{live}/api/events", stream=True, timeout=10) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"
        assert resp.headers["cache-control"] == "no-cache"
        lines = resp.iter_lines(decode_unicode=True)
        items = read_events(lines, lambda got: any(k == "comment" for k, _ in got)
                            and any(k == "storage" for k, _ in got))
        assert ("comment", ": ping") in items

        task_id = requests.post(f"{live}/api/tasks", json={"url": URL.format("sse")}, timeout=10).json()["id"]
        items = read_events(lines, lambda got: any(k == "task" and '"completed"' in v for k, v in got))
        statuses = [v for k, v in items if k == "task"]
        assert all(task_id in v for v in statuses)
        assert '"queued"' in statuses[0]

        requests.delete(f"{live}/api/tasks/{task_id}", timeout=10)
        items = read_events(lines, lambda got: any(k == "task_removed" for k, _ in got))
        assert ("task_removed", f'{{"id": "{task_id}"}}') in items
