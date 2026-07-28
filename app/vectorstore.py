"""Wrapper minimale su ChromaDB persistente su disco."""

from __future__ import annotations

import threading
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from .config import CHROMA_DIR, COLLECTION_NAME, ensure_dirs

_client: chromadb.ClientAPI | None = None
_lock = threading.RLock()


def client() -> chromadb.ClientAPI:
    global _client
    with _lock:
        if _client is None:
            ensure_dirs()
            _client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
            )
        return _client


def collection() -> chromadb.Collection:
    # cosine: piu' stabile della distanza L2 con embedding non normalizzati
    return client().get_or_create_collection(
        name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def add_chunks(
    doc_id: str,
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> None:
    if not texts:
        return
    ids = [f"{doc_id}:{i}" for i in range(len(texts))]
    collection().add(
        ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
    )


def delete_doc(doc_id: str) -> None:
    collection().delete(where={"doc_id": doc_id})


def query(embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
    res = collection().query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict[str, Any]] = []
    documents = (res.get("documents") or [[]])[0]
    metadatas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    for text, meta, dist in zip(documents, metadatas, distances):
        hits.append(
            {
                "text": text,
                "meta": dict(meta or {}),
                # distanza coseno in [0,2] -> similarita' leggibile in [0,1]
                "score": round(max(0.0, 1.0 - float(dist)), 4),
            }
        )
    return hits


def count() -> int:
    try:
        return collection().count()
    except Exception:
        return 0


def reset() -> None:
    """Cancella l'intera collezione. Usato al cambio di modello di embedding."""
    with _lock:
        try:
            client().delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        collection()
