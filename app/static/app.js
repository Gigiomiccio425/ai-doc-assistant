/* Componente Alpine dell'interfaccia. Nessuna dipendenza oltre ad Alpine. */

function ragApp() {
  return {
    // ---- stato ------------------------------------------------------------
    tab: 'docs',
    sidebar: false,
    drag: false,
    busy: false,
    toast: '',
    input: '',
    streaming: false,
    controller: null,
    messages: [],
    docs: [],
    models: [],
    status: {},
    settings: {},
    samples: [
      'Quanto ho pagato di luce a novembre?',
      'Quali sono le clausole di disdetta del contratto di affitto?',
      'Riassumi le scadenze presenti nei miei documenti.',
      'Qual è l’IBAN indicato nell’ultima fattura?'
    ],

    // ---- avvio ------------------------------------------------------------
    async boot() {
      await Promise.all([this.loadStatus(), this.loadDocs(), this.loadSettings()]);
      // Poll leggero: mostra l'avanzamento dell'indicizzazione in background.
      setInterval(() => { this.loadStatus(); this.loadDocs(); }, 4000);
    },

    // ---- helper HTTP ------------------------------------------------------
    async api(path, options = {}) {
      const response = await fetch('/api' + path, options);
      if (!response.ok) {
        let detail = response.statusText;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return response.status === 204 ? null : response.json();
    },

    notify(message) {
      this.toast = message;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this.toast = ''; }, 3500);
    },

    // ---- dati -------------------------------------------------------------
    async loadStatus() { try { this.status = await this.api('/status'); } catch (_) {} },
    async loadDocs()   { try { this.docs = (await this.api('/documents')).documents; } catch (_) {} },
    async loadSettings() { this.settings = await this.api('/settings'); },

    async loadModels() {
      try {
        const data = await this.api('/models');
        this.models = data.models || [];
        this.notify(this.models.length ? `${this.models.length} modelli rilevati` : 'Nessun modello: Ollama non risponde');
      } catch (error) { this.notify('Errore: ' + error.message); }
    },

    async saveSettings() {
      this.busy = true;
      try {
        const result = await this.api('/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.settings)
        });
        this.settings = result.settings;
        this.notify(result.reindex_triggered
          ? 'Salvato. Indice azzerato: reindicizzazione avviata.'
          : 'Impostazioni salvate.');
        this.loadStatus();
      } catch (error) { this.notify('Errore: ' + error.message); }
      finally { this.busy = false; }
    },

    // ---- documenti --------------------------------------------------------
    async uploadFiles(fileList) {
      const files = Array.from(fileList || []);
      if (!files.length) return;
      const form = new FormData();
      files.forEach(f => form.append('files', f));

      this.busy = true;
      try {
        const result = await this.api('/documents/upload', { method: 'POST', body: form });
        let message = `${result.accepted.length} file in coda di indicizzazione`;
        if (result.rejected.length) message += ` · ${result.rejected.length} scartati`;
        this.notify(message);
        this.loadDocs();
      } catch (error) { this.notify('Upload fallito: ' + error.message); }
      finally { this.busy = false; }
    },

    async scanFolder() {
      this.busy = true;
      try {
        const result = await this.api('/documents/scan', { method: 'POST' });
        this.notify(`Scansione: ${result.found} file trovati, ${result.removed} rimossi`);
        this.loadDocs();
      } catch (error) { this.notify('Errore: ' + error.message); }
      finally { this.busy = false; }
    },

    async reindexAll() {
      if (!confirm('Reindicizzare tutti i documenti? Puo’ richiedere parecchi minuti.')) return;
      this.busy = true;
      try {
        await this.api('/documents/reindex-all', { method: 'POST' });
        this.notify('Reindicizzazione avviata');
        this.loadDocs();
      } catch (error) { this.notify('Errore: ' + error.message); }
      finally { this.busy = false; }
    },

    async reindexDoc(id) {
      try {
        await this.api(`/documents/${id}/reindex`, { method: 'POST' });
        this.notify('In coda per la reindicizzazione');
        this.loadDocs();
      } catch (error) { this.notify('Errore: ' + error.message); }
    },

    async removeDoc(doc) {
      const extra = doc.origin === 'upload' ? ' Il file caricato verra’ eliminato dal disco.' : '';
      if (!confirm(`Rimuovere "${doc.name}" dall’indice?${extra}`)) return;
      try {
        await this.api(`/documents/${doc.id}`, { method: 'DELETE' });
        this.docs = this.docs.filter(d => d.id !== doc.id);
        this.notify('Documento rimosso');
      } catch (error) { this.notify('Errore: ' + error.message); }
    },

    // ---- chat -------------------------------------------------------------
    async send() {
      const question = this.input.trim();
      if (!question || this.streaming) return;

      this.input = '';
      if (this.$refs.input) this.$refs.input.style.height = 'auto';
      this.messages.push({ role: 'user', content: question });

      // Il push memorizza l'oggetto GREZZO nell'array reattivo: mutare la
      // variabile locale non passerebbe dal proxy e non farebbe ridisegnare
      // nulla. Va ripreso dall'array, cosi' e' il proxy a essere mutato.
      this.messages.push({ role: 'assistant', content: '', sources: [], streaming: true, error: '' });
      const answer = this.messages[this.messages.length - 1];

      this.streaming = true;
      this.scrollDown();

      // Contesto conversazionale: solo i turni completati, senza le fonti.
      const history = this.messages
        .slice(0, -2)
        .filter(m => m.content)
        .map(m => ({ role: m.role, content: m.content }))
        .slice(-6);

      this.controller = new AbortController();
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, history }),
          signal: this.controller.signal
        });
        if (!response.ok) throw new Error('HTTP ' + response.status);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Gli eventi SSE sono separati da una riga vuota.
          const blocks = buffer.split('\n\n');
          buffer = blocks.pop();

          for (const block of blocks) {
            const event = (block.match(/^event: (.*)$/m) || [])[1];
            const raw = (block.match(/^data: (.*)$/m) || [])[1];
            if (!event || !raw) continue;
            const data = JSON.parse(raw);

            if (event === 'sources') answer.sources = data.sources;
            else if (event === 'token') { answer.content += data.t; this.scrollDown(); }
            else if (event === 'error') answer.error = data.message;
          }
        }
      } catch (error) {
        if (error.name !== 'AbortError') answer.error = error.message;
      } finally {
        answer.streaming = false;
        this.streaming = false;
        this.controller = null;
        this.scrollDown();
      }
    },

    stop() {
      if (this.controller) this.controller.abort();
    },

    scrollDown() {
      this.$nextTick(() => {
        const box = this.$refs.scroll;
        if (box) box.scrollTop = box.scrollHeight;
      });
    },

    autoGrow(el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 160) + 'px';
    },

    // ---- rendering --------------------------------------------------------
    fmtSize(bytes) {
      if (!bytes) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
      return (bytes / Math.pow(1024, i)).toFixed(i ? 1 : 0) + ' ' + units[i];
    },

    /* Markdown minimale. L'escape viene PRIMA di ogni sostituzione:
       il testo arriva dall'LLM e non deve mai poter iniettare HTML. */
    renderMarkdown(text) {
      if (!text) return '';
      let html = text.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      html = html.replace(/```[a-z]*\n?([\s\S]*?)```/g, (_, code) => `<pre>${code.trim()}</pre>`);
      html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
      html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/^\s*[-*]\s+(.+)$/gm, '• $1');
      html = html.replace(/\[(\d{1,2})\]/g, '<span class="cite">$1</span>');
      return html.replace(/\n/g, '<br>');
    }
  };
}
