"""Servidor local do app (somente biblioteca padrão): interface web + API + eventos em tempo real.

SEGURANÇA — este servidor controla o seu PC, então:
- toda requisição exige o CÓDIGO DE ACESSO (cookie HttpOnly/SameSite=Strict ou cabeçalho), em qualquer modo;
- no modo "local" só escuta em 127.0.0.1 e recusa Host desconhecido (protege contra DNS rebinding);
- pedidos que alteram algo exigem que Origin, se presente, seja o próprio servidor (protege contra CSRF);
- tentativas erradas de código são limitadas por endereço.
"""
import base64
import hmac
import json
import mimetypes
import os
import queue
import re
import secrets
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import activity
import automation
import ai
import bus as busmod
import chatsvc
import gemini
import memory
import notify
import permissions
import providers
import reminders
import settings
import spotify_control
import storage
import tasks
import tracking
import usage
import wake

WEB_DIR = Path(__file__).resolve().parent / "web"
TOKEN_FILE = Path("data") / "access_token.txt"
MAX_JSON = 40 * 1024 * 1024
MAX_AUDIO = 10 * 1024 * 1024
COOKIE = "ac"
MEMORY_NAME = re.compile(r"^[\w\- ]{1,40}\.md$", re.UNICODE)
CORE_MEMORY = {"perfil.md", "regras.md", "notas.md"}
FAIL_LIMIT, FAIL_WINDOW = 10, 300


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def load_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(token) >= 20:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token


