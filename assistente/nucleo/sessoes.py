"""Aparelhos conectados (sessões) e registro de acessos.

Em vez de guardar o próprio código de acesso no cookie do navegador, cada aparelho que entra recebe uma **sessão**
própria (um segredo aleatório; só o hash fica em disco). Assim dá para ver quem está conectado, tirar um aparelho
perdido sem trocar o código de todos e limitar o estrago de um cookie vazado. O código de acesso continua servindo
para entrar (e para o cabeçalho X-Access-Code de ferramentas locais).

O registro de acessos guarda, em `data/acessos.jsonl`, os eventos sensíveis: entradas, tentativas erradas, fotos da
tela, atualizações e aparelhos removidos.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

MAX_AGE = 90 * 86400          # sessão sem uso por 90 dias expira
TOUCH_EVERY = 60              # grava "visto por último" no máximo a cada 60 s
MAX_SESSIONS = 30
AUDIT_MAX = 1500
AUDIT_KEEP = 1000


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def device_name(user_agent: str) -> str:
    """Nome curto e legível do aparelho a partir do User-Agent."""
    ua = (user_agent or "").lower()
    if "iphone" in ua:
        so = "iPhone"
    elif "ipad" in ua:
        so = "iPad"
    elif "android" in ua:
        so = "Android"
    elif "windows" in ua:
        so = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        so = "Mac"
    elif "linux" in ua:
        so = "Linux"
    else:
        so = "Aparelho"
    if "edg/" in ua:
        nav = "Edge"
    elif "opr/" in ua or "opera" in ua:
        nav = "Opera"
    elif "firefox" in ua:
        nav = "Firefox"
    elif "chrome" in ua or "crios" in ua:
        nav = "Chrome"
    elif "safari" in ua:
        nav = "Safari"
    else:
        nav = ""
    return f"{so}" + (f" · {nav}" if nav else "")


class Sessions:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self._lock = threading.Lock()
        self._data = self._load()
        self._dirty_at = 0.0
        self._prune()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def _prune(self):
        now = self.clock()
        before = len(self._data)
        self._data = {k: v for k, v in self._data.items() if now - float(v.get("visto", 0)) <= MAX_AGE}
        if len(self._data) > MAX_SESSIONS:       # mantém as mais recentes
            keep = sorted(self._data, key=lambda k: self._data[k].get("visto", 0), reverse=True)[:MAX_SESSIONS]
            self._data = {k: self._data[k] for k in keep}
        if len(self._data) != before:
            self._save()

    def create(self, name: str, ip: str) -> str:
        """Nova sessão; devolve o valor do cookie ("id.segredo")."""
        sid, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._data[sid] = {"hash": _hash(secret), "nome": name[:60], "ip": ip, "criado": now, "visto": now}
            self._prune()
            self._save()
        return f"{sid}.{secret}"

    def verify(self, cookie: str):
        """Id da sessão se o cookie for válido, senão None."""
        sid, _, secret = (cookie or "").partition(".")
        if not sid or not secret:
            return None
        with self._lock:
            s = self._data.get(sid)
            if not s or not hmac.compare_digest(s["hash"], _hash(secret)):
                return None
            now = self.clock()
            if now - float(s.get("visto", 0)) > MAX_AGE:
                del self._data[sid]
                self._save()
                return None
            if now - float(s.get("visto", 0)) >= TOUCH_EVERY:
                s["visto"] = now
                self._save()
            return sid

    def listing(self, current: str = None) -> list:
        with self._lock:
            rows = [{"id": k, "nome": v.get("nome", ""), "ip": v.get("ip", ""), "criado": v.get("criado"),
                     "visto": v.get("visto"), "atual": k == current} for k, v in self._data.items()]
        return sorted(rows, key=lambda r: r["visto"] or 0, reverse=True)

    def revoke(self, sid: str) -> bool:
        with self._lock:
            if sid not in self._data:
                return False
            del self._data[sid]
            self._save()
            return True

    def revoke_others(self, keep: str = None) -> int:
        with self._lock:
            gone = [k for k in self._data if k != keep]
            for k in gone:
                del self._data[k]
            if gone:
                self._save()
            return len(gone)


class Audit:
    """Registro de eventos sensíveis, uma linha JSON por evento. Nunca guarda códigos nem conteúdo."""

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self._lock = threading.Lock()

    def log(self, event: str, detail: str = "", ip: str = "", device: str = ""):
        row = {"t": round(self.clock()), "evento": event, "detalhe": detail[:160], "ip": ip, "aparelho": device[:60]}
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._trim()
            except OSError:
                pass            # o registro nunca pode derrubar o app

    def _trim(self):
        try:
            lines = self.path.read_text("utf-8").splitlines()
        except OSError:
            return
        if len(lines) > AUDIT_MAX:
            self.path.write_text("\n".join(lines[-AUDIT_KEEP:]) + "\n", encoding="utf-8")

    def recent(self, limit: int = 50) -> list:
        with self._lock:
            try:
                lines = self.path.read_text("utf-8").splitlines()[-limit:]
            except OSError:
                return []
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out
