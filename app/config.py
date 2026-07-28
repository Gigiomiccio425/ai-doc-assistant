"""Percorsi, costanti e impostazioni persistenti modificabili dalla UI."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# --- Percorsi (sovrascrivibili da env, vedi docker-compose) -----------------
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DOCS_DIR = Path(os.getenv("DOCS_DIR", "/documents"))

CHROMA_DIR = DATA_DIR / "chroma"
UPLOAD_DIR = DATA_DIR / "uploads"
REGISTRY_DB = DATA_DIR / "registry.sqlite3"
SETTINGS_FILE = DATA_DIR / "settings.json"

COLLECTION_NAME = "documents"

SUPPORTED_EXT = {
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".csv",
    ".log",
    ".json",
}

DEFAULT_SYSTEM_PROMPT = (
    "Sei un assistente che risponde ESCLUSIVAMENTE usando il CONTESTO fornito, "
    "estratto dai documenti personali dell'utente.\n"
    "Regole:\n"
    "1. Rispondi in italiano, in modo diretto e conciso.\n"
    "2. Cita sempre le fonti con i marcatori numerici [1], [2] ... subito dopo "
    "l'informazione a cui si riferiscono.\n"
    "3. Se il CONTESTO non contiene la risposta, scrivi chiaramente "
    "'Non ho trovato questa informazione nei documenti indicizzati'. Non inventare.\n"
    "4. Importi, date, scadenze e clausole vanno riportati con il valore esatto "
    "presente nel documento, senza arrotondare o parafrasare."
)


class Settings(BaseModel):
    """Impostazioni runtime. Salvate in /data/settings.json, editabili dalla UI."""

    ollama_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_URL", "http://ollama:11434")
    )
    llm_model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "llama3.2"))
    embed_model: str = Field(
        default_factory=lambda: os.getenv("EMBED_MODEL", "nomic-embed-text")
    )
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5
    temperature: float = 0.1
    num_ctx: int = 8192
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    watch_enabled: bool = True
    # Modello di embedding con cui l'indice attuale e' stato costruito.
    # Se cambia, i vettori vecchi non sono piu' confrontabili -> reindex totale.
    indexed_embed_model: str | None = None


_lock = threading.RLock()
_cache: Settings | None = None


def ensure_dirs() -> None:
    for path in (DATA_DIR, CHROMA_DIR, UPLOAD_DIR):
        path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    global _cache
    with _lock:
        if _cache is None:
            data: dict[str, Any] = {}
            if SETTINGS_FILE.exists():
                try:
                    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
            _cache = Settings(**data)
        return _cache


def update_settings(patch: dict[str, Any]) -> Settings:
    global _cache
    with _lock:
        current = get_settings().model_dump()
        current.update({k: v for k, v in patch.items() if v is not None})
        _cache = Settings(**current)
        _persist(_cache)
        return _cache


def _persist(settings: Settings) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
