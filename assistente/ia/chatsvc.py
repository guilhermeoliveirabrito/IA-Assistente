"""Serviço de chat: guarda a conversa, roda o agente em segundo plano e transmite os eventos."""
import threading
import time
import uuid

from assistente.ia import agent, agent_tools, agentes, context, debate, gemini
from assistente.nucleo import activity, attachments, permissions, storage

APPROVAL_TIMEOUT = 600  # segundos esperando você aprovar uma ação no chat


class ChatBusy(Exception):
    pass


class ChatError(Exception):
    pass


class ChatService:
    def __init__(self, cfg, bus, window_hooks=None, notifier=None):
        self.cfg = cfg
        self.bus = bus
        self.window_hooks = window_hooks or {}
        self.notifier = notifier
        self.policy = permissions.Policy(cfg)
        self._runs = {}                # conv_id -> {"thread", "stop"}
        self._windows = {}             # conv_id -> {"until": epoch}
        self._approvals = {}           # req_id -> {"event", "answer", "conv"}
        self._pending = {}             # req_id -> request (para a interface reconectar)
        self._lock = threading.RLock()
        self.approval_timeout = APPROVAL_TIMEOUT
        self.on_voice_reply = None     # função(texto) chamada com a resposta de um pedido feito por voz

    # ---- estado ---------------------------------------------------------------------

    def running(self):
        with self._lock:
            return [cid for cid, r in self._runs.items() if r["thread"].is_alive()]

    def pending(self):
        with self._lock:
            return list(self._pending.values())

    def is_running(self, conv_id) -> bool:
        return conv_id in self.running()

    # ---- envio ------------------------------------------------------------------------

    def prepare_parts(self, conv_id, text, files):
        """files: lista de (nome, bytes). Retorna (parts para a API, anexos para exibir)."""
        if len(files) > attachments.MAX_FILES:
            raise ChatError(f"Envie no máximo {attachments.MAX_FILES} arquivos por mensagem.")
        parts, shown = [], []
        for name, data in files:
            try:
                kind, value = attachments.prepare(name, data)
            except attachments.AttachmentError as e:
                raise ChatError(str(e))
            if kind == "file":
                stored = storage.save_upload(conv_id, name, data)
                parts.append({"x_file": stored, "x_name": storage.safe_filename(name), "mimeType": value})
                shown.append({"name": storage.safe_filename(name), "mime": value, "stored": stored})
            else:
                parts.append(attachments.text_part(storage.safe_filename(name), value))
                shown.append({"name": storage.safe_filename(name), "mime": "text/plain", "stored": ""})
        if text:
            parts.append({"text": text})
        elif not parts:
            raise ChatError("Escreva uma mensagem ou anexe um arquivo.")
        else:
            parts.append({"text": "Analise o(s) arquivo(s) anexado(s) e me diga o que é importante."})
        return parts, shown

    def send(self, conv_id, text, files=None, voice=False, agent=None):
        text = (text or "").strip()
        if len(text) > 30000:
            raise ChatError("Mensagem longa demais (máximo 30.000 caracteres). Anexe como arquivo.")
        if conv_id:
            conv = storage.load(conv_id)
        else:
            conv = storage.new_conversation()
        if agent and agent != conv.get("agent"):
            if not agentes.exists(agent):
                raise ChatError("Esse agente não existe.")
            conv["agent"] = agent
        conv_id = conv["id"]
        with self._lock:
            if self.is_running(conv_id):
                raise ChatBusy("O assistente ainda está respondendo nesta conversa.")
            parts, shown = self.prepare_parts(conv_id, text, files or [])
            conv["contents"].append({"role": "user", "parts": parts})
            conv["messages"].append({"id": uuid.uuid4().hex[:8], "role": "user", "text": text, "ts": time.time(),
                                     "attachments": shown})
            if conv["title"] == "Nova conversa":
                conv["title"] = storage.make_title(text or (shown[0]["name"] if shown else ""))
            storage.save(conv)
            stop = threading.Event()
            thread = threading.Thread(target=self._run, args=(conv_id, stop, voice), name=f"chat-{conv_id}", daemon=True)
            self._runs[conv_id] = {"thread": thread, "stop": stop}
            thread.start()
        return conv_id

    def stop(self, conv_id):
        with self._lock:
            run = self._runs.get(conv_id)
            if run:
                run["stop"].set()
                for a in self._approvals.values():
                    if a["conv"] == conv_id:
                        a["answer"] = "deny"
                        a["event"].set()

    def shutdown(self):
        for cid in list(self._runs):
            self.stop(cid)

    # ---- aprovações -----------------------------------------------------------------

    def approve(self, req_id, answer) -> bool:
        if answer not in ("allow", "deny", "always"):
            raise ChatError("Resposta inválida.")
        with self._lock:
            a = self._approvals.get(req_id)
            if not a:
                return False
            a["answer"] = answer
            a["event"].set()
            return True

    def _approval_fn(self, conv_id, stop):
        def ask(req):
            ev = threading.Event()
            entry = {"event": ev, "answer": "deny", "conv": conv_id}
            with self._lock:
                self._approvals[req["id"]] = entry
                self._pending[req["id"]] = {**req, "conversation_id": conv_id}
            deadline = time.time() + self.approval_timeout
            try:
                while not ev.wait(max(0.01, min(1.0, deadline - time.time()))):
                    if stop.is_set():
                        return "deny"
                    if time.time() >= deadline:
                        raise agent.ApprovalTimeout()
                return entry["answer"]
            finally:
                with self._lock:
                    self._approvals.pop(req["id"], None)
                    self._pending.pop(req["id"], None)
        return ask

    # ---- execução ---------------------------------------------------------------------

    def _publish(self, conv_id, event):
        self.bus.publish({**event, "scope": "chat", "conversation_id": conv_id})

    def _run(self, conv_id, stop, voice=False):
        model = (self.cfg.get("ia") or {}).get("modelo", "gemini-3.8-flash")
        assistant = {"id": uuid.uuid4().hex[:8], "role": "assistant", "text": "", "ts": time.time(), "tools": [],
                     "error": ""}
        tools = {}
        contents = None
        notes = []          # avisos do sistema a gravar na conversa (ex.: "resumi o começo")

        def emit(event):
            t = event.get("type")
            if t == "delta":
                assistant["text"] += event["text"]
            elif t == "tool_start":
                entry = {"id": event["id"], "summary": event["summary"], "risk": event.get("risk"), "ok": None, "text": ""}
                tools[event["id"]] = entry
                assistant["tools"].append(entry)
            elif t == "tool_end":
                entry = tools.get(event["id"])
                if entry is None:       # ação negada: não chegou a começar
                    entry = {"id": event["id"], "summary": event.get("summary", ""), "risk": None}
                    assistant["tools"].append(entry)
                entry.update(ok=event.get("ok"), text=event.get("text", ""), denied=bool(event.get("denied")))
            self._publish(conv_id, event)

        try:
            conv = storage.load(conv_id)
            contents = conv["contents"]
            self._publish(conv_id, {"type": "start", "message_id": assistant["id"]})
            if context.needs_compaction(contents):
                self._publish(conv_id, {"type": "info", "text": "Resumindo o começo da conversa para economizar cota…"})
                new, summary = context.compact(contents, model)
                if summary:
                    contents[:] = new
                    notes.append({"id": uuid.uuid4().hex[:8], "role": "note", "ts": time.time(),
                                  "text": "O começo desta conversa foi resumido para manter o assistente rápido."})
            spec = agentes.get(conv.get("agent"))
            if spec["especial"] == "debate":
                self._run_debate(conv, contents, assistant, emit, stop)
                return
            ctx = agent_tools.ToolContext(self.cfg, mode="chat", hooks=dict(self.window_hooks))
            engine = agent.Engine(self.cfg, agent_tools.Registry(ctx, spec["fora"]), self.policy, mode="chat", emit=emit,
                                  ask_approval=self._approval_fn(conv_id, stop), stop_event=stop,
                                  window=self._windows.setdefault(conv_id, {"until": 0.0}),
                                  resolve=lambda c: storage.resolve_contents(conv_id, c))
            status = engine.run(contents, agent.build_system_prompt(self.cfg, "chat", voice=voice, agent=spec["id"]))
            if status == "empty":
                assistant["error"] = "O modelo não devolveu resposta. Tente de novo."
        except gemini.GeminiError as e:
            assistant["error"] = str(e)
            self._publish(conv_id, {"type": "error", "kind": e.kind, "message": str(e)})
            activity.log("erro", f"Chat: {e}")
        except Exception as e:
            assistant["error"] = f"Erro inesperado: {type(e).__name__}: {e}"
            self._publish(conv_id, {"type": "error", "kind": "internal", "message": assistant["error"]})
            activity.log("erro", f"Chat: {assistant['error']}")
        finally:
            try:
                conv = storage.load(conv_id)
                conv["messages"].extend(notes)
                if stop.is_set():
                    assistant["error"] = assistant["error"] or ""
                    assistant["stopped"] = True
                if assistant["text"] or assistant["tools"] or assistant["error"] or assistant.get("stopped"):
                    conv["messages"].append(assistant)
                # `contents` foi alterado pelo motor (a conversa carregada antes); regrava essa versão
                if contents is not None:
                    conv["contents"] = contents
                storage.save(conv)
            except KeyError:
                pass  # a conversa foi apagada durante a resposta
            with self._lock:
                self._runs.pop(conv_id, None)      # antes do aviso: quem recarregar a conversa já a vê como parada
            self._publish(conv_id, {"type": "done", "message_id": assistant["id"], "stopped": stop.is_set()})
            if voice and self.on_voice_reply and not stop.is_set():
                try:
                    self.on_voice_reply(assistant["text"] or assistant["error"])
                except Exception as e:
                    activity.log("erro", f"Voz: {e}")

    def _run_debate(self, conv, contents, assistant, emit, stop):
        """Mesa de debate: defensor, opositor e juiz; a conversa só recebe o parecer do juiz."""
        question = next((m["text"] for m in reversed(conv["messages"]) if m.get("role") == "user" and m.get("text")), "")
        history = [m for m in conv["messages"][:-1] if m.get("text") and m.get("role") in ("user", "assistant")][-4:]
        context_text = "\n".join(f"{'Usuário' if m['role'] == 'user' else 'Assistente'}: {m['text'][:600]}" for m in history)
        try:
            out = debate.run(self.cfg, question, context_text, progress=lambda t: emit({"type": "info", "text": t}), stop=stop)
        except debate.DebateStopped:
            emit({"type": "stopped"})
            return
        except ValueError as e:
            assistant["error"] = str(e)
            emit({"type": "error", "kind": "internal", "message": str(e)})
            return
        emit({"type": "delta", "text": out["parecer"]})
        contents.append({"role": "model", "parts": [{"text": out["parecer"]}]})

    # ---- recomeçar com resumo -----------------------------------------------------------

    def refresh(self, conv_id) -> str:
        """Cria uma conversa nova que continua a atual a partir de um resumo."""
        if self.is_running(conv_id):
            raise ChatBusy("Espere o assistente terminar de responder.")
        old = storage.load(conv_id)
        if len(old["contents"]) < 2:
            raise ChatError("Não há o que resumir nesta conversa ainda.")
        model = (self.cfg.get("ia") or {}).get("modelo", "gemini-3.8-flash")
        turns, summary = context.seed_for_new_conversation(old["contents"], model)
        new = storage.new_conversation(storage.make_title("Continuação: " + old["title"]))
        new["contents"] = turns
        new["messages"] = [{"id": uuid.uuid4().hex[:8], "role": "note", "ts": time.time(),
                            "text": "Conversa nova, começando de um resumo da anterior:\n\n" + summary}]
        storage.save(new)
        return new["id"]
