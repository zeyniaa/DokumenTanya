"""Optional integration checks with real OCR, Docling and E5 weights (no paid LLM)."""
import argparse
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--mode", choices=["ocr", "docling", "e5"], required=True)
    args.add_argument("--output", type=Path)
    options = args.parse_args()
    os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
    os.environ.setdefault("HF_HOME", str(ROOT / "data/model-cache"))
    os.environ["OCR_ENABLED"] = "true"
    from backend.app.config import settings
    from backend.app.services import parser, retrieval
    started = time.perf_counter()
    with TemporaryDirectory(dir=settings().data_dir) as directory:
        if options.mode == "ocr":
            content = parser.parse(ROOT / "examples/sop-scan-demo.pdf", Path(directory), lambda _: None)
            text = " ".join(i["text"] for i in content["items"])
            assert "cuti" in text.lower(), text[:300]
            result = {"mode": "rapidocr", "passed": True, "item_count": len(content["items"]), "scan_pages": len(content["pages"])}
        elif options.mode == "docling":
            settings().parser_backend = "docling"
            content = parser.parse(ROOT / "examples/sop-demo.pdf", Path(directory), lambda _: None)
            assert content["items"] and content["tables"]
            assert "CA-01" in " ".join(i["text"] for i in content["items"])
            result = {"mode": "docling", "passed": True, "table_count": len(content["tables"]), "quality": content["quality"]}
        else:
            from qdrant_client import QdrantClient
            settings().embedding_backend = "e5"
            client = QdrantClient(location=":memory:")
            retrieval.vector_client = lambda: client
            chunks = [{"id": "cuti", "text": "Persyaratan cuti adalah formulir dan persetujuan dosen wali.", "owner": "demo", "document_id": "demo", "version_id": "v1"},
                      {"id": "food", "text": "Kantin menjual nasi goreng dan teh.", "owner": "other", "document_id": "other", "version_id": "v2"}]
            retrieval.index(chunks)
            result_set = retrieval.retrieve("Syarat berhenti kuliah sementara?", chunks[:1], mode="dense")
            assert result_set[0]["id"] == "cuti"
            vectors = retrieval.embed(["contoh"])
            assert len(vectors[0]) == 384
            result = {"mode": "e5_qdrant", "passed": True, "dimensions": len(vectors[0]), "scope_filter": True}
            client.close()
    result["seconds"] = round(time.perf_counter() - started, 2)
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
