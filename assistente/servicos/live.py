"""Ao vivo: o que o assistente está fazendo agora, com pausa e captura da tela (feito para o celular).

Cada resposta do chat e cada tarefa autônoma em andamento se registra aqui. O `Live` acompanha os eventos delas
(ferramentas, textos, aprovações) para mostrar o andamento a qualquer momento, e dá a cada uma um `Gate`: uma trava
que o motor do agente consulta entre um passo e outro. Pausar não interrompe a chamada em curso ao modelo nem a ação
que já começou; o assistente para no PRÓXIMO ponto seguro. Uma pausa esquecida termina sozinha depois de um tempo.
"""
import collections
import threading
import time

MAX_LOG = 14
DEFAULT_MAX_PAUSE = 600          # s: pausa esquecida volta sozinha


class Gate:
    """Trava de pausa consultada pelo motor entre os passos."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._deadline = None
        self._resume = threading.Event()
        self._resume.set()
        self.waiting = False         # o motor está parado nesta trava agora

    @property
    def paused(self) -> bool:
        with self._lock:
            if self._deadline is not None and self._clock() >= self._deadline:
                self._deadline = None
                self._resume.set()
            return not self._resume.is_set()

    def pause(self, max_seconds: float = DEFAULT_MAX_PAUSE):
        with self._lock:
            self._deadline = self._clock() + max(5.0, float(max_seconds))
            self._resume.clear()

    def resume(self):
        with self._lock:
            self._deadline = None
            self._resume.set()

    def wait(self, stop: threading.Event = None, poll: float = 0.2):
        """Bloqueia enquanto estiver pausado. Volta se retomar, se a pausa expirar ou se mandarem parar."""
        if not self.paused:
            return
        self.waiting = True
        try:
            while self.paused:
                if stop is not None and stop.is_set():
                    return
                self._resume.wait(poll)
        finally:
            self.waiting = False


class _Run:
    def __init__(self, key, kind, title, gate, stop, ref):
        self.key, self.kind, self.title, self.gate, self.stop, self.ref = key, kind, title, gate, stop, ref
        self.started = time.time()
        self.log = collections.deque(maxlen=MAX_LOG)
        self.current = "Começando…"
        self.text = ""
        self.waiting_approval = False


class Live:
    def __init__(self, bus=None):
        self._lock = threading.RLock()
        self._runs = {}
        self._bus = bus
        self._thread = None
        self._q = None

    # -- registro
    def register(self, kind: str, ref: str, title: str, stop: threading.Event = None) -> Gate:
        key = f"{kind}:{ref}"
        gate = Gate()
        with self._lock:
            self._runs[key] = _Run(key, kind, " ".join(str(title or "").split())[:80] or "Sem título", gate, stop, ref)
        self._changed()
        return gate

    def unregister(self, kind: str, ref: str):
        with self._lock:
            run = self._runs.pop(f"{kind}:{ref}", None)
        if run:
            run.gate.resume()
            self._changed()

    def _changed(self):
        if self._bus:
            self._bus.publish({"type": "live_changed"})

    # -- eventos
    def start(self):
        if self._bus is None or self._thread:
            return
        self._q = self._bus.subscribe()
        self._thread = threading.Thread(target=self._loop, name="ao-vivo", daemon=True)
        self._thread.start()

    def stop(self):
        if self._q is not None:
            self._bus.unsubscribe(self._q)
            self._q.put({"type": "_quit"})

    def _loop(self):
        while True:
            ev = self._q.get()
            if ev.get("type") == "_quit":
                return
            try:
                self.feed(ev)
            except Exception:
                pass

    def feed(self, e: dict):
        scope = e.get("scope")
        ref = e.get("conversation_id") if scope == "chat" else e.get("task_id") if scope == "task" else None
        if not ref:
            return
        with self._lock:
            run = self._runs.get(f"{scope}:{ref}")
            if not run:
                return
            t, now = e.get("type"), e.get("ts") or time.time()
            if t in ("tool_start", "tool_end", "thinking", "delta", "debate_stage"):
                run.waiting_approval = False             # a aprovação foi respondida: voltou a trabalhar
            if t == "tool_start":
                run.current = e.get("summary") or "Executando…"
                run.log.append({"ts": now, "kind": "acao", "text": run.current})
            elif t == "tool_end":
                run.current = "Pensando…"
                run.log.append({"ts": now, "kind": "ok" if e.get("ok") else "erro",
                                "text": (e.get("summary") or "") + (f" → {e['text']}" if e.get("text") else "")})
            elif t == "thinking":
                run.current = "Pensando…"
            elif t == "delta":
                run.current = "Escrevendo…"
                run.text = (run.text + e.get("text", ""))[-400:]
            elif t == "confirm":
                run.waiting_approval = True
                run.current = "Esperando a sua aprovação: " + str(e.get("summary") or "")
                run.log.append({"ts": now, "kind": "pergunta", "text": run.current})
            elif t == "info":
                run.log.append({"ts": now, "kind": "info", "text": str(e.get("text") or "")})
            elif t == "error":
                run.log.append({"ts": now, "kind": "erro", "text": str(e.get("message") or "")})
            elif t in ("debate_stage",):
                run.current = e.get("text") or "Debatendo…"
        self._changed_soft(t)

    def _changed_soft(self, t):
        if t in ("tool_start", "tool_end", "confirm"):
            self._changed()

    # -- consulta
    def runs(self) -> list:
        with self._lock:
            return [self._public(r) for r in sorted(self._runs.values(), key=lambda r: r.started)]

    def _public(self, r: _Run) -> dict:
        paused = r.gate.paused
        return {"key": r.key, "kind": r.kind, "ref": r.ref, "title": r.title, "started": r.started,
                "status": "paused" if paused else "approval" if r.waiting_approval else "running",
                "paused_waiting": bool(paused and r.gate.waiting), "current": r.current, "text": r.text,
                "log": list(r.log)[-8:]}

    def keys(self, target: str = None) -> list:
        with self._lock:
            return [k for k in self._runs if target in (None, "", k)]

    # -- controle
    def pause(self, target: str = None, max_seconds: float = DEFAULT_MAX_PAUSE) -> list:
        with self._lock:
            runs = [self._runs[k] for k in self.keys(target)]
        for r in runs:
            r.gate.pause(max_seconds)
            r.log.append({"ts": time.time(), "kind": "info", "text": "Pausado a pedido do celular."})
        if runs:
            self._changed()
        return [r.key for r in runs]

    def resume(self, target: str = None) -> list:
        with self._lock:
            runs = [self._runs[k] for k in self.keys(target)]
        for r in runs:
            if r.gate.paused:
                r.log.append({"ts": time.time(), "kind": "info", "text": "Retomado."})
            r.gate.resume()
        if runs:
            self._changed()
        return [r.key for r in runs]

    def wait_paused(self, keys: list, timeout: float = 6.0, poll: float = 0.1) -> bool:
        """Espera as execuções chegarem ao ponto seguro. Devolve True se todas pararam (ou já terminaram)."""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                pending = [k for k in keys if k in self._runs and not self._runs[k].gate.waiting]
            if not pending:
                return True
            time.sleep(poll)
        return False

    def context_text(self, keys: list) -> str:
        parts = []
        with self._lock:
            for k in keys:
                r = self._runs.get(k)
                if not r:
                    continue
                lines = "\n".join(f"  - {x['text']}" for x in list(r.log)[-8:])
                parts.append(f"{'Tarefa' if r.kind == 'task' else 'Conversa'} “{r.title}” — agora: {r.current}\n"
                             f"Últimas ações:\n{lines or '  (nenhuma ainda)'}"
                             + (f"\nÚltimo texto: {r.text[-200:]}" if r.text else ""))
        return "\n\n".join(parts)
