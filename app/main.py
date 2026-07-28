"""API FastAPI dell'Assistente AI Locale per Documenti."""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import __version__, config, ingest, rag, registry, vectorstore, watcher

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    registry.init()
    ingest.manager.start()

    if os.getenv("SCAN_ON_START", "true").lower() in ("1", "true", "yes"):
        await run_in_threadpool(ingest.manager.scan_folder)
    if config.get_settings().watch_enabled:
        watcher.start()
    yield
    watcher.stop()


app = FastAPI(
    title="Assistente AI Locale per Documenti",
    version=__version__,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --- Modelli richiesta ------------------------------------------------------
class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[dict[str, str]] = []


class SettingsPatch(BaseModel):
    ollama_url: str | None = None
    llm_model: str | None = None
    embed_model: str | None = None
    chunk_size: int | None = Field(default=None, ge=200, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    num_ctx: int | None = Field(default=None, ge=1024, le=131072)
    system_prompt: str | None = None
    watch_enabled: bool | None = None


# --- UI ---------------------------------------------------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"version": __version__})


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


# --- Stato ------------------------------------------------------------------
@app.get("/api/status")
async def status():
    settings = config.get_settings()
    stale = bool(
        settings.indexed_embed_model
        and settings.indexed_embed_model != settings.embed_model
    )
    return {
        "ollama": {
            "url": settings.ollama_url,
            "online": await rag.ollama_alive(),
            "llm_model": settings.llm_model,
            "embed_model": settings.embed_model,
        },
        "index": {
            **registry.counts(),
            "vectors": await run_in_threadpool(vectorstore.count),
            "stale_embeddings": stale,
        },
        "ingest": ingest.manager.status(),
        "watch": {
            "enabled": settings.watch_enabled,
            "running": watcher.is_running(),
            "folder": str(config.DOCS_DIR),
        },
    }


# --- Documenti --------------------------------------------------------------
@app.get("/api/documents")
async def list_documents():
    return {"documents": registry.list_all()}


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._()\-\[\]]+")


@app.post("/api/documents/upload")
async def upload(files: list[UploadFile] = File(...)):
    config.ensure_dirs()
    accepted, rejected = [], []

    for upload_file in files:
        name = _SAFE_NAME.sub("_", Path(upload_file.filename or "file").name).strip()
        if not name:
            rejected.append({"name": upload_file.filename, "reason": "nome non valido"})
            continue
        target = config.UPLOAD_DIR / name
        if target.suffix.lower() not in config.SUPPORTED_EXT:
            rejected.append({"name": name, "reason": "formato non supportato"})
            continue

        with target.open("wb") as handle:
            shutil.copyfileobj(upload_file.file, handle)
        await upload_file.close()

        ingest.manager.enqueue(target, origin="upload", force=True)
        accepted.append(name)

    return {"accepted": accepted, "rejected": rejected}


@app.post("/api/documents/scan")
async def scan():
    return await run_in_threadpool(ingest.manager.scan_folder)


@app.post("/api/documents/reindex-all")
async def reindex_all():
    await run_in_threadpool(ingest.manager.reindex_all)
    return {"ok": True}


@app.post("/api/documents/{doc_id}/reindex")
async def reindex(doc_id: str):
    if not ingest.manager.enqueue_doc_id(doc_id, force=True):
        raise HTTPException(404, "Documento non trovato o file mancante sul disco")
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    if not await run_in_threadpool(ingest.manager.remove, doc_id):
        raise HTTPException(404, "Documento non trovato")
    return {"ok": True}


# --- Impostazioni -----------------------------------------------------------
@app.get("/api/settings")
async def read_settings():
    return config.get_settings().model_dump()


@app.post("/api/settings")
async def write_settings(patch: SettingsPatch):
    previous = config.get_settings()
    updated = config.update_settings(patch.model_dump(exclude_none=True))

    # Il modello di embedding definisce lo spazio vettoriale: cambiarlo rende
    # l'indice esistente incomparabile. Si azzera e si reindicizza tutto.
    reindexed = False
    if updated.embed_model != previous.embed_model and previous.indexed_embed_model:
        await run_in_threadpool(vectorstore.reset)
        await run_in_threadpool(ingest.manager.reindex_all)
        reindexed = True

    if updated.watch_enabled and not watcher.is_running():
        watcher.start()
    elif not updated.watch_enabled and watcher.is_running():
        watcher.stop()

    return {"settings": updated.model_dump(), "reindex_triggered": reindexed}


@app.get("/api/models")
async def models():
    try:
        return {"models": await rag.list_models()}
    except Exception as exc:
        return JSONResponse({"models": [], "error": str(exc)}, status_code=200)


# --- Chat (SSE) -------------------------------------------------------------
def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    settings = config.get_settings()

    async def event_stream():
        try:
            chunks = await run_in_threadpool(
                rag.retrieve, request.question, settings.top_k
            )
        except Exception as exc:
            yield _sse("error", {"message": f"Ricerca fallita: {exc}"})
            return

        yield _sse(
            "sources",
            {
                "sources": [
                    {
                        "n": c["n"],
                        "label": c["label"],
                        "file_name": c["file_name"],
                        "page": c["page"],
                        "score": c["score"],
                        "snippet": c["snippet"],
                    }
                    for c in chunks
                ]
            },
        )

        if not chunks:
            yield _sse(
                "token",
                {
                    "t": "Non ho trovato nulla nei documenti indicizzati. "
                    "Verifica che l'indicizzazione sia completata."
                },
            )
            yield _sse("done", {"ok": True})
            return

        try:
            async for token in rag.stream_answer(
                request.question, request.history, chunks
            ):
                yield _sse("token", {"t": token})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
            return

        yield _sse("done", {"ok": True})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disattiva il buffering di eventuali reverse proxy
        },
    )
