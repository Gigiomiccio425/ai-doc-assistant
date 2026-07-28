"""Monitoraggio in tempo reale della cartella NAS (watchdog).

Debounce di 5 secondi per file: una copia via SMB genera decine di eventi
'modified' mentre il file e' ancora incompleto.
"""

from __future__ import annotations

import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import ingest, loaders, registry, vectorstore
from .config import DOCS_DIR

DEBOUNCE_SECONDS = 5.0

_observer: Observer | None = None
_timers: dict[str, threading.Timer] = {}
_lock = threading.Lock()


class _Handler(FileSystemEventHandler):
    def on_created(self, event: FileSystemEvent) -> None:
        self._touch(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._touch(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._drop(Path(event.src_path))
        dest = getattr(event, "dest_path", None)
        if dest:
            self._schedule(Path(dest))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._drop(Path(event.src_path))

    def _touch(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule(Path(event.src_path))

    def _schedule(self, path: Path) -> None:
        if not loaders.is_supported(path):
            return
        key = str(path)
        with _lock:
            timer = _timers.pop(key, None)
            if timer:
                timer.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, _fire, args=(path,))
            timer.daemon = True
            _timers[key] = timer
            timer.start()

    def _drop(self, path: Path) -> None:
        if not loaders.is_supported(path):
            return
        did = registry.doc_id(path)
        if registry.get(did):
            vectorstore.delete_doc(did)
            registry.delete(did)


def _fire(path: Path) -> None:
    with _lock:
        _timers.pop(str(path), None)
    if path.exists():
        ingest.manager.enqueue(path, origin="folder")


def start() -> bool:
    global _observer
    if _observer is not None or not DOCS_DIR.exists():
        return False
    _observer = Observer()
    _observer.schedule(_Handler(), str(DOCS_DIR), recursive=True)
    _observer.start()
    return True


def stop() -> None:
    global _observer
    with _lock:
        for timer in _timers.values():
            timer.cancel()
        _timers.clear()
    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None


def is_running() -> bool:
    return _observer is not None and _observer.is_alive()
