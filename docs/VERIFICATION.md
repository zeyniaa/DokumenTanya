# Verification record

Checked on 12 October 2026 on Windows, Python 3.12.14. This distinguishes implementation coverage from live integration verification.

| Check | Outcome | Scope |
|---|---|---|
| Automated tests | 19 passed | Workflow, session isolation, citations, corrections/reprocessing, Decimal calculations, source validation, summary provenance, metrics, provider contracts |
| Ruff | Passed | backend, tests, scripts, evals |
| JavaScript syntax | Passed | All frontend ES modules |
| Browser workflow | Passed | Real sample upload, question, calculation, citation click and page highlight |
| Responsive layout | Checked | Desktop and 390×844 mobile; no horizontal document overflow at that mobile size |
| Browser console | No errors/warnings observed | Checked after upload/chat/citation and viewport changes |
| RapidOCR real-model check | Passed | Image-only synthetic PDF, 22 text items; see ocr-smoke.json |
| Docling real-model check | Passed | Synthetic PDF, text and one structured table; see docling-smoke.json |
| E5 + Qdrant real-model check | Passed | Real E5 weights, 384 dimensions, owner/version filtering in Qdrant in-memory; see e5-smoke.json |
| Pilot API benchmark | 7/8 checks passed | Eight synthetic questions, extractive baseline; see pilot-results.json |
| Gemini | SDK schema checked; no live request | API key was not available |
| Ollama | Request/response contract checked | No running Ollama/model server available |
| Optional Qwen reranker | Implemented; not live-tested | Requires model download/inference |
| Docker + Redis/RQ/Qdrant server | Configuration supplied; not executed here | Docker was not installed on this host |

Model smoke-check timings include first-run imports/downloads and concurrent checks. They are not steady-state latency measurements. A Docling grade of EXCELLENT is a conversion diagnostic, not proof of table correctness or answer accuracy.

The pilot failure is the missing-phone question: the extractive baseline retrieves the explicit absence statement but marks the response answered rather than insufficient_evidence. This is recorded intentionally. Seven substring checks passing do not imply 87.5% semantic accuracy on real documents.

The paid/generative chatbot path still needs a configured Gemini key or running Ollama. The default clone starts in a clearly labeled extractive mode that can be tried without either. Use docs/EVALUATION.md to repeat optional checks and expand the dataset.
