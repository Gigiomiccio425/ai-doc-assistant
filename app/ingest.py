"""Pipeline di ingestione: parsing -> chunking -> embedding -> ChromaDB.

Un solo thread worker consuma una coda: Ollama non guadagna nulla da richieste
di embedding parallele e cosi' la UI puo' mostrare un avanzamento sensato.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import embeddings, loaders, registry, vectorstore
from .config import DOCS_DIR, get_settings, update_settings

EMBED_BATCH = 32


class _Task:
    def __init__(self, path: Path, origin: str, force: bool = False):
        self.path = path
        self.origin = origin
        self.force = force


class IngestManager:
    def __init__(self) -> None:
        self._queue: "queue.Queue[_Task | None]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current: str | None = None
        self._processed = 0
        self._failed = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=50)

    # --- ciclo di vita -----------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="ingest-worker", daemon=True
        )
        self._thread.start()

    def enqueue(self, path: Path, origin: str = "folder", force: bool = False) -> None:
        if not loaders.is_supported(path):
            return
        registry.upsert(path, origin, status="pending")
        self._queue.put(_Task(path, origin, force))

    def enqueue_doc_id(self, did: str, force: bool = True) -> bool:
        row = registry.get(did)
        if not row:
            return False
        path = Path(row["path"])
        if not path.exists():
            return False
        self.enqueue(path, row["origin"], force=force)
        return True

    def scan_folder(self, force: bool = False) -> dict[str, int]:
        """Scansiona la cartella NAS: aggiunge i nuovi, rimuove gli scomparsi."""
        found = 0
        if DOCS_DIR.exists():
            for path in sorted(DOCS_DIR.rglob("*")):
                if path.is_file() and loaders.is_supported(path):
                    self.enqueue(path, origin="folder", force=force)
                    found += 1

        removed = 0
        for stored in registry.list_paths(origin="folder"):
            if not Path(stored).exists():
                did = registry.doc_id(stored)
                vectorstore.delete_doc(did)
                registry.delete(did)
                removed += 1

        self._log(f"Scansione cartella: {found} file trovati, {removed} rimossi")
        return {"found": found, "removed": removed}

    def reindex_all(self) -> None:
        registry.mark_all_pending()
        for stored in registry.list_paths():
            path = Path(stored)
            if path.exists():
                self.enqueue(path, registry.get_by_path(path)["origin"], force=True)

    def remove(self, did: str) -> bool:
        row = registry.get(did)
        if not row:
            return False
        vectorstore.delete_doc(did)
        registry.delete(did)
        # I file caricati dalla UI vivono solo qui: si cancellano davvero.
        # Quelli del NAS non si toccano mai.
        if row["origin"] == "upload":
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._log(f"Rimosso dall'indice: {row['name']}")
        return True

    # --- worker ------------------------------------------------------------
    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                self._process(task)
            except Exception as exc:  # nessun errore deve uccidere il worker
                self._failed += 1
                self._log(f"ERRORE {task.path.name}: {exc}")
                registry.set_status(registry.doc_id(task.path), "error", str(exc))
            finally:
                with self._lock:
                    self._current = None
                self._queue.task_done()

    def _process(self, task: _Task) -> None:
        path = task.path
        did = registry.doc_id(path)

        if not path.exists():
            vectorstore.delete_doc(did)
            registry.delete(did)
            return

        settings = get_settings()
        fingerprint = registry.fingerprint(path)
        existing = registry.get(did)
        if (
            not task.force
            and existing
            and existing["status"] == "indexed"
            and existing["fingerprint"] == fingerprint
        ):
            return  # gia' indicizzato e non modificato

        with self._lock:
            self._current = path.name
        registry.set_status(did, "indexing", None)

        blocks = loaders.load_file(path)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for block in blocks:
            for i, chunk in enumerate(splitter.split_text(block["text"])):
                if len(chunk.strip()) < 20:
                    continue
                texts.append(chunk)
                metadatas.append(
                    {
                        "doc_id": did,
                        "file_name": path.name,
                        "source_path": str(path),
                        "origin": task.origin,
                        "page": block["page"] if block["page"] is not None else -1,
                        "chunk": i,
                    }
                )

        if not texts:
            raise ValueError("Nessun chunk utile generato dal file")

        # Reindicizzazione = sostituzione: prima si buttano i vettori vecchi.
        vectorstore.delete_doc(did)

        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            vectors = embeddings.embed_texts(batch, model=settings.embed_model)
            vectorstore.add_chunks(
                f"{did}-{start}", batch, vectors, metadatas[start : start + EMBED_BATCH]
            )

        pages = len({b["page"] for b in blocks if b["page"] is not None})
        registry.upsert(
            path,
            task.origin,
            fingerprint=fingerprint,
            chunks=len(texts),
            pages=pages,
            status="indexed",
            error=None,
        )
        if settings.indexed_embed_model != settings.embed_model:
            update_settings({"indexed_embed_model": settings.embed_model})

        self._processed += 1
        self._log(f"Indicizzato {path.name} ({len(texts)} chunk)")

    # --- stato -------------------------------------------------------------
    def _log(self, message: str) -> None:
        self._events.appendleft({"ts": time.time(), "message": message})

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current
        return {
            "running": current is not None,
            "current": current,
            "queued": self._queue.qsize(),
            "processed": self._processed,
            "failed": self._failed,
            "events": list(self._events)[:15],
        }


manager = IngestManager()
