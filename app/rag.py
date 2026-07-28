"""Retrieval + costruzione del prompt + risposta in streaming da Ollama."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from . import embeddings, vectorstore
from .config import get_settings

_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)
MAX_HISTORY_TURNS = 6


def _label(meta: dict[str, Any]) -> str:
    page = meta.get("page", -1)
    if isinstance(page, (int, float)) and page > 0:
        return f"{meta.get('file_name', 'documento')}, pag. {int(page)}"
    chunk = meta.get("chunk", 0)
    return f"{meta.get('file_name', 'documento')}, sezione {int(chunk) + 1}"


def retrieve(question: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Cerca i chunk piu' vicini alla domanda. Chiamata sincrona (bloccante)."""
    settings = get_settings()
    top_k = top_k or settings.top_k
    vector = embeddings.embed_query(question, model=settings.embed_model)
    hits = vectorstore.query(vector, top_k=top_k)

    results = []
    for index, hit in enumerate(hits, start=1):
        meta = hit["meta"]
        results.append(
            {
                "n": index,
                "text": hit["text"],
                "score": hit["score"],
                "file_name": meta.get("file_name", "documento"),
                "source_path": meta.get("source_path", ""),
                "page": int(meta.get("page", -1)),
                "label": _label(meta),
                "snippet": hit["text"][:400].replace("\n", " ").strip(),
            }
        )
    return results


def build_context(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(f"[{chunk['n']}] (fonte: {chunk['label']})\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def build_messages(
    question: str, history: list[dict[str, str]], chunks: list[dict[str, Any]]
) -> list[dict[str, str]]:
    settings = get_settings()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": settings.system_prompt}
    ]

    for turn in history[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append(
        {
            "role": "user",
            "content": (
                f"CONTESTO:\n{build_context(chunks)}\n\n"
                f"DOMANDA: {question}\n\n"
                "Rispondi usando solo il CONTESTO e cita le fonti con [n]."
            ),
        }
    )
    return messages


async def stream_answer(
    question: str, history: list[dict[str, str]], chunks: list[dict[str, Any]]
) -> AsyncIterator[str]:
    """Genera i token della risposta uno alla volta (Ollama /api/chat)."""
    settings = get_settings()
    payload = {
        "model": settings.llm_model,
        "messages": build_messages(question, history, chunks),
        "stream": True,
        "options": {
            "temperature": settings.temperature,
            "num_ctx": settings.num_ctx,
        },
    }
    url = settings.ollama_url.rstrip("/") + "/api/chat"

    async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", "replace")
                raise RuntimeError(
                    f"Ollama ha risposto {response.status_code}: {body[:300]}"
                )
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue  # riga parziale: si ignora
                if data.get("error"):
                    raise RuntimeError(str(data["error"]))
                token = (data.get("message") or {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break


async def list_models() -> list[str]:
    url = get_settings().ollama_url.rstrip("/") + "/api/tags"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return sorted(m["name"] for m in response.json().get("models", []))


async def ollama_alive() -> bool:
    try:
        url = get_settings().ollama_url.rstrip("/") + "/api/version"
        async with httpx.AsyncClient(timeout=5.0) as client:
            return (await client.get(url)).status_code == 200
    except Exception:
        return False
