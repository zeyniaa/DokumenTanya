from decimal import Decimal

import pytest

from backend.app.schemas import Claim, GeneratedAnswer
from backend.app.services import calculations, generation, retrieval


def test_number_formats():
    assert calculations.parse_number("Rp 1.250,50") == (Decimal("1250.50"), "rupiah")
    assert calculations.parse_number("1,25") == (Decimal("1.25"), "number")
    with pytest.raises(ValueError):
        calculations.parse_number("1.25")
    with pytest.raises(ValueError):
        calculations.calculate({"rows": [["Value"], ["Rp 10"], ["20%"]]}, 0, "sum")


def test_retrieval_never_searches_outside_supplied_scope(client):
    chunks = [{"id": "allowed", "text": "cuti formulir CA-01", "owner": "user"}]
    result = retrieval.retrieve("CA-01", chunks)
    assert [c["id"] for c in result] == ["allowed"]
    assert retrieval.retrieve("astronaut", chunks) == []


def test_followup_uses_user_question_not_generated_facts():
    question = generation.rewrite("Berapa lama prosesnya?", [{"question": "Bagaimana pengajuan cuti?"}])
    assert "cuti" in question


def test_unknown_source_cannot_be_formatted():
    answer = GeneratedAnswer(answer_status="answered", claims=[Claim(text="invented", source_ids=["fake"])])
    with pytest.raises(KeyError):
        generation.format_answer(answer, [])


def test_summary_preserves_original_provenance(monkeypatch, client):
    from backend.app.config import settings
    settings().llm_provider = "ollama"
    def fake_generate(question, candidates):
        return GeneratedAnswer(answer_status="answered", claims=[Claim(text="A supported summary", source_ids=[c["id"] for c in candidates])]), {"input_tokens": 10}
    monkeypatch.setattr(generation, "generate", fake_generate)
    chunks = [{"id": f"source-{i}", "text": f"fact {i}"} for i in range(40)]
    answer, usage, _ = generation.summarize(chunks)
    assert set(answer.claims[0].source_ids) == {c["id"] for c in chunks}
    assert usage["input_tokens"] == 60
