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
      let profile = Object.keys(profiles).includes("projeto") ? "projeto" : Object.keys(profiles)[0];
      const opts = Object.entries(profiles).map(([id, label]) => {
        const [name, desc] = splitLabel(label);
        return h("label", { class: "profile-opt" }, h("input", { type: "radio", name: "profile", value: id, checked: id === profile, onchange: () => { profile = id; } }), h("div", {}, h("b", { text: name }), h("span", { text: desc })));
      });
      const body = h("div", {}, h("label", { class: "f" }, h("span", { text: "O que fazer" }), prompt), h("label", { class: "f" }, h("span", { text: "Título" }), title),
        h("div", { style: "margin-bottom:12px" }, h("div", { style: "font-size:13px;color:var(--muted);margin-bottom:6px", text: "O que ele pode fazer sozinho" }), h("div", { style: "display:flex;flex-direction:column;gap:8px" }, opts)),
        h("label", { class: "f" }, h("span", { text: "Orçamento de requisições" }), budget, h("small", { text: "Limite de chamadas à IA para esta tarefa, para ela não gastar a cota do dia inteira." })));
      A.modal({ title: "Nova tarefa", body, wide: true, actions: [{ label: "Cancelar" }, { label: "Começar", kind: "primary", run: async () => {
        try { const t = await api("POST", "/api/tasks", { title: title.value, prompt: prompt.value, profile, budget: Number(budget.value) }); this.sel = t.id; toast("Tarefa na fila.", "ok"); } catch (e) { toast(e.message, "error"); return false; }
      } }] });
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
    ["Geral", null, [["app.seu_nome", "Seu nome", "text", "Usado na saudação."], ["ia.modelo", "Modelo do Gemini", "text", "Se esse modelo não estiver disponível, o assistente usa os reservas."], ["ia.modelos_reserva", "Modelos reserva", "list", "Um por linha. Usados quando a cota do principal acaba."]]],
    ["Limites da cota", "O Google não informa quanto sobrou, então o app conta por conta própria. Ajuste conforme a sua conta.", [["limites.requisicoes_por_dia", "Requisições por dia", "number"], ["limites.requisicoes_por_minuto", "Requisições por minuto", "number"], ["limites.tokens_por_minuto", "Tokens por minuto", "number"], ["limites.fuso_renovacao", "Fuso da renovação", "text", "A cota gratuita do Google renova à meia-noite do Pacífico (America/Los_Angeles)."], ["limites.hora_renovacao", "Hora da renovação", "text", "No formato 00:00."]]],
    ["Tarefas autônomas", null, [["tarefas.orcamento_de_requisicoes", "Orçamento padrão por tarefa", "number"], ["tarefas.espera_de_aprovacao_minutos", "Esperar sua aprovação por (min)", "number", "Passado esse tempo, o pedido é negado e a tarefa segue por outro caminho."], ["tarefas.retomar_apos_renovacao", "Retomar sozinho depois que a cota renovar", "bool"]]],
    ["Permissões", "Sem confirmação, só ações de baixo risco acontecem. Tela, teclado, comandos e envio ao GitHub sempre perguntam no chat.", [["pc.confiar_sem_perguntar", "Fazer sem perguntar", "multi", "", [["abrir", "Abrir apps e sites"], ["projeto_escrever", "Escrever na pasta de projetos"]]], ["pc.janela_de_permissao_minutos", "Duração de “permitir por um tempo” (min)", "number"]]],
    ["Projetos", null, [["projetos.pasta", "Pasta dos projetos", "text", "Onde o assistente cria e edita projetos."], ["projetos.repos_permitidos", "Repositórios onde ele pode enviar (push)", "list", "Um por linha, no formato usuario/repositorio. Vazio = nunca envia."], ["arquivos.pastas_permitidas", "Pastas que ele pode ler", "list", "Um caminho por linha."]]],
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
      this.box.replaceChildren(page("Ajustes", "Tudo o que você pode mudar sem mexer em arquivos.", this.phoneCard(), this.notifyCard(), this.spotifyCard(), ...cards, h("div", { class: "row-btns", style: "position:sticky;bottom:0;padding:12px 0;background:linear-gradient(transparent,var(--bg) 40%)" }, save)));
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

  A.views.tasks = tasks; A.views.activity = activity; A.views.memory = memory; A.views.settings = settings;
})();
