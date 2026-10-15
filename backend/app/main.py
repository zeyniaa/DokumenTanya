import hashlib
import json
import logging
import re
import shutil
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import jobs, store
from .config import ROOT, settings
from .schemas import CalculationInput, ConversationInput, CorrectionInput, MessageInput
from .services import calculations, generation, parser, retrieval

logger = logging.getLogger("dokumentanya")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def owner(request):
    if "owner" not in request.session:
        request.session["owner"] = store.uid()
    return request.session["owner"]


def document_for(request, document_id):
    document = store.one("SELECT * FROM documents WHERE id=? AND owner=?", (document_id, owner(request)))
    if not document:
        raise HTTPException(404, "Dokumen tidak ditemukan.")
    return document


def content_for(document, version_id=None):
    version_id = version_id or document["active_version"]
    row = store.one("SELECT * FROM versions WHERE id=? AND document_id=?", (version_id, document["id"]))
    if not row:
        raise HTTPException(409 if not version_id else 404, "Versi dokumen belum tersedia.")
    return json.loads(row["content"]), row


def conversation_for(request, conversation_id):
    conversation = store.one("SELECT * FROM conversations WHERE id=? AND owner=?",
                             (conversation_id, owner(request)))
    if not conversation:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    return conversation


def new_job(db, document, user, payload=None):
    job_id = store.uid()
    row = db.execute("SELECT status FROM documents WHERE id=?", (document,)).fetchone()
    if not row or row[0] == "deleting":
        raise HTTPException(409, "Dokumen sedang dihapus.")
    if db.execute("SELECT 1 FROM jobs WHERE document_id=? AND status IN ('queued','processing')",
                  (document,)).fetchone():
        raise HTTPException(409, "Dokumen masih diproses. Tunggu pekerjaan selesai.")
    db.execute("INSERT INTO jobs(id,document_id,owner,status,stage,created,payload) VALUES(?,?,?,'queued',?,?,?)",
               (job_id, document, user, "Menunggu", store.now(), json.dumps(payload or {}, ensure_ascii=False)))
    db.execute("UPDATE documents SET status='processing' WHERE id=?", (document,))
    return job_id


def schedule(job_id):
    try:
        jobs.enqueue(job_id)
    except Exception as exc:
        job = store.one("SELECT document_id FROM jobs WHERE id=?", (job_id,))
        doc = store.one("SELECT active_version FROM documents WHERE id=?", (job["document_id"],))
        store.execute("UPDATE jobs SET status='failed',stage='Gagal',error=? WHERE id=?",
                      ("Antrean tidak tersedia. Periksa Redis/worker lalu coba lagi.", job_id))
        store.execute("UPDATE documents SET status=? WHERE id=?",
                      ("ready" if doc["active_version"] else "failed", job["document_id"]))
        raise HTTPException(503, "Antrean pemrosesan tidak tersedia; gunakan Coba lagi.") from exc


