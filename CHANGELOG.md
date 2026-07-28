# Changelog

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).
Il progetto segue il [Semantic Versioning](https://semver.org/lang/it/).

## [1.0.1] - 2026-07-28

### Corretto

- **La risposta della chat non compariva mai.** Il messaggio dell'assistente
  veniva inserito in `messages` e poi mutato tramite la variabile locale, che
  punta all'oggetto grezzo: le scritture non passavano dal proxy reattivo di
  Alpine e non ridisegnavano nulla. I token arrivavano dal backend e finivano
  in memoria senza mai essere mostrati, fonti comprese. Ora il riferimento
  viene ripreso dall'array subito dopo il push.
- **Installazione dall'App Store di ZimaOS/CasaOS.** I compose usavano
  l'interpolazione `${VAR:-default}`, che il parser dell'App Store rifiuta con
  `invalid interpolation format for services.app.volumes.[].source`. Tutti i
  valori sono ora letterali. Rimosso `.env.example`, che non serve più.
- Aggiunta una variante `docker-compose.external-ollama.yml` per chi ha già
  Ollama installato sul NAS.
- La CI ora valida i compose (`docker compose config`, campi `x-casaos`) e
  fallisce se ricompare un `${` in quei file.

L'immagine Docker non cambia: i compose non ne fanno parte.

## [1.0.0] - 2026-07-28

Prima release.

### Aggiunto

- **Chat RAG in streaming.** Endpoint `POST /api/chat` in Server-Sent Events:
  evento `sources` inviato prima dei token, così la UI mostra le fonti mentre
  la risposta è ancora in generazione.
- **Citazione delle fonti.** Il contesto passato al modello è numerato con
  nome file e pagina; la UI rende i marcatori `[n]` come badge e apre
  l'anteprima del chunk con punteggio di similarità.
- **Ingestione documenti.** PDF (con numero di pagina), DOCX, TXT, Markdown,
  CSV, LOG, JSON. Pipeline: loader LangChain → `RecursiveCharacterTextSplitter`
  → embedding Ollama in batch da 32 → ChromaDB persistente.
- **Sync cartella NAS.** Scansione completa all'avvio più watchdog ricorsivo con
  debounce di 5 s, per non indicizzare file ancora in copia via SMB. I file
  spariti dal disco vengono rimossi dall'indice.
- **Gestione indice.** Anagrafica SQLite con stato per documento
  (`pending`/`indexing`/`indexed`/`error`), reindicizzazione singola o totale,
  eliminazione. I file del NAS non vengono mai cancellati dal disco.
- **Impostazioni da UI.** URL Ollama, modello LLM, modello di embedding,
  dimensione chunk, overlap, top-k, temperatura, system prompt, watcher on/off.
  Il cambio del modello di embedding azzera l'indice e riaccoda tutto, perché
  spazi vettoriali diversi non sono confrontabili.
- **Upload dalla Web UI** con drag & drop multiplo.
- **Integrazione Zima OS/CasaOS.** `docker-compose.yml` con metadati `x-casaos`
  (icona, titolo e descrizione bilingui, categoria, port map, tips) e
  descrizioni per env, porte e volumi.
- **Container Ollama incluso** più servizio one-shot `ollama-pull` che scarica
  i modelli al primo avvio.
- **CI GitHub Actions.** Import check delle dipendenze reali e build pubblicata
  su `ghcr.io/gigiomiccio425/ai-doc-assistant`.

### Note

- `main` pubblica solo `linux/amd64`. I tag `v*` pubblicano anche `linux/arm64`.
- I PDF privi di livello di testo (scansioni) finiscono in stato `error`: serve
  un OCR a monte, non incluso.

[1.0.1]: https://github.com/Gigiomiccio425/ai-doc-assistant/releases/tag/v1.0.1
[1.0.0]: https://github.com/Gigiomiccio425/ai-doc-assistant/releases/tag/v1.0.0
