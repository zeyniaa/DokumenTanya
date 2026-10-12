from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    parser_backend: Literal["pdfplumber", "docling"] = "pdfplumber"
    ocr_enabled: bool = False
    ocr_engine: Literal["rapidocr", "tesseract"] = "rapidocr"
    embedding_backend: Literal["none", "e5"] = "none"
    embedding_model: str = "intfloat/multilingual-e5-small"
    llm_provider: Literal["extractive", "gemini", "ollama"] = "extractive"
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    reranker_enabled: bool = False
    reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    job_backend: Literal["local", "rq"] = "local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    max_upload_mb: int = 20
    max_pages: int = 50
    session_secret: str = ""
    secure_cookie: bool = False
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    retrieval_mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    retrieval_top_k: int = 6
    llm_timeout: int = 60

    def prepare(self):
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(self.data_dir / "model-cache"))
        if self.embedding_backend == "e5" and not self.qdrant_url:
            raise ValueError("E5 membutuhkan QDRANT_URL untuk indeks bersama API/worker.")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("LLM_PROVIDER=gemini membutuhkan GEMINI_API_KEY.")
        if not self.session_secret:
            import secrets
            key = self.data_dir / "session.key"
            try:
                with key.open("x", encoding="utf-8") as stream:
                    stream.write(secrets.token_hex(32))
            except FileExistsError:
                pass
            self.session_secret = key.read_text(encoding="utf-8").strip()


@lru_cache
def settings():
    config = Settings()
    config.prepare()
    return config
