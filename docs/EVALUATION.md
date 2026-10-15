# Evaluation

## Reproduce the pilot

Start the local server, then run:

```bash
uv run --extra dev python evals/run.py
```

The runner uploads the synthetic PDF in its own session, creates independent conversations, records answers/latency/configuration/source pages/token usage, and deletes the uploaded document after the run. Results are written to ignored evals/results/pilot.json. This dataset is a smoke benchmark, not an accuracy claim on real-world documents.

The missing-phone question is intentionally difficult for the lexical baseline: it retrieves the sentence saying the phone is not listed, but its status may still be answered. Report this failure rather than concealing it. The unrelated question should produce no evidence. A semantic model also needs calibrated abstention evaluation; cosine scores are not probabilities.

## Build the real test set

Collect 15–20 permitted PDFs from one organization/domain. Include real scans, two-column pages, clean PDFs, and tables. Keep 100 labeled questions: 35 facts/procedures, 20 table lookups, 10 calculations, 15 follow-ups, and 20 unanswerable/ambiguous cases. Record answer, source item/page, category, document checksum, and usage permission. Add manually transcribed pages and table cell ground truth.

Split by source document, including its scan derivatives. Tune retrieval/prompt/threshold on development documents only. Freeze a test set before comparing configurations.

Compare BM25, dense, hybrid, and hybrid + reranker at constant generation model, prompt, and context budget. Compare generation providers separately. When changing multiple components together, report a system comparison rather than crediting a single component.

## Metrics

- CER/WER: OCR against manual transcription, documenting normalization.
- Table cell/structure accuracy against ground truth.
- Evidence hit rate@5 and multi-source evidence recall.
- Answer correctness, claim support, citation precision, and citation coverage.
- Abstention precision/recall and false refusals.
- Exact calculations after agreed format/unit normalization.
- Ingestion time per page, p50/p95 chat latency, memory, actual token usage/cost.

Ragas can support automated checks; its LLM judges are fallible and chargeable. Audit a sample manually and inspect every important failure. Always report counts as well as percentages on a small dataset.

## Optional real-model smoke checks

```bash
uv sync --extra dev --extra ai --extra ocr
uv run --extra dev --extra ai --extra ocr python scripts/smoke_ai.py --mode ocr
uv run --extra dev --extra ai --extra ocr python scripts/smoke_ai.py --mode docling
uv run --extra dev --extra ai --extra ocr python scripts/smoke_ai.py --mode e5
```

The E5 smoke check uses the real model and Qdrant's in-memory implementation, not a running Qdrant HTTP server. These checks download weights on first use and exercise synthetic documents. They do not test a paid LLM provider or the Docker stack.

## Interactive local-model smoke check

With Ollama running and `LLM_PROVIDER=ollama`, run:

```bash
uv run python -m scripts.smoke_chat --output docs/ollama-smoke.json
```

This reads only the bundled synthetic PDF. It tests overview, conclusion, conversational simplification, and a question outside document scope. Success checks answer status and citation presence; inspect the recorded wording manually for support and useful simplification. Four questions are not an accuracy benchmark. Timings depend on loading, hardware and concurrent work.
