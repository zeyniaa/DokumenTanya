import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import store
from .config import settings
from .services import parser, retrieval

logger = logging.getLogger("dokumentanya")
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-worker")
LOCAL_TASKS = set()
TASK_LOCK = threading.Lock()


def progress(job_id, stage):
    store.execute("UPDATE jobs SET stage=? WHERE id=?", (stage, job_id))


def process_job(job_id):
    started = time.perf_counter()
    job = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job or job["status"] in ("ready", "failed"):
        return
    document = store.one("SELECT * FROM documents WHERE id=?", (job["document_id"],))
    if not document:
        return
    root = settings().data_dir / document["id"]
    version_id = store.uid()
    try:
        store.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
        payload = json.loads(job["payload"] or "{}")
        if payload.get("content"):
            content = payload["content"]
        else:
            content = parser.parse(root / "original.pdf", root / "pages",
                                   lambda stage: progress(job_id, stage))
        progress(job_id, "Membuat indeks pencarian")
        content["pipeline_config"] = {"parser": settings().parser_backend, "ocr_enabled": settings().ocr_enabled,
            "embedding_backend": settings().embedding_backend, "embedding_model": settings().embedding_model,
            "chunk_strategy": "grouped-items-token-bounded-v1"}
        content["chunks"] = retrieval.make_chunks(content, document["id"], version_id,
                                                   document["owner"], document["name"])
        retrieval.index(content["chunks"])
        with store.connection() as db:
            number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM versions WHERE document_id=?",
                                (document["id"],)).fetchone()[0]
            db.execute("INSERT INTO versions VALUES(?,?,?,?,?)",
                       (version_id, document["id"], number, json.dumps(content, ensure_ascii=False), store.now()))
            db.execute("UPDATE documents SET active_version=?,status='ready',pages=? WHERE id=?",
                       (version_id, len(content["pages"]), document["id"]))
            db.execute("UPDATE jobs SET status='ready',stage='Siap',finished=? WHERE id=?", (store.now(), job_id))
        logger.info(json.dumps({"event": "ingestion_ready", "document_id": document["id"],
                               "version_id": version_id, "seconds": round(time.perf_counter() - started, 3)}))
    except Exception as exc:
        message = str(exc)[:300] if isinstance(exc, ValueError) else (
            f"Pemrosesan gagal ({type(exc).__name__}). Periksa dependency/model atau koneksi layanan, lalu coba lagi.")
        with store.connection() as db:
            db.execute("UPDATE jobs SET status='failed',stage='Gagal',error=?,finished=? WHERE id=?",
                       (message, store.now(), job_id))
            db.execute("UPDATE documents SET status=? WHERE id=?",
                       ("ready" if document["active_version"] else "failed", document["id"]))
        logger.error(json.dumps({"event": "ingestion_failed", "job_id": job_id,
                                 "error_type": type(exc).__name__}))


def enqueue(job_id):
    if settings().job_backend == "rq":
        from redis import Redis
        from rq import Queue
        Queue("documents", connection=Redis.from_url(settings().redis_url)).enqueue(
            "backend.app.jobs.process_job", job_id, job_id=job_id, job_timeout=1800,
            result_ttl=3600, failure_ttl=86400)
    else:
        future = POOL.submit(process_job, job_id)
        with TASK_LOCK:
            LOCAL_TASKS.add(future)
        future.add_done_callback(task_finished)


def task_finished(future):
    with TASK_LOCK:
        LOCAL_TASKS.discard(future)


def recover_local_jobs():
    if settings().job_backend != "local":
        return
    for job in store.many("SELECT * FROM jobs WHERE status IN ('queued','processing')"):
        # Local development executor is not durable. Mark interrupted work explicitly.
        store.execute("UPDATE jobs SET status='failed',stage='Terhenti',error=?,finished=? WHERE id=?",
                      ("Server sebelumnya berhenti. Gunakan tombol Coba lagi.", store.now(), job["id"]))
        document = store.one("SELECT active_version FROM documents WHERE id=?", (job["document_id"],))
        store.execute("UPDATE documents SET status=? WHERE id=?",
                      ("ready" if document and document["active_version"] else "failed", job["document_id"]))
