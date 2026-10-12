import hashlib
import re
import threading
from functools import lru_cache

from rank_bm25 import BM25Okapi

from ..config import settings

MODEL_LOCK = threading.RLock()
STOPWORDS = set("apa apakah bagaimana berapa yang dan atau di ke dari untuk dengan pada ini itu saya kamu tolong jelaskan menurut dokumen what is the of a an in how".split())


def tokens(text):
    return [t for t in re.findall(r"[\w]+(?:[-./][\w]+)*", text.lower()) if t not in STOPWORDS]


@lru_cache
def encoder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ValueError("Embedding belum terpasang. Jalankan uv sync --extra ai.") from exc
    return SentenceTransformer(settings().embedding_model)


def embed(texts, query=False):
    with MODEL_LOCK:
        return encoder().encode([("query: " if query else "passage: ") + t for t in texts],
                                normalize_embeddings=True).tolist()


def split_text(text, max_tokens=360):
    if settings().embedding_backend == "e5":
        tokenizer = encoder().tokenizer
        ids = tokenizer.encode(text, add_special_tokens=False)
        return [tokenizer.decode(ids[i:i + max_tokens], skip_special_tokens=True)
                for i in range(0, len(ids), max_tokens)]
    words = text.split()
    return [" ".join(words[i:i + 180]) for i in range(0, len(words), 180)]


def make_chunks(content, document_id, version_id, owner, filename):
    chunks = []
    # Group neighboring text lines on the same page. Keep tables separate.
    groups = []
    for item in content["items"]:
        if (groups and item["type"] == "text" and groups[-1][-1]["type"] == "text"
                and item["page_no"] == groups[-1][0]["page_no"]
                and sum(len(x["text"].split()) for x in groups[-1]) < 100):
            groups[-1].append(item)
        else:
            groups.append([item])
    for group in groups:
        text = "\n".join(item["text"] for item in group)
        for piece in split_text(text):
            chunk_id = hashlib.sha256(f"{version_id}:{len(chunks)}".encode()).hexdigest()[:24]
            chunks.append({"id": chunk_id, "text": piece, "document_id": document_id,
                           "version_id": version_id, "owner": owner, "filename": filename,
                           "page_no": group[0]["page_no"], "item_ids": [i["id"] for i in group],
                           "bboxes": [i["bbox"] for i in group], "table_id": group[0].get("table_id")})
    return chunks


@lru_cache
def vector_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings().qdrant_url, api_key=settings().qdrant_api_key or None, timeout=30)


def collection_name():
    return "dokumentanya_" + hashlib.sha256(settings().embedding_model.encode()).hexdigest()[:10]


def index(chunks):
    if settings().embedding_backend == "none":
        return
    from qdrant_client import models
    import uuid
    vectors = embed([c["text"] for c in chunks])
    client, collection = vector_client(), collection_name()
    if not client.collection_exists(collection):
        client.create_collection(collection, vectors_config=models.VectorParams(
            size=len(vectors[0]), distance=models.Distance.COSINE))
    for offset in range(0, len(chunks), 64):
        client.upsert(collection, wait=True, points=[models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["id"])), vector=vector,
            payload={k: c[k] for k in ("id", "owner", "document_id", "version_id")})
            for c, vector in zip(chunks[offset:offset + 64], vectors[offset:offset + 64])])


def remove_document(document_id, owner):
    if not settings().qdrant_url:
        return
    from qdrant_client import models
    client = vector_client()
    # Also clean older embedding-model collections created by this application.
    for collection in client.get_collections().collections:
        if collection.name.startswith("dokumentanya_"):
            client.delete(collection.name, wait=True, points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="owner", match=models.MatchValue(value=owner)),
                                           models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])))


def retrieve(question, chunks, mode=None, limit=None):
    if not chunks:
        return []
    mode = mode or settings().retrieval_mode
    limit = limit or settings().retrieval_top_k
    query_tokens = tokens(question)
    lexical = []
    if query_tokens:
        corpus = [tokens(c["text"]) or ["_"] for c in chunks]
        scores = BM25Okapi(corpus, epsilon=0.25).get_scores(query_tokens)
        # BM25 can produce zero/negative IDF on tiny corpora; lexical overlap still matters.
        lexical = sorted((i for i, t in enumerate(corpus) if set(query_tokens) & set(t)),
                         key=lambda i: float(scores[i]), reverse=True)[:20]
    dense = []
    if mode != "bm25" and settings().embedding_backend == "e5":
        from qdrant_client import models
        versions = sorted({c["version_id"] for c in chunks})
        result = vector_client().query_points(collection_name(), query=embed([question], query=True)[0],
            query_filter=models.Filter(must=[
                models.FieldCondition(key="owner", match=models.MatchValue(value=chunks[0]["owner"])),
                models.FieldCondition(key="version_id", match=models.MatchAny(any=versions))]),
            limit=20, with_payload=True).points
        lookup = {c["id"]: i for i, c in enumerate(chunks)}
        dense = [lookup[p.payload["id"]] for p in result if p.payload["id"] in lookup]
    ranks = [lexical] if mode == "bm25" or not dense else ([dense] if mode == "dense" else [lexical, dense])
    merged = {}
    for ranking in ranks:
        for rank, i in enumerate(ranking):
            merged[i] = merged.get(i, 0) + 1 / (60 + rank + 1)
    indices = sorted(merged, key=merged.get, reverse=True)[:20]
    results = [dict(chunks[i], retrieval_score=merged[i]) for i in indices]
    if settings().reranker_enabled and results:
        results = rerank(question, results)
    return results[:limit]


@lru_cache
def reranker():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(settings().reranker_model, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(settings().reranker_model).eval()
    return tokenizer, model


def rerank(question, candidates):
    import torch
    tokenizer, model = reranker()
    prefix = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
    yes, no = tokenizer.convert_tokens_to_ids("yes"), tokenizer.convert_tokens_to_ids("no")
    with MODEL_LOCK, torch.inference_mode():
        for candidate in candidates:
            prompt = prefix + "<Instruct>: Retrieve relevant evidence for a document question\n<Query>: " + question + "\n<Document>: " + candidate["text"] + suffix
            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
            logits = model(**inputs).logits[0, -1, [no, yes]].float().softmax(dim=0)
            candidate["rerank_score"] = float(logits[1])
    return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
