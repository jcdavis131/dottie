/* Human-First v5 — Shared JS (zero-deps, idempotent, lifecycle-safe) */
window.DumbModel = window.DumbModel || {};
window.DumbModel.HumanV5 = (function() {
  const Selection = {
    _sel: null,
    _listeners: [],
    init() {
      // idempotent
      if (this._inited) return;
      this._inited = true;
      window.addEventListener('popstate', () => this._fromURL());
      this._fromURL();
    },
    update(id, opts = {}) {
      const push = opts.push !== false;
      this._sel = id;
      const url = new URL(window.location);
      if (id) url.searchParams.set('id', id);
      else url.searchParams.delete('id');
      if (push) history.pushState({}, '', url);
      else history.replaceState({}, '', url);
      this._listeners.forEach(fn => fn(id));
      document.dispatchEvent(new CustomEvent('hv5:selection', { detail: { id } }));
    },
    clear() { this.update(null); },
    onChange(fn) { this._listeners.push(fn); },
    _fromURL() {
      const id = new URLSearchParams(window.location.search).get('id');
      if (id !== this._sel) {
        this._sel = id;
        this._listeners.forEach(fn => fn(id));
        document.dispatchEvent(new CustomEvent('hv5:selection', { detail: { id } }));
      }
    },
    destroy() {
      this._listeners = [];
      this._inited = false;
    }
  };

  const Search = {
    init(inputSel, resultSel, dataFn) {
      const input = document.querySelector(inputSel);
      const results = document.querySelector(resultSel);
      if (!input || !results) return;
      let last = '';
      input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        if (q === last) return;
        last = q;
        const items = dataFn ? dataFn(q) : [];
        results.innerHTML = items.slice(0, 8).map(i =>
          `<button class="hv5-btn" data-id="${i.id}" style="width:100%;justify-content:flex-start;text-align:left">${i.name}</button>`
        ).join('');
        results.querySelectorAll('[data-id]').forEach(b => {
          b.addEventListener('click', () => {
            Selection.update(b.getAttribute('data-id'));
            results.innerHTML = '';
            input.value = '';
          });
        });
      });
    },
    destroy() {}
  };

  const Peers = {
    init(containerSel) {
      this.container = document.querySelector(containerSel);
    },
    update(peers) {
      if (!this.container) return;
      if (!peers || !peers.length) {
        this.container.innerHTML = '<div class="hv5-state hv5-state--empty">No comparable peers found for this selection.</div>';
        return;
      }
      this.container.innerHTML = peers.slice(0, 5).map(p => `
        <div class="hv5-peer hv5-select" data-peer="${p.id}">
          <div class="hv5-peer__name">${p.name || p.id}</div>
          <div class="hv5-peer__rel">${p.relationship || 'similar style'}</div>
          <div class="hv5-peer__sim"><b>Similar:</b> ${p.similarity || '—'}<br><b>Different:</b> ${p.difference || '—'}</div>
          <div class="hv5-peer__conf">confidence ${p.confidence || '—'}</div>
        </div>
      `).join('');
      this.container.querySelectorAll('[data-peer]').forEach(el => {
        el.addEventListener('click', () => Selection.update(el.getAttribute('data-peer')));
      });
    },
    destroy() { if (this.container) this.container.innerHTML = ''; }
  };

  const Evidence = {
    init(triggerSel, drawerSel) {
      const trigger = document.querySelector(triggerSel);
      const drawer = document.querySelector(drawerSel);
      if (!trigger || !drawer) return;
      trigger.addEventListener('click', () => {
        const open = drawer.getAttribute('data-open') === 'true';
        drawer.setAttribute('data-open', open ? 'false' : 'true');
        drawer.style.display = open ? 'none' : 'block';
      });
    },
    open(sel) { const d = document.querySelector(sel); if (d) { d.style.display = 'block'; d.setAttribute('data-open','true'); } },
    close(sel) { const d = document.querySelector(sel); if (d) { d.style.display = 'none'; d.setAttribute('data-open','false'); } },
    destroy() {}
  };

  const Share = {
    init(btnSel) {
      const btn = document.querySelector(btnSel);
      if (!btn) return;
      btn.addEventListener('click', async () => {
        const url = window.location.href;
        try {
          await navigator.clipboard.writeText(url);
          const prev = btn.textContent;
          btn.textContent = 'Copied';
          setTimeout(() => btn.textContent = prev, 1200);
        } catch {
          window.prompt('Copy this link:', url);
        }
      });
    },
    copy() { return navigator.clipboard.writeText(window.location.href); },
    destroy() {}
  };

  return { Selection, Search, Peers, Evidence, Share };
})();
