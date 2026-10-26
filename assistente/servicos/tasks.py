"""Tarefas autônomas: você entrega um projeto e o assistente trabalha sozinho, em fila.

Garantias:
- uma tarefa por vez, na ordem de chegada;
- cada tarefa tem um PERFIL de permissões e um ORÇAMENTO de chamadas ao Gemini;
- se a cota do dia acabar, a tarefa PAUSA e continua sozinha na renovação;
- ações fora do perfil viram pedidos de aprovação (a tarefa espera, com prazo);
- tudo é salvo em disco: se o app fechar, a tarefa volta para a fila ao reabrir;
- nada de loops infinitos: limite de passos, de orçamento e de tentativas de rede.
"""
import json
import threading
import time
import uuid
from pathlib import Path

from assistente.ia import agent, agent_tools, agentes, context, gemini
from assistente.nucleo import activity, permissions, usage, workspace

DATA = Path("data")
TASK_DIR = DATA / "tasks"
ID_RE = __import__("re").compile(r"^[0-9a-f]{10}$")

ACTIVE = {"running", "waiting_approval"}
RUNNABLE = {"queued"}
FINAL = {"done", "failed", "stopped"}
STATUS_LABELS = {
    "queued": "Na fila", "running": "Trabalhando", "waiting_approval": "Esperando sua aprovação",
    "waiting_user": "Esperando sua resposta", "paused_quota": "Pausada (cota do dia acabou)",
    "paused_budget": "Pausada (orçamento esgotado)", "done": "Concluída", "failed": "Falhou", "stopped": "Parada",
}
QUOTA_MAX_WAIT = 120          # espera curta (limite por minuto); acima disso pausa até a renovação
NETWORK_RETRIES = 15          # 15 x 60s sem internet antes de falhar
RESUME_MARGIN = 90            # segundos depois da renovação para retomar
MAX_PROMPT = 8000


class TaskError(Exception):
    pass


class TaskNotFound(TaskError):
    pass


def _check_id(tid):
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise TaskError("Tarefa inválida.")


