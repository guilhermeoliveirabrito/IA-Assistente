"""Histórico de atividade do assistente: o que ele planejou, fez e perguntou.

Fica em data/activity.jsonl (uma linha por evento) e se apaga sozinho: eventos mais antigos
que `historico.dias_de_retencao` (config.yaml) são removidos, e há um teto de eventos.
Serve para você ver, ao voltar, o que ele fez enquanto você estava fora.
"""
import json
import threading
import time
import uuid
from pathlib import Path

DATA = Path("data")
FILE = DATA / "activity.jsonl"
MAX_TEXT = 2000
DEFAULT_DAYS = 7
DEFAULT_MAX_EVENTS = 5000
PRUNE_EVERY = 3600  # segundos entre limpezas automáticas

KINDS = {"tarefa", "plano", "acao", "resultado", "erro", "pergunta", "info"}

_lock = threading.RLock()
_last_prune = 0.0
_settings = {"days": DEFAULT_DAYS, "max_events": DEFAULT_MAX_EVENTS}


def configure(cfg: dict):
    h = (cfg or {}).get("historico") or {}
    _settings["days"] = float(h.get("dias_de_retencao", DEFAULT_DAYS))
    _settings["max_events"] = int(h.get("maximo_de_eventos", DEFAULT_MAX_EVENTS))


def _read_all():
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for ln in lines:
        try:
            events.append(json.loads(ln))
        except ValueError:
            continue  # linha corrompida é ignorada
    return events


def _rewrite(events):
    DATA.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    tmp.replace(FILE)


def prune(now: float = None) -> int:
    """Remove eventos vencidos e acima do teto. Retorna quantos foram apagados."""
    global _last_prune
    now = time.time() if now is None else now
    with _lock:
        events = _read_all()
        cutoff = now - _settings["days"] * 86400
        kept = [e for e in events if e.get("t", 0) >= cutoff]
        kept = kept[-_settings["max_events"]:]
        removed = len(events) - len(kept)
        if removed:
            _rewrite(kept)
        _last_prune = now
        return removed


def log(kind: str, text: str, task: str = None, now: float = None, **data) -> dict:
    """Registra um evento. `kind` ∈ tarefa, plano, acao, resultado, erro, pergunta, info."""
    now = time.time() if now is None else now
    if kind not in KINDS:
        kind = "info"
    event = {"id": uuid.uuid4().hex[:10], "t": now, "kind": kind,
             "text": (text or "")[:MAX_TEXT], "task": task}
    if data:
        event["data"] = data
    with _lock:
        DATA.mkdir(exist_ok=True)
        with FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if now - _last_prune > PRUNE_EVERY:
            prune(now)
    return event


def recent(limit: int = 200, task: str = None, since: float = None, kinds=None):
    """Eventos mais novos primeiro."""
    with _lock:
        events = _read_all()
    if task:
        events = [e for e in events if e.get("task") == task]
    if since:
        events = [e for e in events if e.get("t", 0) >= since]
    if kinds:
        events = [e for e in events if e.get("kind") in kinds]
    return list(reversed(events))[:limit]


def clear():
    with _lock:
        FILE.unlink(missing_ok=True)
