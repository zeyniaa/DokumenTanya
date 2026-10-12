"""Pilot API benchmark. It records outcomes, never fabricates benchmark claims."""
import argparse
import json
import statistics
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--url", default="http://127.0.0.1:8000")
    arguments.add_argument("--output", type=Path, default=ROOT / "evals/results/pilot.json")
    args = arguments.parse_args()
    with httpx.Client(base_url=args.url, timeout=120) as client:
        config = client.get("/api/config").json()
        result = client.post("/api/documents", files={"file": ("evaluation-demo.pdf", (ROOT / "examples/sop-demo.pdf").read_bytes())})
        result.raise_for_status()
        doc = result.json()
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{doc['job_id']}").json()
            if job["status"] in ("ready", "failed"):
                break
            time.sleep(1)
        if job["status"] != "ready":
            raise RuntimeError(f"Ingestion did not finish: {job.get('error', job['status'])}")
        results = []
        for entry in json.loads((ROOT / "evals/dataset.json").read_text(encoding="utf-8")):
            conv = client.post("/api/conversations", json={"document_ids": [doc["document_id"]]}).json()["id"]
            started = time.perf_counter()
            response = client.post(f"/api/conversations/{conv}/messages", json={"question": entry["question"], "request_id": str(uuid4())})
            response.raise_for_status()
            answer = response.json()
            abstained = answer["answer_status"] == "insufficient_evidence"
            passed = abstained if entry.get("unanswerable") else entry["answer_contains"].casefold() in answer["answer"].casefold()
            results.append({**entry, "passed": passed, "seconds": round(time.perf_counter() - started, 3),
                            "answer": answer["answer"], "status": answer["answer_status"],
                            "source_pages": [c["page_no"] for c in answer["citations"]], "usage": answer["usage"]})
        latencies = sorted(r["seconds"] for r in results)
        report = {"dataset": "synthetic-demo-v1", "config": config, "count": len(results),
                  "checks_passed": sum(r["passed"] for r in results),
                  "median_seconds": statistics.median(latencies), "results": results,
                  "note": "Small synthetic smoke benchmark. Answer substring checks are not semantic correctness; inspect evidence manually."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"count": report["count"], "checks_passed": report["checks_passed"], "output": str(args.output)}))
        client.delete(f"/api/documents/{doc['document_id']}").raise_for_status()


if __name__ == "__main__":
    main()