class TaskManager:
    def __init__(self, cfg, bus=None, notifier=None, window_hooks=None, clock=time.time, sleep=None,
                 start_thread=True, live=None):
        self.cfg = cfg
        self.live = live
        self.bus = bus
        self.notifier = notifier
        self.window_hooks = window_hooks or {}
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._stops = {}                 # id -> Event
        self._approvals = {}             # req_id -> {"event", "answer", "task"}
        self._shutdown = threading.Event()
        self._sleep_override = sleep
        self.policy = permissions.Policy(cfg)
        t = (cfg.get("tarefas") or {})
        self.default_budget = int(t.get("orcamento_de_requisicoes", 60))
        self.approval_wait = float(t.get("espera_de_aprovacao_minutos", 45)) * 60
        self.auto_resume = bool(t.get("retomar_apos_renovacao", True))
        self.keep_days = float(t.get("dias_para_manter_concluidas", 14))
        self.context_limit = int((cfg.get("ia") or {}).get("limite_de_contexto_tokens", context.DEFAULT_LIMIT_TOKENS))
        self.tasks = {}
        self.current = None              # id da tarefa em execução
        self._load_all()
        self._thread = None
        if start_thread:
            self.start()

    # ---- persistência ---------------------------------------------------------------

    def _path(self, tid):
        return TASK_DIR / f"{tid}.json"

    def _save(self, task):
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        task["updated"] = self._clock()
        tmp = self._path(task["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(task["id"]))

    def _load_all(self):
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        for p in TASK_DIR.glob("*.json"):
            try:
                task = json.loads(p.read_text(encoding="utf-8"))
                _check_id(task["id"])
            except (OSError, ValueError, KeyError, TaskError):
                continue
            if task.get("status") in ACTIVE:    # o app foi fechado no meio: volta para a fila
                task["status"] = "queued"
                task["pending"] = None
                task.setdefault("notes", []).append("Retomada depois que o app foi reaberto.")
                self._save(task)
            self.tasks[task["id"]] = task

    def prune(self, now=None) -> int:
        now = self._clock() if now is None else now
        cutoff = now - self.keep_days * 86400
        removed = 0
        with self._lock:
            for tid in [t for t, k in self.tasks.items() if k["status"] in FINAL and k.get("updated", now) < cutoff]:
                self._path(tid).unlink(missing_ok=True)
                del self.tasks[tid]
                removed += 1
        return removed

    # ---- visão para a interface -----------------------------------------------------

    def public(self, task, with_contents=False) -> dict:
        out = {k: v for k, v in task.items() if k != "contents"}
        out["status_label"] = STATUS_LABELS.get(task["status"], task["status"])
        out["budget_left"] = max(0, task["budget"] - task["requests"])
        if with_contents:
            out["messages"] = context.render_transcript(task["contents"], 30000)
        return out

    def list(self):
        with self._lock:
            return sorted((self.public(t) for t in self.tasks.values()), key=lambda t: t["created"], reverse=True)

    def get(self, tid) -> dict:
        _check_id(tid)
        with self._lock:
            if tid not in self.tasks:
                raise TaskNotFound("Tarefa não encontrada.")
            return self.public(self.tasks[tid], with_contents=True)

    def pending_approvals(self):
        with self._lock:
            return [t["pending"] for t in self.tasks.values() if t.get("pending")]

    def _publish(self, event):
        if self.bus:
            self.bus.publish(event)

    def _changed(self, task):
        self._save(task)
        self._publish({"type": "task_update", "task": self.public(task)})

    def _notify(self, kind, title, message, priority=3):
        if self.notifier:
            try:
                self.notifier.notify(kind, title, message, priority)
            except Exception:
                pass

    def _set_status(self, task, status, **fields):
        with self._lock:
            task["status"] = status
            task.update(fields)
            self._changed(task)
            self._wake.notify_all()

    # ---- ações do usuário -----------------------------------------------------------

    def create(self, title: str, prompt: str, profile: str = "leitura", budget: int = None, agent_id: str = None) -> dict:
        title = " ".join((title or "").split())[:80]
        prompt = (prompt or "").strip()
        if not prompt:
            raise TaskError("Descreva o que a tarefa deve fazer.")
        if len(prompt) > MAX_PROMPT:
            raise TaskError(f"Descrição longa demais (máximo {MAX_PROMPT} caracteres).")
        if profile not in permissions.PROFILES:
            raise TaskError("Perfil de permissões inválido.")
        agent_id = agent_id or agentes.DEFAULT
        if not agentes.exists(agent_id) or agentes.get(agent_id)["especial"]:
            raise TaskError("Esse agente não pode ser usado em tarefas.")
        title = title or (prompt[:60] + ("…" if len(prompt) > 60 else ""))
        budget = self.default_budget if budget is None else max(1, min(int(budget), 1000))
        tid = uuid.uuid4().hex[:10]
        task = {"id": tid, "title": title, "prompt": prompt, "profile": profile,
                "agent": agent_id, "granted": sorted(permissions.grants_for(profile)), "status": "queued", "created": self._clock(),
                "updated": self._clock(), "budget": budget, "requests": 0, "plan": [], "summary": "", "error": "",
                "question": "", "pending": None, "resume_at": None, "quota_strikes": 0, "notes": [],
                "project": f"{workspace.slugify(title)}-{tid[:4]}", "contents": []}
        with self._lock:
            self.tasks[tid] = task
            self._changed(task)
            self._wake.notify_all()
        activity.log("tarefa", f"Nova tarefa na fila: {title}", task=tid, perfil=profile)
        return self.public(task)

    def stop(self, tid):
        _check_id(tid)
        with self._lock:
            task = self.tasks.get(tid)
            if not task:
                raise TaskNotFound("Tarefa não encontrada.")
            if task["status"] in FINAL:
                return self.public(task)
            ev = self._stops.get(tid)
            if task["status"] in ACTIVE and ev is not None:
                ev.set()                                   # o executor finaliza e marca como parada
                for _req_id, a in list(self._approvals.items()):
                    if a["task"] == tid:
                        a["answer"] = "deny"
                        a["event"].set()
            else:
                task["pending"] = None
                self._set_status(task, "stopped")
                activity.log("info", "Tarefa parada pelo usuário.", task=tid)
            return self.public(task)

    def resume(self, tid, extra_budget: int = 0):
        """Retoma uma tarefa pausada ou parada (opcionalmente liberando mais chamadas)."""
        _check_id(tid)
        with self._lock:
            task = self.tasks.get(tid)
            if not task:
                raise TaskNotFound("Tarefa não encontrada.")
            if task["status"] not in ("paused_quota", "paused_budget", "stopped", "failed"):
                raise TaskError("Esta tarefa não está pausada.")
            if extra_budget:
                task["budget"] += max(0, min(int(extra_budget), 1000))
            if task["requests"] >= task["budget"]:
                task["budget"] = task["requests"] + (self.default_budget // 2 or 10)
            task.update(error="", resume_at=None, quota_strikes=0)
            self._stops.pop(tid, None)
            self._set_status(task, "queued")
        activity.log("info", "Tarefa retomada pelo usuário.", task=tid)
        return self.public(task)

    def answer(self, tid, text: str):
        """Responde a uma pergunta (pedir_ajuda) ou dá uma nova instrução a uma tarefa parada."""
        _check_id(tid)
        text = (text or "").strip()
        if not text:
            raise TaskError("Escreva a resposta.")
        with self._lock:
            task = self.tasks.get(tid)
            if not task:
                raise TaskNotFound("Tarefa não encontrada.")
            if task["status"] not in ("waiting_user", "stopped", "paused_budget", "paused_quota", "failed", "done"):
                raise TaskError("Esta tarefa não está esperando resposta.")
            task["contents"].append({"role": "user", "parts": [{"text": text[:MAX_PROMPT]}]})
            task.update(question="", error="", summary="" if task["status"] == "done" else task["summary"],
                        resume_at=None, quota_strikes=0)
            if task["requests"] >= task["budget"]:
                task["budget"] = task["requests"] + (self.default_budget // 2 or 10)
            self._stops.pop(tid, None)
            self._set_status(task, "queued")
        activity.log("info", f"Resposta do usuário: {text[:200]}", task=tid)
        return self.public(task)

    def delete(self, tid):
        _check_id(tid)
        with self._lock:
            task = self.tasks.get(tid)
            if not task:
                return
            if task["status"] in ACTIVE:
                raise TaskError("Pare a tarefa antes de apagar.")
            self._path(tid).unlink(missing_ok=True)
            del self.tasks[tid]
        self._publish({"type": "task_removed", "id": tid})

    def approve(self, req_id: str, answer: str) -> bool:
        if answer not in ("allow", "deny", "always"):
            raise TaskError("Resposta inválida.")
        with self._lock:
            a = self._approvals.get(req_id)
            if not a:
                return False
            a["answer"] = answer
            a["event"].set()
            return True

    def raise_budget(self, tid, extra: int):
        return self.resume(tid, extra)

    # ---- executor ---------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._worker, name="tarefas", daemon=True)
        self._thread.start()

    def shutdown(self, wait: float = 5.0):
        self._shutdown.set()
        with self._lock:
            for ev in self._stops.values():
                ev.set()
            for a in self._approvals.values():
                a["answer"] = "deny"
                a["event"].set()
            self._wake.notify_all()
        if self._thread:
            self._thread.join(wait)

    def _sleep(self, tid, seconds: float) -> bool:
        """Espera de forma interrompível. Retorna True se foi interrompida (parar/fechar)."""
        if self._sleep_override:
            self._sleep_override(seconds)
            ev = self._stops.get(tid)
            return bool(self._shutdown.is_set() or (ev and ev.is_set()))
        ev = self._stops.setdefault(tid, threading.Event())
        end = time.time() + seconds
        while time.time() < end:
            if ev.wait(min(1.0, max(0.0, end - time.time()))) or self._shutdown.is_set():
                return True
        return False

    def _next(self):
        now = self._clock()
        with self._lock:
            ready = [t for t in self.tasks.values()
                     if t["status"] in RUNNABLE
                     or (t["status"] == "paused_quota" and self.auto_resume and t.get("resume_at") and t["resume_at"] <= now)]
            return min(ready, key=lambda t: t["created"]) if ready else None

    def run_once(self) -> bool:
        """Executa a próxima tarefa pronta (se houver). Retorna True se executou alguma."""
        task = self._next()
        if task is None:
            return False
        try:
            self._run(task)
        except Exception as e:  # nunca deixa o executor morrer
            with self._lock:
                self._set_status(task, "failed", error=f"Erro interno: {type(e).__name__}: {e}"[:400])
            activity.log("erro", f"Erro interno na tarefa: {e}", task=task["id"])
        finally:
            self.current = None
            if self.live is not None:
                self.live.unregister("task", task["id"])
        return True

    def _worker(self):
        last_prune = 0.0
        while not self._shutdown.is_set():
            if not self.run_once():
                with self._lock:
                    self._wake.wait(timeout=5.0)
                if self._clock() - last_prune > 3600:
                    self.prune()
                    last_prune = self._clock()

    def _make_hooks(self, task):
        def on_plan(steps):
            with self._lock:
                task["plan"] = [{"text": s, "status": "pendente", "note": ""} for s in steps]
                self._changed(task)
            activity.log("plano", " | ".join(f"{i}. {s}" for i, s in enumerate(steps, 1)), task=task["id"])

        def on_step(n, status, note):
            with self._lock:
                if not 1 <= n <= len(task["plan"]):
                    raise ValueError(f"Não existe o passo {n} (o plano tem {len(task['plan'])}).")
                task["plan"][n - 1].update(status=status, note=note[:200])
                self._changed(task)
            activity.log("plano", f"Passo {n}: {status}" + (f" — {note}" if note else ""), task=task["id"])

        def on_finish(summary):
            activity.log("resultado", f"Tarefa concluída: {summary}", task=task["id"])

        def on_help(question):
            activity.log("pergunta", question, task=task["id"])

        hooks = {"on_plan": on_plan, "on_step": on_step, "on_finish": on_finish, "on_help": on_help}
        hooks.update({k: v for k, v in self.window_hooks.items() if k in ("hide_window", "show_window")})
        return hooks

    def _approval_fn(self, task, stop):
        def ask(req):
            req_id = req["id"]
            ev = threading.Event()
            entry = {"event": ev, "answer": "deny", "task": task["id"]}
            with self._lock:
                self._approvals[req_id] = entry
                task["pending"] = {**req, "task": task["id"], "task_title": task["title"], "asked": self._clock()}
                self._set_status(task, "waiting_approval")
            self._notify("pedido", "Aprovação pendente", f"{task['title']}: {req['summary']}"[:200], 4)
            deadline = time.time() + self.approval_wait
            try:
                while not ev.wait(max(0.01, min(1.0, deadline - time.time()))):
                    if stop.is_set() or self._shutdown.is_set():
                        return "deny"
                    if time.time() >= deadline:
                        raise agent.ApprovalTimeout()
                return entry["answer"]
            finally:
                with self._lock:
                    self._approvals.pop(req_id, None)
                    task["pending"] = None
                    if task["status"] == "waiting_approval":
                        self._set_status(task, "running")
        return ask

    def _emit_fn(self, task):
        def emit(event):
            if event.get("type") == "error" and event.get("kind") == "max_steps":
                return  # em tarefas o executor continua sozinho
            self._publish({**event, "scope": "task", "task_id": task["id"]})
        return emit

    def _run(self, task):
        tid = task["id"]
        self.current = tid
        stop = self._stops[tid] = threading.Event()
        contents = task["contents"]
        if not contents:
            contents.append({"role": "user", "parts": [{"text": self._first_turn(task)}]})
        context.repair_contents(contents)
        self._set_status(task, "running", error="", resume_at=None)
        activity.log("tarefa", f"Começou: {task['title']}", task=tid)

        ctx = agent_tools.ToolContext(self.cfg, mode="task", project=task["project"], hooks=self._make_hooks(task))
        spec = agentes.get(task.get("agent"))
        registry = agent_tools.Registry(ctx, spec["fora"])
        granted = set(task["granted"])

        def on_grant(category):
            with self._lock:
                if category not in task["granted"]:
                    task["granted"] = sorted(set(task["granted"]) | {category})
                    self._save(task)

        def on_request():
            with self._lock:
                if task["requests"] >= task["budget"]:
                    raise agent.BudgetExceeded()
                task["requests"] += 1
                self._save(task)

        gate = self.live.register("task", tid, task["title"], stop) if self.live is not None else None
        engine = agent.Engine(self.cfg, registry, self.policy, mode="task", emit=self._emit_fn(task), gate=gate,
                              ask_approval=self._approval_fn(task, stop), stop_event=stop, granted=granted,
                              task_id=tid, on_request=on_request, on_grant=on_grant)
        model = (self.cfg.get("ia") or {}).get("modelo", "gemini-3.8-flash")
        empties = network = 0
        system = agent.build_system_prompt(self.cfg, "task", task["project"], task, agent=spec["id"])

        while True:
            if stop.is_set() or self._shutdown.is_set():
                return self._finish(task, "stopped", "", stopped=True)
            counted = False
            try:
                if context.needs_compaction(contents, self.context_limit):
                    new, summary = context.compact(contents, model)
                    if summary:
                        contents[:] = new
                        activity.log("info", "Histórico da tarefa resumido para economizar cota.", task=tid)
                counted = True       # a partir daqui cada chamada do motor passa pelo orçamento
                result = engine.run(contents, system)
                network = 0
                with self._lock:
                    task["quota_strikes"] = 0
                    self._save(task)
            except agent.BudgetExceeded:
                self._set_status(task, "paused_budget", error=f"Usou as {task['budget']} chamadas liberadas.")
                activity.log("info", "Orçamento de chamadas esgotado; tarefa pausada.", task=tid)
                self._notify("pausa", "Tarefa pausada", f"{task['title']}: orçamento esgotado. Libere mais para continuar.")
                return
            except gemini.GeminiError as e:
                if counted:  # a chamada que falhou não gerou resposta: não gasta orçamento
                    with self._lock:
                        task["requests"] = max(0, task["requests"] - 1)
                        self._save(task)
                if self._handle_gemini_error(task, e, stop, network) == "retry":
                    network += 1 if e.kind in ("network", "server") else 0
                    continue
                return
            with self._lock:
                self._save(task)

            if result == "stopped":
                return self._finish(task, "stopped", "", stopped=True)
            if result == "finished":
                return self._finish(task, "done", ctx.control["finished"])
            if result == "help":
                self._set_status(task, "waiting_user", question=ctx.control["help"])
                ctx.control["help"] = None
                self._notify("pedido", "Tarefa precisa de você", f"{task['title']}: {task['question']}"[:200], 4)
                return
            if result == "done":
                text = "".join(p.get("text", "") for p in contents[-1].get("parts", []) if not p.get("thought")).strip()
                return self._finish(task, "done", text or "Terminou sem resumo.")
            if result == "empty":
                empties += 1
                if empties >= 2:
                    return self._finish(task, "failed", "", error="O modelo não respondeu duas vezes seguidas.")
            # max_steps: segue o laço (o orçamento é quem limita)

    def _first_turn(self, task):
        label = permissions.PROFILE_LABELS[task["profile"]]
        return (f"TAREFA: {task['title']}\n\n{task['prompt']}\n\n"
                f"Pasta do projeto: {task['project']}\nPermissões: {label}\n"
                f"Orçamento: até {task['budget']} chamadas ao modelo. Comece pelo plano.")

    def _finish(self, task, status, summary, error="", stopped=False):
        with self._lock:
            task["pending"] = None
            self._set_status(task, status, summary=summary or "", error=error)
        if status == "done":
            activity.log("resultado", f"Concluída: {summary}", task=task["id"])
            self._notify("pronta", "Tarefa concluída", f"{task['title']}: {summary}"[:200])
        elif status == "failed":
            activity.log("erro", f"Falhou: {error}", task=task["id"])
            self._notify("erro", "Tarefa falhou", f"{task['title']}: {error}"[:200], 4)
        elif stopped:
            activity.log("info", "Tarefa parada.", task=task["id"])

    def _handle_gemini_error(self, task, e, stop, network_count):
        """Retorna 'retry' (tentar de novo) ou 'end' (a tarefa já foi atualizada)."""
        tid = task["id"]
        if e.kind == "quota":
            with self._lock:
                task["quota_strikes"] += 1
                strikes = task["quota_strikes"]
            wait = e.retry_after if e.retry_after else 65
            if wait <= QUOTA_MAX_WAIT and strikes <= 3:
                activity.log("info", f"Limite por minuto atingido; esperando {int(wait)}s.", task=tid)
                return self._interrupted(task) if self._sleep(tid, wait + 2) else "retry"
            nxt = usage.summary(self.cfg)["reset_epoch"] + RESUME_MARGIN
            self._set_status(task, "paused_quota", resume_at=nxt, error="A cota gratuita do dia acabou.")
            activity.log("info", "Cota do dia esgotada; a tarefa continua sozinha na renovação.", task=tid)
            self._notify("pausa", "Tarefa pausada", f"{task['title']}: cota do dia acabou. Volta sozinha na renovação.")
            return "end"
        if e.kind in ("network", "server"):
            if network_count >= NETWORK_RETRIES:
                self._finish(task, "failed", "", error=f"Sem conexão com o Gemini por muito tempo: {e}")
                return "end"
            activity.log("info", f"Sem conexão; tentando de novo em 60s ({e}).", task=tid)
            return self._interrupted(task) if self._sleep(tid, 60) else "retry"
        self._finish(task, "failed", "", error=str(e)[:400])
        return "end"

    def _interrupted(self, task):
        if task["status"] not in FINAL:
            self._finish(task, "stopped", "", stopped=True)
        return "end"
