"""Rastreio de encomendas: você informa o código, o assistente acompanha e avisa quando algo muda.

Usa o serviço 17TRACK (reconhece Correios e centenas de transportadoras do mundo todo). Precisa de uma chave de
acesso GRATUITA (veja o README): coloque `TRACK17_KEY=...` no arquivo .env. Sem a chave o app guarda os códigos e
oferece o link do site de rastreio, mas não consegue consultar sozinho.

Os Correios não têm mais API pública sem contrato (CNPJ), por isso esta é a alternativa gratuita.
Tudo fica em data/rastreio.json. Um código entregue deixa de ser consultado.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from assistente.nucleo import activity

FILE = Path("data") / "rastreio.json"
API = "https://api.17track.net/track/v2.2"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{4,39}$")
MAX_ITEMS = 60
MAX_EVENTS = 40
MAX_UPDATES = 30
MIN_INTERVAL_MIN = 15
STALE_DAYS = 90               # sem nenhuma novidade por tanto tempo: para de consultar

STATUS_PT = {
    "NotFound": "Ainda não encontrado",
    "InfoReceived": "Pedido registrado, aguardando a postagem",
    "InTransit": "Em trânsito",
    "Expired": "Sem atualização há muito tempo",
    "AvailableForPickup": "Disponível para retirada",
    "OutForDelivery": "Saiu para entrega",
    "DeliveryFailure": "Falha na entrega",
    "Delivered": "Entregue",
    "Exception": "Problema no transporte",
    "Pending": "Aguardando a primeira consulta",
}
FINAL = {"Delivered"}
GOOD = {"Delivered", "OutForDelivery", "AvailableForPickup"}


class TrackingError(Exception):
    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind            # "key" | "quota" | "network" | "other"


def tracking_url(code: str) -> str:
    return "https://t.17track.net/pt#nums=" + re.sub(r"[^A-Za-z0-9\-]", "", code)


def valid_code(code: str) -> str:
    code = re.sub(r"\s+", "", str(code or "")).upper()
    if not CODE_RE.match(code):
        raise ValueError("Código de rastreio inválido. Use só letras, números e hífen (ex.: AA123456789BR).")
    return code


def api_key() -> str:
    return (os.environ.get("TRACK17_KEY") or "").strip()


# ---------------------------------------------------------------- serviço de rastreio (17TRACK)

def _http_post(path: str, body, key: str, timeout: int = 25):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"17token": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TrackingError("A chave do 17TRACK foi recusada. Confira o TRACK17_KEY no arquivo .env.", "key") from e
        if e.code == 429:
            raise TrackingError("O 17TRACK pediu para esperar (limite de consultas). Tento de novo depois.", "quota") from e
        raise TrackingError(f"O 17TRACK respondeu com erro {e.code}.", "other") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TrackingError(f"Sem conexão com o 17TRACK: {e}", "network") from e


def _place(e: dict) -> str:
    loc = e.get("location")
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    addr = e.get("address")
    if isinstance(addr, dict):
        return ", ".join(str(addr[k]) for k in ("city", "state", "country") if addr.get(k))
    return addr.strip() if isinstance(addr, str) else ""


def _event(e: dict) -> dict:
    return {"time": e.get("time_iso") or e.get("time_utc") or e.get("time_raw") or "",
            "text": (e.get("description") or "").strip(),
            "place": _place(e),
            "stage": e.get("stage") or ""}


def parse_info(accepted: dict) -> dict:
    """Resposta do 17TRACK (um item de data.accepted) -> {status, events, carrier}."""
    info = accepted.get("track_info") or {}
    status = ((info.get("latest_status") or {}).get("status")) or "NotFound"
    events = []
    carrier = ""
    for p in ((info.get("tracking") or {}).get("providers") or []):
        carrier = carrier or ((p.get("provider") or {}).get("name") or "")
        events += [_event(e) for e in (p.get("events") or [])]
    if not events and info.get("latest_event"):
        events = [_event(info["latest_event"])]
    events = [e for e in events if e["text"] or e["time"]]
    events.sort(key=lambda e: e["time"], reverse=True)       # mais novo primeiro (ISO ordena como texto)
    return {"status": status if status in STATUS_PT else "InTransit", "events": events[:MAX_EVENTS], "carrier": carrier}


class Track17:
    def __init__(self, key_fn=api_key, post=_http_post):
        self.key_fn = key_fn
        self.post = post

    @property
    def configured(self) -> bool:
        return bool(self.key_fn())

    def fetch(self, code: str) -> dict:
        key = self.key_fn()
        if not key:
            raise TrackingError("Falta a chave do 17TRACK (TRACK17_KEY no arquivo .env; veja o README).", "key")
        reg = self.post("register", [{"number": code}], key)
        self._check_code(reg)
        rejected = ((reg.get("data") or {}).get("rejected") or [])
        for r in rejected:
            err = (r.get("error") or {})
            c = err.get("code")
            if c == -18019901:          # já estava cadastrado: normal
                continue
            if c in (-18019907, -18019908):
                raise TrackingError("Acabou a cota gratuita de códigos do 17TRACK.", "quota")
            if c == -18019903:
                return {"status": "NotFound", "events": [], "carrier": "", "note": "Não reconheci a transportadora desse código."}
            raise TrackingError(err.get("message") or "O 17TRACK recusou o código.", "other")
        info = self.post("gettrackinfo", [{"number": code}], key)
        self._check_code(info)
        data = info.get("data") or {}
        accepted = data.get("accepted") or []
        if accepted:
            return parse_info(accepted[0])
        for r in (data.get("rejected") or []):
            c = (r.get("error") or {}).get("code")
            if c in (-18019909, -18019910):       # ainda sem dados (acabou de cadastrar)
                return {"status": "NotFound", "events": [], "carrier": "", "note": "O serviço ainda está buscando esse código."}
        return {"status": "NotFound", "events": [], "carrier": ""}

    @staticmethod
    def _check_code(obj):
        code = obj.get("code") if isinstance(obj, dict) else None
        if code not in (0, None):
            if code in (-18010002, -18010003, -18010004):
                raise TrackingError("A chave do 17TRACK é inválida ou está bloqueada.", "key")
            raise TrackingError(f"O 17TRACK devolveu o erro {code}.", "other")


# ---------------------------------------------------------------- armazenamento

def _load():
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("items"), list) else {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def _save(data):
    FILE.parent.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def _signature(result: dict) -> str:
    top = result["events"][0] if result["events"] else {}
    raw = f"{result['status']}|{top.get('time')}|{top.get('text')}|{len(result['events'])}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def describe(item: dict) -> str:
    ev = (item.get("events") or [None])[0]
    text = item.get("status_label") or ""
    if ev and ev.get("text"):
        text += f" — {ev['text']}" + (f" ({ev['place']})" if ev.get("place") else "")
    return text


# ---------------------------------------------------------------- o acompanhamento

class Tracker:
    def __init__(self, cfg, provider=None, on_update=None, on_change=None, clock=time.time):
        self.cfg = cfg
        self.provider = provider or Track17()
        self.on_update = on_update or (lambda item, text, kind="info": None)   # novidade para avisar o usuário
        self.on_change = on_change or (lambda: None)             # qualquer mudança de estado (interface)
        self.clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._next = None
        self._busy = set()
        self.last = {"ts": None, "ok": None, "text": "", "running": False}

    # ---- configuração
    @property
    def interval(self) -> int:
        m = int(((self.cfg.get("rastreio") or {}).get("verificar_a_cada_minutos", 60)) or 60)
        return max(MIN_INTERVAL_MIN, m) * 60

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", True))

    # ---- lista
    def items(self):
        with self._lock:
            return [dict(i) for i in _load()["items"]]

    def get(self, item_id):
        for i in self.items():
            if i["id"] == item_id:
                return i
        raise KeyError("Encomenda não encontrada.")

    def find_code(self, code):
        code = valid_code(code)
        for i in self.items():
            if i["code"] == code:
                return i
        raise KeyError("Não estou acompanhando esse código.")

    def unread(self) -> int:
        return sum(1 for i in self.items() if i.get("unread"))

    def active(self):
        now = self.clock()
        return [i for i in self.items()
                if i.get("status") not in FINAL and now - (i.get("last_change") or i["added"]) < STALE_DAYS * 86400]

    def _update(self, item_id, **fields):
        with self._lock:
            data = _load()
            for i in data["items"]:
                if i["id"] == item_id:
                    i.update(fields)
                    _save(data)
                    return dict(i)
        raise KeyError("Encomenda não encontrada.")

    def add(self, code, name="", check=True):
        code = valid_code(code)
        name = " ".join(str(name or "").split())[:60]
        with self._lock:
            data = _load()
            if any(i["code"] == code for i in data["items"]):
                raise ValueError("Já estou acompanhando esse código.")
            if len(data["items"]) >= MAX_ITEMS:
                raise ValueError(f"Limite de {MAX_ITEMS} encomendas. Remova as antigas.")
            now = self.clock()
            item = {"id": uuid.uuid4().hex[:12], "code": code, "name": name or code, "added": now, "status": "Pending",
                    "status_label": STATUS_PT["Pending"], "found": None, "events": [], "carrier": "", "sig": "",
                    "last_check": None, "last_change": now, "unread": False, "error": "", "note": "", "updates": [],
                    "url": tracking_url(code)}
            data["items"].insert(0, item)
            _save(data)
        self.on_change()
        if check:
            threading.Thread(target=self.check, args=(item["id"],), kwargs={"first": True}, name="rastreio-novo",
                             daemon=True).start()
        return dict(item)

    def rename(self, item_id, name):
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise ValueError("Dê um nome para a encomenda.")
        item = self._update(item_id, name=name)
        self.on_change()
        return item

    def mark_read(self, item_id=None):
        with self._lock:
            data = _load()
            for i in data["items"]:
                if item_id is None or i["id"] == item_id:
                    i["unread"] = False
            _save(data)
        self.on_change()

    def remove(self, item_id):
        with self._lock:
            data = _load()
            n = len(data["items"])
            data["items"] = [i for i in data["items"] if i["id"] != item_id]
            if len(data["items"]) == n:
                raise KeyError("Encomenda não encontrada.")
            _save(data)
        self.on_change()

    # ---- consulta
    def check(self, item_id, first=False) -> dict:
        """Consulta uma encomenda e avisa se algo mudou. Nunca levanta erro de rede: guarda em item['error']."""
        with self._lock:
            if item_id in self._busy:
                return self.get(item_id)
            self._busy.add(item_id)
        try:
            item = self.get(item_id)
            self.last["running"] = True
            self.on_change()
            try:
                result = self.provider.fetch(item["code"])
            except TrackingError as e:
                changed_err = item.get("error") != str(e)
                item = self._update(item_id, error=str(e), last_check=self.clock())
                if changed_err:
                    activity.log("erro", f"Rastreio {item['code']}: {e}")
                    self.on_update(item, f"Não consegui consultar: {e}", kind="erro")
                self.last.update(ts=self.clock(), ok=False, text=str(e))
                return item
            return self._apply(item, result, first)
        finally:
            with self._lock:
                self._busy.discard(item_id)
            self.last["running"] = False
            self.on_change()

    def _apply(self, item, result, first):
        sig = _signature(result)
        found = result["status"] != "NotFound" or bool(result["events"])
        label = STATUS_PT.get(result["status"], result["status"])
        changed = sig != item.get("sig")
        fields = dict(status=result["status"], status_label=label, events=result["events"], found=found, sig=sig,
                      carrier=result.get("carrier") or item.get("carrier", ""), note=result.get("note", ""), error="",
                      last_check=self.clock())
        was_found = item.get("found")
        notify_text = None
        if first and not found:
            notify_text = "Ainda não encontrei esse código. Pode levar horas depois da postagem; sigo tentando e aviso quando aparecer."
        elif found and (was_found is not True or (changed and item.get("sig"))):
            fields.update(last_change=self.clock(), unread=True)
            probe = {**item, **fields}
            notify_text = ("Encontrei! " if was_found is not True else "") + describe(probe)
        if notify_text:
            ups = ([{"ts": self.clock(), "text": notify_text}] + list(item.get("updates") or []))[:MAX_UPDATES]
            fields["updates"] = ups
        item = self._update(item["id"], **fields)
        self.last.update(ts=self.clock(), ok=True, text=notify_text or "Sem novidades.")
        if notify_text:
            self.on_update(item, notify_text, kind="pronta" if result["status"] in GOOD else "info")
        return item

    def check_all(self) -> int:
        n = 0
        for i in self.active():
            if self._stop.is_set():
                break
            self.check(i["id"])
            n += 1
        if n:
            self.last.update(ts=self.clock())
        return n

    # ---- segundo plano
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._next = self.clock() + 30
        self._thread = threading.Thread(target=self._loop, name="rastreio", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(5):
            if self._next is not None and self.clock() >= self._next:
                self.run_now()

    def run_now(self):
        if self.configured:
            self.check_all()
        self._next = self.clock() + self.interval
        self.on_change()

    def run_async(self):
        threading.Thread(target=self.run_now, name="rastreio-agora", daemon=True).start()

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        act = self.active() if self.configured else []
        note = ""
        if not self.configured:
            note = "Falta a chave do 17TRACK (veja a aba Encomendas)."
        elif not act:
            note = "Nenhuma encomenda para acompanhar."
        return {"id": "rastreio", "label": "Rastreio de encomendas", "every": f"a cada {self.interval // 60} min",
                "next_ts": self._next if (act and self._thread and self._thread.is_alive()) else None, "note": note,
                "last_ts": self.last["ts"], "last_ok": self.last["ok"], "last_text": self.last["text"],
                "running": self.last["running"], "can_run": bool(act), "run_url": "/api/tracking/check"}


# ---------------------------------------------------------------- acesso das ferramentas do agente

_default = None


def set_default(tracker):
    global _default
    _default = tracker


def default() -> "Tracker":
    if _default is None:
        raise ValueError("O rastreio de encomendas não está disponível.")
    return _default
