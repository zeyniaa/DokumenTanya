import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PARSER_BACKEND", "pdfplumber")
    monkeypatch.setenv("OCR_ENABLED", "false")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    monkeypatch.setenv("EMBEDDING_BACKEND", "none")
    monkeypatch.setenv("JOB_BACKEND", "local")
    monkeypatch.setenv("QDRANT_URL", "")
    from backend.app.config import settings
    settings.cache_clear()
    from backend.app.main import create_app
    with TestClient(create_app()) as test_client:
        test_client.get("/api/config")
        yield test_client
    settings.cache_clear()


def wait_job(client, job_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(.03)
    raise AssertionError("Job timeout")


@pytest.fixture
def uploaded(client):
    result = client.post("/api/documents", files={"file": ("panduan.pdf", (ROOT / "examples/sop-demo.pdf").read_bytes(), "application/pdf")})
    assert result.status_code == 202, result.text
    data = result.json()
    assert wait_job(client, data["job_id"])["status"] == "ready"
    return data
