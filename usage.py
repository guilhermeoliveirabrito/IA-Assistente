"""Medidor de consumo do Gemini.

A API do Gemini NÃO informa quanto da cota gratuita ainda resta. Por isso o app conta
localmente cada chamada (requisições e tokens) e compara com os limites que você configura
em `limites:` no config.yaml. Confira seus limites reais em https://aistudio.google.com/rate-limit.

A cota diária do Gemini renova à meia-noite do horário do Pacífico (America/Los_Angeles).
"""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path("data")
USAGE_FILE = DATA / "usage.json"
KEEP_SECONDS = 3 * 24 * 3600

_lock = threading.Lock()

DEFAULT_LIMITS = {
    "requisicoes_por_dia": 250,
    "requisicoes_por_minuto": 10,
    "tokens_por_minuto": 250000,
    "fuso_renovacao": "America/Los_Angeles",
    "hora_renovacao": "00:00",
}


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"events": [], "last_quota_error": None}


def _save(state: dict):
    DATA.mkdir(exist_ok=True)
    tmp = USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(USAGE_FILE)


def record(model: str, tokens_in: int = 0, tokens_out: int = 0, now: float = None):
    """Registra uma chamada concluída ao Gemini."""
    now = time.time() if now is None else now
    with _lock:
        state = _load()
        state["events"] = [e for e in state["events"] if e["t"] > now - KEEP_SECONDS]
        state["events"].append(
            {"t": now, "model": model, "in": int(tokens_in or 0), "out": int(tokens_out or 0)}
        )
        _save(state)


def record_quota_error(retry_after: float = None, now: float = None):
    """Guarda que a API respondeu 'limite atingido' (429)."""
    now = time.time() if now is None else now
    with _lock:
        state = _load()
        state["last_quota_error"] = {"t": now, "retry_after": retry_after}
        _save(state)


def _window(now: float, tz_name: str, reset_hhmm: str):
    """Início do ciclo diário atual e o próximo reset (epoch), no fuso da renovação."""
    hh, mm = (int(x) for x in reset_hhmm.split(":"))
    tz = ZoneInfo(tz_name)
    now_dt = datetime.fromtimestamp(now, tz)
    start = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if start > now_dt:
        start = start - timedelta(days=1)
    nxt = start + timedelta(days=1)
    nxt = nxt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return start.timestamp(), nxt.timestamp()


def summary(cfg: dict = None, now: float = None) -> dict:
    """Resumo pronto para a interface."""
    now = time.time() if now is None else now
    limits = {**DEFAULT_LIMITS, **((cfg or {}).get("limites") or {})}
    start, nxt = _window(now, limits["fuso_renovacao"], limits["hora_renovacao"])
    with _lock:
        state = _load()
    events = state["events"]
    today = [e for e in events if e["t"] >= start]
    minute = [e for e in events if e["t"] >= now - 60]

    req_day = len(today)
    tok_day = sum(e["in"] + e["out"] for e in today)
    req_min = len(minute)
    tok_min = sum(e["in"] + e["out"] for e in minute)

    def pct(used, limit):
        return round(min(100.0, 100.0 * used / limit), 1) if limit else 0.0

    qerr = state.get("last_quota_error")
    quota_hit = bool(qerr and qerr["t"] >= start and now - qerr["t"] < 15 * 60)

    return {
        "requests_day": {"used": req_day, "limit": limits["requisicoes_por_dia"],
                         "percent": pct(req_day, limits["requisicoes_por_dia"]),
                         "remaining": max(0, limits["requisicoes_por_dia"] - req_day)},
        "requests_minute": {"used": req_min, "limit": limits["requisicoes_por_minuto"],
                            "percent": pct(req_min, limits["requisicoes_por_minuto"])},
        "tokens_minute": {"used": tok_min, "limit": limits["tokens_por_minuto"],
                          "percent": pct(tok_min, limits["tokens_por_minuto"])},
        "tokens_day": tok_day,
        "reset_at": datetime.fromtimestamp(nxt).astimezone().isoformat(timespec="minutes"),
        "reset_epoch": nxt,
        "seconds_to_reset": max(0, int(nxt - now)),
        "quota_hit": quota_hit,
        "estimated": True,
    }
