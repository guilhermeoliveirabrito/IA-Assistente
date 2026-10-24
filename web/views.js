/* Seções do app: Tarefas, Histórico, Memória e Ajustes. Usa o núcleo exposto em window.A (app.js). */
(function () {
  "use strict";
  const A = window.A, S = A.S, h = A.h, api = A.api, toast = A.toast, F = A.fmt;

  const FINAL = ["done", "failed", "stopped"];
  // "Só leitura: lê arquivos..." -> ["Só leitura", "lê arquivos..."]
  const splitLabel = (label) => { const i = String(label).indexOf(": "); return i < 0 ? [String(label), ""] : [label.slice(0, i), label.slice(i + 2)]; };
  const page = (title, sub, ...kids) => h("div", { class: "scroll" }, h("div", { class: "column page" }, h("h2", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null, ...kids));

  // =================================================================== TAREFAS

  const tasks = {
    sel: null, feed: [], timer: 0, box: null, detail: null,

    async render(content) {
      this.box = content;
      try { S.tasks = (await api("GET", "/api/tasks")).tasks; } catch (e) { toast(e.message, "error"); }
      this.paint();
    },
    resync() { if (S.view === "tasks") this.render(this.box); },
    leave() { clearTimeout(this.timer); },

    paint() {
      const left = h("div", { class: "list", role: "list" });
      if (!S.tasks.length) left.append(h("div", { class: "card" }, h("h3", { text: "Nenhuma tarefa ainda" }), h("p", { class: "desc", text: "Descreva um trabalho e o assistente executa sozinho, mesmo com você fora. Você vê o plano e tudo o que ele fez." })));
      for (const t of S.tasks) {
        left.append(h("div", { class: "item" + (t.id === this.sel ? " sel" : ""), role: "listitem", tabindex: "0", onclick: () => this.select(t.id), onkeydown: (e) => { if (e.key === "Enter") this.select(t.id); } },
          h("div", { class: "t", text: t.title }),
          h("div", { class: "m" }, h("span", { class: "st-chip " + t.status, text: t.status_label }), h("span", { text: `${t.requests}/${t.budget} req.` }), h("span", { text: F.ago(t.updated) }))));
      }
      this.detail = h("div", { id: "task-detail" });
      const right = this.detail;
      const head = h("div", { style: "display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:6px" }, h("div"), h("button", { class: "btn primary", type: "button", onclick: () => this.newTask() }, A.icon("plus", 16), "Nova tarefa"));
      this.box.replaceChildren(page("Tarefas", "Trabalhos que o assistente faz sozinho, em segundo plano. Fique de olho aqui ou no celular.", head, h("div", { class: "split" }, left, right)));
      this.paintDetail();
    },

    select(id) { this.sel = id; this.feed = []; this.paint(); this.loadFeed(); },

    onTask(e) {
      if (S.view !== "tasks") return;
      const keep = this.box.querySelector(".scroll");
      const top = keep ? keep.scrollTop : 0;
      this.paint();
      const sc = this.box.querySelector(".scroll"); if (sc) sc.scrollTop = top;
    },
    onTaskEvent(e) {
      if (S.view !== "tasks" || e.task_id !== this.sel) return;
      if (["tool_start", "tool_end", "error", "confirm", "info"].includes(e.type)) { clearTimeout(this.timer); this.timer = setTimeout(() => this.loadFeed(), 500); }
    },

    async loadFeed() {
      if (!this.sel) return;
      const id = this.sel;
      try {
        const r = await api("GET", `/api/activity?task=${id}&limit=120`);
        if (id !== this.sel) return;
        this.feed = r.events; this.paintDetail();
      } catch (e) { /* ignora */ }
    },

    async paintDetail() {
      const box = this.detail; if (!box) return;
      box.replaceChildren();
      const t = S.tasks.find((x) => x.id === this.sel);
      if (!t) { box.append(h("div", { class: "card" }, h("p", { class: "desc", style: "margin:0", text: "Escolha uma tarefa para ver o plano, o andamento e o que foi feito." }))); return; }
      const c = h("div", { class: "card" });
      c.append(h("div", { style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap" }, h("h3", { text: t.title, style: "margin:0;flex:1;font-size:17px" }), h("span", { class: "st-chip " + t.status, text: t.status_label })));
      c.append(h("div", { class: "kv", style: "margin:8px 0 12px;color:var(--muted);font-size:13px" },
        h("span", { text: `Permissões: ${(S.state.profiles || {})[t.profile] ? splitLabel(S.state.profiles[t.profile])[0] : t.profile}` }), "·",
        h("span", { text: `${t.requests} de ${t.budget} requisições` }), "·", h("span", { text: "Pasta: " }), h("code", { text: t.project })));
      c.append(h("p", { style: "margin:0 0 14px;white-space:pre-wrap;overflow-wrap:anywhere", text: t.prompt }));
      if (t.question && t.status === "waiting_user") c.append(this.questionBox(t));
      if (t.status === "waiting_approval") c.append(h("div", { class: "alert warn", text: "Esperando sua aprovação. O pedido aparece no canto da tela (e no aviso do celular)." }));
      if (t.status === "paused_quota") c.append(h("div", { class: "alert warn", text: `A cota gratuita do dia acabou. Retomo sozinho${t.resume_at ? " " + F.dayTime(t.resume_at) : " depois da renovação"}.` }));
      if (t.status === "paused_budget") c.append(h("div", { class: "alert warn", text: "O orçamento de requisições desta tarefa acabou. Dê mais orçamento para continuar." }));
      if (t.error) c.append(h("div", { class: "err-box", text: t.error }));
      if (t.plan && t.plan.length) {
        c.append(h("h3", { text: "Plano", style: "margin:14px 0 8px" }),
          h("ol", { class: "plan" }, t.plan.map((p) => h("li", { class: p.status }, h("span", { class: "dot" }, p.status === "feito" ? A.icon("check", 12) : null), h("div", {}, h("div", { class: "txt", text: p.text }), p.note ? h("div", { class: "note", text: p.note }) : null)))));
      }
      if (t.summary) c.append(h("h3", { text: "Resultado", style: "margin:14px 0 6px" }), h("div", { class: "prose", html: MD.render(t.summary) }));
      (t.notes || []).forEach((n) => c.append(h("div", { class: "note", style: "color:var(--faint);font-size:12.5px;margin-top:6px", text: n })));
      c.append(this.actions(t));
      box.append(c);
      const feed = h("div", { class: "card" }, h("h3", { text: "O que ele fez" }));
      if (!this.feed.length) feed.append(h("p", { class: "desc", style: "margin:0", text: "Nada registrado ainda." }));
      else feed.append(h("div", { class: "feed" }, [...this.feed].reverse().map(evRow(false))));
      box.append(feed);
      try {
        const full = await api("GET", `/api/tasks/${t.id}`);
        if (t.id === this.sel && full.messages && !box.querySelector("details.tx")) {
          box.append(h("details", { class: "card tx" }, h("summary", { text: "Conversa completa do agente", style: "cursor:pointer" }), h("pre", { style: "white-space:pre-wrap;overflow-wrap:anywhere;font-size:12.5px;color:var(--muted);max-height:360px;overflow:auto", text: full.messages })));
        }
      } catch (e) { /* ignora */ }
    },

    questionBox(t) {
      const input = h("textarea", { class: "field", placeholder: "Sua resposta…", "aria-label": "Resposta para o assistente" });
      return h("div", { class: "confirm" }, h("div", { class: "top" }, h("b", { text: "O assistente precisa de você" })), h("div", { class: "sum", text: t.question }), input,
        h("div", { class: "row-btns", style: "margin-top:10px" }, h("button", { class: "btn primary sm", type: "button", text: "Responder", onclick: async () => {
          if (!input.value.trim()) return;
          try { await api("POST", `/api/tasks/${t.id}/answer`, { text: input.value }); toast("Resposta enviada.", "ok"); } catch (e) { toast(e.message, "error"); }
        } })));
    },

    actions(t) {
      const row = h("div", { class: "row-btns", style: "margin-top:16px" });
      const call = async (path, body, okMsg) => { try { await api("POST", `/api/tasks/${t.id}/${path}`, body); if (okMsg) toast(okMsg, "ok"); } catch (e) { toast(e.message, "error"); } };
      if (!FINAL.includes(t.status)) row.append(h("button", { class: "btn danger", type: "button", text: "Parar tarefa", onclick: () => call("stop", {}, "Tarefa parada.") }));
      if (["paused_quota", "paused_budget", "stopped", "failed"].includes(t.status)) {
        const extra = h("input", { type: "number", min: "0", max: "1000", value: t.status === "paused_budget" ? "30" : "0", style: "width:90px", "aria-label": "Requisições extras" });
        row.append(h("span", { class: "kv", style: "gap:6px" }, h("button", { class: "btn primary", type: "button", text: "Retomar", onclick: () => call("resume", { extra_budget: Number(extra.value) || 0 }, "Tarefa retomada.") }), h("span", { style: "color:var(--muted);font-size:13px", text: "+ requisições:" }), extra));
      }
      if (FINAL.includes(t.status)) row.append(h("button", { class: "btn", type: "button", text: "Apagar", onclick: async () => {
        if (!(await A.confirm("Apagar tarefa?", "Some da lista. Os arquivos do projeto na sua pasta continuam lá.", "Apagar", true))) return;
        try { await api("DELETE", `/api/tasks/${t.id}`); this.sel = null; } catch (e) { toast(e.message, "error"); }
      } }));
      return row;
    },

    newTask() {
      const profiles = S.state.profiles || {};
      const title = h("input", { type: "text", maxlength: "80", placeholder: "Opcional" });
      const prompt = h("textarea", { class: "field", style: "min-height:130px", placeholder: "Ex.: Crie um site de portfólio em HTML e CSS, salve em uma pasta nova e suba para o meu GitHub." });
      const budget = h("input", { type: "number", min: "1", max: "1000", value: String(S.state.default_budget || 60) });
      const auto = !!S.state.autonomous;
      let profile = auto ? "total" : Object.keys(profiles).includes("projeto") ? "projeto" : Object.keys(profiles)[0];
      const opts = Object.entries(profiles).map(([id, label]) => {
        const [name, desc] = splitLabel(label);
        return h("label", { class: "profile-opt" }, h("input", { type: "radio", name: "profile", value: id, checked: id === profile, onchange: () => { profile = id; } }), h("div", {}, h("b", { text: name }), h("span", { text: desc })));
      });
      const body = h("div", {}, h("label", { class: "f" }, h("span", { text: "O que fazer" }), prompt), h("label", { class: "f" }, h("span", { text: "Título" }), title),
        auto ? h("p", { class: "desc", text: "Modo autônomo ligado: ele faz tudo sozinho, sem pedir permissão, e só para se algo for contra uma regra sua." }) : h("div", { style: "margin-bottom:12px" }, h("div", { style: "font-size:13px;color:var(--muted);margin-bottom:6px", text: "O que ele pode fazer sozinho" }), h("div", { style: "display:flex;flex-direction:column;gap:8px" }, opts)),
        h("label", { class: "f" }, h("span", { text: "Orçamento de requisições" }), budget, h("small", { text: "Limite de chamadas à IA para esta tarefa, para ela não gastar a cota do dia inteira." })));
      A.modal({ title: "Nova tarefa", body, wide: true, actions: [{ label: "Cancelar" }, { label: "Começar", kind: "primary", run: async () => {
        try { const t = await api("POST", "/api/tasks", { title: title.value, prompt: prompt.value, profile, budget: Number(budget.value) }); this.sel = t.id; toast("Tarefa na fila.", "ok"); } catch (e) { toast(e.message, "error"); return false; }
      } }] });
    },
  };

  // =================================================================== ENCOMENDAS

  const TRK_CLASS = { Delivered: "done", OutForDelivery: "running", AvailableForPickup: "running", InTransit: "running", Exception: "failed", DeliveryFailure: "failed", Expired: "failed" };
  const evTime = (t) => { const d = new Date(t); return isNaN(d) ? String(t || "") : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };

  const tracking = {
    box: null, data: { items: [] }, sel: null,

    async render(content) { this.box = content; await this.refresh(); },
    resync() { if (S.view === "tracking") this.refresh(); },

    async refresh() {
      if (S.view !== "tracking" || !this.box) return;
      try { this.data = await api("GET", "/api/tracking"); } catch (e) { toast(e.message, "error"); return; }
      if (!this.data.items.some((i) => i.id === this.sel)) this.sel = this.data.items.length ? this.data.items[0].id : null;
      this.paint();
    },

    current() { return this.data.items.find((i) => i.id === this.sel) || null; },

    paint() {
      const d = this.data;
      const kids = [];
      if (!d.configured) {
        kids.push(h("div", { class: "card" }, h("h3", { text: "Falta a chave do serviço de rastreio" }),
          h("p", { class: "desc" }, "O assistente consulta as encomendas pelo 17TRACK (grátis, reconhece Correios e transportadoras do mundo todo). Crie uma conta em ", h("code", { text: "17track.net" }), ", gere a chave de acesso da API e coloque no arquivo ", h("code", { text: ".env" }), " como ", h("code", { text: "TRACK17_KEY=sua_chave" }), ". Reabra o app. Passo a passo no README."),
          h("p", { class: "desc", style: "margin:0", text: "Enquanto isso, você já pode guardar os códigos aqui e abrir o rastreio de cada um no site." })));
      }
      const code = h("input", { type: "text", placeholder: "Código de rastreio (ex.: AA123456789BR)", maxlength: "40", "aria-label": "Código de rastreio" });
      code.addEventListener("input", () => { code.value = code.value.toUpperCase(); });
      const name = h("input", { type: "text", placeholder: "Nome (ex.: Fone novo)", maxlength: "60", "aria-label": "Nome da encomenda" });
      const add = async () => {
        if (!code.value.trim()) return;
        try { const r = await api("POST", "/api/tracking", { code: code.value, name: name.value }); code.value = ""; name.value = ""; this.sel = r.item.id; toast(d.configured ? "Consultando agora…" : "Código guardado.", "ok"); await this.refresh(); } catch (e) { toast(e.message, "error"); }
      };
      code.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      const st = d.status || {};
      kids.push(h("div", { class: "card" }, h("h3", { text: "Acompanhar uma encomenda" }),
        h("div", { class: "trk-add" }, code, name, h("button", { class: "btn primary", type: "button", text: "Acompanhar", onclick: add })),
        h("p", { class: "desc", style: "margin:10px 0 0" }, "Você também pode pedir no chat: “acompanhe a encomenda AA123456789BR”. ",
          st.next_ts ? h("span", {}, "Próxima consulta automática em ", h("b", { "data-next": String(st.next_ts), text: A.countdown(st.next_ts) }), ". ") : null,
          d.items.length && d.configured ? h("button", { class: "btn sm", type: "button", text: "Consultar todas agora", onclick: async () => { try { await api("POST", "/api/tracking/check"); toast("Consultando…"); } catch (e) { toast(e.message, "error"); } } }) : null)));
      const left = h("div", { class: "list", role: "list" });
      if (!d.items.length) left.append(h("div", { class: "card" }, h("h3", { text: "Nenhuma encomenda ainda" }), h("p", { class: "desc", style: "margin:0", text: "Cole o código de rastreio acima. O assistente consulta sozinho e te avisa (aqui, no medidor e no celular) quando a situação mudar." })));
      for (const i of d.items) {
        const ev = (i.events || [])[0];
        left.append(h("div", { class: "item" + (i.id === this.sel ? " sel" : ""), role: "listitem", tabindex: "0", onclick: () => this.select(i.id), onkeydown: (e) => { if (e.key === "Enter") this.select(i.id); } },
          h("div", { class: "t" }, i.unread ? h("span", { class: "dot", title: "Novidade" }) : null, i.name),
          h("div", { class: "m" }, h("span", { class: "st-chip " + (TRK_CLASS[i.status] || "waiting_user"), text: i.status_label }), ev ? h("span", { text: evTime(ev.time) }) : null),
          h("div", { class: "m", style: "margin-top:4px" }, h("code", { text: i.code }))));
      }
      kids.push(h("div", { class: "split" }, left, this.detail()));
      this.box.replaceChildren(page("Encomendas", "Informe o código e o assistente avisa de cada novidade.", ...kids));
    },

    async select(id) {
      this.sel = id;
      const i = this.current();
      if (i && i.unread) { try { await api("POST", `/api/tracking/${id}/read`); } catch (e) { /* ignora */ } await this.refresh(); } else this.paint();
    },

    detail() {
      const i = this.current();
      if (!i) return h("div", {});
      const card = h("div", { class: "card" });
      const title = h("h3", { text: i.name });
      card.append(h("div", { style: "display:flex;align-items:center;gap:10px;justify-content:space-between" }, title,
        h("span", { class: "st-chip " + (TRK_CLASS[i.status] || "waiting_user"), text: i.status_label })),
        h("div", { class: "kv", style: "margin:6px 0 12px" }, h("code", { text: i.code }), i.carrier ? h("span", { style: "color:var(--muted)", text: "· " + i.carrier }) : null));
      if (i.error) card.append(h("div", { class: "alert err", text: i.error }));
      else if (i.found === false) card.append(h("p", { class: "desc", text: i.note || "Ainda não encontrei esse código. Logo depois da postagem pode levar algumas horas. Sigo tentando e aviso quando aparecer." }));
      else if (i.found === null) card.append(h("p", { class: "desc", text: "Aguardando a primeira consulta…" }));
      if ((i.events || []).length) {
        card.append(h("ol", { class: "trk-line" }, i.events.map((e, n) => h("li", { class: n === 0 ? "now" : "" }, h("time", { text: evTime(e.time) }), h("div", { class: "tx", text: e.text || "Atualização" }), e.place ? h("div", { class: "pl", text: e.place }) : null))));
      }
      if (i.last_check) card.append(h("p", { class: "desc", style: "margin:12px 0 0;font-size:12.5px", text: "Última consulta " + F.ago(i.last_check - ((S.skew) || 0)) + "." }));
      const row = h("div", { class: "row-btns", style: "margin-top:14px" },
        this.data.configured ? h("button", { class: "btn", type: "button", text: "Consultar agora", onclick: async () => { try { await api("POST", `/api/tracking/${i.id}/check`); toast("Consultando…"); } catch (e) { toast(e.message, "error"); } } }) : null,
        h("a", { class: "btn", href: i.url, target: "_blank", rel: "noopener noreferrer", text: "Abrir no site de rastreio" }),
        h("button", { class: "btn", type: "button", text: "Renomear", onclick: () => this.rename(i) }),
        h("button", { class: "btn danger", type: "button", text: "Remover", onclick: async () => {
          if (!(await A.confirm("Remover encomenda?", "O assistente para de acompanhar este código.", "Remover", true))) return;
          try { await api("DELETE", `/api/tracking/${i.id}`); await this.refresh(); } catch (e) { toast(e.message, "error"); }
        } }));
      card.append(row);
      return card;
    },

    rename(i) {
      const input = h("input", { type: "text", maxlength: "60", value: i.name, "aria-label": "Novo nome" });
      A.modal({ title: "Renomear", body: h("label", { class: "f" }, h("span", { text: "Nome da encomenda" }), input), actions: [{ label: "Cancelar" }, { label: "Salvar", kind: "primary", run: async () => {
        try { await api("POST", `/api/tracking/${i.id}/rename`, { name: input.value }); await this.refresh(); } catch (e) { toast(e.message, "error"); return false; }
      } }] });
    },
  };

  // =================================================================== AUTOMAÇÃO

  // ------------------------------------------------------------------ início
  const HOME_ASKS = [["Resumir meus e-mails", "Resuma meus e-mails importantes de hoje."], ["Como está minha agenda?", "Como está minha agenda dos próximos dias?"],
    ["Pesquisar na internet", "Pesquise na internet: "], ["Marcar um lembrete", "Me lembra daqui a 30 minutos de "], ["Ver minhas encomendas", "Como estão minhas encomendas?"]];
  const home = {
    box: null, data: null, rem: null,
    async render(content) { this.box = content; await this.refresh(); },
    resync() { if (S.view === "home") this.refresh(); },
    async refresh() {
      if (S.view !== "home" || !this.box) return;
      try { [this.data, this.rem] = await Promise.all([api("GET", "/api/briefing"), api("GET", "/api/reminders")]); await A.refreshState(); } catch (e) { toast(e.message, "error"); return; }
      this.paint();
    },
    paint() {
      const d = this.data, st = S.state || {}, name = st.name;
      const kids = [];
      const run = h("button", { class: "btn sm", type: "button", text: d.latest.ts ? "Atualizar agora" : "Gerar o resumo de hoje", onclick: async (ev) => {
        ev.currentTarget.disabled = true; ev.currentTarget.textContent = "Montando…";
        try { await api("POST", "/api/briefing/run"); setTimeout(() => this.refresh(), 6000); setTimeout(() => this.refresh(), 15000); } catch (e) { toast(e.message, "error"); }
      } });
      const card = h("div", { class: "card" }, h("div", { style: "display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap" }, h("h3", { text: "Resumo do dia", style: "margin:0" }), run));
      if (d.latest.text) {
        card.append(h("div", { class: "prose", style: "margin-top:10px", html: MD.render(d.latest.text) }),
          h("p", { class: "desc", style: "margin:10px 0 0", text: "Gerado " + F.dayTime(d.latest.ts) + (d.status.next_ts ? ". Próximo automático em " : "") }, d.status.next_ts ? h("b", { "data-next": String(d.status.next_ts), text: A.countdown(d.status.next_ts) }) : null));
      } else card.append(h("p", { class: "desc", style: "margin:10px 0 0", text: "Todo dia de manhã o assistente junta sua agenda, e-mails importantes, encomendas e lembretes aqui e te avisa no celular. Clique para ver como fica agora." }));
      kids.push(card);
      const next = (this.rem.items || []).filter((i) => i.status === "ativo").slice(0, 3);
      const glance = h("div", { class: "home-grid" },
        h("div", { class: "card" }, h("h3", { text: "Próximos lembretes" }), next.length ? next.map((i) => h("div", { class: "kv", style: "margin-bottom:6px" }, h("span", { text: (i.tipo === "alarme" ? "⏰ " : "🔔 ") + i.texto }), h("b", { "data-next": String(i.due), text: A.countdown(i.due) }))) : h("p", { class: "desc", style: "margin:0", text: "Nada marcado." }), h("div", { style: "margin-top:8px" }, h("button", { class: "btn sm", type: "button", text: "Abrir lembretes", onclick: () => A.go("reminders") }))),
        h("div", { class: "card" }, h("h3", { text: "Encomendas" }), h("p", { class: "desc", style: "margin:0 0 8px", text: (st.tracking && st.tracking.count) ? `${st.tracking.count} acompanhada(s)` + (st.tracking.unread ? `, ${st.tracking.unread} com novidade` : ".") : "Nenhuma acompanhada." }), h("button", { class: "btn sm", type: "button", text: "Abrir encomendas", onclick: () => A.go("tracking") })),
        h("div", { class: "card" }, h("h3", { text: "Pedir algo" }), h("div", { class: "chips", style: "justify-content:flex-start" }, HOME_ASKS.map(([label, prompt]) => h("button", { class: "chip", type: "button", text: label, onclick: () => A.ask(prompt) })))));
      kids.push(glance);
      this.box.replaceChildren(page(`${F.greeting()}${name ? ", " + name : ""}`, "O que está acontecendo hoje.", ...kids));
    },
  };

  // ------------------------------------------------------------------ lembretes e alarmes
  const REPEAT_LABEL = [["nao", "Uma vez"], ["diario", "Todo dia"], ["dias_uteis", "Dias úteis"], ["semanal", "Toda semana"], ["mensal", "Todo mês"], ["intervalo", "A cada N minutos"]];
  const reminders = {
    box: null, data: null,
    async render(content) { this.box = content; if ("Notification" in window && Notification.permission === "default") { try { Notification.requestPermission(); } catch (e) { /* ignora */ } } await this.refresh(); },
    resync() { if (S.view === "reminders") this.refresh(); },
    async refresh() {
      if (S.view !== "reminders" || !this.box) return;
      try { this.data = await api("GET", "/api/reminders"); } catch (e) { toast(e.message, "error"); return; }
      this.paint();
    },
    paint() {
      const d = this.data;
      const text = h("input", { type: "text", placeholder: "Do que devo lembrar? (ex.: ligar pro João)", maxlength: "400", "aria-label": "Texto do lembrete" });
      const when = h("input", { type: "datetime-local", "aria-label": "Quando" });
      const soon = new Date(Date.now() + 3600e3); soon.setSeconds(0, 0); when.value = new Date(soon - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      const rep = h("select", { "aria-label": "Repetir" }, REPEAT_LABEL.map(([v, l]) => h("option", { value: v, text: l })));
      const every = h("input", { type: "number", min: "5", max: "10080", placeholder: "minutos", style: "width:100px;display:none", "aria-label": "A cada quantos minutos" });
      rep.addEventListener("change", () => { every.style.display = rep.value === "intervalo" ? "" : "none"; });
      const alarm = h("input", { type: "checkbox" }), run = h("input", { type: "checkbox" });
      const add = async () => {
        if (!text.value.trim()) return toast("Escreva do que devo lembrar.", "error");
        try {
          await api("POST", "/api/reminders", { text: text.value, when: when.value.replace("T", " "), repeat: rep.value, every_minutes: every.value || null, alarm: alarm.checked, run: run.checked });
          text.value = ""; toast("Lembrete marcado.", "ok"); await this.refresh();
        } catch (e) { toast(e.message, "error"); }
      };
      text.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      const form = h("div", { class: "card" }, h("h3", { text: "Novo lembrete" }),
        h("div", { class: "rem-add" }, text, when, rep, every, h("button", { class: "btn primary", type: "button", text: "Marcar", onclick: add })),
        h("div", { class: "rem-opts" },
          h("label", { class: "switch" }, alarm, h("span", { text: "Alarme (toca até eu dispensar)" })),
          h("label", { class: "switch" }, run, h("span", { text: "Não só avisar: o assistente FAZ isso na hora (tarefa)" }))),
        h("p", { class: "desc", style: "margin:8px 0 0", text: "Também dá para pedir no chat ou por voz: “me lembra às 18h de ligar pro João”, “todo dia às 8h resume meus e-mails”. Avisa aqui (com som) e no celular, se os avisos do celular estiverem ligados em Ajustes." }));
      const list = h("div", { class: "list", role: "list" });
      if (!d.items.length) list.append(h("div", { class: "card" }, h("h3", { text: "Nada marcado" }), h("p", { class: "desc", style: "margin:0", text: "Quando você marcar um lembrete, ele aparece aqui com a contagem regressiva." })));
      for (const i of d.items) {
        const ringing = i.status === "tocando";
        list.append(h("div", { class: "item rem-item" + (ringing ? " ringing" : ""), role: "listitem" },
          h("div", { class: "t" }, (i.tipo === "alarme" ? "⏰ " : "🔔 ") + i.texto),
          h("div", { class: "m" }, h("span", { text: new Date(i.quando.replace(" ", "T")).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) }),
            h("span", { text: i.repete }), i.executa ? h("span", { class: "st-chip waiting_user", text: "o assistente faz" }) : null,
            ringing ? h("span", { class: "st-chip failed", text: "esperando você" }) : h("b", { "data-next": String(i.due), text: A.countdown(i.due) })),
          h("div", { class: "row-btns", style: "margin-top:8px" },
            ringing ? h("button", { class: "btn sm primary", type: "button", text: "Dispensar", onclick: () => this.act(i.id, "dismiss") }) : null,
            h("button", { class: "btn sm", type: "button", text: "+10 min", onclick: () => this.act(i.id, "snooze", { minutes: 10 }) }),
            h("button", { class: "btn sm", type: "button", text: "Apagar", onclick: () => this.remove(i.id) }))));
      }
      this.box.replaceChildren(page("Lembretes", "Avisos e alarmes no PC e no celular, e tarefas que o assistente faz sozinho na hora marcada.", form, list));
    },
    async act(id, path, body) { try { await api("POST", `/api/reminders/${id}/${path}`, body || {}); await this.refresh(); } catch (e) { toast(e.message, "error"); } },
    async remove(id) { try { await api("DELETE", `/api/reminders/${id}`); await this.refresh(); } catch (e) { toast(e.message, "error"); } },
  };

  const automation = {
    box: null,
    render(content) { this.box = content; this.paint(); },
    resync() { if (S.view === "automation") A.refreshState().then(() => this.paint()); },
    paint() {
      if (S.view !== "automation" || !this.box) return;
      const c = (S.state && S.state.checks) || { jobs: [] };
      const g = (S.state && S.state.google) || {};
      const kids = [];
      kids.push(h("div", { class: "card" }, h("h3", { text: "Tudo o que o assistente confere sozinho" }),
        h("p", { class: "desc", style: "margin:0", text: "Enquanto o app está aberto, ele confere e-mails, agenda e encomendas por conta própria. Aqui você vê quando cada uma roda de novo, o que a última achou e pode forçar uma verificação agora." })));
      if (!c.running) {
        kids.push(h("div", { class: "alert err" }, c.connected ? "A rotina de e-mails e agenda está parada. Reabra o app para ligar." : "E-mails e agenda estão desligados porque o Google ainda não está conectado. Conecte em Ajustes › Gmail e Agenda.",
          h("div", { style: "margin-top:8px" }, h("button", { class: "btn sm", type: "button", text: "Ir para Ajustes", onclick: () => A.go("settings") }))));
      }
      const jobs = (c.jobs || []).filter((j) => c.running || j.id === "rastreio");
      const groups = [["E-mail e agenda (Google)", ["triagem", "agenda", "resumo"]], ["Encomendas", ["rastreio"]]];
      for (const [title, ids] of groups) {
        const mine = jobs.filter((j) => ids.includes(j.id));
        if (!mine.length) continue;
        const card = h("div", { class: "card" }, h("h3", { text: title }));
        mine.forEach((j) => card.append(A.checkRow(j)));
        if (ids.includes("rastreio")) card.append(h("div", { class: "row-btns" }, h("button", { class: "btn sm", type: "button", text: "Abrir a aba Encomendas", onclick: () => A.go("tracking") })));
        kids.push(card);
      }
      this.box.replaceChildren(page("Automação", "Verificações em segundo plano e quando rodam de novo.", ...kids));
    },
  };

  // =================================================================== HISTÓRICO

  function evRow(showTask) {
    return (e) => {
      const d = new Date(e.t * 1000);
      const task = showTask && e.task ? (S.tasks.find((t) => t.id === e.task) || {}).title : "";
      return h("div", { class: "ev " + e.kind }, h("time", { text: d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) }), h("span", { class: "k" }),
        h("div", { class: "tx" }, e.text, task ? h("span", { style: "color:var(--faint)", text: "  · " + task }) : null));
    };
  }

  const FILTERS = [["", "Tudo"], ["acao,resultado", "Ações"], ["plano,tarefa", "Planos"], ["pergunta", "Pedidos"], ["erro", "Erros"]];
  const activity = {
    kinds: "", timer: 0, box: null,
    async render(content) {
      this.box = content;
      if (!S.tasks.length) { try { S.tasks = (await api("GET", "/api/tasks")).tasks; } catch (e) { /* ok */ } }
      await this.load();
      clearInterval(this.timer);
      this.timer = setInterval(() => { if (S.view === "activity") this.load(); else clearInterval(this.timer); }, 15000);
    },
    leave() { clearInterval(this.timer); },
    resync() { if (S.view === "activity") this.load(); },
    async load() {
      let r;
      try { r = await api("GET", `/api/activity?limit=400${this.kinds ? "&kinds=" + encodeURIComponent(this.kinds) : ""}`); } catch (e) { toast(e.message, "error"); return; }
      const seg = h("div", { class: "seg", role: "group", "aria-label": "Filtrar" }, FILTERS.map(([k, l]) => h("button", { type: "button", "aria-pressed": String(k === this.kinds), text: l, onclick: () => { this.kinds = k; this.load(); } })));
      const list = h("div", {});
      let day = "";
      for (const e of r.events) {
        const label = new Date(e.t * 1000).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
        if (label !== day) { day = label; list.append(h("div", { class: "day", text: label })); }
        list.append(evRow(true)(e));
      }
      if (!r.events.length) list.append(h("div", { class: "card" }, h("p", { class: "desc", style: "margin:0", text: "Nada registrado por enquanto. Quando o assistente trabalhar, tudo aparece aqui." })));
      const keep = this.box.querySelector(".scroll"), top = keep ? keep.scrollTop : 0;
      this.box.replaceChildren(page("Histórico", `Tudo o que o assistente planejou e fez. Apaga sozinho depois de ${r.retention_days} dia(s) — ajuste em Ajustes.`,
        h("div", { style: "display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px" }, seg, h("button", { class: "btn sm", type: "button", text: "Limpar histórico", onclick: async () => {
          if (!(await A.confirm("Limpar histórico?", "Apaga o registro de tudo o que o assistente fez. As conversas e tarefas continuam.", "Limpar", true))) return;
          try { await api("DELETE", "/api/activity"); this.load(); } catch (e) { toast(e.message, "error"); }
        } })), list));
      const sc = this.box.querySelector(".scroll"); if (sc) sc.scrollTop = top;
    },
  };

  // =================================================================== MEMÓRIA

  const memory = {
    sel: "perfil.md", data: null, box: null,
    async render(content) {
      this.box = content;
      try { this.data = await api("GET", "/api/memory"); } catch (e) { toast(e.message, "error"); return; }
      this.paint();
    },
    paint() {
      const d = this.data;
      if (!d.files.some((f) => f.name === this.sel)) this.sel = d.files.length ? d.files[0].name : null;
      const file = d.files.find((f) => f.name === this.sel);
      const names = { "perfil.md": "Quem você é", "regras.md": "Regras", "notas.md": "Notas" };
      const list = h("div", { class: "list" }, d.files.map((f) => h("div", { class: "item" + (f.name === this.sel ? " sel" : ""), tabindex: "0", onclick: () => { this.sel = f.name; this.paint(); }, onkeydown: (e) => { if (e.key === "Enter") { this.sel = f.name; this.paint(); } } },
        h("div", { class: "t", text: names[f.name] || f.name }), h("div", { class: "m", text: f.name }))));
      list.append(h("button", { class: "btn sm", type: "button", text: "Novo arquivo", onclick: () => this.newFile() }));
      let editor = h("div");
      if (file) {
        const ta = h("textarea", { class: "editor", spellcheck: "false", "aria-label": "Conteúdo de " + file.name }); ta.value = file.content;
        const save = h("button", { class: "btn primary", type: "button", text: "Salvar", onclick: async () => {
          try { this.data = await api("PUT", "/api/memory/file", { name: file.name, content: ta.value }); toast("Memória salva. O assistente já usa na próxima mensagem.", "ok"); this.paint(); } catch (e) { toast(e.message, "error"); }
        } });
        editor = h("div", { class: "card" }, h("h3", { text: names[file.name] || file.name }),
          h("p", { class: "desc", text: file.name === "perfil.md" ? "Quem você é, seus projetos, jeito de falar e o que importa para você." : file.name === "regras.md" ? "Regras que o assistente sempre segue (o que pode, o que nunca deve fazer, como te responder)." : file.name === "notas.md" ? "Anotações curtas. O assistente também adiciona aqui quando você pede para lembrar de algo." : "Arquivo extra de memória — o assistente lê junto com os outros." }),
          ta, h("div", { class: "row-btns", style: "margin-top:12px" }, save, !file.core ? h("button", { class: "btn danger", type: "button", text: "Apagar arquivo", onclick: async () => {
            if (!(await A.confirm("Apagar arquivo?", `${file.name} será removido da memória.`, "Apagar", true))) return;
            try { this.data = await api("DELETE", `/api/memory/file?name=${encodeURIComponent(file.name)}`); this.paint(); } catch (e) { toast(e.message, "error"); }
          } }) : null));
      }
      const note = h("input", { type: "text", placeholder: "Ex.: Prefiro reuniões à tarde", maxlength: "300", "aria-label": "Nova nota" });
      const add = async () => { if (!note.value.trim()) return; try { this.data = await api("POST", "/api/memory/notes", { text: note.value }); this.paint(); } catch (e) { toast(e.message, "error"); } };
      note.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      const notes = h("div", { class: "card" }, h("h3", { text: "Lembretes rápidos" }), h("p", { class: "desc", text: "Cada linha é um fato curto que o assistente deve lembrar." }),
        h("div", { class: "list", style: "margin-bottom:12px" }, d.notes.length ? d.notes.map((n, i) => h("div", { class: "item", style: "display:flex;gap:10px;align-items:center;cursor:default" }, h("div", { class: "t", style: "white-space:normal;flex:1", text: n.replace(/^-\s*/, "") }),
          h("button", { class: "icon-btn", type: "button", "aria-label": "Esquecer", title: "Esquecer", onclick: async () => { try { this.data = await api("DELETE", `/api/memory/notes/${i + 1}`); this.paint(); } catch (e) { toast(e.message, "error"); } } }, A.icon("x", 16)))) : [h("div", { class: "desc", text: "Nenhum lembrete." })]),
        h("div", { style: "display:flex;gap:8px" }, note, h("button", { class: "btn", type: "button", text: "Adicionar", onclick: add })));
      this.box.replaceChildren(page("Memória", "Tudo o que o assistente sabe sobre você e as regras dele. É tudo texto simples e fica só no seu computador.", h("div", { class: "split" }, list, h("div", {}, editor, notes))));
    },
    newFile() {
      const name = h("input", { type: "text", placeholder: "projetos", maxlength: "36" });
      A.modal({ title: "Novo arquivo de memória", body: h("label", { class: "f" }, h("span", { text: "Nome" }), name, h("small", { text: "Letras, números, espaço e hífen. O .md é adicionado." })), actions: [{ label: "Cancelar" }, { label: "Criar", kind: "primary", run: async () => {
        const n = name.value.trim().replace(/\.md$/i, "") + ".md";
        try { this.data = await api("PUT", "/api/memory/file", { name: n, content: "# " + n.replace(/\.md$/, "") + "\n\n" }); this.sel = n; this.paint(); } catch (e) { toast(e.message, "error"); return false; }
      } }] });
    },
  };

  // =================================================================== AJUSTES

  const SECTIONS = [
    ["Geral", null, [["app.seu_nome", "Seu nome", "text", "Usado na saudação."], ["ia.modelo", "Modelo do Gemini", "text", "Se esse modelo não estiver disponível, o assistente usa os reservas."], ["ia.modelos_reserva", "Modelos reserva", "list", "Um por linha. Usados quando a cota do principal acaba."], ["ia.raciocinio", "Quanto o modelo pensa nas conversas", "select", "Pensar menos responde mais rápido (só modelos Gemini 3).", [["auto", "Automático (o modelo decide)"], ["minimal", "Mínimo (mais rápido)"], ["low", "Baixo"], ["medium", "Médio"], ["high", "Alto (mais lento, mais cuidadoso)"]]], ["ia.raciocinio_pc", "Quanto o modelo pensa ao controlar o PC", "select", "Cada passo é só olhar a tela e escolher o clique: mínimo costuma bastar e acelera muito.", [["auto", "Automático (o modelo decide)"], ["minimal", "Mínimo (mais rápido)"], ["low", "Baixo"], ["medium", "Médio"], ["high", "Alto (mais lento, mais cuidadoso)"]]]]],
    ["Limites da cota", "O Google não informa quanto sobrou: o app conta cada chamada por modelo e aprende o limite real quando o Google recusa. Os números abaixo são o ponto de partida.", [["limites.requisicoes_por_dia", "Requisições por dia", "number"], ["limites.requisicoes_por_minuto", "Requisições por minuto", "number"], ["limites.tokens_por_minuto", "Tokens por minuto", "number"], ["limites.por_modelo", "Limites de cada modelo", "list", "Um por linha: modelo=por_dia,por_minuto,tokens_por_minuto. Os números acima valem para quem não estiver aqui. Quando o Google recusa uma chamada, o app aprende o limite real sozinho."], ["limites.fuso_renovacao", "Fuso da renovação", "text", "A cota gratuita do Google renova à meia-noite do Pacífico (America/Los_Angeles)."], ["limites.hora_renovacao", "Hora da renovação", "text", "No formato 00:00."]]],
    ["Tarefas autônomas", null, [["tarefas.orcamento_de_requisicoes", "Orçamento padrão por tarefa", "number"], ["tarefas.espera_de_aprovacao_minutos", "Esperar sua aprovação por (min)", "number", "Passado esse tempo, o pedido é negado e a tarefa segue por outro caminho."], ["tarefas.retomar_apos_renovacao", "Retomar sozinho depois que a cota renovar", "bool"]]],
    ["Permissões", "Com o modo autônomo desligado, tela, teclado, comandos e envio ao GitHub sempre perguntam no chat.", [["pc.modo_autonomo", "Modo autônomo: usar o PC sem pedir permissão", "bool", "Ele age e você vê tudo no Histórico. Só pergunta se a ação for contra uma regra que você escreveu em Memória › Regras."], ["pc.esconder_janela", "Minimizar esta janela enquanto ele usa o PC", "bool", "Evita que ele digite ou clique no próprio assistente. A janela volta sozinha quando ele termina."], ["pc.confiar_sem_perguntar", "Se o modo autônomo estiver desligado, fazer sem perguntar", "multi", "", [["abrir", "Abrir apps e sites"], ["projeto_escrever", "Escrever na pasta de projetos"]]], ["pc.janela_de_permissao_minutos", "Duração de “permitir por um tempo” (min)", "number"]]],
    ["Projetos", null, [["projetos.pasta", "Pasta dos projetos", "text", "Onde o assistente cria e edita projetos."], ["projetos.repos_permitidos", "Repositórios onde ele pode enviar (push)", "list", "Um por linha, no formato usuario/repositorio. Vazio = nunca envia."], ["arquivos.pastas_permitidas", "Pastas que ele pode ler (e gravar)", "list", "Um caminho por linha."]]],
    ["Arquivos que ele cria", "Notas, resumos e listas que você pede ficam na pasta de saída. Ele só grava texto e dados (md, txt, csv, json, html…), nunca programas.", [["arquivos.pasta_de_saida", "Pasta de saída", "text", "Nomes sem pasta caem aqui."], ["arquivos.gravar_sem_perguntar", "Gravar arquivos sem pedir permissão", "bool", "Desligado: com o modo autônomo desligado, cada gravação pede a sua confirmação. Ao substituir um arquivo, ele guarda uma cópia .bak."]]],
    ["Histórico", null, [["historico.dias_de_retencao", "Apagar o histórico depois de (dias)", "number"]]],
  ];

  const settings = {
    box: null, values: null, restart: new Set(), access: null,
    async render(content) {
      this.box = content;
      try {
        const [s, a] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/access")]);
        this.values = s.values; this.restart = new Set(s.restart_fields); this.access = a;
      } catch (e) { toast(e.message, "error"); return; }
      await A.refreshState();
      this.paint();
    },
    paint() {
      const inputs = {};
      const cards = [];
      for (const [title, desc, fields] of SECTIONS) {
        const card = h("div", { class: "card" }, h("h3", { text: title }));
        if (desc) card.append(h("p", { class: "desc", text: desc })); else card.append(h("div", { style: "height:10px" }));
        for (const [key, label, type, help, options] of fields) card.append(this.field(inputs, key, label, type, help, options));
        cards.push(card);
      }
      const save = h("button", { class: "btn primary", type: "button", text: "Salvar ajustes", onclick: async (ev) => {
        const changes = {};
        for (const [k, get] of Object.entries(inputs)) { const v = get(); if (JSON.stringify(v) !== JSON.stringify(this.values[k])) changes[k] = v; }
        if (!Object.keys(changes).length) return toast("Nada para salvar.");
        ev.currentTarget.disabled = true;
        try {
          const r = await api("POST", "/api/settings", { changes });
          this.values = r.values;
          toast(r.restart ? "Salvo. Algumas mudanças só valem depois de reabrir o app." : "Salvo.", "ok");
          await A.refreshState(); this.paint();
        } catch (e) { toast(e.message, "error"); ev.currentTarget.disabled = false; }
      } });
      this.box.replaceChildren(page("Ajustes", "Tudo o que você pode mudar sem mexer em arquivos.", this.providersCard(), this.phoneCard(), this.petCard(), this.voiceCard(), this.notifyCard(), this.googleCard(), this.spotifyCard(), ...cards, h("div", { class: "row-btns", style: "position:sticky;bottom:0;padding:12px 0;background:linear-gradient(transparent,var(--bg) 40%)" }, save)));
    },

    field(inputs, key, label, type, help, options) {
      const val = this.values[key];
      const flag = this.restart.has(key) ? " (vale depois de reabrir)" : "";
      const small = (help || flag) ? h("small", { text: (help || "") + flag }) : null;
      if (type === "bool") {
        const cb = h("input", { type: "checkbox", checked: !!val }); inputs[key] = () => cb.checked;
        return h("label", { class: "switch" }, cb, h("span", { text: label }));
      }
      if (type === "multi") {
        const boxes = options.map(([id, l]) => ({ id, el: h("input", { type: "checkbox", checked: (val || []).includes(id) }), l }));
        inputs[key] = () => boxes.filter((b) => b.el.checked).map((b) => b.id);
        return h("div", { style: "margin-bottom:12px" }, h("div", { style: "font-size:13px;color:var(--muted);margin-bottom:6px", text: label }), boxes.map((b) => h("label", { class: "switch", style: "margin-bottom:6px" }, b.el, h("span", { text: b.l }))), small);
      }
      if (type === "select") {
        const sel = h("select", {}, options.map(([id, l]) => h("option", { value: id, text: l })));
        sel.value = val || options[0][0]; inputs[key] = () => sel.value;
        return h("label", { class: "f" }, h("span", { text: label }), sel, small);
      }
      if (type === "list") {
        const ta = h("textarea", { class: "field", style: "min-height:76px;font-family:var(--mono);font-size:13.5px", spellcheck: "false" }); ta.value = (val || []).join("\n");
        inputs[key] = () => ta.value.split("\n").map((x) => x.trim()).filter(Boolean);
        return h("label", { class: "f" }, h("span", { text: label }), ta, small);
      }
      const inp = h("input", { type: type === "number" ? "number" : "text", step: "any", value: val == null ? "" : String(val) });
      inputs[key] = () => (type === "number" ? (inp.value === "" ? "" : Number(inp.value)) : inp.value);
      return h("label", { class: "f" }, h("span", { text: label }), inp, small);
    },

    phoneCard() {
      const a = this.access;
      const card = h("div", { class: "card" }, h("h3", { text: "Usar pelo celular" }),
        h("p", { class: "desc", text: "Com o acesso pela rede ligado, você abre o assistente no iPhone, aprova pedidos e manda tarefas de longe. O computador precisa estar ligado com o app aberto." }));
      const rede = a.mode === "rede";
      const sw = h("input", { type: "checkbox", checked: rede });
      sw.addEventListener("change", async () => {
        try { await api("POST", "/api/settings", { changes: { "app.acesso": sw.checked ? "rede" : "local" } }); toast("Salvo. Feche e abra o app para valer.", "ok"); this.render(this.box); } catch (e) { toast(e.message, "error"); sw.checked = !sw.checked; }
      });
      card.append(h("label", { class: "switch" }, sw, h("span", { text: "Permitir acesso pela rede (celular)" })));
      if (rede) {
        card.append(h("div", { class: "kv" }, h("span", { text: "Código de acesso:" }), h("code", { text: a.code })));
        a.urls.forEach((u) => card.append(h("div", { class: "kv", style: "margin-top:6px" }, h("code", { style: "overflow-wrap:anywhere", text: u }))));
        card.append(h("p", { class: "desc", style: "margin-top:12px", text: "No iPhone, abra um desses endereços no Safari (a mesma rede Wi-Fi) e use Compartilhar › Adicionar à Tela de Início. Para usar fora de casa com segurança (e o microfone), instale o Tailscale no PC e no iPhone e abra o endereço do Tailscale com o mesmo código. Nunca exponha a porta direto na internet." }));
      } else card.append(h("p", { class: "desc", style: "margin:0", text: "Desligado: só este computador acessa." }));
      return card;
    },

    providersCard() {
      const card = h("div", { class: "card" }, h("h3", { text: "Provedores de IA" }),
        h("p", { class: "desc", text: "O Gemini atende primeiro. Se ele acabar a cota, cair ou ficar sem chave, o assistente passa sozinho para o próximo da fila que tiver chave, sem perder a conversa. Marque quem pode ser usado, ajuste a ordem com as setas e cole a chave de cada um (ela fica só no arquivo .env do seu PC). Os limites grátis mudam: confira no site de cada um." }));
      const list = h("div", { class: "prov-list" }, h("p", { class: "desc", text: "Carregando…" }));
      card.append(list);
      let rows = [];                                     // { p, on }
      const saveOrder = async () => {
        const order = rows.filter((r) => r.on).map((r) => r.p.id);
        if (!order.length) { toast("Deixe pelo menos um provedor marcado.", "error"); return; }
        try { const r = await api("POST", "/api/settings", { changes: { "ia.ordem_provedores": order } }); this.values = r.values; paintRows(); } catch (e) { toast(e.message, "error"); }
      };
      const paintRows = () => {
        list.replaceChildren(...rows.map((r, i) => {
          const p = r.p;
          const key = h("input", { type: "password", placeholder: p.local ? "não precisa de chave" : (p.configurada ? "chave guardada (cole outra para trocar)" : "cole a chave aqui"), autocomplete: "off", disabled: p.local });
          const model = h("input", { type: "text", value: p.modelo || "", "aria-label": "Modelo de " + p.nome, spellcheck: "false" });
          const status = h("span", { class: "prov-st " + (p.configurada ? "ok" : ""), text: p.configurada ? "pronto" : "sem chave" });
          const out = h("small", { class: "prov-out" });
          const cb = h("input", { type: "checkbox", checked: r.on });
          cb.addEventListener("change", () => { r.on = cb.checked; saveOrder(); });
          const move = (d) => () => { const j = i + d; if (j < 0 || j >= rows.length) return; [rows[i], rows[j]] = [rows[j], rows[i]]; saveOrder(); };
          const row = h("div", { class: "prov-row" },
            h("div", { class: "prov-head" },
              h("label", { class: "switch", style: "margin:0" }, cb, h("strong", { text: p.nome })),
              p.gratis ? h("span", { class: "prov-tag", text: "grátis" }) : h("span", { class: "prov-tag paid", text: "pago" }),
              p.visao ? h("span", { class: "prov-tag", text: "vê imagens" }) : null, status,
              h("span", { class: "prov-mv" }, h("button", { class: "btn sm", type: "button", text: "↑", "aria-label": "Subir", onclick: move(-1) }), h("button", { class: "btn sm", type: "button", text: "↓", "aria-label": "Descer", onclick: move(1) }))),
            h("small", { class: "desc", text: p.nota + " " }, h("a", { href: p.link, target: "_blank", rel: "noopener", text: "Pegar chave" })),
            h("div", { class: "prov-edit" }, p.id === "gemini" ? null : model, p.local ? null : key,
              h("button", { class: "btn sm", type: "button", text: "Salvar", onclick: async () => {
                try {
                  if (p.id !== "gemini" && model.value.trim() !== (p.modelo || "")) { const r = await api("POST", "/api/settings", { changes: { ["provedores." + p.id + ".modelo"]: model.value.trim() } }); this.values = r.values; }
                  if (key.value.trim()) { await api("POST", "/api/providers/key", { id: p.id, key: key.value.trim() }); key.value = ""; }
                  toast("Salvo.", "ok"); load();
                } catch (e) { toast(e.message, "error"); } } }),
              h("button", { class: "btn sm", type: "button", text: "Testar", onclick: async (ev) => {
                const b = ev.currentTarget; b.disabled = true; out.textContent = "testando…";
                try { const t = await api("POST", "/api/providers/test", { id: p.id }); out.textContent = t.ok ? `Funcionou (${t.segundos} s): ${t.resposta || "ok"}` : t.erro; out.className = "prov-out " + (t.ok ? "good" : "bad"); } catch (e) { out.textContent = e.message; out.className = "prov-out bad"; }
                b.disabled = false; } })),
            out);
          return row;
        }));
      };
      const load = async () => {
        try {
          const d = await api("GET", "/api/providers");
          const byId = Object.fromEntries(d.providers.map((p) => [p.id, p]));
          const used = d.order.map((id) => ({ p: byId[id], on: true })).filter((r) => r.p);
          const rest = d.providers.filter((p) => !d.order.includes(p.id)).map((p) => ({ p, on: false }));
          rows = used.concat(rest); paintRows();
        } catch (e) { list.replaceChildren(h("p", { class: "desc", text: e.message })); }
      };
      load();
      return card;
    },

    petCard() {
      const pr = A.pet ? A.pet.prefs() : { on: true, name: "Mia" };
      const card = h("div", { class: "card" }, h("h3", { text: "Gatinho" }),
        h("p", { class: "desc", text: "Um gatinho pequeno que acompanha o que o assistente faz: pensa, digita quando usa ferramentas, escuta quando você fala, comemora quando termina, fica triste se dá erro e dorme se ficar parado. Clique nele para fazer carinho." }));
      const sw = h("input", { type: "checkbox", checked: pr.on });
      sw.addEventListener("change", () => A.pet.configure({ on: sw.checked }));
      const name = h("input", { type: "text", value: pr.name, maxlength: "20", "aria-label": "Nome do gatinho" });
      name.addEventListener("change", () => { A.pet.configure({ name: name.value }); toast("Nome salvo.", "ok"); });
      card.append(h("label", { class: "switch" }, sw, h("span", { text: "Mostrar o gatinho (vem desligado)" })),
        h("label", { class: "f", style: "margin-top:12px" }, h("span", { text: "Nome dele" }), name),
        h("p", { class: "desc", style: "margin:8px 0 0", text: `Carinhos feitos até agora: ${A.pet ? A.pet.count() : 0}. (Guardado só neste navegador.)` }));
      return card;
    },

    voiceCard() {
      const card = h("div", { class: "card" }, h("h3", { text: "Ativação por voz" }));
      const body = h("div");
      card.append(h("p", { class: "desc", text: "Fale a frase de chamada e o assistente começa a ouvir o seu comando na hora, como a Siri ou o “Ok Google”. Funciona com o app aberto (pode ficar minimizado)." }), body);
      const save = async (changes) => { try { const r = await api("POST", "/api/settings", { changes }); this.values = r.values; await A.refreshState(); } catch (e) { toast(e.message, "error"); } };
      const paint = () => {
        const v = (S.state && S.state.voice) || {};
        const kids = [];
        const deps = v.deps || {};
        const missing = Object.keys(deps).filter((k) => !deps[k]);
        if (missing.length) {
          kids.push(h("p", { class: "desc" }, "Falta instalar: ", h("code", { text: missing.join(", ") }), ". Feche o app e rode ", h("code", { text: "pip install -r requirements.txt" }), ". Depois reabra."));
        }
        if (v.model_download) {
          kids.push(h("p", { class: "desc", text: `Baixando o modelo de voz… ${v.model_download.percent}%` }));
        } else if (!v.model_ready) {
          kids.push(h("p", { class: "desc", text: "Falta o modelo de voz em português (≈ 30 MB, baixado uma vez, fica no seu computador)." }),
            h("button", { class: "btn primary", type: "button", text: "Baixar modelo de voz", onclick: async () => { try { await api("POST", "/api/voice/model"); } catch (e) { toast(e.message, "error"); } } }));
        } else kids.push(h("p", { class: "desc", text: "Modelo de voz instalado." }));
        const on = h("input", { type: "checkbox", checked: !!v.enabled });
        on.addEventListener("change", async () => { await save({ "voz.ativada": on.checked }); });
        kids.push(h("label", { class: "switch", style: "margin:8px 0" }, on, h("span", { text: "Ouvir a frase de chamada" })));
        if (v.enabled) {
          const text = { off: "Desligada.", listening: "Ouvindo…", idle: "Ouvindo…", recording: "Gravando o seu comando…", processing: "Entendendo…", paused: "Em pausa.", error: "Problema: " + (v.detail || "") }[v.state] || "";
          kids.push(h("p", { class: "desc", style: v.state === "error" ? "color:var(--err)" : "", text: text }));
        }
        const phrase = h("input", { type: "text", value: v.phrase || "ei assistente", maxlength: "40" });
        kids.push(h("label", { class: "f" }, h("span", { text: "Frase de chamada" }), phrase,
          h("small", { text: "Precisa ser palavras que existam no modelo de voz; se não existirem, o app avisa. Frases de 2 a 3 palavras funcionam melhor. Marcas estrangeiras (“Siri”, “Google”) costumam não ser entendidas." })));
        kids.push(h("button", { class: "btn", type: "button", text: "Salvar frase", onclick: () => save({ "voz.frase_de_ativacao": phrase.value.trim() }) }));
        const spk = h("input", { type: "checkbox", checked: v.speak_reply !== false });
        spk.addEventListener("change", () => save({ "voz.falar_resposta": spk.checked }));
        kids.push(h("label", { class: "switch", style: "margin-top:12px" }, spk, h("span", { text: "Ler a resposta em voz alta quando eu pedir por voz" })));
        const tr = h("select", {}, h("option", { value: "gemini", text: "Gemini (acerta mais, gasta 1 requisição por comando)" }), h("option", { value: "local", text: "Local (grátis e sem internet, erra mais)" }));
        tr.value = v.transcription || "gemini";
        tr.addEventListener("change", () => save({ "voz.transcricao": tr.value }));
        kids.push(h("label", { class: "f", style: "margin-top:12px" }, h("span", { text: "Entender o comando com" }), tr));
        kids.push(h("p", { class: "desc", style: "margin:12px 0 0", text: "Privacidade: a frase de chamada é reconhecida no seu computador e o que você fala fora dela é descartado na hora. Só o trecho depois da chamada é transcrito (pelo Gemini, se você escolher essa opção). Use fones ou fale perto do microfone; a escuta pausa sozinha enquanto o assistente fala." }));
        body.replaceChildren(...kids);
      };
      paint();
      const listener = () => { if (!card.isConnected) { A.voiceListeners = (A.voiceListeners || []).filter((f) => f !== listener); return; } const a = document.activeElement; if (!(a && body.contains(a) && a.tagName === "INPUT" && a.type === "text")) paint(); };
      A.voiceListeners = [...(A.voiceListeners || []), listener];
      return card;
    },

    notifyCard() {
      const topic = this.values["notificacoes.ntfy_topico"];
      const card = h("div", { class: "card" }, h("h3", { text: "Avisos no celular" }),
        h("p", { class: "desc", text: "Receba no iPhone um aviso quando o assistente precisar de você ou terminar algo. Usa o app gratuito ntfy: instale, toque em “+” e assine o tópico abaixo. Quem souber o nome do tópico lê os avisos — por isso ele é aleatório e não contém dados sensíveis." }));
      if (topic) card.append(h("div", { class: "kv", style: "margin-bottom:12px" }, h("span", { text: "Tópico:" }), h("code", { text: topic })));
      const row = h("div", { class: "row-btns" },
        h("button", { class: "btn", type: "button", text: topic ? "Gerar outro tópico" : "Ativar avisos", onclick: async () => {
          try { await api("POST", "/api/notify/topic"); toast("Tópico criado.", "ok"); this.render(this.box); } catch (e) { toast(e.message, "error"); }
        } }),
        topic ? h("button", { class: "btn", type: "button", text: "Enviar teste", onclick: async () => { try { const r = await api("POST", "/api/notify/test"); toast(r.sent ? "Teste enviado." : "Não consegui enviar. Veja a internet.", r.sent ? "ok" : "error"); } catch (e) { toast(e.message, "error"); } } }) : null);
      card.append(row);
      const tog = [["notificacoes.avisar_pedidos", "Quando precisar da minha aprovação ou resposta"], ["notificacoes.avisar_conclusao", "Quando terminar uma tarefa"], ["notificacoes.avisar_pausas", "Quando pausar (cota ou orçamento)"], ["notificacoes.avisar_erros", "Quando uma tarefa falhar"]];
      if (topic) {
        card.append(h("div", { style: "margin-top:14px" }, tog.map(([k, l]) => {
          const cb = h("input", { type: "checkbox", checked: !!this.values[k] });
          cb.addEventListener("change", async () => { try { const r = await api("POST", "/api/settings", { changes: { [k]: cb.checked } }); this.values = r.values; } catch (e) { toast(e.message, "error"); cb.checked = !cb.checked; } });
          return h("label", { class: "switch", style: "margin-bottom:8px" }, cb, h("span", { text: l }));
        })));
      }
      return card;
    },

    googleCard() {
      const g = S.state.google || {};
      const card = h("div", { class: "card" }, h("h3", { text: "Gmail e Agenda" }));
      if (g.connected) {
        card.append(h("p", { class: "desc", text: g.running ? "Conectado. A triagem de e-mails (a cada 15 min), o resumo diário e a análise da agenda rodam sozinhos enquanto o app estiver aberto." : "Conectado. Reabra o app para ligar a rotina automática." }),
          h("p", { class: "desc", text: "Para pedir agora, é só falar no chat: “resuma meus e-mails”, “marque dentista amanhã às 15h”, “responda o e-mail da Maria dizendo que sim” (vira rascunho no seu Gmail)." }));
        if (!g.calendar_write) card.append(h("div", { class: "alert warn" }, "A agenda está conectada só para leitura. Para o assistente criar e mudar eventos, reconecte e aceite a nova permissão. ",
          h("button", { class: "btn sm", type: "button", text: "Reconectar para permitir criar eventos", onclick: async () => { try { await api("POST", "/api/google/connect", { reauth: true }); toast("Autorize no navegador que abriu…"); } catch (e) { toast(e.message, "error"); } } })));
        const send = h("input", { type: "checkbox", checked: !!g.send_email });
        send.addEventListener("change", async () => { try { await api("POST", "/api/settings", { changes: { "google.permitir_enviar_email": send.checked } }); await A.refreshState(); toast(send.checked ? "Ele agora pode enviar e-mails sozinho." : "Ele só prepara rascunhos.", "ok"); } catch (e) { toast(e.message, "error"); send.checked = !send.checked; } });
        card.append(h("label", { class: "switch" }, send, h("span", { text: "Permitir que ele ENVIE e-mails sozinho (desligado = só cria rascunhos para você enviar)" })));
      } else if (!g.credentials) {
        card.append(h("p", { class: "desc", style: "margin:0" }, "Falta o arquivo ", h("code", { text: "credentials.json" }), " na pasta do projeto. Ele é criado no Google Cloud (grátis) — veja o passo 4 do README. Depois volte aqui e clique em Conectar."));
      } else {
        card.append(h("p", { class: "desc", text: "Vai abrir o navegador para você entrar na sua conta Google e autorizar. (Se aparecer “app não verificado”, é o seu próprio app: Avançado › continuar.)" }),
          h("button", { class: "btn primary", type: "button", text: "Conectar Google", onclick: async () => {
            try { await api("POST", "/api/google/connect"); toast("Autorize no navegador que abriu…"); } catch (e) { toast(e.message, "error"); }
          } }));
      }
      return card;
    },

    spotifyCard() {
      const sp = S.state.spotify || {};
      const card = h("div", { class: "card" }, h("h3", { text: "Spotify" }));
      if (!sp.configured) {
        card.append(h("p", { class: "desc", style: "margin:0" }, "Para tocar músicas é preciso uma conta Premium e um app no ", h("code", { text: "developer.spotify.com" }), ". Coloque o ", h("code", { text: "SPOTIFY_CLIENT_ID" }), " no arquivo ", h("code", { text: ".env" }), " (veja o README) e reabra o app."));
        return card;
      }
      card.append(h("p", { class: "desc", text: sp.connected ? "Conectado. Peça “toque tal música” no chat." : "Ainda não conectado. Vai abrir o navegador para você autorizar." }),
        h("button", { class: "btn" + (sp.connected ? "" : " primary"), type: "button", text: sp.connected ? "Conectar de novo" : "Conectar Spotify", onclick: async () => {
          try { await api("POST", "/api/spotify/connect"); toast("Autorize no navegador que abriu…"); } catch (e) { toast(e.message, "error"); }
        } }));
      return card;
    },
  };

  A.views.home = home; A.views.reminders = reminders; A.views.automation = automation; A.views.tracking = tracking; A.views.tasks = tasks; A.views.activity = activity; A.views.memory = memory; A.views.settings = settings;
})();
