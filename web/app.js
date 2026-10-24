/* Interface do assistente: núcleo (estado, eventos em tempo real, barra lateral, consumo, aprovações e chat).
   Sem bibliotecas e sem etapa de build. Todo texto vem da API e entra no DOM por textContent;
   só o Markdown passa por MD.render (que escapa tudo antes). */
(function () {
  "use strict";

  const A = (window.A = {
    S: {
      state: null, convs: [], convId: null, conv: null, live: {}, view: "home", pendingPrompt: "", approvals: [],
      attachments: [], speak: false, online: false, tasks: [], sidebarOpen: false,
    },
    views: {},
  });
  const S = A.S;

  // ------------------------------------------------------------------ utilidades

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "html") el.innerHTML = v;            // só para MD.render e ícones fixos
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else if (k === "checked") el.checked = !!v;
      else if (k === "disabled") el.disabled = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const ICON = {
    plus: '<path d="M12 5v14M5 12h14"/>', chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    tasks: '<path d="M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>', more: '<circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/>',
    clip: '<path d="M21 12.5l-8.5 8.5a5.5 5.5 0 0 1-7.8-7.8L13.5 4.4a3.7 3.7 0 0 1 5.2 5.2l-8.8 8.8a1.8 1.8 0 0 1-2.6-2.6l8-8"/>',
    mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    speaker: '<path d="M4 9v6h4l5 4V5L8 9zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    bolt: '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    box: '<path d="M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8"/>',
    home: '<path d="M3 11l9-8 9 8M5 10v10h14V10M10 20v-6h4v6"/>',
    bell: '<path d="M18 8a6 6 0 10-12 0c0 7-3 8-3 8h18s-3-1-3-8M13.7 21a2 2 0 01-3.4 0"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.5-3.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14.5 3.5L20 15M20 20v-5h-5"/>',
  };
  function icon(name, size) {
    const s = size || 18;
    return h("span", { class: "ico", html: `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name] || ""}</svg>` });
  }

  async function api(method, url, body, opts) {
    const init = { method, headers: {}, credentials: "same-origin" };
    if (body !== undefined && body !== null) {
      if (body instanceof Blob) { init.body = body; init.headers["Content-Type"] = body.type || "application/octet-stream"; }
      else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
    }
    let r;
    try { r = await fetch(url, init); } catch (e) { throw new Error("Sem conexão com o app. Ele ainda está aberto no computador?"); }
    if (r.status === 401) { location.href = "/login"; throw new Error("Sessão expirada."); }
    let data = {};
    try { data = await r.json(); } catch (e) { /* resposta vazia */ }
    if (!r.ok) { const err = new Error(data.error || `Erro ${r.status}`); err.status = r.status; throw err; }
    return data;
  }

  function toast(text, kind) {
    let box = document.querySelector(".toasts");
    if (!box) { box = h("div", { class: "toasts", role: "status" }); document.body.append(box); }
    const t = h("div", { class: "toast " + (kind || "") , text });
    box.append(t);
    setTimeout(() => t.remove(), kind === "error" ? 7000 : 4000);
  }

  function modal({ title, body, actions, onClose, wide }) {
    const bg = h("div", { class: "modal-bg" });
    const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); if (onClose) onClose(); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title });
    if (wide) box.style.width = "min(720px,100%)";
    box.append(h("h3", { text: title }), body, h("div", { class: "row-btns", style: "margin-top:16px;justify-content:flex-end" }, (actions || []).map((a) =>
      h("button", { class: "btn " + (a.kind || ""), type: "button", text: a.label, onclick: async (ev) => {
        if (a.keep) { await a.run(close, ev.currentTarget); return; }
        const r = a.run ? await a.run(close, ev.currentTarget) : undefined;
        if (r !== false) close();
      } }))));
    bg.append(box);
    bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
    document.addEventListener("keydown", onKey);
    document.body.append(bg);
    const first = box.querySelector("input,textarea,select");
    if (first) first.focus();
    return close;
  }

  function confirmBox(title, text, okLabel, danger) {
    return new Promise((resolve) => {
      let done = false;
      modal({ title, body: h("p", { style: "margin:0;color:var(--muted)", text }), onClose: () => { if (!done) resolve(false); },
        actions: [{ label: "Cancelar" }, { label: okLabel || "Confirmar", kind: danger ? "danger" : "primary", run: () => { done = true; resolve(true); } }] });
    });
  }

  function menuAt(anchor, items) {
    document.querySelectorAll(".menu").forEach((m) => m.remove());
    const r = anchor.getBoundingClientRect();
    const m = h("div", { class: "menu", role: "menu" }, items.map((it) =>
      h("button", { type: "button", role: "menuitem", class: it.danger ? "danger" : "", onclick: () => { m.remove(); it.run(); } }, it.icon ? icon(it.icon, 16) : null, it.label)));
    m.style.top = Math.min(r.bottom + 4, innerHeight - items.length * 40 - 16) + "px";
    m.style.left = Math.max(8, Math.min(r.left, innerWidth - 210)) + "px";
    document.body.append(m);
    const off = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("mousedown", off, true); } };
    setTimeout(() => document.addEventListener("mousedown", off, true), 0);
  }

  const F = (A.fmt = {
    num: (n) => new Intl.NumberFormat("pt-BR").format(n),
    dur(sec) {
      sec = Math.max(0, Math.round(sec));
      const d = Math.floor(sec / 86400), hh = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
      if (d) return `${d} d ${hh} h`;
      if (hh) return `${hh} h ${String(m).padStart(2, "0")} min`;
      if (m) return `${m} min`;
      return "menos de 1 min";
    },
    clock: (epoch) => new Date(epoch * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }),
    dayTime(epoch) {
      const d = new Date(epoch * 1000), today = new Date();
      const same = d.toDateString() === today.toDateString();
      const tomorrow = new Date(today.getTime() + 86400000).toDateString() === d.toDateString();
      return (same ? "hoje" : tomorrow ? "amanhã" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })) + " às " + F.clock(epoch);
    },
    ago(epoch) {
      const s = Date.now() / 1000 - epoch;
      if (s < 60) return "agora";
      if (s < 3600) return `há ${Math.floor(s / 60)} min`;
      if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
      return `há ${Math.floor(s / 86400)} d`;
    },
    greeting() {
      const hr = new Date().getHours();
      return hr < 5 ? "Boa madrugada" : hr < 12 ? "Bom dia" : hr < 18 ? "Boa tarde" : "Boa noite";
    },
  });
  A.h = h; A.icon = icon; A.api = api; A.toast = toast; A.modal = modal; A.confirm = confirmBox; A.menuAt = menuAt;

  function store(key, value) {
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { return null; }
    return null;
  }

  // ------------------------------------------------------------------ estado e eventos

  async function refreshState() {
    try {
      S.state = await api("GET", "/api/state");
      S.approvals = S.state.approvals || [];
      S.live_ids = new Set(S.state.running_chats || []);
      paintNav(); paintUsage(); paintApprovals(); paintConvList(); S.skew = ((S.state.checks || {}).now || Date.now() / 1000) - Date.now() / 1000; tickChecks();
    } catch (e) { /* sem conexão: o indicador já mostra */ }
  }
  A.refreshState = refreshState;

  async function refreshConvs() {
    try { S.convs = (await api("GET", "/api/conversations")).conversations; paintConvList(); } catch (e) { /* ignora */ }
  }

  function connect() {
    const es = new EventSource("/api/events");
    es.addEventListener("hello", () => { setOnline(true); refreshState(); refreshConvs(); if (S.convId) loadConv(S.convId, true); if (A.views[S.view] && A.views[S.view].resync) A.views[S.view].resync(); });
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { /* evento inválido */ } };
    es.onerror = () => setOnline(false);
  }
  function setOnline(on) {
    S.online = on;
    const d = document.querySelector(".status-dot"), t = document.querySelector("#conn-text");
    if (d) d.className = "status-dot " + (on ? "on" : "off");
    if (t) t.textContent = on ? "Conectado" : "Reconectando…";
  }

  function onEvent(e) {
    if (A.pet) A.pet.onEvent(e);
    if (e.type === "toast") return toast(e.text, e.kind);
    if (e.type === "reminder") { showReminder(e); return; }
    if (e.type === "briefing") { if (S.view === "home" && A.views.home) A.views.home.refresh(); return; }
    if (e.type === "reminders") {
      if (S.state) { S.state.reminders = { count: e.count, ringing: e.ringing }; paintNav(); }
      if (S.view === "reminders" && A.views.reminders) A.views.reminders.refresh();
      return;
    }
    if (e.type === "tracking") {
      if (S.state) { S.state.tracking = { ...(S.state.tracking || {}), unread: e.unread, configured: e.configured }; paintNav(); }
      if (S.view === "tracking" && A.views.tracking) A.views.tracking.refresh();
      return;
    }
    if (e.type === "checks") { if (S.state) { S.state.checks = e.checks; S.skew = e.checks.now - Date.now() / 1000; tickChecks(); if (S.view === "automation" && A.views.automation) A.views.automation.paint(); if (document.querySelector("#usage .pop")) paintUsage(); } return; }
    if (e.type === "voice") { if (S.state) { S.state.voice = e.voice; paintWake(); (A.voiceListeners || []).forEach((f) => f()); } return; }
    if (e.type === "voice_command") {
      S.voiceCid = e.conversation_id;
      openConv(e.conversation_id).then(() => { refreshConvs(); });
      return;
    }
    if (e.type === "usage") { if (S.state) { S.state.usage = e.usage; paintUsage(); } return; }
    if (e.type === "model_switch") {
      toast(e.text, "ok");
      Object.keys(S.live).forEach((cid) => { S.live[cid].info = e.text; });
      if (liveFor()) scheduleLive();
      return;
    }
    if (e.type === "task_update" || e.type === "task_removed") {
      if (e.type === "task_update") {
        const i = S.tasks.findIndex((t) => t.id === e.task.id);
        if (i >= 0) S.tasks[i] = e.task; else S.tasks.unshift(e.task);
        if (S.state) { recount(); }
      } else S.tasks = S.tasks.filter((t) => t.id !== e.id);
      paintNav();
      if (A.views[S.view] && A.views[S.view].onTask) A.views[S.view].onTask(e);
      return;
    }
    if (e.scope === "task") {
      trackApproval(e);
      if (A.views.tasks && A.views.tasks.onTaskEvent) A.views.tasks.onTaskEvent(e);
      return;
    }
    if (e.scope === "chat") { trackApproval(e); onChatEvent(e); }
  }

  function recount() {
    const counts = {};
    S.tasks.forEach((t) => { counts[t.status] = (counts[t.status] || 0) + 1; });
    S.state.task_counts = counts;
  }

  function trackApproval(e) {
    if (e.type === "confirm") {
      if (!S.approvals.some((a) => a.id === e.id)) S.approvals.push({ id: e.id, tool: e.tool, category: e.category, categoryLabel: e.categoryLabel, risk: e.risk, summary: e.summary, task: e.task || null, conversation_id: e.conversation_id || null });
      paintApprovals(); paintNav();
    } else if (e.type === "tool_end" && e.id) {
      const n = S.approvals.length;
      S.approvals = S.approvals.filter((a) => a.id !== e.id);
      if (n !== S.approvals.length) { paintApprovals(); paintNav(); }
    } else if (e.type === "done") {
      const n = S.approvals.length;
      S.approvals = S.approvals.filter((a) => a.conversation_id !== e.conversation_id);
      if (n !== S.approvals.length) paintApprovals();
    }
  }

  // ------------------------------------------------------------------ estrutura (barra lateral e topo)

  const NAV = [["home", "Início", "home"], ["chat", "Conversa", "chat"], ["tasks", "Tarefas", "tasks"], ["reminders", "Lembretes", "bell"], ["tracking", "Encomendas", "box"], ["automation", "Automação", "bolt"], ["activity", "Histórico", "clock"], ["memory", "Memória", "brain"], ["settings", "Ajustes", "gear"]];

  function buildShell() {
    const app = document.getElementById("app");
    app.replaceChildren();
    const nav = h("nav", { class: "nav", "aria-label": "Seções" }, NAV.map(([id, label, ic]) =>
      h("button", { type: "button", "data-view": id, onclick: () => go(id) }, icon(ic), h("span", { text: label, style: "flex:1;text-align:left" }), h("span", { class: "badge hidden", "data-badge": id }))));
    const side = h("aside", { class: "sidebar", id: "sidebar" },
      h("div", { class: "brand" }, h("span", { class: "brand-mark" }), "Assistente"),
      h("button", { class: "btn-new", type: "button", onclick: newChat }, icon("plus", 16), "Nova conversa"),
      nav,
      h("div", { class: "side-title", text: "Conversas" }),
      h("div", { class: "conv-list", id: "conv-list" }),
      h("div", { id: "pet-slot" }),
      h("div", { class: "side-checks", id: "side-checks", title: "Verificações automáticas (clique para ver os detalhes)", onclick: () => { const b = document.querySelector(".usage-pill"); if (b) b.click(); } }),
      h("div", { class: "side-foot" }, h("span", { class: "status-dot off" }), h("span", { id: "conn-text", text: "Conectando…", style: "font-size:13px;color:var(--muted)" })));
    const top = h("header", { class: "topbar" },
      h("button", { class: "icon-btn menu-btn", type: "button", "aria-label": "Abrir menu", onclick: () => toggleSidebar(true) }, icon("menu")),
      h("h1", { id: "page-title", text: "Nova conversa" }),
      h("div", { id: "pet-slot-mini" }),
      h("button", { class: "icon-btn mic-btn hidden", id: "wake-btn", type: "button", onclick: toggleWake }, icon("mic")),
      h("button", { class: "icon-btn", id: "speak-btn", type: "button", title: "Ler respostas em voz alta", "aria-label": "Ler respostas em voz alta", "aria-pressed": "false", onclick: toggleSpeak }, icon("speaker")),
      h("div", { class: "usage", id: "usage" }));
    const shell = h("div", { class: "shell", id: "shell" }, side, h("div", { class: "overlay", onclick: () => toggleSidebar(false) }),
      h("main", { class: "main" }, top, h("div", { id: "content", style: "display:flex;flex-direction:column;flex:1;min-height:0" })));
    app.append(shell, h("div", { class: "approvals-bar", id: "approvals", "aria-live": "assertive" }));
    paintSpeak();
    paintWake();
    if (A.pet) A.pet.mount();
  }

  function toggleSidebar(open) {
    S.sidebarOpen = open;
    document.getElementById("shell").classList.toggle("open", open);
  }

  function paintNav() {
    document.querySelectorAll(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.view === S.view ? "page" : "false"));
    const c = (S.state && S.state.task_counts) || {};
    const active = (c.running || 0) + (c.queued || 0);
    const waiting = (c.waiting_approval || 0) + (c.waiting_user || 0);
    const rb = document.querySelector('[data-badge="reminders"]');
    if (rb) { const n = (S.state && S.state.reminders && S.state.reminders.ringing) || 0; rb.textContent = n || ""; rb.classList.toggle("hidden", !n); }
    const tb = document.querySelector('[data-badge="tracking"]');
    if (tb) { const n = (S.state && S.state.tracking && S.state.tracking.unread) || 0; tb.textContent = n || ""; tb.classList.toggle("hidden", !n); }
    const badge = document.querySelector('[data-badge="tasks"]');
    if (badge) {
      const n = waiting || active;
      badge.textContent = n || "";
      badge.classList.toggle("hidden", !n);
      badge.classList.toggle("soft", !waiting);
    }
  }

  function paintConvList() {
    const box = document.getElementById("conv-list");
    if (!box) return;
    box.replaceChildren();
    if (!S.convs.length) { box.append(h("div", { class: "side-title", style: "text-transform:none", text: "Nenhuma conversa ainda." })); return; }
    for (const c of S.convs) {
      const running = !!S.live[c.id];
      const row = h("div", { class: "conv" + (c.id === S.convId && S.view === "chat" ? " active" : ""), tabindex: "0", role: "button", onclick: () => openConv(c.id), onkeydown: (ev) => { if (ev.key === "Enter") openConv(c.id); } },
        h("span", { class: "t", text: c.title || "Conversa" }), running ? h("span", { class: "dot", title: "Respondendo" }) : null,
        h("button", { class: "more", type: "button", "aria-label": "Opções da conversa", onclick: (ev) => { ev.stopPropagation(); convMenu(ev.currentTarget, c); } }, icon("more", 16)));
      box.append(row);
    }
  }

  function convMenu(anchor, c) {
    menuAt(anchor, [
      { label: "Renomear", icon: "file", run: () => renameConv(c) },
      { label: "Resumir e continuar", icon: "refresh", run: () => refreshConv(c.id) },
      { label: "Apagar", danger: true, icon: "x", run: () => deleteConv(c) },
    ]);
  }

  async function renameConv(c) {
    const input = h("input", { type: "text", value: c.title, maxlength: "80", "aria-label": "Novo título" });
    modal({ title: "Renomear conversa", body: input, actions: [{ label: "Cancelar" }, { label: "Salvar", kind: "primary", run: async () => {
      try { await api("POST", `/api/conversations/${c.id}/rename`, { title: input.value }); await refreshConvs(); if (S.convId === c.id) setTitle(input.value); } catch (e) { toast(e.message, "error"); return false; }
    } }] });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.closest(".modal").querySelector(".btn.primary").click(); });
  }

  async function deleteConv(c) {
    if (!(await confirmBox("Apagar conversa?", `"${c.title}" será apagada com os arquivos anexados. Isso não pode ser desfeito.`, "Apagar", true))) return;
    try {
      await api("DELETE", `/api/conversations/${c.id}`);
      if (S.convId === c.id) { S.convId = null; S.conv = null; if (S.view === "chat") renderView(); }
      refreshConvs();
    } catch (e) { toast(e.message, "error"); }
  }

  async function refreshConv(id) {
    toast("Resumindo a conversa…");
    try { const r = await api("POST", `/api/conversations/${id}/refresh`); await refreshConvs(); openConv(r.id); toast("Pronto: conversa nova começando do resumo.", "ok"); }
    catch (e) { toast(e.message, "error"); }
  }

  function setTitle(t) { const el = document.getElementById("page-title"); if (el) el.textContent = t; }

  // ------------------------------------------------------------------ consumo (cota)

  const shortModel = (m) => String(m || "—").replace(/^gemini-/, "");
  const currentModel = (u) => (u.models || []).find((m) => m.model === u.current_model) || (u.models || [])[0];

  function paintUsage() {
    const box = document.getElementById("usage");
    if (!box || !S.state) return;
    const u = S.state.usage;
    const cur = currentModel(u);
    const pct = cur ? Math.min(100, Math.round(cur.requests_day.percent)) : Math.min(100, Math.round(u.requests_day.percent));
    const out = cur && (cur.status === "esgotado" || cur.status === "cheio");
    const cls = out || pct >= 100 ? "err" : pct >= 80 ? "warn" : "";
    const r = 9, c = 2 * Math.PI * r;
    const open = box.querySelector(".pop");
    const label = cur ? `${shortModel(cur.model)} · ${F.num(cur.requests_day.used)}/${F.num(cur.requests_day.limit)}` : `${F.num(u.requests_day.remaining)} restantes`;
    box.replaceChildren(
      h("button", { class: "usage-pill", type: "button", "aria-expanded": open ? "true" : "false", "aria-label": `Modelo em uso: ${cur ? cur.model : "—"}. ${pct}% da cota diária dele usada. Abrir detalhes`, onclick: () => togglePop() },
        h("span", { html: `<svg class="ring ${cls}" viewBox="0 0 24 24" aria-hidden="true"><circle class="bg" cx="12" cy="12" r="${r}"/><circle class="fg" cx="12" cy="12" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct / 100)}"/></svg>` }),
        h("span", { class: "lbl", text: label })));
    if (open) { const keep = open.scrollTop; box.append(usagePop()); box.querySelector(".pop").scrollTop = keep; }
  }

  function togglePop() {
    const box = document.getElementById("usage");
    const open = box.querySelector(".pop");
    if (open) { open.remove(); return; }
    box.append(usagePop());
    const off = (e) => {
      if (document.querySelector(".modal-bg")) return;
      if (!box.contains(e.target)) { const p = box.querySelector(".pop"); if (p) p.remove(); document.removeEventListener("mousedown", off, true); }
    };
    setTimeout(() => document.addEventListener("mousedown", off, true), 0);
  }

  // ------------------------------------------------------------------ verificações automáticas (e-mail, agenda, encomendas)

  const pad2 = (n) => String(n).padStart(2, "0");
  const nowS = () => Date.now() / 1000 + (S.skew || 0);
  function countdown(ts) {
    const sec = Math.round(ts - nowS());
    if (sec <= 0) return "agora";
    if (sec >= 3600) return F.dur(sec);
    return `${Math.floor(sec / 60)}:${pad2(sec % 60)}`;
  }
  function tickSince() {
    document.querySelectorAll("[data-since]").forEach((el) => {
      const s = Math.max(0, Math.round((Date.now() - Number(el.dataset.since)) / 1000));
      el.textContent = s >= 5 ? ` · ${s} s` : "";
      el.classList.toggle("slow", s >= 30);
    });
  }
  function tickChecks() {
    tickSince();
    document.querySelectorAll("[data-next]").forEach((el) => { el.textContent = countdown(Number(el.dataset.next)); });
    const box = document.getElementById("side-checks");
    if (!box || !S.state) return;
    const c = S.state.checks;
    if (!c || !c.jobs || !c.jobs.length) { box.textContent = ""; return; }
    const mail = c.jobs.find((j) => j.id === "triagem") || c.jobs[0];
    if (!c.running) box.textContent = "E-mails: ligue o Google em Ajustes";
    else if (mail.running) box.textContent = "Verificando os e-mails…";
    else if (mail.next_ts) box.textContent = `Próxima checagem de e-mail em ${countdown(mail.next_ts)}`;
    else box.textContent = "";
  }
  A.countdown = countdown;

  // ------------------------------------------------------------------ lembretes e alarmes (banner + som)

  const ring = (() => {
    let ctx = null, timer = null, n = 0;
    const beep = () => {
      try {
        ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
        [[880, 0], [1175, 0.18], [1568, 0.36]].forEach(([f, t]) => {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.type = "sine"; o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
          const t0 = ctx.currentTime + t; g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
          o.start(t0); o.stop(t0 + 0.18);
        });
      } catch (e) { /* sem áudio */ }
    };
    return {
      start(loop) { n += 1; beep(); if (loop && !timer) timer = setInterval(beep, 2500); },
      stop() { n = Math.max(0, n - 1); if (!n && timer) { clearInterval(timer); timer = null; } },
    };
  })();

  function showReminder(e) {
    const it = e.item, bar = document.getElementById("approvals");
    if (!bar) return;
    ring.start(e.alarm);
    let done = false;
    const finish = () => { if (done) return; done = true; ring.stop(); card.remove(); };
    const act = async (path, body) => { try { await api("POST", `/api/reminders/${it.id}/${path}`, body || {}); } catch (err) { toast(err.message, "error"); } finish(); };
    const snooze = (m, label) => h("button", { class: "btn sm", type: "button", text: label, onclick: () => act("snooze", { minutes: m }) });
    const card = h("div", { class: "confirm reminder-card" + (e.alarm ? " alarm" : ""), role: "alertdialog", "aria-label": e.alarm ? "Alarme" : "Lembrete" },
      h("div", { class: "rc-title", text: (e.alarm ? "⏰ Alarme" : "🔔 Lembrete") + (e.late_s > 120 ? " (atrasado)" : "") }),
      h("div", { class: "rc-text", text: it.texto }),
      h("div", { class: "row-btns", style: "margin-top:10px" },
        h("button", { class: "btn primary sm", type: "button", text: "Dispensar", onclick: () => act("dismiss") }),
        snooze(5, "+5 min"), snooze(10, "+10 min"), snooze(60, "+1 h")));
    bar.append(card);
    if (!e.ringing) setTimeout(finish, 20000);       // lembrete recorrente (só avisa): some sozinho
    try { if ("Notification" in window && Notification.permission === "granted") new Notification(e.alarm ? "Alarme" : "Lembrete", { body: it.texto }); } catch (err) { /* ignora */ }
  }
  A.checkRow = (j) => checkRow(j);
  function checkRow(j) {
    const status = j.running ? h("span", { class: "chk-now", text: "Verificando agora…" })
      : !j.next_ts && j.note ? h("span", { text: j.note })
      : j.next_ts ? h("span", {}, "Próxima ", j.every === "todo dia" ? "" : "em ", h("b", { "data-next": String(j.next_ts), text: countdown(j.next_ts) }), ` (${F.dayTime(j.next_ts)})`)
      : h("span", { text: "Parada" });
    const last = j.last_ts ? h("div", { class: "chk-last" }, `Última ${F.ago(j.last_ts - (S.skew || 0))}: `, h("span", { class: j.last_ok === false ? "bad" : "", text: j.last_text || (j.last_ok ? "ok" : "") }))
      : h("div", { class: "chk-last", text: "Ainda não verificou desde que o app abriu." });
    return h("div", { class: "chk" },
      h("div", { class: "chk-top" }, h("b", { text: j.label }), h("span", { class: "chk-every", text: j.every })),
      h("div", { class: "chk-next" }, status), last,
      j.can_run && !j.running && j.next_ts ? h("button", { class: "btn sm", type: "button", text: "Verificar agora", onclick: async () => { try { await api("POST", j.run_url || "/api/automation/run", { job: j.id }); } catch (e) { toast(e.message, "error"); } } }) : null);
  }
  function checksBlock() {
    const c = S.state.checks || { jobs: [] };
    const box = h("div", { class: "checks" }, h("h4", { text: "Verificações automáticas" }));
    if (!c.running) {
      box.append(h("p", { class: "desc", style: "margin:0", text: c.connected ? "A rotina de e-mails e agenda está parada. Reabra o app para ligar." : "Não estou verificando e-mails nem agenda: o Google ainda não está conectado (Ajustes › Gmail e Agenda)." }));
    }
    (c.jobs || []).filter((j) => c.running || j.id !== "triagem" && j.id !== "agenda" && j.id !== "resumo").forEach((j) => box.append(checkRow(j)));
    return box;
  }

  function bar(pct, label) {
    const p = Math.min(100, Math.round(pct));
    return h("div", { class: "bar " + (p >= 100 ? "err" : p >= 80 ? "warn" : ""), role: "progressbar", "aria-valuenow": p, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": label }, h("i", { style: `width:${p}%` }));
  }

  const STATUS_CLASS = { em_uso: "running", disponivel: "done", esgotado: "failed", espera: "waiting_user", cheio: "waiting_user" };
  const SRC = { Google: "limite confirmado pelo Google", "seu config": "limite do seu config", estimado: "limite estimado (ainda não confirmado)" };

  function modelCard(m, resetLeft) {
    const rd = m.requests_day;
    const card = h("div", { class: "mcard" + (m.in_use ? " active" : "") },
      h("div", { class: "mhead" }, h("code", { text: m.model }), h("span", { class: "st-chip " + (STATUS_CLASS[m.status] || ""), text: m.status === "em_uso" ? "Em uso" : m.status === "disponivel" ? "Disponível" : m.status === "esgotado" ? "Esgotado hoje" : m.status === "espera" ? "Aguardando" : "No limite" })),
      h("div", { class: "meter", style: "margin:8px 0 6px" }, h("div", { class: "row" }, h("span", { text: "Requisições hoje" }), h("b", { text: `${F.num(rd.used)} de ${F.num(rd.limit)} · restam ${F.num(rd.remaining)}` })), bar(rd.percent, "Requisições hoje de " + m.model)),
      h("div", { class: "mfine" },
        h("span", { text: `Último minuto: ${m.requests_minute.used}/${m.requests_minute.limit} req.` }),
        h("span", { text: `Tokens no minuto: ${F.num(m.tokens_minute.used)}/${F.num(m.tokens_minute.limit)}` }),
        h("span", { text: `Tokens hoje: ${F.num(m.tokens_day)}` }),
        m.rejections_day ? h("span", { class: "bad", text: `Recusas do Google hoje: ${m.rejections_day}` }) : null),
      h("div", { class: "mfine faint" }, h("span", { text: SRC[rd.limit_source] || rd.limit_source }), m.calibrated ? h("span", { text: "· ajustado pelo painel" }) : null));
    if (m.status === "esgotado") card.append(h("div", { class: "mnote", text: `O Google recusou: a cota diária deste modelo acabou. Volta em ${F.dur(resetLeft)}.` }));
    else if (m.status === "cheio") card.append(h("div", { class: "mnote", text: rd.limit_source === "Google" ? "Chegou ao limite real deste modelo (confirmado pelo Google): as próximas chamadas devem ser recusadas e o app troca de modelo." : "A contagem chegou ao limite estimado. O Google ainda não recusou; se estiver impreciso, use “Ajustar”." }));
    else if (m.status === "espera") card.append(h("div", { class: "mnote", text: m.status_label }));
    card.append(h("button", { class: "btn sm", type: "button", text: "Ajustar com o painel do Google", onclick: () => calibrateModal(m) }));
    return card;
  }

  function calibrateModal(m) {
    const input = h("input", { type: "number", min: "0", value: String(m.requests_day.used), "aria-label": "Requisições hoje no painel do Google" });
    modal({ title: "Ajustar " + m.model, body: h("div", {},
      h("p", { class: "desc", style: "margin-top:0", text: "Abra aistudio.google.com/rate-limit (ou o painel da API), ache este modelo e digite quantas requisições ele mostra hoje. O app soma a diferença à contagem dele. Serve para quando você usa a mesma chave em outro lugar." }),
      h("label", { class: "f" }, h("span", { text: "Requisições hoje, segundo o painel do Google" }), input)),
      actions: [{ label: "Cancelar" }, { label: "Ajustar", kind: "primary", run: async () => {
        try { const u = await api("POST", "/api/usage/calibrate", { model: m.model, requests: Number(input.value) }); S.state.usage = u; paintUsage(); toast("Contagem ajustada.", "ok"); }
        catch (e) { toast(e.message, "error"); return false; }
      } }] });
  }

  function usagePop() {
    const u = S.state.usage;
    const left = Math.max(0, u.reset_epoch - Date.now() / 1000);
    const cur = currentModel(u);
    const pop = h("div", { class: "pop wide", role: "dialog", "aria-label": "Consumo por modelo" },
      h("h3", { text: "Consumo por modelo" }),
      h("div", { class: "now" }, h("span", { class: "orb-s" }), h("span", {}, "Modelo em uso agora: ", h("b", { text: cur ? cur.model : "nenhum ainda" }))));
    if ((u.models || []).length && u.models.every((m) => m.status === "esgotado")) pop.append(h("div", { class: "alert err", text: `Todos os modelos foram recusados pelo Google hoje. Tarefas pausam e voltam sozinhas quando renovar (em ${F.dur(left)}).` }));
    const seen = store("usage_notice_seen") === "1";
    const truth = h("details", { class: "truth" }, h("summary", {}, h("b", { text: "Contagem real, feita a cada chamada — como funciona" })),
      h("ul", {},
        h("li", { text: "Cada requisição que este app faz a cada modelo é contada na hora, junto com os tokens." }),
        h("li", { text: "“Esgotado” e os limites reais vêm do próprio Google: o app só marca quando ele recusa a chamada." }),
        h("li", { text: "Limitação: o app não enxerga uso da mesma chave fora dele (o painel do Google pode mostrar mais). Use “Ajustar” para igualar." })));
    if (!seen) { truth.open = true; truth.addEventListener("toggle", () => store("usage_notice_seen", "1")); }
    pop.append(truth);
    (u.models || []).forEach((m) => pop.append(modelCard(m, left)));
    pop.append(checksBlock());
    pop.append(h("div", { class: "reset" }, icon("clock", 16), h("span", {}, "A cota diária renova em ", h("b", { text: F.dur(left) }), ` (${F.dayTime(u.reset_epoch)})`)));
    if ((u.switches || []).length) {
      pop.append(h("div", { class: "sw-title", text: "Trocas de modelo recentes" }),
        h("ul", { class: "sw" }, u.switches.map((s) => h("li", {}, h("time", { text: F.clock(s.t) }), `${s.from ? shortModel(s.from) + " → " : ""}${shortModel(s.to)}`, h("span", { class: "why", text: " · " + s.reason })))));
    }
    return pop;
  }

  // ------------------------------------------------------------------ aprovações

  function paintApprovals() {
    const box = document.getElementById("approvals");
    if (!box) return;
    box.replaceChildren();
    const win = (S.state && S.state.permission_window_minutes) || 10;
    for (const a of S.approvals) {
      const inTask = !!a.task;
      const always = inTask ? "Permitir nesta tarefa" : `Permitir por ${win} min`;
      const canAlways = a.category !== "regra" && (inTask || !["tela", "entrada", "comandos", "git_push", "regra"].includes(a.category));
      const taskTitle = inTask ? ((S.tasks.find((t) => t.id === a.task) || {}).title || "tarefa") : "";
      box.append(h("div", { class: "confirm " + (a.risk === "high" ? "high" : ""), role: "alertdialog", "aria-label": "Pedido de permissão" },
        h("div", { class: "top" }, h("span", { class: "risk " + a.risk, text: a.risk === "high" ? "Risco alto" : a.risk === "medium" ? "Risco médio" : "Risco baixo" }), h("span", { text: a.categoryLabel || "Permissão" }), inTask ? h("span", { style: "color:var(--faint)", text: "· " + taskTitle }) : null),
        h("div", { class: "sum", text: a.summary }),
        h("div", { class: "row-btns" },
          h("button", { class: "btn primary sm", type: "button", text: "Permitir", onclick: () => answer(a, "allow") }),
          canAlways ? h("button", { class: "btn sm", type: "button", text: always, onclick: () => answer(a, "always") }) : null,
          h("button", { class: "btn sm danger", type: "button", text: "Negar", onclick: () => answer(a, "deny") }))));
    }
  }

  async function answer(a, ans) {
    S.approvals = S.approvals.filter((x) => x.id !== a.id);
    paintApprovals();
    try { await api("POST", "/api/approve", { id: a.id, answer: ans }); }
    catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------------ voz (saída)

  function paintSpeak() {
    const b = document.getElementById("speak-btn");
    if (!b) return;
    if (!("speechSynthesis" in window)) { b.classList.add("hidden"); return; }
    b.classList.toggle("on", S.speak);
    b.setAttribute("aria-pressed", S.speak ? "true" : "false");
  }
  function toggleSpeak() {
    S.speak = !S.speak;
    store("speak", S.speak ? "1" : "0");
    if (!S.speak && window.speechSynthesis) speechSynthesis.cancel();
    paintSpeak();
    toast(S.speak ? "As respostas serão lidas em voz alta." : "Voz desligada.");
  }
  function speak(text) {
    if (!("speechSynthesis" in window) || !text) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(MD.plain(text).slice(0, 4000));
    u.lang = "pt-BR";
    const v = speechSynthesis.getVoices().find((x) => x.lang && x.lang.toLowerCase().startsWith("pt-br")) || speechSynthesis.getVoices().find((x) => x.lang && x.lang.toLowerCase().startsWith("pt"));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  }
  A.speak = speak;

  // ------------------------------------------------------------------ ativação por voz ("ei assistente")

  const WAKE_LABEL = { off: "desligada", listening: "ouvindo a frase de chamada", recording: "gravando o seu comando", processing: "entendendo…", idle: "ouvindo a frase de chamada", paused: "em pausa", error: "com problema" };
  function paintWake() {
    const b = document.getElementById("wake-btn");
    if (!b) return;
    const v = (S.state && S.state.voice) || {};
    b.classList.toggle("hidden", !v.enabled);
    b.className = "icon-btn mic-btn" + (v.enabled ? "" : " hidden") + " " + (v.state || "off");
    const label = `Ativação por voz (“${v.phrase || "ei assistente"}”): ${WAKE_LABEL[v.state] || ""}${v.detail ? ". " + v.detail : ""}`;
    b.title = label + (v.state === "error" ? "" : ". Clique para pausar ou retomar.");
    b.setAttribute("aria-label", b.title);
  }
  async function toggleWake() {
    const v = (S.state && S.state.voice) || {};
    if (v.state === "error") { go("settings"); return; }
    try { const r = await api("POST", "/api/voice/pause", { paused: v.state === "paused" ? false : true }); S.state.voice = r; paintWake(); } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------------ navegação

  function go(view) {
    S.view = view;
    toggleSidebar(false);
    paintNav(); paintConvList();
    renderView();
  }
  A.go = go;

  function renderView() {
    const content = document.getElementById("content");
    if (!content) return;
    if (A.views[S.view] && A.views[S.view].leave) A.views[S.view].leave();
    content.replaceChildren();
    const v = A.views[S.view];
    if (S.view === "chat") { renderChat(content); return; }
    const titles = { home: "Início", reminders: "Lembretes", automation: "Automação", tracking: "Encomendas", tasks: "Tarefas", activity: "Histórico", memory: "Memória", settings: "Ajustes" };
    setTitle(titles[S.view] || "");
    if (v) v.render(content); else content.append(h("div", { class: "column" }, h("p", { text: "Seção indisponível." })));
  }

  function newChat() {
    S.convId = null; S.conv = null; S.view = "chat";
    toggleSidebar(false);
    paintNav(); paintConvList();
    renderView();
  }

  async function openConv(id) {
    S.view = "chat"; S.convId = id;
    toggleSidebar(false);
    paintNav(); paintConvList();
    await loadConv(id, false);
  }

  async function loadConv(id, silent) {
    try {
      const c = await api("GET", `/api/conversations/${id}`);
      if (S.convId !== id) return;
      S.conv = c;
      // o servidor é quem sabe se ainda está respondendo (a página pode ter sido recarregada no meio)
      if (c.running && !S.live[id]) S.live[id] = { text: "", tools: [], label: "Pensando…", info: "", error: "" };
      if (!c.running && S.live[id]) delete S.live[id];
      if (S.view === "chat") renderChat(document.getElementById("content"));
    } catch (e) {
      if (e.status === 404) { S.convId = null; S.conv = null; if (S.view === "chat") renderChat(document.getElementById("content")); refreshConvs(); }
      else if (!silent) toast(e.message, "error");
    }
  }

  // ------------------------------------------------------------------ chat

  let msgsEl = null, liveEl = null, scrollEl = null, textarea = null, sendBtn = null, rafId = 0, stickBottom = true;
  const SUGGESTIONS = [
    ["Resuma meus e-mails", "Resuma os e-mails que chegaram hoje e me diga quais são realmente importantes."],
    ["Como está minha agenda?", "Analise minha agenda dos próximos 7 dias e aponte conflitos ou dias sobrecarregados."],
    ["Toque uma música", "Abra o Spotify e toque uma música para eu me concentrar."],
    ["Crie um projeto", "Crie um projeto simples em Python com um README e suba para o meu GitHub."],
  ];

  function renderChat(content) {
    content.replaceChildren();
    setTitle(S.conv ? S.conv.title : "Nova conversa");
    scrollEl = h("div", { class: "scroll", id: "scroll", tabindex: "-1" });
    msgsEl = h("div", { class: "column", id: "msgs", role: "log", "aria-live": "off" });
    scrollEl.append(msgsEl);
    scrollEl.addEventListener("scroll", () => { stickBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 80; });
    content.append(scrollEl, composer());
    paintMessages();
    scrollDown(true);
    if (!(S.conv && S.conv.messages.length) && !liveFor()) textarea.focus();
    if (S.pendingPrompt) { const p = S.pendingPrompt; S.pendingPrompt = ""; textarea.value = p; autosize(); if (p.endsWith(" ")) { textarea.focus(); textarea.setSelectionRange(p.length, p.length); updateSendState(); } else send(); }
  }
  A.ask = (prompt) => { S.pendingPrompt = prompt; newChat(); };               // abre uma conversa nova já com o pedido

  function liveFor() { return S.convId && S.live[S.convId]; }

  function paintMessages() {
    msgsEl.replaceChildren();
    liveEl = null;
    const msgs = (S.conv && S.conv.messages) || [];
    if (!msgs.length && !liveFor()) { msgsEl.append(emptyState()); return; }
    msgs.forEach((m) => msgsEl.append(messageEl(m)));
    if (liveFor()) { liveEl = h("div", { class: "msg assistant", "aria-busy": "true" }); msgsEl.append(liveEl); drawLive(); }
  }

  function emptyState() {
    const name = S.state && S.state.name;
    const box = h("div", { class: "empty" },
      h("h2", { text: `${F.greeting()}${name ? ", " + name : ""}` }),
      h("p", { text: "Posso ler seus e-mails e agenda, entender arquivos e imagens, controlar o computador e trabalhar em projetos enquanto você está fora." }));
    if (S.state && !S.state.gemini_key) box.append(h("div", { class: "alert warn", style: "max-width:460px;text-align:left" }, "Falta a chave do Gemini. Coloque ", h("code", { text: "GEMINI_API_KEY=..." }), " no arquivo ", h("code", { text: ".env" }), " e reabra o app (ou configure outro provedor em Ajustes › Provedores de IA)."));
    box.append(h("div", { class: "chips" }, SUGGESTIONS.map(([label, prompt]) => h("button", { class: "chip", type: "button", text: label, onclick: () => { textarea.value = prompt; autosize(); send(); } }))));
    return box;
  }

  function attChips(list, withImgs, cid) {
    return list.map((a) => {
      const isImg = (a.mime || "").startsWith("image/");
      const media = isImg && a.stored && cid ? h("img", { src: `/api/conversations/${cid}/files/${encodeURIComponent(a.stored)}`, alt: "", loading: "lazy" })
        : isImg && a.preview ? h("img", { src: a.preview, alt: "" }) : h("span", { class: "ico" }, icon("file", 18));
      return h("div", { class: "att" }, media, h("span", { text: a.name }));
    });
  }

  function messageEl(m) {
    if (m.role === "user") {
      const el = h("div", { class: "msg user" });
      if (m.attachments && m.attachments.length) el.append(h("div", { class: "atts" }, attChips(m.attachments, true, S.convId)));
      if (m.text) el.append(h("div", { class: "bubble", text: m.text }));
      return el;
    }
    if (m.role === "note") return h("div", { class: "msg note" }, h("div", { class: "box prose", html: MD.render(m.text) }));
    const el = h("div", { class: "msg assistant" });
    if (m.tools && m.tools.length) el.append(h("div", { class: "tools" }, m.tools.map(toolRow)));
    if (m.text) el.append(h("div", { class: "body prose", html: MD.render(m.text) }));
    if (m.error) el.append(h("div", { class: "err-box", text: m.error }));
    if (m.stopped) el.append(h("div", { class: "stopped-tag", text: "Você interrompeu esta resposta." }));
    if (m.text) el.append(h("div", { class: "msg-actions" },
      h("button", { class: "icon-btn", type: "button", title: "Copiar", "aria-label": "Copiar resposta", onclick: (ev) => copyText(m.text, ev.currentTarget) }, icon("copy", 16)),
      "speechSynthesis" in window ? h("button", { class: "icon-btn", type: "button", title: "Ouvir", "aria-label": "Ouvir resposta", onclick: () => speak(m.text) }, icon("speaker", 16)) : null));
    return el;
  }

  function toolRow(t) {
    const st = t.ok === null || t.ok === undefined ? h("span", { class: "spin", title: "Em andamento" }) : t.denied ? h("span", { class: "st deny-i" }, icon("x", 16)) : t.ok ? h("span", { class: "st ok-i" }, icon("check", 16)) : h("span", { class: "st err-i" }, icon("x", 16));
    return h("div", { class: "tool" + (t.denied ? " denied" : t.ok === false ? " fail" : "") }, st,
      h("div", { class: "what" }, h("b", { text: t.summary }), t.text ? h("div", { class: "res", text: t.text }) : null));
  }

  async function copyText(text, btn) {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); } catch (e2) { /* ignora */ } ta.remove();
    }
    if (btn) { btn.classList.add("on"); setTimeout(() => btn.classList.remove("on"), 1200); }
  }

  // botões "Copiar" dos blocos de código (delegação)
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest(".code-copy");
    if (!b) return;
    const code = b.closest(".codeblock").querySelector("code").textContent;
    copyText(code);
    b.textContent = "Copiado";
    setTimeout(() => { b.textContent = "Copiar"; }, 1500);
  });

  function scrollDown(force) {
    if (!scrollEl) return;
    if (force || stickBottom) scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  // --- resposta em andamento

  function onChatEvent(e) {
    const cid = e.conversation_id;
    if (e.type === "start") { S.live[cid] = { text: "", tools: [], label: "Pensando…", info: "", error: "" }; paintConvList(); if (cid === S.convId) ensureLive(); return; }
    const live = S.live[cid];
    if (e.type === "done") {
      delete S.live[cid]; paintConvList(); refreshConvs(); refreshState();
      if (cid === S.convId) {
        loadConv(cid, true).then(() => {
          if (S.speak && S.conv && !(cid === S.voiceCid && S.state && S.state.voice && S.state.voice.speak_reply)) { const last = [...S.conv.messages].reverse().find((m) => m.role === "assistant"); if (last && last.text) speak(last.text); }
        });
      }
      updateSendState();
      return;
    }
    if (!live) return;
    switch (e.type) {
      case "thinking": live.since = e.since ? e.since * 1000 - (S.skew || 0) * 1000 : Date.now(); live.label = live.tools.some((t) => t.ok === null) ? "Executando…" : live.text ? "Escrevendo…" : "Pensando…"; break;
      case "delta": live.text += e.text; live.label = "Escrevendo…"; break;
      case "tool_start": live.tools.push({ id: e.id, summary: e.summary, ok: null, text: "" }); live.label = "Executando…"; break;
      case "tool_end": {
        const t = live.tools.find((x) => x.id === e.id);
        if (t) Object.assign(t, { ok: e.ok, text: e.text || "", denied: !!e.denied });
        else live.tools.push({ id: e.id, summary: e.summary || "", ok: e.ok, text: e.text || "", denied: !!e.denied });
        live.label = "Pensando…"; break;
      }
      case "info": live.info = e.text; break;
      case "error": live.error = e.message; break;
      default: return;
    }
    if (cid === S.convId) scheduleLive();
  }

  function ensureLive() {
    if (!msgsEl) return;
    if (!liveEl) {
      const empty = msgsEl.querySelector(".empty");
      if (empty) empty.remove();
      liveEl = h("div", { class: "msg assistant", "aria-busy": "true" });
      msgsEl.append(liveEl);
    }
    drawLive(); scrollDown(true); updateSendState();
  }
  function scheduleLive() {
    if (rafId) return;
    rafId = requestAnimationFrame(() => { rafId = 0; ensureLive2(); });
  }
  function ensureLive2() { if (liveFor()) { if (!liveEl) ensureLive(); else { drawLive(); scrollDown(false); } } }

  function drawLive() {
    const live = liveFor();
    if (!live || !liveEl) return;
    liveEl.replaceChildren();
    if (live.tools.length) liveEl.append(h("div", { class: "tools" }, live.tools.map(toolRow)));
    if (live.text) liveEl.append(h("div", { class: "body prose", html: MD.render(live.text) }));
    if (live.info) liveEl.append(h("div", { class: "alert warn", text: live.info }));
    if (live.error) liveEl.append(h("div", { class: "err-box", text: live.error }));
    else liveEl.append(h("div", { class: "thinking", role: "status" }, h("span", { class: "orb" }), h("span", { class: "lbl", text: live.label }), live.since ? h("span", { class: "el", "data-since": String(live.since), text: "" }) : null));
  }

  // --- caixa de texto, anexos, microfone

  function composer() {
    textarea = h("textarea", { rows: "1", placeholder: "Pergunte ou peça algo…", "aria-label": "Mensagem", maxlength: "30000" });
    textarea.addEventListener("input", () => { autosize(); updateSendState(); });
    textarea.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && !matchMedia("(pointer:coarse)").matches) { ev.preventDefault(); send(); }
    });
    textarea.addEventListener("paste", (ev) => {
      const files = [...(ev.clipboardData ? ev.clipboardData.files : [])];
      if (files.length) { ev.preventDefault(); addFiles(files); }
    });
    const fileInput = h("input", { type: "file", multiple: "", class: "hidden", accept: "image/*,.pdf,.txt,.md,.csv,.json,.py,.js,.html,.css,.docx,.log,.yaml,.yml,.xml,.sql", onchange: (ev) => { addFiles([...ev.target.files]); ev.target.value = ""; } });
    sendBtn = h("button", { class: "send", type: "button", "aria-label": "Enviar", onclick: () => (liveFor() ? stopChat() : send()) });
    const mic = canRecord() ? h("button", { class: "icon-btn mic", type: "button", title: "Falar em vez de digitar", "aria-label": "Gravar mensagem de voz", id: "mic-btn", onclick: toggleRecord }, icon("mic")) : null;
    const box = h("div", { class: "composer", id: "composer" },
      h("div", { class: "att-row", id: "att-row" }), textarea,
      h("div", { class: "tools-row" }, h("button", { class: "icon-btn", type: "button", title: "Anexar arquivos (imagem, PDF, texto, Word)", "aria-label": "Anexar arquivos", onclick: () => fileInput.click() }, icon("clip")), fileInput, h("span", { class: "grow" }), mic, sendBtn));
    ["dragenter", "dragover"].forEach((n) => box.addEventListener(n, (ev) => { ev.preventDefault(); box.classList.add("drag"); }));
    ["dragleave", "drop"].forEach((n) => box.addEventListener(n, (ev) => { ev.preventDefault(); box.classList.remove("drag"); }));
    box.addEventListener("drop", (ev) => addFiles([...ev.dataTransfer.files]));
    const wrap = h("div", { class: "composer-wrap" }, h("div", { class: "column", style: "padding:0" }, box, h("div", { class: "hint", text: "O assistente pode errar. Confira informações importantes e ações antes de aprovar." })));
    paintAttachments(); updateSendState();
    return wrap;
  }

  function autosize() { textarea.style.height = "auto"; textarea.style.height = Math.min(textarea.scrollHeight, 220) + "px"; }

  function updateSendState() {
    if (!sendBtn) return;
    const running = !!liveFor();
    sendBtn.replaceChildren(icon(running ? "stop" : "send", 18));
    sendBtn.classList.toggle("stop", running);
    sendBtn.setAttribute("aria-label", running ? "Parar resposta" : "Enviar");
    const stopping = running && S.live[S.convId].stopping;
    sendBtn.disabled = stopping || (!running && !(textarea.value.trim() || S.attachments.length));
  }

  const MAX_FILE = 15 * 1024 * 1024, MAX_FILES = 6;
  function addFiles(files) {
    for (const f of files) {
      if (S.attachments.length >= MAX_FILES) { toast(`No máximo ${MAX_FILES} arquivos por mensagem.`, "error"); break; }
      if (f.size > MAX_FILE) { toast(`"${f.name}" passa de 15 MB.`, "error"); continue; }
      const att = { name: f.name || "imagem.png", file: f, mime: f.type, preview: f.type.startsWith("image/") ? URL.createObjectURL(f) : "" };
      S.attachments.push(att);
    }
    paintAttachments(); updateSendState();
  }
  function paintAttachments() {
    const row = document.getElementById("att-row");
    if (!row) return;
    row.replaceChildren();
    row.classList.toggle("hidden", !S.attachments.length);
    S.attachments.forEach((a, i) => {
      const chip = h("div", { class: "att-chip" }, ...attChips([a]), h("button", { type: "button", "aria-label": `Remover ${a.name}`, onclick: () => { if (a.preview) URL.revokeObjectURL(a.preview); S.attachments.splice(i, 1); paintAttachments(); updateSendState(); } }, icon("x", 12)));
      row.append(chip);
    });
  }

  function toBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error("Não consegui ler " + file.name));
      r.readAsDataURL(file);
    });
  }

  async function send() {
    if (liveFor()) return;
    const text = textarea.value.trim();
    if (!text && !S.attachments.length) return;
    const files = S.attachments.slice();
    sendBtn.disabled = true;
    try {
      const payload = [];
      for (const a of files) payload.push({ name: a.name, data: await toBase64(a.file) });
      if (!S.conv) S.conv = { id: null, title: "Nova conversa", messages: [] };
      S.conv.messages.push({ id: "tmp", role: "user", text, attachments: files.map((a) => ({ name: a.name, mime: a.mime, preview: a.preview })) });
      if (msgsEl.querySelector(".empty")) msgsEl.replaceChildren();
      msgsEl.append(messageEl(S.conv.messages[S.conv.messages.length - 1]));
      textarea.value = ""; autosize(); S.attachments = []; paintAttachments();
      scrollDown(true);
      if (S.speak && window.speechSynthesis) speechSynthesis.cancel();
      const r = await api("POST", "/api/chat", { conversation_id: S.convId, text, attachments: payload });
      const isNew = S.convId !== r.conversation_id;
      S.convId = r.conversation_id;
      // a resposta pode já ter começado (ou até terminado) antes desta chamada voltar: o servidor é quem sabe
      const cur = await api("GET", `/api/conversations/${S.convId}`);
      if (S.convId === cur.id) {
        S.conv = cur;
        if (cur.running && !S.live[cur.id]) S.live[cur.id] = { text: "", tools: [], label: "Pensando…", info: "", error: "" };
        if (!cur.running) delete S.live[cur.id];
        paintMessages(); scrollDown(true);
      }
      if (isNew) { await refreshConvs(); setTitle((S.convs.find((c) => c.id === S.convId) || {}).title || "Conversa"); }
      paintConvList();
    } catch (e) {
      toast(e.message, "error");
      if (S.convId && S.live[S.convId] && !(await running(S.convId))) delete S.live[S.convId];
      if (S.convId) loadConv(S.convId, true); else { S.conv = null; renderChat(document.getElementById("content")); }
      textarea.value = text; autosize();
    }
    updateSendState();
  }
  async function running(cid) { try { return (await api("GET", `/api/conversations/${cid}`)).running; } catch (e) { return false; } }

  async function stopChat() {
    if (!S.convId) return;
    const live = S.live[S.convId];
    if (live) { live.label = "Parando…"; live.stopping = true; drawLive(); }
    if (sendBtn) sendBtn.disabled = true;
    try { await api("POST", "/api/chat/stop", { conversation_id: S.convId }); } catch (e) { toast(e.message, "error"); }
  }

  // --- voz (entrada)

  let rec = null;
  function canRecord() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder); }
  async function toggleRecord() {
    const btn = document.getElementById("mic-btn");
    if (rec) { rec.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) { toast("Não consegui usar o microfone. Verifique a permissão do navegador.", "error"); return; }
    const chunks = [];
    const mr = new MediaRecorder(stream);
    rec = mr;
    mr.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data); };
    mr.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      rec = null; btn.classList.remove("rec"); btn.setAttribute("aria-label", "Gravar mensagem de voz");
      if (!chunks.length) return;
      const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
      toast("Transcrevendo…");
      try {
        const r = await api("POST", "/api/transcribe", blob);
        if (r.text) { textarea.value = (textarea.value ? textarea.value + " " : "") + r.text; autosize(); updateSendState(); textarea.focus(); }
        else toast("Não entendi o áudio. Tente de novo.", "error");
      } catch (e) { toast(e.message, "error"); }
    };
    mr.start();
    btn.classList.add("rec"); btn.setAttribute("aria-label", "Parar gravação");
    setTimeout(() => { if (rec === mr && mr.state === "recording") mr.stop(); }, 120000);
  }

  A.views.chat = { render: renderChat };

  // ------------------------------------------------------------------ início

  async function init() {
    S.speak = store("speak") === "1";
    buildShell();
    paintNav();
    renderView();
    await Promise.all([refreshState(), refreshConvs()]);
    try { S.tasks = (await api("GET", "/api/tasks")).tasks; } catch (e) { /* ok */ }
    paintNav();
    if (S.view === "chat" && !S.conv) renderView();   // saudação com o nome
    connect();
    setInterval(() => { if (S.state && S.state.usage) paintUsage(); }, 30000);
    setInterval(tickChecks, 1000);
    setInterval(refreshState, 60000);
    if ("speechSynthesis" in window) speechSynthesis.getVoices();
  }
  document.addEventListener("DOMContentLoaded", init);
  if (document.readyState !== "loading") init();
})();
