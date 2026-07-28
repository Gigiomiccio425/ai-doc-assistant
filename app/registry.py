"""Anagrafica dei documenti indicizzati (SQLite).

Chroma tiene i vettori; qui teniamo lo stato "umano" di ogni file:
percorso, dimensione, impronta, numero di chunk, stato, errore.
Serve per la sezione "Gestione indice" della UI e per capire cosa
va reindicizzato dopo una modifica sul NAS.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import REGISTRY_DB, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT 'folder',   -- 'folder' | 'upload'
    ext         TEXT,
    size        INTEGER DEFAULT 0,
    mtime       REAL    DEFAULT 0,
    fingerprint TEXT,
    chunks      INTEGER DEFAULT 0,
    pages       INTEGER DEFAULT 0,
    status      TEXT    DEFAULT 'pending',        -- pending|indexing|indexed|error
    error       TEXT,
    updated_at  REAL    DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(REGISTRY_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        # Nessun processo puo' essere rimasto "indexing" dopo un riavvio.
        conn.execute("UPDATE documents SET status='pending' WHERE status='indexing'")


def doc_id(path: Path | str) -> str:
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]


def fingerprint(path: Path) -> str:
    """Impronta rapida: dimensione + mtime. Evita di rileggere PDF da 50 MB."""
    stat = path.stat()
    return f"{stat.st_size}-{int(stat.st_mtime)}"


def upsert(path: Path, origin: str, **fields: Any) -> str:
    did = doc_id(path)
    stat = path.stat() if path.exists() else None
    row = {
        "id": did,
        "path": str(path),
        "name": path.name,
        "origin": origin,
        "ext": path.suffix.lower(),
        "size": stat.st_size if stat else 0,
        "mtime": stat.st_mtime if stat else 0,
        "updated_at": time.time(),
    }
    row.update(fields)
    columns = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row if k != "id")
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            row,
        )
    return did


def set_status(did: str, status: str, error: str | None = None, **fields: Any) -> None:
    row: dict[str, Any] = {"status": status, "error": error, "updated_at": time.time()}
    row.update(fields)
    assignments = ", ".join(f"{k}=:{k}" for k in row)
    row["id"] = did
    with _conn() as conn:
        conn.execute(f"UPDATE documents SET {assignments} WHERE id=:id", row)


def get(did: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    return dict(row) if row else None


def get_by_path(path: Path | str) -> dict[str, Any] | None:
    return get(doc_id(path))


def list_all() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_paths(origin: str | None = None) -> list[str]:
    query = "SELECT path FROM documents"
    params: tuple[Any, ...] = ()
    if origin:
        query += " WHERE origin=?"
        params = (origin,)
    with _conn() as conn:
        return [r["path"] for r in conn.execute(query, params).fetchall()]


def delete(did: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM documents WHERE id=?", (did,))


def mark_all_pending() -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE documents SET status='pending', chunks=0, fingerprint=NULL, error=NULL"
        )


def counts() -> dict[str, int]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        chunks = (
            conn.execute("SELECT COALESCE(SUM(chunks),0) AS n FROM documents").fetchone()["n"]
        )
    result = {r["status"]: r["n"] for r in rows}
    result["total"] = total
    result["chunks"] = chunks
    return result
