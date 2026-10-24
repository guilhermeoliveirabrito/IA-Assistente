"""Lembretes, alarmes e tarefas recorrentes.

Um lembrete avisa na hora marcada: no PC (banner no app + som, mesmo com a janela fechada na bandeja) e no celular
(ntfy). Um alarme é um lembrete que toca até você dispensar ou adiar. Qualquer um pode se repetir (todo dia, dias
úteis, toda semana, todo mês, a cada N minutos) e pode, em vez de só avisar, MANDAR O ASSISTENTE FAZER algo
("todo dia às 8h resuma as notícias") como uma tarefa autônoma de leitura.

Os horários são sempre os do relógio do seu computador.
"""
import calendar
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

FILE = Path("data") / "lembretes.json"
TICK = 5
MAX_ITEMS = 200
REPEATS = ("nao", "diario", "dias_uteis", "semanal", "mensal", "intervalo")
KEEP_DONE_SECONDS = 7 * 24 * 3600
STALE_RUN_SECONDS = 3600           # tarefa recorrente atrasada mais que isto (app fechado) não roda: só reagenda
STALE_NOTICE_SECONDS = 12 * 3600   # aviso recorrente atrasado mais que isto também é pulado


class ReminderError(ValueError):
    pass


# ---------------------------------------------------------------- horários

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_when(text, now: float) -> float:
    """'2026-10-24 18:30', '2026-10-24T18:30' ou só '18:30' (hoje, ou amanhã se já passou) -> epoch local."""
    text = " ".join(str(text or "").split())
    cur = datetime.fromtimestamp(now)
    m = _DATE.match(text)
    try:
        if m:
            y, mo, d, h, mi = (int(x) for x in m.groups())
            return datetime(y, mo, d, h, mi).timestamp()
        m = _TIME.match(text)
        if m:
            t = cur.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            return (t if t.timestamp() > now else t + timedelta(days=1)).timestamp()
    except ValueError:
        pass
    raise ReminderError("Horário inválido. Use AAAA-MM-DD HH:MM (ex.: 2026-10-24 18:30) ou só HH:MM.")


