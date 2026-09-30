"""HTTP API through FastAPI's test client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from downloader.app import create_app
from downloader.config import Settings
from downloader.jobs import JobManager
from downloader.providers import default_registry
from downloader.proxies import ProxyPool


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", download_dir=tmp_path / "downloads",
                        web_dist=tmp_path / "no-dist", captcha_ocr=False, use_proxies=False)
    manager = JobManager(settings, default_registry(),
                         proxies=ProxyPool(settings.data_dir / "proxies.txt", enabled=False))
    with TestClient(create_app(settings, manager, preload_proxies=False)) as test_client:
        yield test_client


def test_proxies_status(client):
    response = client.get("/api/proxies")
    assert response.status_code == 200
    assert response.json() == {"loaded": False, "public_enabled": False, "user": 0, "public": 0}


def test_providers(client):
    names = [p["name"] for p in client.get("/api/providers").json()]
    assert names == ["k2s", "direct"]


def test_resolve(client):
    ok = client.post("/api/resolve", json={"url": "https://k2s.cc/file/8d028cc29f08b/x.rar"})
    assert ok.status_code == 200
    assert ok.json() == {"supported": True, "provider": "k2s", "label": "Keep2Share",
                         "file_id": "8d028cc29f08b"}
    bad = client.post("/api/resolve", json={"url": "ftp://nope"})
    assert bad.status_code == 200
    assert bad.json()["supported"] is False and "Unsupported URL" in bad.json()["error"]


@pytest.mark.parametrize("body,fragment", [
    ({"url": "not a url"}, "Unsupported URL"),
    ({"url": "https://k2s.cc/folder/abc"}, "not a file link"),
    ({"url": "https://example.com/a.zip", "split_size": "1MB"}, "20 MiB"),
    ({"url": "https://example.com/a.zip", "split_size": "lots"}, "Cannot parse size"),
])
def test_create_job_rejects(client, body, fragment):
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 400
    assert fragment in resp.json()["detail"]


def test_create_job_rejects_bad_connections(client):
    resp = client.post("/api/jobs", json={"url": "https://example.com/a.zip", "connections": 0})
    assert resp.status_code == 422


def test_direct_job_end_to_end(client, server, content, tmp_path):
    import time

    created = client.post("/api/jobs", json={"url": server.url, "connections": 3})
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert "links" not in created.json()

    duplicate = client.post("/api/jobs", json={"url": server.url})
    assert duplicate.status_code == 409

    deadline = time.monotonic() + 15
    while client.get(f"/api/jobs/{job_id}").json()["state"] != "completed":
        assert time.monotonic() < deadline
        time.sleep(0.05)

    file_resp = client.get(f"/api/jobs/{job_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.content == content
    assert client.get("/api/jobs").json()[0]["filename"] == "sample.bin"

    assert client.post(f"/api/jobs/{job_id}/pause").status_code == 409
    assert client.get(f"/api/jobs/{job_id}/captcha").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert (tmp_path / "downloads" / "sample.bin").exists()


def test_unknown_job(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/resume").status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 404