def create_app():
    config = settings()
    rate = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        jobs.recover_local_jobs()
        yield

    app = FastAPI(title="DokumenTanya API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=config.session_secret, same_site="strict",
                       https_only=config.secure_cookie, max_age=60 * 60 * 24 * 30, session_cookie="dt_session")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts.split(","))

    @app.middleware("http")
    async def browser_policy(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if ((origin and urlparse(origin).netloc != request.url.netloc)
                    or request.headers.get("sec-fetch-site") == "cross-site"):
                return JSONResponse({"detail": "Permintaan dari origin lain ditolak."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "frontend/index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def public_config(request: Request):
        owner(request)
        return {"parser": config.parser_backend, "ocr_enabled": config.ocr_enabled,
                "embedding": config.embedding_backend, "provider": config.llm_provider,
                "embedding_model": config.embedding_model,
                "llm_model": config.gemini_model if config.llm_provider == "gemini" else (config.ollama_model if config.llm_provider == "ollama" else None),
                "reranker_enabled": config.reranker_enabled,
                "retrieval_effective": config.retrieval_mode if config.embedding_backend == "e5" else "bm25",
                "max_upload_mb": config.max_upload_mb, "max_pages": config.max_pages,
                "job_backend": config.job_backend, "retrieval_mode": config.retrieval_mode}

    @app.get("/api/demo/file")
    def demo():
        return FileResponse(ROOT / "examples/sop-demo.pdf", filename="Panduan Akademik Demo.pdf")

    @app.get("/api/documents")
    def documents(request: Request):
        return store.many("SELECT id,name,status,active_version,pages,created FROM documents WHERE owner=? ORDER BY created DESC",
                          (owner(request),))

    @app.post("/api/documents", status_code=202)
    async def upload(request: Request, file: UploadFile = File(...)):
        user = owner(request)
        if store.one("SELECT COUNT(*) AS n FROM documents WHERE owner=?", (user,))["n"] >= 20:
            raise HTTPException(429, "Maksimal 20 dokumen per sesi. Hapus dokumen sebelum menambah.")
        document_id = store.uid()
        directory = config.data_dir / document_id
        directory.mkdir()
        path = directory / "original.pdf"
        size, digest = 0, hashlib.sha256()
        try:
            with path.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"File melebihi {config.max_upload_mb} MB.")
                    digest.update(chunk)
                    stream.write(chunk)
            with path.open("rb") as stream:
                if not stream.read(8).startswith(b"%PDF-"):
                    raise HTTPException(422, "Format file harus PDF.")
            try:
                pages = await run_in_threadpool(parser.inspect_pdf, path)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            duplicate = store.one("SELECT * FROM documents WHERE owner=? AND hash=?", (user, digest.hexdigest()))
            if duplicate:
                shutil.rmtree(directory)
                latest = store.one("SELECT id FROM jobs WHERE document_id=? ORDER BY created DESC LIMIT 1", (duplicate["id"],))
                return {"document_id": duplicate["id"], "job_id": latest["id"] if latest else None, "duplicate": True}
            name = Path((file.filename or "document.pdf").replace("\\", "/")).name[:200]
            with store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO documents(id,owner,name,hash,status,pages,created) VALUES(?,?,?,?,'queued',?,?)",
                           (document_id, user, name, digest.hexdigest(), pages, store.now()))
                job_id = new_job(db, document_id, user)
        except Exception:
            if not store.one("SELECT id FROM documents WHERE id=?", (document_id,)):
                shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            await file.close()
        schedule(job_id)
        return {"document_id": document_id, "job_id": job_id, "duplicate": False}

    @app.get("/api/jobs/{job_id}")
    def job(request: Request, job_id: str):
        row = store.one("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner(request)))
        if not row:
            raise HTTPException(404, "Pekerjaan tidak ditemukan.")
        if config.job_backend == "rq" and row["status"] in ("queued", "processing"):
            from redis import Redis
            from rq.job import Job
            try:
                status = str(Job.fetch(job_id, connection=Redis.from_url(config.redis_url)).get_status()).lower()
                if "failed" in status or "stopped" in status or "canceled" in status:
                    store.execute("UPDATE jobs SET status='failed',stage='Gagal',error=? WHERE id=?",
                                  ("Worker berhenti atau melewati batas waktu. Coba lagi.", job_id))
                    doc = document_for(request, row["document_id"])
                    store.execute("UPDATE documents SET status=? WHERE id=?",
                                  ("ready" if doc["active_version"] else "failed", doc["id"]))
                    row.update(status="failed", stage="Gagal", error="Worker berhenti. Coba lagi.")
            except Exception:
                row["queue_warning"] = "Tidak dapat membaca Redis. Periksa layanan antrean."
        row.pop("payload", None)
        row.pop("owner", None)
        return row

    @app.get("/api/documents/{document_id}/jobs")
    def document_jobs(request: Request, document_id: str):
        document_for(request, document_id)
        return store.many("SELECT id,document_id,status,stage,error,created,progress_percent,pages_done,pages_total,phase FROM jobs WHERE document_id=? ORDER BY created DESC LIMIT 1",
                          (document_id,))

    @app.post("/api/documents/{document_id}/retry", status_code=202)
    def retry(request: Request, document_id: str):
        doc = document_for(request, document_id)
        last = store.one("SELECT * FROM jobs WHERE document_id=? ORDER BY created DESC LIMIT 1", (doc["id"],))
        if not last or last["status"] != "failed":
            raise HTTPException(409, "Hanya pekerjaan gagal yang bisa dicoba lagi.")
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job_id = new_job(db, doc["id"], owner(request), json.loads(last["payload"] or "{}"))
        schedule(job_id)
        return {"document_id": doc["id"], "job_id": job_id}

    @app.post("/api/documents/{document_id}/reprocess", status_code=202)
    def reprocess(request: Request, document_id: str):
        doc = document_for(request, document_id)
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job_id = new_job(db, doc["id"], owner(request))
        schedule(job_id)
        return {"document_id": doc["id"], "job_id": job_id}

    @app.get("/api/documents/{document_id}/extraction")
    def extraction(request: Request, document_id: str, version_id: str | None = None):
        doc = document_for(request, document_id)
        content, version = content_for(doc, version_id)
        return {"document_id": doc["id"], "version_id": version["id"], "version_number": version["number"],
                "name": doc["name"], **{k: content[k] for k in ("pages", "items", "tables", "warnings", "parser", "quality")}}

    @app.get("/api/documents/{document_id}/pages/{page_no}")
    def page(request: Request, document_id: str, page_no: int, version_id: str | None = None):
        doc = document_for(request, document_id)
        content, _ = content_for(doc, version_id)
        if page_no not in {p["page_no"] for p in content["pages"]}:
            raise HTTPException(404, "Halaman tidak tersedia.")
        return FileResponse(config.data_dir / doc["id"] / "pages" / f"{page_no}.png", media_type="image/png")

    @app.get("/api/documents/{document_id}/export")
    def export(request: Request, document_id: str, format: str = "json", version_id: str | None = None):
        doc = document_for(request, document_id)
        content, version = content_for(doc, version_id)
        if format == "json":
            body = json.dumps(content, ensure_ascii=False, indent=2)
            media = "application/json"
        elif format == "markdown":
            body = "\n\n".join(f"<!-- Page {i['page_no']} -->\n{i['text']}" for i in content["items"])
            media = "text/markdown"
        else:
            raise HTTPException(422, "Format harus json atau markdown.")
        extension = "md" if format == "markdown" else "json"
        return Response(body, media_type=media, headers={"Content-Disposition":
                        f'attachment; filename="extraction-v{version["number"]}.{extension}"'})

    @app.patch("/api/documents/{document_id}/items/{item_id}", status_code=202)
    def correction(request: Request, document_id: str, item_id: str, payload: CorrectionInput):
        doc = document_for(request, document_id)
        if doc["active_version"] != payload.expected_version_id:
            raise HTTPException(409, "Versi berubah. Muat ulang hasil ekstraksi sebelum mengoreksi.")
        content, _ = content_for(doc)
        item = next((i for i in content["items"] if i["id"] == item_id), None)
        if not item or item["type"] != "text":
            raise HTTPException(422, "Koreksi teks hanya tersedia untuk item teks.")
        item["original_text"] = item.get("original_text", item["text"])
        item["text"] = payload.text.strip()
        item["corrected"] = True
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT active_version FROM documents WHERE id=?", (doc["id"],)).fetchone()[0]
            if active != payload.expected_version_id:
                raise HTTPException(409, "Versi berubah; muat ulang dokumen.")
            job_id = new_job(db, doc["id"], owner(request), {"content": content})
        schedule(job_id)
        return {"job_id": job_id, "document_id": doc["id"]}

    @app.post("/api/documents/{document_id}/calculate")
    def calculation(request: Request, document_id: str, payload: CalculationInput):
        doc = document_for(request, document_id)
        content, _ = content_for(doc, payload.version_id)
        table = next((t for t in content["tables"] if t["id"] == payload.table_id), None)
        if not table:
            raise HTTPException(404, "Tabel tidak ditemukan.")
        try:
            result = calculations.calculate(table, payload.column, payload.operation)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {**result, "operation": payload.operation, "column": table["rows"][0][payload.column],
                "document_id": doc["id"], "version_id": payload.version_id,
                "page_no": table["page_no"], "bboxes": [table["bbox"]]}

    @app.delete("/api/documents/{document_id}")
    def delete(request: Request, document_id: str):
        doc = document_for(request, document_id)
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM documents WHERE id=?", (doc["id"],)).fetchone()
            if not row or row[0] == "deleting":
                raise HTTPException(409, "Dokumen sedang dihapus.")
            if db.execute("SELECT 1 FROM jobs WHERE document_id=? AND status IN ('queued','processing')", (doc["id"],)).fetchone():
                raise HTTPException(409, "Tunggu pemrosesan selesai sebelum menghapus dokumen.")
            db.execute("UPDATE documents SET status='deleting' WHERE id=?", (doc["id"],))
        try:
            retrieval.remove_document(doc["id"], owner(request))
            shutil.rmtree(config.data_dir / doc["id"])
        except Exception as exc:
            store.execute("UPDATE documents SET status=? WHERE id=?", (doc["status"], doc["id"]))
            raise HTTPException(503, "File atau indeks belum bisa dihapus. Periksa layanan dan coba lagi.") from exc
        with store.connection() as db:
            for conversation in db.execute("SELECT id,document_ids FROM conversations WHERE owner=?", (owner(request),)).fetchall():
                if doc["id"] in json.loads(conversation["document_ids"]):
                    db.execute("DELETE FROM conversations WHERE id=?", (conversation["id"],))
            db.execute("DELETE FROM documents WHERE id=?", (doc["id"],))
        return {"deleted": True}

    @app.get("/api/conversations")
    def conversations(request: Request):
        return [{**c, "document_ids": json.loads(c["document_ids"])} for c in store.many(
            "SELECT id,document_ids,created FROM conversations WHERE owner=? ORDER BY created DESC", (owner(request),))]

    @app.post("/api/conversations", status_code=201)
    def conversation(request: Request, payload: ConversationInput):
        ids = list(dict.fromkeys(payload.document_ids))
        for document_id in ids:
            doc = document_for(request, document_id)
            if not doc["active_version"]:
                raise HTTPException(409, "Dokumen belum siap untuk percakapan.")
        conversation_id = store.uid()
        store.execute("INSERT INTO conversations VALUES(?,?,?,?)",
                      (conversation_id, owner(request), json.dumps(ids), store.now()))
        return {"id": conversation_id, "document_ids": ids}

    @app.get("/api/conversations/{conversation_id}/messages")
    def history(request: Request, conversation_id: str):
        conversation_for(request, conversation_id)
        return [{**row, "response": json.loads(row["response"]) if row["response"] else None} for row in
                store.many("SELECT id,question,status,response,created FROM messages WHERE conversation_id=? ORDER BY created", (conversation_id,))]

    @app.post("/api/conversations/{conversation_id}/messages")
    def message(request: Request, conversation_id: str, payload: MessageInput):
        conversation = conversation_for(request, conversation_id)
        question = payload.question.strip()
        if not question:
            raise HTTPException(422, "Pertanyaan tidak boleh kosong.")
        existing = store.one("SELECT * FROM messages WHERE conversation_id=? AND request_id=?",
                             (conversation_id, payload.request_id))
        if existing:
            if existing["question"] != question:
                raise HTTPException(409, "Request ID sudah dipakai untuk pertanyaan lain.")
            if existing["response"]:
                return json.loads(existing["response"])
            raise HTTPException(409, "Permintaan masih berjalan atau gagal. Muat ulang riwayat sebelum mencoba lagi.")
        clock = time.monotonic()
        bucket = rate[owner(request)]
        while bucket and bucket[0] < clock - 60:
            bucket.popleft()
        if len(bucket) >= 20:
            raise HTTPException(429, "Batas 20 pertanyaan per menit. Coba sebentar lagi.")
        bucket.append(clock)
        message_id = store.uid()
        try:
            store.execute("INSERT INTO messages(id,conversation_id,request_id,question,status,created) VALUES(?,?,?,?,'processing',?)",
                          (message_id, conversation_id, payload.request_id, question, store.now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Request ID sedang diproses.") from exc
        started = time.perf_counter()
        try:
            chunks, warnings, versions, tables = [], [], [], []
            for document_id in json.loads(conversation["document_ids"]):
                doc = document_for(request, document_id)
                content, version = content_for(doc)
                chunks.extend(content["chunks"])
                warnings.extend(content["warnings"])
                versions.append({"document_id": doc["id"], "version_id": version["id"], "number": version["number"]})
                tables.extend((doc, version, table) for table in content["tables"])
            previous = store.many("SELECT question,response FROM messages WHERE conversation_id=? AND status='complete' ORDER BY created", (conversation_id,))
            chat_history = [{"question": entry["question"], "answer": json.loads(entry["response"])["answer"][:3000]}
                            for entry in previous[-3:]]
            retrieval_question = generation.rewrite(question, previous[-3:])
            operation = next((op for pattern, op in [(r"\b(total|jumlah)\b", "sum"), (r"rata[- ]rata", "average"),
                                                      (r"\b(tertinggi|maksimum)\b", "max"), (r"\b(terendah|minimum)\b", "min")]
                              if re.search(pattern, question.lower())), None)
            matches = []
            if operation:
                query_terms = set(retrieval.tokens(question))
                for doc, version, table in tables:
                    for column, header in enumerate(table["rows"][0]):
                        if query_terms & set(retrieval.tokens(header)):
                            try:
                                value = calculations.calculate(table, column, operation)
                                matches.append((doc, version, table, column, value))
                            except ValueError:
                                pass
            usage = {}
            if operation and len(matches) == 1:
                doc, version, table, column, value = matches[0]
                label = {"sum": "Total", "average": "Rata-rata", "min": "Minimum", "max": "Maksimum"}[operation]
                formatted = calculations.display_number(value["result"])
                answer = f"{label} {table['rows'][0][column]}: {formatted} ({value['unit']}). Dihitung dengan kode dari {value['count']} sel. [1]"
                citations = [{"chunk_id": table["id"], "document_id": doc["id"], "version_id": version["id"],
                              "filename": doc["name"], "page_no": table["page_no"],
                              "quote": parser.table_text(table["rows"]), "bboxes": [table["bbox"]]}]
                answer_status = "answered"
            elif operation and re.search(r"\b(hitung|berapa|total|rata[- ]rata|tertinggi|terendah|maksimum|minimum)\b", question.lower()):
                answer = "Perhitungan belum bisa ditentukan dengan aman. Buka tab Tabel dan pilih tabel, kolom, serta operasi yang dimaksud."
                citations, answer_status = [], "insufficient_evidence"
            else:
                summary = generation.is_overview(question, previous[-3:])
                candidates = chunks if summary else retrieval.retrieve(retrieval_question, chunks)
                # Small documents fit entirely in context; semantic questions need not match exact words.
                if config.llm_provider != "extractive" and len(generation.context(question, chunks, chat_history)) <= 18000:
                    candidates = chunks
                elif not summary and previous and generation.rewrite(question, previous[-3:]) != question:
                    prior_ids = {c["chunk_id"] for c in json.loads(previous[-1]["response"])["citations"]}
                    candidates = list({c["id"]: c for c in candidates + [c for c in chunks if c["id"] in prior_ids]}.values())
                if not candidates and config.llm_provider != "extractive":
                    summary, candidates = True, chunks
                if summary:
                    generated, usage, summary_warnings = generation.summarize(candidates, question, chat_history)
                    warnings.extend(summary_warnings)
                else:
                    generated, usage = generation.generate(question, candidates, chat_history)
                answer, citations = generation.format_answer(generated, candidates)
                answer_status = generated.answer_status
            if config.llm_provider == "extractive" and not operation:
                warnings.insert(0, "Mode kutipan: menampilkan bukti relevan, belum menyusun jawaban dengan LLM.")
            response = {"message_id": message_id, "conversation_id": conversation_id,
                "answer": answer, "answer_status": answer_status, "citations": citations,
                "warnings": list(dict.fromkeys(warnings)), "document_versions": versions,
                "provider": "calculation" if operation and len(matches) == 1 else config.llm_provider, "usage": usage,
                "elapsed_seconds": round(time.perf_counter() - started, 3)}
            store.execute("UPDATE messages SET status='complete',response=? WHERE id=?",
                          (json.dumps(response, ensure_ascii=False), message_id))
            logger.info(json.dumps({"event": "chat_complete", "message_id": message_id,
                                    "seconds": response["elapsed_seconds"], "source_count": len(citations), "usage": usage}))
            return response
        except HTTPException:
            store.execute("UPDATE messages SET status='failed' WHERE id=?", (message_id,))
            raise
        except Exception as exc:
            store.execute("UPDATE messages SET status='failed' WHERE id=?", (message_id,))
            logger.error(json.dumps({"event": "chat_failed", "message_id": message_id, "error_type": type(exc).__name__}))
            raise HTTPException(503, "Jawaban belum bisa dibuat. Periksa model/koneksi dan coba lagi; sumber tidak direkayasa.") from exc

    app.mount("/assets", StaticFiles(directory=ROOT / "frontend/assets"), name="assets")
    return app


app = create_app()
