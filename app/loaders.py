"""Parsing dei file in blocchi di testo con riferimento di pagina/sezione.

Usa i document loader di LangChain Community, che normalizzano PDF, DOCX e
testo semplice in oggetti Document con metadati.
"""

from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)

from .config import SUPPORTED_EXT


class UnsupportedFile(ValueError):
    pass


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXT


def load_file(path: Path) -> list[dict]:
    """Restituisce [{'text': str, 'page': int|None, 'section': str|None}, ...]."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise UnsupportedFile(f"Estensione non supportata: {ext}")

    if ext == ".pdf":
        docs = PyPDFLoader(str(path)).load()
        blocks = [
            {
                "text": d.page_content,
                # PyPDFLoader indicizza le pagine da 0: +1 per la citazione umana
                "page": int(d.metadata.get("page", 0)) + 1,
                "section": None,
            }
            for d in docs
        ]
    elif ext == ".docx":
        docs = Docx2txtLoader(str(path)).load()
        blocks = [{"text": d.page_content, "page": None, "section": None} for d in docs]
    else:
        docs = TextLoader(str(path), autodetect_encoding=True).load()
        blocks = [{"text": d.page_content, "page": None, "section": None} for d in docs]

    cleaned = [b for b in blocks if b["text"] and b["text"].strip()]
    if not cleaned:
        raise ValueError(
            "Nessun testo estraibile (PDF scansionato? Serve OCR, non incluso)."
        )
    return cleaned