def lan_addresses():
    """Endereços deste computador que outros aparelhos da rede (ou do Tailscale) conseguem alcançar."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # não envia nada; só descobre a interface de saída
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found


class App:
    """Reúne os serviços e as regras de negócio por trás da API."""

    def __init__(self, cfg, window_hooks=None):
        self.cfg = cfg
        self.bus = busmod.Bus()
        self.notifier = notify.Notifier(cfg)
        self.window_hooks = window_hooks or {}
        activity.configure(cfg)
        ai.configure(cfg)
        usage.configure(cfg)
        usage.subscribe(self._usage_changed)
        memory.ensure()
        self.tasks = tasks.TaskManager(cfg, bus=self.bus, notifier=self.notifier, window_hooks=self.window_hooks)
        self.chat = chatsvc.ChatService(cfg, self.bus, self.window_hooks, self.notifier)
        self.automation = automation.Automation(cfg, on_change=self._checks_changed)
        self.tracker = tracking.Tracker(cfg, on_update=self._tracking_update, on_change=self._tracking_changed)
        tracking.set_default(self.tracker)
        self.tracker.start()
        self.reminders = reminders.Reminders(cfg, on_fire=self._reminder_fired, on_change=self._reminders_changed)
        reminders.set_default(self.reminders)
        self.reminders.start()
        self._voice_conv = {"id": None, "ts": 0.0}
        self.voice = wake.VoiceService(cfg, self.voice_command, self.bus.publish, self._transcribe_voice)
        self.chat.on_voice_reply = self.voice.speak_reply
        self.started = time.time()
        if self.voice.enabled:
            self.voice.start()

    # ---- voz ---------------------------------------------------------------------------

    def _transcribe_voice(self, wav: bytes) -> str:
        return ai.transcribe(wav, "audio/wav", (self.cfg.get("ia") or {}).get("modelo", "gemini-3.8-flash"))

    def voice_command(self, text: str):
        """Comando falado: continua a conversa por voz recente (até 30 min) ou abre uma nova."""
        now = time.time()
        cid = self._voice_conv["id"]
        if cid and (now - self._voice_conv["ts"] > 1800 or self.chat.is_running(cid)):
            cid = None
        try:
            cid = self.chat.send(cid, text, [], voice=True)
        except KeyError:                                   # a conversa foi apagada
            cid = self.chat.send(None, text, [], voice=True)
        self._voice_conv.update(id=cid, ts=now)
        self.bus.publish({"type": "voice_command", "conversation_id": cid, "text": text})
        reveal = self.window_hooks.get("reveal_window")
        if reveal:
            try:
                reveal()
            except Exception:
                pass

    def checks(self):
        """Verificações em segundo plano (e-mail, agenda...) com a contagem para a próxima."""
        st = self.automation.status()
        st["jobs"] = st["jobs"] + [self.tracker.status(), self.reminders.status()]
        return st

    # ---- encomendas ----------------------------------------------------------------------

    def _tracking_update(self, item, text, kind="info"):
        title = item.get("name") or item.get("code")
        activity.log("erro" if kind == "erro" else "resultado", f"Encomenda {title}: {text}")
        self.bus.publish({"type": "toast", "kind": "error" if kind == "erro" else "ok", "text": f"📦 {title}: {text}"})
        self.notifier.notify("erro" if kind == "erro" else "encomenda", f"Encomenda: {title}", text)

    def _tracking_changed(self):
        self.bus.publish({"type": "tracking", "unread": self.tracker.unread(), "configured": self.tracker.configured})
        self._checks_changed()

    # ---- lembretes -----------------------------------------------------------------------

    def _reminder_fired(self, item, late):
        """Hora marcada: banner e som no app, som no PC mesmo com a janela escondida, aviso no celular e, se for o caso, tarefa."""
        alarm = item["kind"] == "alarme"
        text = item["text"]
        activity.log("resultado", f"{'Alarme' if alarm else 'Lembrete'}: {text}")
        self.bus.publish({"type": "reminder", "item": reminders.public(item), "alarm": alarm, "late_s": round(late),
                          "ringing": item["status"] == "tocando"})
        self.notifier.notify("lembrete", "⏰ Alarme" if alarm else "🔔 Lembrete", text, priority=5 if alarm else 4)
        threading.Thread(target=wake.beep, args=("alarm" if alarm else "wake",), daemon=True).start()
        if alarm:
            reveal = self.window_hooks.get("reveal_window")
            if reveal:
                try:
                    reveal()
                except Exception:
                    pass
        if item.get("run"):
            try:
                self.tasks.create("Lembrete: " + text[:60], text, "leitura")
            except Exception as e:
                activity.log("erro", f"Não consegui iniciar a tarefa do lembrete: {e}")

    def _reminders_changed(self):
        self.bus.publish({"type": "reminders", "count": len(self.reminders.items()),
                          "ringing": len([i for i in self.reminders.items() if i["status"] == "tocando"])})
        self._checks_changed()

    def _checks_changed(self):
        self.bus.publish({"type": "checks", "checks": self.checks()})

    def _usage_changed(self, event):
        """O medidor mudou (chamada feita, recusa do Google ou troca de modelo): avisa a interface na hora."""
        if event.get("type") == "model_switch":
            self.bus.publish({**event, "text": f"Troquei de {event['from']} para {event['to']}: {event['reason']}."})
        self.bus.publish({"type": "usage", "usage": usage.summary(self.cfg)})

    def shutdown(self):
        usage.unsubscribe(self._usage_changed)
        self.voice.stop()
        self.tracker.stop()
        self.reminders.stop()
        reminders.set_default(None)
        tracking.set_default(None)
        self.automation.stop()
        self.chat.shutdown()
        self.tasks.shutdown()

    # ---- estado ---------------------------------------------------------------------

    def state(self):
        cfg = self.cfg
        key_ok = bool(os.environ.get("GEMINI_API_KEY"))
        if not key_ok:
            try:
                gemini.api_key()
                key_ok = True
            except gemini.GeminiError:
                key_ok = False
        key_ok = key_ok or bool(providers.extras(cfg))      # sem Gemini, mas com outro provedor configurado, segue funcionando
        t = self.tasks.list()
        counts = {}
        for item in t:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "name": (cfg.get("app") or {}).get("seu_nome", ""),
            "model": (cfg.get("ia") or {}).get("modelo", ""),
            "usage": usage.summary(cfg),
            "gemini_key": key_ok,
            "running_chats": self.chat.running(),
            "approvals": self.chat.pending() + self.tasks.pending_approvals(),
            "task_counts": counts,
            "notifications": self.notifier.enabled,
            "spotify": {"configured": bool(os.environ.get("SPOTIFY_CLIENT_ID")),
                        "connected": spotify_control.TOKEN_FILE.exists()},
            "retention_days": (cfg.get("historico") or {}).get("dias_de_retencao", 7),
            "profiles": permissions.PROFILE_LABELS,
            "default_budget": int((cfg.get("tarefas") or {}).get("orcamento_de_requisicoes", 60)),
            "access": (cfg.get("app") or {}).get("acesso", "local"),
            "google": {"credentials": Path("credentials.json").exists(), "connected": automation.google_ready(),
                       "running": self.automation.running, "calendar_write": automation.calendar_write(),
                       "send_email": bool((cfg.get("google") or {}).get("permitir_enviar_email"))},
            "voice": self.voice.status(),
            "checks": self.checks(),
            "reminders": {"count": len(self.reminders.items()),
                          "ringing": len([i for i in self.reminders.items() if i["status"] == "tocando"])},
            "tracking": {"unread": self.tracker.unread(), "configured": self.tracker.configured,
                         "count": len(self.tracker.items())},
            "autonomous": bool((cfg.get("pc") or {}).get("modo_autonomo", False)),
            "permission_window_minutes": (cfg.get("pc") or {}).get("janela_de_permissao_minutos", 10),
        }

    # ---- memória ----------------------------------------------------------------------

    def memory_state(self):
        memory.ensure()
        files = []
        for f in sorted(memory.MEMORY_DIR.glob("*.md")):
            files.append({"name": f.name, "core": f.name in CORE_MEMORY, "content": f.read_text(encoding="utf-8")})
        return {"files": files, "notes": memory.list_notes()}

    def memory_write(self, name, content):
        if not isinstance(name, str) or not MEMORY_NAME.match(name):
            raise HTTPError(400, "Nome inválido. Use letras, números, espaço ou hífen e termine com .md.")
        if not isinstance(content, str) or len(content) > 100_000:
            raise HTTPError(400, "Conteúdo inválido ou maior que 100 KB.")
        memory.ensure()
        (memory.MEMORY_DIR / name).write_text(content.replace("\r\n", "\n"), encoding="utf-8")

    def memory_delete(self, name):
        if not isinstance(name, str) or not MEMORY_NAME.match(name) or name in CORE_MEMORY:
            raise HTTPError(400, "Só é possível apagar arquivos extras (não perfil, regras ou notas).")
        (memory.MEMORY_DIR / name).unlink(missing_ok=True)

    # ---- google (gmail + agenda) ------------------------------------------------------

    def google_connect(self, reauth=False):
        if not Path("credentials.json").exists():
            raise HTTPError(400, "Falta o arquivo credentials.json na pasta do projeto. Veja o passo 4 do README "
                                 "(criar o acesso no Google Cloud).")

        def go():
            try:
                import google_auth

                google_auth.get_credentials(force=reauth)   # abre o navegador para você entrar e autorizar
                self.automation.start()
                self.bus.publish({"type": "toast", "kind": "ok", "text": "Google conectado. Gmail e Agenda ligados."})
            except BaseException as e:                  # inclui o SystemExit do login
                self.bus.publish({"type": "toast", "kind": "error", "text": f"Google: {e}"})

        threading.Thread(target=go, daemon=True).start()

    # ---- spotify ---------------------------------------------------------------------

    def spotify_connect(self):
        import agent_tools

        sp = agent_tools.build_spotify(self.cfg)
        sp._require_client_id()

        def go():
            try:
                sp.authorize()
                self.bus.publish({"type": "toast", "kind": "ok", "text": "Spotify conectado."})
            except Exception as e:
                self.bus.publish({"type": "toast", "kind": "error", "text": f"Spotify: {e}"})

        threading.Thread(target=go, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "Assistente"
    protocol_version = "HTTP/1.0"
    app: App = None
    token: str = ""
    port: int = 0
    mode: str = "local"
    fails = {}
    fails_lock = threading.Lock()

    def log_message(self, *args):
        pass

    # ---- utilidades de resposta -------------------------------------------------------

    def _send(self, status, body: bytes, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200, headers=None):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), headers=headers)

    def _error(self, status, message):
        self._json({"error": message}, status)

    # ---- segurança ----------------------------------------------------------------------

    def _client(self):
        return self.client_address[0]

    def _too_many_failures(self) -> bool:
        now = time.time()
        with Handler.fails_lock:
            recent = [t for t in Handler.fails.get(self._client(), []) if now - t < FAIL_WINDOW]
            Handler.fails[self._client()] = recent
            return len(recent) >= FAIL_LIMIT

    def _register_failure(self):
        with Handler.fails_lock:
            Handler.fails.setdefault(self._client(), []).append(time.time())

    def _host_ok(self) -> bool:
        if self.mode != "local":
            return True
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _authorized(self) -> bool:
        given = self._cookie_token() or self.headers.get("X-Access-Code") or ""
        return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = (self.headers.get("Host") or "").lower()
        return urlparse(origin).netloc.lower() == host

    def _cookie_header(self):
        return {"Set-Cookie": f"{COOKIE}={self.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}

    # ---- roteamento ---------------------------------------------------------------------

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        try:
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            if not self._host_ok():
                return self._error(403, "Endereço não permitido.")
            if path == "/health" and method == "GET":
                return self._json({"ok": True})
            if path == "/login":
                return self._login(method, query)
            # código na URL (QR/atalho): vira cookie e a URL é limpa
            if method == "GET" and "k" in query:
                if self._too_many_failures():
                    return self._error(429, "Muitas tentativas. Espere alguns minutos.")
                if hmac.compare_digest(query["k"][0].encode(), self.token.encode()):
                    return self._send(HTTPStatus.FOUND, b"", headers={**self._cookie_header(), "Location": path or "/"})
                self._register_failure()
                return self._redirect_login()
            if not self._authorized():
                if path.startswith("/api/"):
                    self._register_failure() if self._cookie_token() or self.headers.get("X-Access-Code") else None
                    return self._error(401, "Acesso não autorizado.")
                return self._redirect_login()
            if method != "GET" and not self._origin_ok():
                return self._error(403, "Origem não permitida.")
            if path.startswith("/api/"):
                return self._api(method, path, query)
            if method != "GET":
                return self._error(405, "Método não permitido.")
            return self._static(path)
        except HTTPError as e:
            self._error(e.status, e.message)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # nunca deixa o servidor cair
            try:
                self._error(500, f"Erro interno: {type(e).__name__}")
            except OSError:
                pass
            print(f"[erro] {self.command} {self.path}: {type(e).__name__}: {e}", flush=True)

    def _redirect_login(self):
        self._send(HTTPStatus.FOUND, b"", headers={"Location": "/login"})

    def _login(self, method, query):
        if method == "POST":
            if self._too_many_failures():
                return self._error(429, "Muitas tentativas. Espere alguns minutos.")
            code = (parse_qs(self._read_body(4096).decode("utf-8", "ignore")).get("code") or [""])[0].strip()
            if hmac.compare_digest(code.encode(), self.token.encode()):
                return self._send(HTTPStatus.FOUND, b"", headers={**self._cookie_header(), "Location": "/"})
            self._register_failure()
            return self._send(401, _login_page("Código incorreto."), "text/html; charset=utf-8")
        return self._send(200, _login_page(""), "text/html; charset=utf-8")

    # ---- arquivos estáticos ---------------------------------------------------------------

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            return self._error(404, "Não encontrado.")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/manifest+json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    # ---- corpo da requisição ------------------------------------------------------------------

    def _read_body(self, limit=MAX_JSON) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise HTTPError(400, "Cabeçalho inválido.")
        if length > limit:
            raise HTTPError(413, "Conteúdo grande demais.")
        return self.rfile.read(length) if length else b""

    def _body(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "JSON inválido.")
        if not isinstance(data, dict):
            raise HTTPError(400, "Esperava um objeto JSON.")
        return data

    # ---- API ------------------------------------------------------------------------------------

    ROUTES = []

    def _api(self, method, path, query):
        for m, pattern, fn in self.ROUTES:
            if m != method:
                continue
            match = pattern.match(path)
            if match:
                try:
                    return fn(self, query, *match.groups())
                except KeyError as e:
                    raise HTTPError(404, str(e.args[0]) if e.args else "Não encontrado.")
                except chatsvc.ChatBusy as e:
                    raise HTTPError(409, str(e))
                except tasks.TaskNotFound as e:
                    return self._error(404, str(e))
                except (chatsvc.ChatError, tasks.TaskError, ValueError, spotify_control.SpotifyError) as e:
                    raise HTTPError(400, str(e))
                except gemini.GeminiError as e:
                    raise HTTPError(502, str(e))
        raise HTTPError(404, "Rota não encontrada.")


def route(method, pattern):
    regex = re.compile("^" + pattern + "$")

    def deco(fn):
        Handler.ROUTES.append((method, regex, fn))
        return fn
    return deco


def _login_page(error: str) -> bytes:
    msg = f"<p class=e>{error}</p>" if error else ""
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acesso</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#1f1e1d;color:#ece9e3;font:16px system-ui,sans-serif}}
form{{width:min(360px,88vw)}}h1{{font-size:20px;margin:0 0 6px}}p{{color:#a19d94;margin:0 0 18px;font-size:14px;line-height:1.5}}
input,button{{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid #3a3836;background:#2a2927;color:inherit;font:inherit}}
button{{margin-top:10px;background:#d08a62;color:#1b1410;border:0;font-weight:600;cursor:pointer}}.e{{color:#e58b8b}}</style>
<form method="post" action="/login"><h1>Assistente</h1><p>Digite o código de acesso. Ele aparece nos Ajustes do app, no computador.</p>{msg}
<input name="code" type="password" autocomplete="off" autofocus placeholder="Código de acesso"><button>Entrar</button></form>""".encode("utf-8")


