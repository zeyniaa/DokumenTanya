from backend.app import store
from backend.app.services import generation, parser
from backend.app.schemas import Claim, GeneratedAnswer
from conftest import ROOT, wait_job


def test_real_page_progress(client, tmp_path):
    events = []
    parsed = parser.parse(ROOT / "examples/sop-demo.pdf", tmp_path / "pages", lambda *args: events.append(args))
    updates = [e for e in events if e[-1] == "extract" and e[2] > 0]
    total = len(parsed["pages"])
    assert [e[2] for e in updates] == list(range(1, total + 1))
    assert updates[-1][1:4] == (100, total, total)
    assert all(e[1] < 100 for e in updates[:-1])


def test_progress_survives_reload_and_ready(client, uploaded):
    job = wait_job(client, uploaded["job_id"])
    persisted = client.get(f'/api/documents/{uploaded["document_id"]}/jobs').json()[0]
    assert persisted["progress_percent"] == job["progress_percent"] == 100
    assert persisted["pages_done"] == persisted["pages_total"] == 2
    assert persisted["phase"] == "ready"


def test_overview_followup_uses_all_pages_and_conversation(client, uploaded, monkeypatch):
    from backend.app.config import settings
    settings().llm_provider = "ollama"
    calls = []
    def fake_generate(question, candidates, history=None):
        calls.append((question, candidates, history))
        return GeneratedAnswer(answer_status="answered", claims=[Claim(text="Dokumen menjelaskan aturan akademik.", source_ids=[candidates[0]["id"]])]), {}
    monkeypatch.setattr(generation, "generate", fake_generate)
    conversation = client.post('/api/conversations', json={"document_ids": [uploaded["document_id"]]}).json()["id"]
    for i, question in enumerate(("Dokumen ini membahas apa?", "Apa kesimpulannya?", "Jelaskan lebih sederhana")):
        response = client.post(f'/api/conversations/{conversation}/messages', json={"question": question, "request_id": f"overview-{i}"})
        assert response.status_code == 200, response.text
    assert {c["page_no"] for c in calls[0][1]} == {1, 2}
    assert calls[1][0] == "Apa kesimpulannya?"
    assert calls[2][2][-1]["question"] == "Apa kesimpulannya?"
    assert calls[2][2][-1]["answer"].startswith("Dokumen menjelaskan")


def test_additive_job_migration_keeps_history(client, uploaded):
    with store.connection() as db:
        for column in ("progress_percent", "pages_done", "pages_total", "phase"):
            db.execute(f"ALTER TABLE jobs DROP COLUMN {column}")
    store.initialize()
    store.initialize()
    assert store.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 1
    assert store.one("SELECT status FROM jobs WHERE id=?", (uploaded["job_id"],))["status"] == "ready"
    assert store.one("SELECT active_version FROM documents WHERE id=?", (uploaded["document_id"],))["active_version"]


def test_removed_ui_elements(client):
    html = client.get('/').text
    assert 'id="mode-badge"' not in html
    assert 'id="demo-button"' not in html
    assert 'Jawaban bisa diperiksa.' not in html
    assert 'id="empty-upload"' in html
