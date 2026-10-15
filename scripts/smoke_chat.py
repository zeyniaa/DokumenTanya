"""Opt-in live local LLM check on a synthetic document, never on user PDFs."""
import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--output", type=Path)
    options = args.parse_args()
    from backend.app.config import settings
    from backend.app.services import generation, parser, retrieval
    config = settings()
    if config.llm_provider != "ollama":
        raise SystemExit("Configure LLM_PROVIDER=ollama and a running model first.")
    config.parser_backend, config.ocr_enabled = "pdfplumber", False
    config.embedding_backend = "none"
    with TemporaryDirectory(dir=config.data_dir) as directory:
        content = parser.parse(ROOT / "examples/sop-demo.pdf", Path(directory), lambda *args: None)
    chunks = retrieval.make_chunks(content, "synthetic-document", "synthetic-version", "smoke", "sop-demo.pdf")
    history, results = [], []
    for question in ("Dokumen ini membahas apa?", "Apa kesimpulannya?", "Jelaskan lebih sederhana", "Siapa presiden Republik Indonesia saat ini?"):
        started = time.perf_counter()
        answer, _ = generation.generate(question, chunks, history)
        text, citations = generation.format_answer(answer, chunks)
        result = {"question": question, "answer": text, "answer_status": answer.answer_status,
                  "source_pages": sorted({c["page_no"] for c in citations}),
                  "seconds": round(time.perf_counter() - started, 2)}
        results.append(result)
        history.append({"question": question, "answer": text})
        print(json.dumps(result, ensure_ascii=False), flush=True)
    passed = all(r["answer_status"] == "answered" and r["source_pages"] for r in results[:3]) and results[-1]["answer_status"] == "insufficient_evidence"
    record = {"provider": "ollama", "model": config.ollama_model, "passed": passed,
              "scope": "Four synthetic smoke questions; not an accuracy benchmark", "results": results}
    if options.output:
        options.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed:
        raise SystemExit("Live smoke expectations failed; inspect answers.")


if __name__ == "__main__":
    main()