def _add_months(dt: datetime, n: int) -> datetime:
    month = dt.month - 1 + n
    year, month = dt.year + month // 12, month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def next_due(item: dict, after: float) -> float:
    """Próxima ocorrência estritamente depois de `after`, mantendo a hora do relógio (inclusive no horário de verão)."""
    rep = (item.get("repeat") or {}).get("tipo", "nao")
    base = datetime.fromtimestamp(item["due"])
    if rep == "intervalo":
        step = max(1, int(item["repeat"].get("minutos") or 60)) * 60
        n = int((after - item["due"]) // step) + 1
        return item["due"] + max(1, n) * step
    cur, i = base, 0
    while cur.timestamp() <= after and i < 4000:
        i += 1
        if rep == "diario":
            cur = cur + timedelta(days=1)
        elif rep == "semanal":
            cur = cur + timedelta(days=7)
        elif rep == "mensal":
            cur = _add_months(base, i)
        elif rep == "dias_uteis":
            cur = cur + timedelta(days=1)
            while cur.weekday() >= 5:
                cur = cur + timedelta(days=1)
        else:
            break
    return cur.timestamp()


def describe_repeat(rep: dict) -> str:
    t = (rep or {}).get("tipo", "nao")
    return {"nao": "uma vez", "diario": "todo dia", "dias_uteis": "dias úteis", "semanal": "toda semana",
            "mensal": "todo mês", "intervalo": f"a cada {int((rep or {}).get('minutos') or 0)} min"}.get(t, t)


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


def _check_id(rid):
    if not re.match(r"^[0-9a-f]{8}$", str(rid or "")):
        raise ReminderError("Código de lembrete inválido.")


# ---------------------------------------------------------------- o serviço

class Reminders:
    """status: ativo (vai disparar) | tocando (disparou, esperando você dispensar) | concluido."""

    def __init__(self, cfg=None, on_fire=None, on_change=None, clock=time.time):
        self.cfg = cfg or {}
        self.on_fire = on_fire or (lambda item, late: None)
        self.on_change = on_change or (lambda: None)
        self.clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    # -- criação e consulta
    def add(self, text, when_ts: float, kind="lembrete", repeat="nao", every_minutes=None, run=False) -> dict:
        text = " ".join(str(text or "").split())
        if not text:
            raise ReminderError("Diga do que devo lembrar.")
        if len(text) > 400:
            raise ReminderError("Texto longo demais (máximo 400 caracteres).")
        if kind not in ("lembrete", "alarme"):
            raise ReminderError("O tipo precisa ser lembrete ou alarme.")
        if repeat not in REPEATS:
            raise ReminderError("Repetição inválida: " + ", ".join(REPEATS) + ".")
        rep = {"tipo": repeat}
        if repeat == "intervalo":
            try:
                n = int(every_minutes)
            except (TypeError, ValueError):
                raise ReminderError("Informe de quantos em quantos minutos repetir.")
            if not 5 <= n <= 7 * 24 * 60:
                raise ReminderError("O intervalo deve ficar entre 5 minutos e 7 dias.")
            rep["minutos"] = n
        now = self.clock()
        if when_ts < now - 60:
            raise ReminderError("Esse horário já passou.")
        if when_ts > now + 3 * 365 * 24 * 3600:
            raise ReminderError("Esse horário está longe demais (máximo 3 anos).")
        with self._lock:
            data = _load()
            if len([i for i in data["items"] if i["status"] != "concluido"]) >= MAX_ITEMS:
                raise ReminderError(f"Limite de {MAX_ITEMS} lembretes ativos.")
            item = {"id": uuid.uuid4().hex[:8], "text": text, "due": float(when_ts), "kind": kind, "repeat": rep,
                    "run": bool(run), "status": "ativo", "created": now, "fired": 0, "last_fired": None}
            data["items"].append(item)
            _save(data)
        self.on_change()
        return dict(item)

    def items(self, include_done=False) -> list:
        with self._lock:
            items = _load()["items"]
        items = [i for i in items if include_done or i["status"] != "concluido"]
        return sorted(items, key=lambda i: (i["status"] != "tocando", i["due"]))

    def get(self, rid) -> dict:
        _check_id(rid)
        for i in self.items(True):
            if i["id"] == rid:
                return dict(i)
        raise ReminderError("Não achei esse lembrete.")

    def _mutate(self, rid, fn):
        _check_id(rid)
        with self._lock:
            data = _load()
            for i, it in enumerate(data["items"]):
                if it["id"] == rid:
                    out = fn(it)
                    if out is None:
                        del data["items"][i]
                    _save(data)
                    break
            else:
                raise ReminderError("Não achei esse lembrete.")
        self.on_change()
        return out

    def cancel(self, rid):
        self._mutate(rid, lambda it: None)

    def dismiss(self, rid) -> dict:
        """Dispensa o que está tocando. Se for recorrente, segue ativo para a próxima vez."""
        def fn(it):
            if it["status"] == "tocando":
                it["status"] = "ativo" if it["repeat"]["tipo"] != "nao" else "concluido"
                it["done_at"] = self.clock()
            return it
        return dict(self._mutate(rid, fn))

    def snooze(self, rid, minutes=10) -> dict:
        try:
            minutes = max(1, min(int(minutes), 24 * 60))
        except (TypeError, ValueError):
            raise ReminderError("Informe os minutos de soneca.")

        def fn(it):
            if it["status"] == "concluido":
                raise ReminderError("Esse lembrete já foi concluído.")
            when = self.clock() + minutes * 60
            if it["repeat"]["tipo"] == "nao":
                it["due"] = when
            else:                                  # a série continua igual; só esta ocorrência é adiada
                it["snooze_due"] = when
            it["status"] = "ativo"
            return it
        return dict(self._mutate(rid, fn))

    # -- disparo
    def check_due(self) -> int:
        """Dispara o que venceu. Devolve quantos dispararam."""
        now = self.clock()
        fired = []
        with self._lock:
            data = _load()
            changed = False
            keep = []
            for it in data["items"]:
                if it["status"] == "concluido" and now - (it.get("done_at") or it["created"]) > KEEP_DONE_SECONDS:
                    changed = True
                    continue
                keep.append(it)
                snooze = it.get("snooze_due")
                due = snooze if snooze else it["due"]
                rep = it["repeat"]["tipo"]
                if it["status"] == "concluido" or (it["status"] == "tocando" and rep == "nao") or due > now:
                    continue
                late = now - due
                if snooze:
                    it.pop("snooze_due", None)
                elif rep != "nao":
                    it["due"] = next_due(it, now)
                changed = True
                if rep != "nao" and not snooze and late > (STALE_RUN_SECONDS if it.get("run") else STALE_NOTICE_SECONDS):
                    continue                                        # ficou muito para trás (app fechado): só reagenda
                it["fired"] += 1
                it["last_fired"] = now
                if it.get("run") and rep == "nao":
                    it["status"], it["done_at"] = "concluido", now      # tarefa feita pelo assistente: nada a dispensar
                elif it["kind"] == "alarme" or rep == "nao":
                    it["status"] = "tocando"                            # espera você dispensar ou adiar
                else:
                    it["status"] = "ativo"                              # lembrete recorrente: só avisa e segue
                fired.append((dict(it), late))
            data["items"] = keep
            if changed:
                _save(data)
        for item, late in fired:
            try:
                self.on_fire(item, late)
            except Exception:
                pass
        if changed:
            self.on_change()
        return len(fired)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lembretes", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(TICK):
            try:
                self.check_due()
            except Exception:
                pass

    def stop(self):
        self._stop.set()

    # -- painel de verificações (mesmo formato do rastreio)
    def status(self) -> dict:
        items = self.items()
        act = [i for i in items if i["status"] == "ativo"]
        nxt = min((i.get("snooze_due") or i["due"] for i in act), default=None)
        ringing = len([i for i in items if i["status"] == "tocando"])
        note = "Nenhum lembrete marcado." if not act else ""
        if ringing:
            note = f"{ringing} esperando você dispensar."
        return {"id": "lembretes", "label": "Lembretes e alarmes", "every": "na hora marcada", "next_ts": nxt, "note": note,
                "last_ts": None, "last_ok": None, "last_text": "", "running": False, "can_run": False}


# ---------------------------------------------------------------- acesso das ferramentas do agente

_default = None


def set_default(r):
    global _default
    _default = r


def default() -> "Reminders":
    if _default is None:
        raise ReminderError("Os lembretes não estão disponíveis.")
    return _default


def public(item: dict) -> dict:
    """Versão curta (para o modelo e para a interface)."""
    when = datetime.fromtimestamp(item.get("snooze_due") or item["due"]).strftime("%Y-%m-%d %H:%M")
    return {"id": item["id"], "texto": item["text"], "quando": when, "tipo": item["kind"],
            "repete": describe_repeat(item["repeat"]), "executa": bool(item.get("run")), "status": item["status"]}
