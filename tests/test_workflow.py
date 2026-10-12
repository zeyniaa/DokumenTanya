import json
from uuid import uuid4

from fastapi.testclient import TestClient

from conftest import ROOT, wait_job


def conversation(client, document_id):
    result = client.post("/api/conversations", json={"document_ids": [document_id]})
    assert result.status_code == 201
    return result.json()["id"]


def ask(client, conv, question, request_id=None):
    return client.post(f"/api/conversations/{conv}/messages", json={"question": question, "request_id": request_id or str(uuid4())})


def test_html_and_session(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="id"' in response.text
    assert "Streamlit" not in response.text
    assert client.get("/assets/js/app.js").status_code == 200
    assert client.get("/api/config").json()["provider"] == "extractive"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_upload_and_citation(client, uploaded):
    doc = uploaded["document_id"]
    extraction = client.get(f"/api/documents/{doc}/extraction").json()
    assert len(extraction["pages"]) == 2
    assert extraction["tables"]
    for item in extraction["items"]:
        assert all(0 <= value <= 1 for value in item["bbox"])
    conv = conversation(client, doc)
    response = ask(client, conv, "Apa persyaratan pengajuan cuti?")
    assert response.status_code == 200
    data = response.json()
    assert data["answer_status"] == "answered"
    assert "CA-01" in data["answer"]
    assert data["citations"] and data["provider"] == "extractive"
    source = data["citations"][0]
    assert source["version_id"] == extraction["version_id"]
    image = client.get(f"/api/documents/{doc}/pages/{source['page_no']}?version_id={source['version_id']}")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{doc}/pages/99").status_code == 404


def test_duplicate_and_bad_input(client, uploaded):
    duplicate = client.post("/api/documents", files={"file": ("another.pdf", (ROOT / "examples/sop-demo.pdf").read_bytes())})
    assert duplicate.json()["duplicate"]
    assert duplicate.json()["document_id"] == uploaded["document_id"]
    assert len(client.get("/api/documents").json()) == 1
    assert client.post("/api/documents", files={"file": ("not.pdf", b"bad")}).status_code == 422
    assert client.post("/api/documents", files={"file": ("bad.pdf", b"%PDF-corrupt")}).status_code == 422


def test_session_isolation(client, uploaded):
    from backend.app.main import app
    # Same endpoints/settings, different cookie jar.
    with TestClient(app) as stranger:
        doc = uploaded["document_id"]
        assert stranger.get("/api/documents").json() == []
        assert stranger.get(f"/api/documents/{doc}/extraction").status_code == 404
        assert stranger.get(f"/api/jobs/{uploaded['job_id']}").status_code == 404
        assert stranger.post("/api/conversations", json={"document_ids": [doc]}).status_code == 404
        assert stranger.delete(f"/api/documents/{doc}").status_code == 404


def test_versioned_corrections(client, uploaded):
    doc = uploaded["document_id"]
    old = client.get(f"/api/documents/{doc}/extraction").json()
    item = next(i for i in old["items"] if "verifikasi" in i["text"].lower())
    result = client.patch(f"/api/documents/{doc}/items/{item['id']}", json={"expected_version_id": old["version_id"], "text": "Proses verifikasi cuti membutuhkan 9 hari kerja."})
    assert result.status_code == 202
    assert wait_job(client, result.json()["job_id"])["status"] == "ready"
    current = client.get(f"/api/documents/{doc}/extraction").json()
    assert current["version_id"] != old["version_id"] and current["version_number"] == 2
    previous = client.get(f"/api/documents/{doc}/extraction?version_id={old['version_id']}").json()
    assert next(i for i in previous["items"] if i["id"] == item["id"])["text"] == item["text"]
    assert client.patch(f"/api/documents/{doc}/items/{item['id']}", json={"expected_version_id": old["version_id"], "text": "conflict"}).status_code == 409
    answer = ask(client, conversation(client, doc), "Berapa lama verifikasi cuti?").json()
    assert "9 hari" in answer["answer"]
    assert all(c["version_id"] == current["version_id"] for c in answer["citations"])


def test_calculation_and_natural_question(client, uploaded):
    doc = uploaded["document_id"]
    content = client.get(f"/api/documents/{doc}/extraction").json()
    table = content["tables"][0]
    result = client.post(f"/api/documents/{doc}/calculate", json={"version_id": content["version_id"], "table_id": table["id"], "column": 1, "operation": "sum"})
    assert result.status_code == 200, result.text
    assert result.json()["result"] == "80000"
    answer = ask(client, conversation(client, doc), "Berapa total biaya administrasi?").json()
    assert "80.000" in answer["answer"] and answer["citations"]
    assert answer["provider"] == "calculation"
    invalid = client.post(f"/api/documents/{doc}/calculate", json={"version_id": content["version_id"], "table_id": table["id"], "column": 0, "operation": "sum"})
    assert invalid.status_code == 422


def test_abstention_and_idempotency(client, uploaded):
    conv = conversation(client, uploaded["document_id"])
    request_id = str(uuid4())
    response = ask(client, conv, "Siapakah astronaut pemenang galaksi?", request_id)
    data = response.json()
    assert data["answer_status"] == "insufficient_evidence" and data["citations"] == []
    assert ask(client, conv, "Siapakah astronaut pemenang galaksi?", request_id).json()["message_id"] == data["message_id"]
    assert ask(client, conv, "Pertanyaan berbeda", request_id).status_code == 409
    assert len(client.get(f"/api/conversations/{conv}/messages").json()) == 1


def test_export_and_delete(client, uploaded):
    doc = uploaded["document_id"]
    conv = conversation(client, doc)
    assert json.loads(client.get(f"/api/documents/{doc}/export").text)["chunks"]
    assert "Page 1" in client.get(f"/api/documents/{doc}/export?format=markdown").text
    assert client.delete(f"/api/documents/{doc}").status_code == 200
    assert client.get(f"/api/documents/{doc}/extraction").status_code == 404
    assert client.get(f"/api/conversations/{conv}/messages").status_code == 404
    from backend.app.config import settings
    assert not (settings().data_dir / doc).exists()


def test_scan_without_ocr_is_explicit_failure(client):
    result = client.post("/api/documents", files={"file": ("scan.pdf", (ROOT / "examples/sop-scan-demo.pdf").read_bytes())})
    assert result.status_code == 202
    job = wait_job(client, result.json()["job_id"])
    assert job["status"] == "failed" and "OCR" in job["error"]


def test_cross_origin_and_limits(client):
    assert client.post("/api/conversations", headers={"Origin": "https://evil.example"}, json={"document_ids": ["x"]}).status_code == 403
    from backend.app.config import settings
    settings().max_pages = 1
    response = client.post("/api/documents", files={"file": ("two-pages.pdf", (ROOT / "examples/sop-demo.pdf").read_bytes())})
    assert response.status_code == 422


def test_reprocess_makes_a_new_version_without_losing_old_sources(client, uploaded):
    doc = uploaded["document_id"]
    old = client.get(f"/api/documents/{doc}/extraction").json()["version_id"]
    result = client.post(f"/api/documents/{doc}/reprocess")
    assert result.status_code == 202
    assert wait_job(client, result.json()["job_id"])["status"] == "ready"
    latest = client.get(f"/api/documents/{doc}/extraction").json()
    assert latest["version_id"] != old and latest["version_number"] == 2
    assert client.get(f"/api/documents/{doc}/extraction?version_id={old}").status_code == 200
