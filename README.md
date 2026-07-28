# Assistente AI Locale per Documenti (RAG personale)

[![Build & publish image](https://github.com/Gigiomiccio425/ai-doc-assistant/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Gigiomiccio425/ai-doc-assistant/actions/workflows/docker-publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Chat privata sui documenti del NAS. Nessuna chiamata verso l'esterno: parsing,
embedding, ricerca vettoriale e generazione avvengono tutti dentro la tua rete.

**Stack:** FastAPI · LangChain (loader + splitter) · ChromaDB persistente · Ollama
· TailwindCSS + Alpine.js · Docker Compose con metadati CasaOS/Zima OS.

---

## Struttura

```
ai-doc-assistant/
├── .github/workflows/
│   └── docker-publish.yml   # CI: import check + build multi-arch su GHCR
├── docker-compose.yml       # servizi + metadati x-casaos
├── Dockerfile               # build multi-stage
├── requirements.txt
├── .env.example             # percorsi NAS, porte, modelli
├── .dockerignore
└── app/
    ├── main.py              # FastAPI: rotte, SSE, lifespan
    ├── config.py            # percorsi + impostazioni persistenti
    ├── registry.py          # anagrafica documenti (SQLite)
    ├── loaders.py           # PDF / DOCX / TXT -> blocchi di testo
    ├── ingest.py            # chunking -> embedding -> Chroma (worker)
    ├── embeddings.py        # client Ollama /api/embed
    ├── vectorstore.py       # wrapper ChromaDB
    ├── watcher.py           # monitoraggio cartella NAS (watchdog)
    ├── rag.py               # retrieval + prompt + streaming
    ├── templates/index.html # UI chat + gestione indice
    └── static/{app.js,icon.svg}
```

---

## Immagine pronta

L'immagine viene costruita da GitHub Actions a ogni push su `main` e pubblicata su
GitHub Container Registry — non serve compilare nulla sul NAS:

```
ghcr.io/gigiomiccio425/ai-doc-assistant:latest
```

`main` produce `linux/amd64` (il target di ZimaBoard / ZimaCube). I tag di
release `v*` producono anche `linux/arm64`, che sotto emulazione QEMU richiede
molto più tempo perché ChromaDB va compilato da sorgente.

## Installazione su Zima OS

1. Copia la cartella sul NAS, per esempio in `/DATA/AppData/ai-doc-assistant/src`
   (oppure `git clone https://github.com/Gigiomiccio425/ai-doc-assistant.git`).
2. Prepara la configurazione:

   ```bash
   cd ai-doc-assistant
   cp .env.example .env
   nano .env          # imposta DOCUMENTS_PATH e la porta
   ```

3. Avvio:

   ```bash
   docker compose pull
   docker compose up -d
   ```

   Il servizio `ollama-pull` scarica `llama3.2` e `nomic-embed-text` al primo
   avvio (alcuni GB) e poi termina. Segui l'avanzamento con
   `docker compose logs -f ollama-pull`.

4. Apri `http://<ip-del-nas>:8088`.

Il package è pubblico: nessun `docker login` necessario sul NAS.

### Farla comparire nella dashboard Zima

Zima OS legge i blocchi `x-casaos`. Due strade:

- **Import da UI:** App Store → *Custom Install* → incolla il contenuto di
  `docker-compose.yml`. Icona, titolo e link vengono presi dai metadati.
- **Manuale:** dopo `docker compose up -d`, il container compare tra le app; il
  campo `icon` punta a un PNG pubblico — sostituiscilo con un tuo file, ad
  esempio `icon: http://<ip-del-nas>:8088/static/icon.svg` (l'icona SVG è già
  servita dall'app).

### Se Ollama è già installato

Cancella i servizi `ollama` e `ollama-pull` dal compose, rimuovi il blocco
`depends_on` del servizio `app` e imposta in `.env`:

```
OLLAMA_URL=http://<ip-del-nas>:11434
```

Ollama deve ascoltare su tutte le interfacce (`OLLAMA_HOST=0.0.0.0`), altrimenti
il container non lo raggiunge.

---

## Uso

- **Documenti:** trascina i file nella sidebar oppure lascia che la scansione
  automatica trovi quanto sta in `/DATA/Documents`. Il watcher indicizza i nuovi
  file entro pochi secondi dalla copia.
- **Chat:** ogni risposta riporta i marcatori `[1] [2]`; sotto compaiono le fonti
  espandibili con nome file, pagina, punteggio di similarità e anteprima.
- **Indice:** ogni riga ha reindicizza (documento modificato) ed elimina. I file
  del NAS non vengono mai cancellati dal disco — solo i vettori. I file caricati
  dalla UI vivono in `/data/uploads` e vengono rimossi davvero.
- **Impostazioni:** URL Ollama, modello LLM, modello di embedding, dimensione
  chunk, top-k, temperatura e system prompt.

---

## Note operative

**Cambio del modello di embedding.** Modelli diversi producono spazi vettoriali
diversi e dimensioni diverse: i vettori vecchi diventano inconfrontabili. L'app
se ne accorge, azzera la collezione e riaccoda tutti i documenti. Con centinaia
di PDF l'operazione richiede tempo.

**PDF scansionati.** Senza livello di testo non si estrae nulla: il documento
finisce in stato `error` con la relativa nota. Serve un OCR a monte (per esempio
OCRmyPDF che scrive nella cartella monitorata); non è incluso.

**Permessi.** Il container gira come uid 1000. Se `/DATA/AppData/...` appartiene
a un altro utente, l'app non riesce a scrivere il vector DB:

```bash
sudo chown -R 1000:1000 /DATA/AppData/ai-doc-assistant
```

**Tailwind e Alpine via CDN.** Come da specifica, `index.html` li carica da CDN:
il browser che apre la UI deve avere internet, il NAS no — nessun documento
viene comunque trasmesso. Per un funzionamento del tutto offline scarica i due
file in `app/static/` e sostituisci i due `<script>` con percorsi locali.

**Prestazioni.** Un solo worker uvicorn e un solo thread di ingestione: Ollama
serve comunque una richiesta alla volta, e così l'avanzamento resta leggibile.
Su hardware senza GPU conviene un modello piccolo (`phi3`, `qwen2.5:3b`) e
`num_ctx` ridotto.

---

## API

| Metodo | Rotta | Descrizione |
|---|---|---|
| `POST` | `/api/chat` | Domanda; risposta SSE (`sources`, `token`, `done`, `error`) |
| `GET` | `/api/status` | Stato Ollama, indice, ingestione, watcher |
| `GET` | `/api/documents` | Elenco documenti indicizzati |
| `POST` | `/api/documents/upload` | Upload multiplo (multipart) |
| `POST` | `/api/documents/scan` | Rescan della cartella NAS |
| `POST` | `/api/documents/{id}/reindex` | Reindicizza un documento |
| `POST` | `/api/documents/reindex-all` | Reindicizza tutto |
| `DELETE` | `/api/documents/{id}` | Rimuove dall'indice |
| `GET/POST` | `/api/settings` | Legge / aggiorna le impostazioni |
| `GET` | `/api/models` | Modelli disponibili su Ollama |
| `GET` | `/health` | Healthcheck |
