"""Client di embedding verso Ollama.

Implementazione diretta via httpx invece di langchain-ollama: cosi' possiamo
usare l'endpoint batch /api/embed (molto piu' veloce su centinaia di chunk)
con fallback automatico sul vecchio /api/embeddings per Ollama datati.
"""

from __future__ import annotations

import httpx

from .config import get_settings

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)


class EmbeddingError(RuntimeError):
    pass


def _base_url() -> str:
    return get_settings().ollama_url.rstrip("/")


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Restituisce un vettore per ogni testo, nello stesso ordine."""
    if not texts:
        return []
    model = model or get_settings().embed_model
    url = _base_url()

    with httpx.Client(timeout=_TIMEOUT) as client:
        # Endpoint batch (Ollama >= 0.3.x)
        try:
            resp = client.post(
                f"{url}/api/embed", json={"model": model, "input": texts}
            )
            if resp.status_code == 200:
                vectors = resp.json().get("embeddings")
                if vectors and len(vectors) == len(texts):
                    return vectors
            elif resp.status_code == 404:
                pass  # Ollama vecchio: si usa il fallback
            else:
                raise EmbeddingError(
                    f"Ollama /api/embed ha risposto {resp.status_code}: {resp.text[:200]}"
                )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama non raggiungibile su {url}: {exc}") from exc

        # Fallback: una richiesta per testo
        vectors = []
        for text in texts:
            resp = client.post(
                f"{url}/api/embeddings", json={"model": model, "prompt": text}
            )
            if resp.status_code != 200:
                raise EmbeddingError(
                    f"Ollama /api/embeddings ha risposto {resp.status_code}: {resp.text[:200]}"
                )
            vectors.append(resp.json()["embedding"])
        return vectors


def embed_query(text: str, model: str | None = None) -> list[float]:
    return embed_texts([text], model=model)[0]