# =============================== rotas ===============================

@route("GET", "/api/state")
def r_state(h, q):
    h._json(h.app.state())


@route("POST", "/api/usage/calibrate")
def r_usage_calibrate(h, q):
    b = h._body()
    model = str(b.get("model") or "")
    if not re.match(r"^[\w.\-]{1,60}$", model):
        raise HTTPError(400, "Modelo inválido.")
    try:
        usage.calibrate(model, int(b.get("requests")))
    except (TypeError, ValueError):
        raise HTTPError(400, "Digite o número de requisições que o painel do Google mostra para este modelo hoje.")
    h._json(usage.summary(h.app.cfg))


@route("GET", "/api/usage")
def r_usage(h, q):
    h._json(usage.summary(h.app.cfg))


@route("GET", "/api/events")
def r_events(h, q):
    sub = h.app.bus.subscribe()
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Accel-Buffering", "no")
        h.end_headers()
        h.wfile.write(b"retry: 3000\n\n")
        h.wfile.write(b"event: hello\ndata: {}\n\n")
        h.wfile.flush()
        last_beat = time.time()
        while True:
            try:
                event = sub.get(timeout=5)
                h.wfile.write(b"data: " + json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n\n")
                h.wfile.flush()
            except queue.Empty:
                if time.time() - last_beat >= 15:
                    h.wfile.write(b": ping\n\n")
                    h.wfile.flush()
                    last_beat = time.time()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        h.app.bus.unsubscribe(sub)


# ---- conversas ----

@route("GET", "/api/conversations")
def r_conv_list(h, q):
    h._json({"conversations": storage.list_all(), "running": h.app.chat.running()})


@route("POST", "/api/conversations")
def r_conv_new(h, q):
    h._json(_public_conv(storage.new_conversation()))


@route("GET", "/api/conversations/([0-9a-f]{12})")
def r_conv_get(h, q, cid):
    conv = _public_conv(storage.load(cid))
    conv["running"] = h.app.chat.is_running(cid)
    h._json(conv)


@route("DELETE", "/api/conversations/([0-9a-f]{12})")
def r_conv_delete(h, q, cid):
    if h.app.chat.is_running(cid):
        raise HTTPError(409, "Pare a resposta antes de apagar a conversa.")
    storage.delete(cid)
    h._json({"ok": True})


@route("POST", "/api/conversations/([0-9a-f]{12})/rename")
def r_conv_rename(h, q, cid):
    title = h._body().get("title", "")
    if not str(title).strip():
        raise HTTPError(400, "Digite um título.")
    h._json(_public_conv(storage.rename(cid, str(title))))


@route("POST", "/api/conversations/([0-9a-f]{12})/refresh")
def r_conv_refresh(h, q, cid):
    h._json({"id": h.app.chat.refresh(cid)})


@route("GET", "/api/conversations/([0-9a-f]{12})/files/([\\w.\\-()]+)")
def r_conv_file(h, q, cid, stored):
    data = storage.read_upload(cid, stored)
    mime = "application/octet-stream"
    conv = storage.load(cid)
    for m in conv["messages"]:
        for a in m.get("attachments", []):
            if a.get("stored") == stored:
                mime = a["mime"]
    if not (mime.startswith("image/") or mime == "application/pdf"):
        mime = "application/octet-stream"
    h._send(200, data, mime, {"Content-Disposition": "inline", "Cache-Control": "private, max-age=3600"})


def _public_conv(conv):
    return {k: conv[k] for k in ("id", "title", "created", "updated", "messages")}


@route("POST", "/api/chat")
def r_chat(h, q):
    body = h._body()
    files = []
    for item in body.get("attachments") or []:
        try:
            files.append((str(item.get("name") or "arquivo"), base64.b64decode(item.get("data") or "", validate=True)))
        except (ValueError, TypeError, AttributeError):
            raise HTTPError(400, "Anexo inválido.")
    cid = h.app.chat.send(body.get("conversation_id") or None, body.get("text"), files)
    h._json({"conversation_id": cid})


@route("POST", "/api/chat/stop")
def r_chat_stop(h, q):
    cid = h._body().get("conversation_id")
    h.app.chat.stop(cid)
    h._json({"ok": True})


@route("POST", "/api/approve")
def r_approve(h, q):
    body = h._body()
    rid, answer = body.get("id"), body.get("answer")
    if not isinstance(rid, str):
        raise HTTPError(400, "Pedido inválido.")
    done = h.app.chat.approve(rid, answer) or h.app.tasks.approve(rid, answer)
    if not done:
        raise HTTPError(404, "Esse pedido já foi respondido ou expirou.")
    h._json({"ok": True})


@route("POST", "/api/transcribe")
def r_transcribe(h, q):
    raw = h._read_body(MAX_AUDIO)
    mime = (h.headers.get("Content-Type") or "audio/webm").split(";")[0].strip().lower()
    if not mime.startswith("audio/") or not raw:
        raise HTTPError(400, "Envie um áudio.")
    h._json({"text": ai.transcribe(raw, mime, h.app.cfg["ia"]["modelo"])})


# ---- tarefas ----

@route("GET", "/api/tasks")
def r_tasks(h, q):
    h._json({"tasks": h.app.tasks.list()})


@route("POST", "/api/tasks")
def r_task_new(h, q):
    b = h._body()
    h._json(h.app.tasks.create(b.get("title", ""), b.get("prompt", ""), b.get("profile", "leitura"), b.get("budget")))


@route("GET", "/api/tasks/([0-9a-f]{10})")
def r_task_get(h, q, tid):
    h._json(h.app.tasks.get(tid))


@route("POST", "/api/tasks/([0-9a-f]{10})/stop")
def r_task_stop(h, q, tid):
    h._json(h.app.tasks.stop(tid))


@route("POST", "/api/tasks/([0-9a-f]{10})/resume")
def r_task_resume(h, q, tid):
    h._json(h.app.tasks.resume(tid, int(h._body().get("extra_budget") or 0)))


@route("POST", "/api/tasks/([0-9a-f]{10})/answer")
def r_task_answer(h, q, tid):
    h._json(h.app.tasks.answer(tid, h._body().get("text", "")))


@route("DELETE", "/api/tasks/([0-9a-f]{10})")
def r_task_delete(h, q, tid):
    h.app.tasks.delete(tid)
    h._json({"ok": True})


# ---- histórico ----

@route("GET", "/api/activity")
def r_activity(h, q):
    limit = max(1, min(int((q.get("limit") or ["200"])[0]), 1000))
    task = (q.get("task") or [None])[0]
    kinds = set((q.get("kinds") or [""])[0].split(",")) - {""} or None
    h._json({"events": activity.recent(limit, task=task, kinds=kinds),
             "retention_days": (h.app.cfg.get("historico") or {}).get("dias_de_retencao", 7)})


@route("DELETE", "/api/activity")
def r_activity_clear(h, q):
    activity.clear()
    h._json({"ok": True})


# ---- memória ----

@route("GET", "/api/memory")
def r_memory(h, q):
    h._json(h.app.memory_state())


@route("PUT", "/api/memory/file")
def r_memory_write(h, q):
    b = h._body()
    h.app.memory_write(b.get("name"), b.get("content"))
    h._json(h.app.memory_state())


@route("DELETE", "/api/memory/file")
def r_memory_delete(h, q):
    h.app.memory_delete((q.get("name") or [""])[0])
    h._json(h.app.memory_state())


@route("POST", "/api/memory/notes")
def r_memory_note(h, q):
    memory.remember(str(h._body().get("text", "")))
    h._json(h.app.memory_state())


@route("DELETE", "/api/memory/notes/(\\d{1,4})")
def r_memory_note_delete(h, q, n):
    memory.forget(int(n))
    h._json(h.app.memory_state())


# ---- ajustes, acesso, avisos, spotify ----

@route("GET", "/api/settings")
def r_settings(h, q):
    h._json({"values": settings.current_values(h.app.cfg), "restart_fields": [k for k, (_, r) in settings.FIELDS.items() if r]})


@route("POST", "/api/settings")
def r_settings_save(h, q):
    try:
        changed, restart = settings.update(h.app.cfg, h._body().get("changes") or {})
    except ValueError as e:
        try:
            raise HTTPError(400, "; ".join(f"{k}: {v}" for k, v in json.loads(str(e)).items()))
        except ValueError:
            raise HTTPError(400, str(e))
    activity.configure(h.app.cfg)
    if any(k.startswith("voz.") for k in changed):
        h.app.voice.restart() if h.app.voice.enabled else h.app.voice.stop()
    h._json({"changed": changed, "restart": restart, "values": settings.current_values(h.app.cfg)})


@route("GET", "/api/providers")
def r_providers(h, q):
    h._json({"providers": providers.status(h.app.cfg), "order": providers.order(h.app.cfg)})


@route("POST", "/api/providers/key")
def r_provider_key(h, q):
    b = h._body()
    try:
        providers.save_key(str(b.get("id") or ""), b.get("key"))
    except ValueError as e:
        raise HTTPError(400, str(e))
    h._json({"providers": providers.status(h.app.cfg)})


@route("POST", "/api/providers/test")
def r_provider_test(h, q):
    pid = str(h._body().get("id") or "")
    try:
        h._json(providers.ping(h.app.cfg, pid))
    except (gemini.GeminiError, ValueError) as e:
        h._json({"ok": False, "erro": str(e)})


@route("GET", "/api/access")
def r_access(h, q):
    port = h.port
    urls = [f"http://{ip}:{port}/?k={h.token}" for ip in lan_addresses()]
    h._json({"mode": h.mode, "code": h.token, "port": port, "urls": urls if h.mode == "rede" else [],
             "local_url": f"http://127.0.0.1:{port}/"})


@route("POST", "/api/notify/topic")
def r_notify_topic(h, q):
    topic = notify.new_topic()
    settings.update(h.app.cfg, {"notificacoes.ntfy_topico": topic})
    h.app.notifier = notify.Notifier(h.app.cfg)
    h.app.tasks.notifier = h.app.notifier
    h._json({"topic": topic})


@route("POST", "/api/notify/test")
def r_notify_test(h, q):
    if not h.app.notifier.enabled:
        raise HTTPError(400, "Crie um tópico de avisos primeiro.")
    ok = h.app.notifier.notify("pronta", "Teste do assistente", "Se você recebeu isto, os avisos estão funcionando.")
    h._json({"sent": ok})


@route("POST", "/api/automation/run")
def r_automation_run(h, q):
    job = str(h._body().get("job") or "")
    if job not in automation.Automation.JOBS:
        raise HTTPError(400, "Rotina desconhecida.")
    try:
        h.app.automation.run_job_async(job)
    except RuntimeError as e:
        raise HTTPError(400, str(e))
    h._json({"ok": True})


def _tracking_payload(app):
    return {"items": app.tracker.items(), "configured": app.tracker.configured, "unread": app.tracker.unread(),
            "status": app.tracker.status(), "now": time.time()}


def _reminders_payload(app):
    return {"items": [{**reminders.public(i), "due": i.get("snooze_due") or i["due"], "fired": i["fired"]}
                      for i in app.reminders.items()], "now": time.time()}


@route("GET", "/api/reminders")
def r_reminders(h, q):
    h._json(_reminders_payload(h.app))


@route("POST", "/api/reminders")
def r_reminders_add(h, q):
    b = h._body()
    try:
        if b.get("in_minutes") not in (None, ""):
            when = time.time() + float(b["in_minutes"]) * 60
        else:
            when = reminders.parse_when(b.get("when"), time.time())
        item = h.app.reminders.add(b.get("text"), when, "alarme" if b.get("alarm") else "lembrete",
                                   b.get("repeat") or "nao", b.get("every_minutes"), bool(b.get("run")))
    except (reminders.ReminderError, TypeError, ValueError) as e:
        raise HTTPError(400, str(e))
    h._json({"item": reminders.public(item)})


@route("POST", "/api/reminders/([0-9a-f]{8})/dismiss")
def r_reminders_dismiss(h, q, rid):
    try:
        h.app.reminders.dismiss(rid)
    except reminders.ReminderError as e:
        raise HTTPError(404, str(e))
    h._json({"ok": True})


@route("POST", "/api/reminders/([0-9a-f]{8})/snooze")
def r_reminders_snooze(h, q, rid):
    try:
        item = h.app.reminders.snooze(rid, h._body().get("minutes") or 10)
    except reminders.ReminderError as e:
        raise HTTPError(400, str(e))
    h._json({"item": reminders.public(item)})


@route("DELETE", "/api/reminders/([0-9a-f]{8})")
def r_reminders_delete(h, q, rid):
    try:
        h.app.reminders.cancel(rid)
    except reminders.ReminderError as e:
        raise HTTPError(404, str(e))
    h._json({"ok": True})


@route("GET", "/api/tracking")
def r_tracking(h, q):
    h._json(_tracking_payload(h.app))


@route("POST", "/api/tracking")
def r_tracking_add(h, q):
    b = h._body()
    try:
        item = h.app.tracker.add(b.get("code"), b.get("name"))
    except ValueError as e:
        raise HTTPError(400, str(e))
    h._json({"item": item})


@route("POST", "/api/tracking/check")
def r_tracking_check_all(h, q):
    if not h.app.tracker.configured:
        raise HTTPError(400, "Falta a chave do 17TRACK (veja o README).")
    h.app.tracker.run_async()
    h._json({"ok": True})


@route("POST", "/api/tracking/read")
def r_tracking_read_all(h, q):
    h.app.tracker.mark_read()
    h._json({"ok": True})


@route("POST", "/api/tracking/([0-9a-f]{12})/check")
def r_tracking_check(h, q, tid):
    if not h.app.tracker.configured:
        raise HTTPError(400, "Falta a chave do 17TRACK (veja o README).")
    try:
        h.app.tracker.get(tid)
    except KeyError as e:
        raise HTTPError(404, str(e.args[0]))
    threading.Thread(target=h.app.tracker.check, args=(tid,), daemon=True).start()
    h._json({"ok": True})


@route("POST", "/api/tracking/([0-9a-f]{12})/read")
def r_tracking_read(h, q, tid):
    h.app.tracker.mark_read(tid)
    h._json({"ok": True})


@route("POST", "/api/tracking/([0-9a-f]{12})/rename")
def r_tracking_rename(h, q, tid):
    try:
        h._json({"item": h.app.tracker.rename(tid, h._body().get("name"))})
    except ValueError as e:
        raise HTTPError(400, str(e))
    except KeyError as e:
        raise HTTPError(404, str(e.args[0]))


@route("DELETE", "/api/tracking/([0-9a-f]{12})")
def r_tracking_delete(h, q, tid):
    try:
        h.app.tracker.remove(tid)
    except KeyError as e:
        raise HTTPError(404, str(e.args[0]))
    h._json({"ok": True})


@route("GET", "/api/voice")
def r_voice(h, q):
    h._json(h.app.voice.status())


@route("POST", "/api/voice/model")
def r_voice_model(h, q):
    if not h.app.voice.download_model_async():
        raise HTTPError(409, "O download do modelo já está em andamento.")
    h._json({"ok": True})


@route("POST", "/api/voice/pause")
def r_voice_pause(h, q):
    h.app.voice.toggle_pause(h._body().get("paused"))
    h._json(h.app.voice.status())


@route("POST", "/api/google/connect")
def r_google(h, q):
    h.app.google_connect(bool(h._body().get("reauth")))
    h._json({"ok": True})


@route("POST", "/api/spotify/connect")
def r_spotify(h, q):
    h.app.spotify_connect()
    h._json({"ok": True})


# =============================== inicialização ===============================

class RunningServer:
    def __init__(self, httpd, app, thread, port, mode, token):
        self.httpd, self.app, self.thread, self.port, self.mode, self.token = httpd, app, thread, port, mode, token

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/?k={self.token}"

    def shutdown(self):
        self.app.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


def start(cfg, window_hooks=None, port=None, mode=None) -> RunningServer:
    app = App(cfg, window_hooks)
    token = load_token()
    mode = mode or (cfg.get("app") or {}).get("acesso", "local")
    port = int(port if port is not None else (cfg.get("app") or {}).get("porta", 8765))
    handler = type("BoundHandler", (Handler,), {"app": app, "token": token, "mode": mode, "port": port,
                                                  "fails": {}, "fails_lock": threading.Lock(), "ROUTES": Handler.ROUTES})
    httpd = _Server(("0.0.0.0" if mode == "rede" else "127.0.0.1", port), handler)
    real_port = httpd.server_address[1]
    handler.port = real_port
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return RunningServer(httpd, app, thread, real_port, mode, token)
