# Verification record

Baseline checked on 12 October 2026; local Qwen3 conversation checks completed on 15 October 2026 on Windows, Python 3.12.14. This distinguishes implementation coverage from live integration verification.

| Check | Outcome | Scope |
|---|---|---|
| Automated tests | 25 passed | Workflow, session isolation, citations, corrections/reprocessing, Decimal calculations, source validation, summary provenance, metrics, provider contracts, page progress, additive migration, interactive overview/follow-up |
| Ruff | Passed | backend, tests, scripts, evals |
| JavaScript syntax | Passed | All frontend ES modules |
| Browser workflow | Passed | Real sample upload, question, calculation, citation click and page highlight |
| Responsive layout | Baseline checked | Desktop and 390×844 mobile on 12 October; fresh browser automation on 15 October stopped because the active URL could not be verified |
| Browser console | No errors/warnings observed in the baseline check | Latest fresh browser check was unavailable; no claim of a new console pass |
| RapidOCR real-model check | Passed | Image-only synthetic PDF, 22 text items; see ocr-smoke.json |
| Docling real-model check | Passed | Synthetic PDF, text and one structured table; see docling-smoke.json |
| E5 + Qdrant real-model check | Passed | Real E5 weights, 384 dimensions, owner/version filtering in Qdrant in-memory; see e5-smoke.json |
| Pilot API benchmark | 7/8 checks passed | Eight synthetic questions, extractive baseline; see pilot-results.json |
| Gemini | SDK schema checked; no live request | API key was not available |
| Ollama | Live Qwen3 4B generation checked | Synthetic overview, conclusion and conversational follow-up; see ollama-smoke.json |
| Optional Qwen reranker | Implemented; not live-tested | Requires model download/inference |
| Docker + Redis/RQ/Qdrant server | Configuration supplied; not executed here | Docker was not installed on this host |

Model smoke-check timings include first-run imports/downloads and concurrent checks. They are not steady-state latency measurements. A Docling grade of EXCELLENT is a conversion diagnostic, not proof of table correctness or answer accuracy.

The pilot failure is the missing-phone question: the extractive baseline retrieves the explicit absence statement but marks the response answered rather than insufficient_evidence. This is recorded intentionally. Seven substring checks passing do not imply 87.5% semantic accuracy on real documents.

The development workspace now uses the existing local Ollama Qwen3 4B model. The default clone still starts in extractive mode; configure a running Ollama model or Gemini key for generative answers. The removed header badge is replaced by provider information in help and response metadata. Use docs/EVALUATION.md to repeat optional checks and expand the dataset.

OCR page-progress proof: `images/ocr-progress.jpg` records 3/8 completed pages (38%, rounded) on a synthetic PDF. Docling conversion retained original page numbers and table provenance. Obsolete baseline screenshots were removed from the showcase.

The final live Qwen3 run answered overview, conclusion and simplification with valid source IDs and declined an unrelated question. Observed per-response times were 19.22–34.02 seconds on this synthetic two-page PDF. These are four observations, not p50/p95 measurements. After adding response-length constraints, the eight provider/service tests also passed. The full automated suite has 25 tests.
