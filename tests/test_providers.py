import json

import httpx
import pytest

from backend.app.services import generation


def test_ollama_structured_answer_and_invalid_citation(client, monkeypatch):
    from backend.app.config import settings
    settings().llm_provider = "ollama"
    candidates = [{"id": "real-source", "filename": "demo.pdf", "page_no": 1, "text": "Cuti 5 hari."}]
    calls = []
    def response(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"message": {"content": json.dumps({"answer_status": "answered", "claims": [{"text": "Lima hari.", "source_ids": ["real-source"]}]})}})
    monkeypatch.setattr(httpx, "post", response)
    answer, _ = generation.generate("Berapa hari?", candidates)
    assert answer.claims[0].source_ids == ["real-source"]
    assert "untrusted document data" in calls[0]["json"]["messages"][0]["content"]
    def bad_response(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={"message": {"content": json.dumps({"answer_status": "answered", "claims": [{"text": "Invented", "source_ids": ["invented-source"]}]})}})
    monkeypatch.setattr(httpx, "post", bad_response)
    with pytest.raises(ValueError, match="referensi sumber"):
        generation.generate("Berapa hari?", candidates)


def test_gemini_sdk_schema(client):
    pytest.importorskip("google.genai")
    from google.genai import types
    from backend.app.schemas import GeneratedAnswer
    config = types.GenerateContentConfig(response_mime_type="application/json",
                                         response_json_schema=GeneratedAnswer.model_json_schema())
    assert config.response_json_schema["properties"]["claims"]
