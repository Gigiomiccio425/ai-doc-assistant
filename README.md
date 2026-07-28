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
├── docker-compose.yml       # app + Ollama incluso, metadati x-casaos
├── docker-compose.external-ollama.yml   # solo app, per Ollama gia' presente
├── Dockerfile               # build multi-stage
├── requirements.txt
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

L'immagine viene costruita da GitHub Actions e pubblicata su GitHub Container
Registry — non serve compilare nulla sul NAS:

```
ghcr.io/gigiomiccio425/ai-doc-assistant:1.0.1
```

Il package è pubblico: nessun `docker login` necessario.

### Versioni

Il progetto segue il [Semantic Versioning](https://semver.org); ogni release ha
la sua voce nel [CHANGELOG](CHANGELOG.md).

| Tag | Contenuto | Architetture |
|---|---|---|
| `1.0.1` | release stabile, immutabile — **consigliato in produzione** | amd64 + arm64 |
| `1.0` | ultima patch della minor, si aggiorna da sola | amd64 + arm64 |
| `latest` | l'ultima build in ordine di tempo: release *oppure* commit su `main` | varia |
| `main`, `sha-<commit>` | build di sviluppo | amd64 |

`latest` è ambiguo per costruzione — segue sia le release sia i push su `main`,
quindi le architetture disponibili dipendono da quale delle due è arrivata per
ultima. Su un NAS usa sempre un tag di versione.

Il compose punta a un tag fisso: un riavvio del NAS non deve mai tirare giù una
versione nuova a sorpresa. Per aggiornare, cambia il tag nella riga `image:` e
fai `docker compose pull && docker compose up -d`.

`linux/arm64` viene costruito solo sui tag di release: sotto emulazione QEMU la
build è molto più lenta, e i target Zima (ZimaBoard, ZimaCube) sono x86.

## Installazione su Zima OS

Scegli il compose:

| File | Quando |
|---|---|
| `docker-compose.yml` | non hai Ollama: viene installato insieme all'app |
| `docker-compose.external-ollama.yml` | hai già Ollama sul NAS |

### Dall'App Store (consigliato)

App Store → *Custom Install* → incolla il contenuto del file scelto. Icona,
titolo, categoria e link della dashboard arrivano dai metadati `x-casaos`.

> **Niente `${VARIABILI}` nei compose.** Il parser dell'App Store non supporta
> l'interpolazione con default e risponde
> `invalid interpolation format ... You may need to escape any $ with another $`.
> Per questo i valori sono scritti in chiaro. Se cambi qualcosa, restano in
> chiaro.

Cosa modificare prima di incollare, se i tuoi percorsi differiscono:

- `- /DATA/Documents:/documents:ro` → la cartella da indicizzare
- `- "8088:8000"` → la porta della Web UI
- `LLM_MODEL` / `EMBED_MODEL` → i modelli da usare

### Da riga di comando

```bash
git clone https://github.com/Gigiomiccio425/ai-doc-assistant.git
cd ai-doc-assistant
nano docker-compose.yml      # percorsi, porta, modelli
docker compose pull && docker compose up -d
```

Con `docker-compose.yml` il servizio `ollama-pull` scarica `llama3.2` e
`nomic-embed-text` al primo avvio (alcuni GB) e poi termina:
`docker compose logs -f ollama-pull` per seguirlo.

Poi apri `http://<ip-del-nas>:8088`. Il package è pubblico, nessun
`docker login` necessario.

Il campo `icon` punta a un PNG pubblico su GitHub. Puoi sostituirlo con l'icona
servita dall'app stessa: `icon: http://<ip-del-nas>:8088/static/icon.svg`.

### Se Ollama è già installato

Usa il secondo compose: avvia solo l'app, senza scaricare di nuovo i modelli né
contendere la GPU.

```bash
docker compose -f docker-compose.external-ollama.yml up -d
```

Il default `OLLAMA_URL=http://host.docker.internal:11434` funziona sia con
Ollama nativo sull'host sia con Ollama in un container che pubblica la porta
11434 — l'`extra_hosts: host-gateway` nel compose fa risolvere quel nome
all'host anche su Linux. In alternativa scrivi l'IP del NAS al posto di
`host.docker.internal`.

**Ollama deve ascoltare su `0.0.0.0`**, non solo su `127.0.0.1`, altrimenti dal
container non è raggiungibile. Verifica dall'host:

```bash
curl http://127.0.0.1:11434/api/version
```

Se è un servizio systemd:

```bash
sudo systemctl edit ollama
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0"
sudo systemctl restart ollama
```

I modelli devono essere già scaricati — qui non c'è il servizio `ollama-pull`:

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

Se il tuo Ollama gira in un container che **non** pubblica la porta, nel compose
c'è un blocco commentato per collegare l'app alla sua rete e usare il nome del
container come host.

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

**Le variabili d'ambiente valgono solo al primo avvio.** `OLLAMA_URL`,
`LLM_MODEL` ed `EMBED_MODEL` sono i valori iniziali: appena salvi qualcosa dalle
impostazioni della UI, l'app scrive `/data/settings.json` e da quel momento è
quel file a comandare. Se cambi la variabile nel compose e non vedi effetto,
modificala dalla UI oppure cancella `settings.json` e riavvia il container.

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
