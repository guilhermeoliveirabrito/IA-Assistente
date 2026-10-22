"""Medidor de consumo do Gemini, MODELO POR MODELO.

A API do Gemini não tem nenhuma chamada que diga quanto da cota ainda resta. O que o app sabe com certeza:

  1. quantas chamadas ELE MESMO fez a cada modelo, e quantos tokens (contagem exata, uma por requisição);
  2. quando o Google RECUSA uma chamada (erro 429): isso é a palavra do próprio Google de que a cota daquele
     modelo acabou, e a resposta costuma trazer o LIMITE real (guardado como "limite confirmado").

O que ele não enxerga: uso da mesma chave fora do app (outro programa, o AI Studio). Para isso há o
"ajustar" (calibrar): você digita o número que o painel do Google mostra e o app passa a somar a diferença.

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


_cfg = None            # a configuração viva (o app chama configure); sem ela valem os padrões
_listeners = []


def configure(cfg):
    global _cfg
    _cfg = cfg


def unsubscribe(fn):
    if fn in _listeners:
        _listeners.remove(fn)


def subscribe(fn):
    """fn(evento: dict) é chamada quando o consumo muda ou o modelo em uso é trocado."""
    _listeners.append(fn)


def _notify(event: dict):
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception:
            pass


def _limits(cfg=None) -> dict:
    return {**DEFAULT_LIMITS, **(((cfg if cfg is not None else _cfg) or {}).get("limites") or {})}


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
    _notify({"type": "usage"})


def _model_state(state: dict, model: str) -> dict:
    return state.setdefault("models", {}).setdefault(model, {})


def record_quota_error(retry_after: float = None, now: float = None, model: str = None, quota: dict = None):
    """Guarda que a API respondeu 'limite atingido' (429) — para um modelo específico, quando se sabe qual.

    quota (opcional, lido da resposta do Google): {"scope": "day"|"minute"|None, "kind": "requests"|"tokens",
    "limit": int|None}. Com isso o app aprende o limite REAL do modelo.
    """
    now = time.time() if now is None else now
    quota = quota or {}
    with _lock:
        state = _load()
        state["last_quota_error"] = {"t": now, "retry_after": retry_after, "model": model}
        if model:
            m = _model_state(state, model)
            start, nxt = _window(now, *(_limits()[k] for k in ("fuso_renovacao", "hora_renovacao")))
            scope = quota.get("scope")
            if scope is None:       # o Google não disse: pausas curtas são de minuto; o resto, tratamos como do dia
                scope = "minute" if retry_after is not None and retry_after <= 120 else "day"
            if scope == "day":
                m["day_exhausted_until"] = nxt
            else:
                m["minute_until"] = now + (retry_after if retry_after else 60)
            m["last_rejection"] = {"t": now, "scope": scope, "confirmed_by_google": bool(quota)}
            m.setdefault("rejections", []).append(now)
            m["rejections"] = [t for t in m["rejections"] if t >= start]
            if quota.get("limit"):
                key = {("requests", "day"): "rpd", ("requests", "minute"): "rpm", ("tokens", "minute"): "tpm",
                       ("tokens", "day"): "tpd"}.get((quota.get("kind", "requests"), scope))
                if key:
                    m.setdefault("learned", {})[key] = int(quota["limit"])
        _save(state)
    _notify({"type": "usage"})


def note_model(model: str, skipped=(), now: float = None):
    """Chamada quando um modelo ACEITOU a requisição. Registra a troca de modelo, se houve, e o motivo."""
    now = time.time() if now is None else now
    switch = None
    with _lock:
        state = _load()
        m = _model_state(state, model)
        m["day_exhausted_until"] = None        # respondeu: a cota existe
        m["minute_until"] = None
        previous = state.get("current")
        if previous != model:
            reasons = {"quota": "a cota acabou", "server": "estava sobrecarregado", "model": "não está disponível"}
            if skipped:
                why = "; ".join(f"{m_}: {reasons.get(k, k)}" for m_, k in skipped)
            else:
                why = "voltou ao modelo principal" if previous else "primeiro uso"
            switch = {"t": now, "from": previous, "to": model, "reason": why}
            state.setdefault("switches", []).append(switch)
            state["switches"] = state["switches"][-20:]
        state["current"] = model
        _save(state)
    if switch and switch["from"]:
        _notify({"type": "model_switch", **switch})
    _notify({"type": "usage"})


def blocked_models(models):
    """Quais destes o Google recusou há pouco por cota (dia ou minuto)."""
    now = time.time()
    with _lock:
        flags = (_load().get("models") or {})
    def blocked(m):
        f = flags.get(m) or {}
        return (f.get("day_exhausted_until") or 0) > now or (f.get("minute_until") or 0) > now
    return [m for m in models if blocked(m)]


def prefer_order(models):
    """Modelos que o Google acabou de recusar por cota vão para o fim da fila (sem sumir dela)."""
    bad = set(blocked_models(models))
    return [m for m in models if m not in bad] + [m for m in models if m in bad]


def calibrate(model: str, requests_used: int, now: float = None):
    """Você viu no painel do Google que o modelo já usou N requisições hoje: o app soma a diferença."""
    now = time.time() if now is None else now
    n = int(requests_used)
    if n < 0 or n > 10_000_000:
        raise ValueError("Número inválido.")
    start, _ = _window(now, *(_limits()[k] for k in ("fuso_renovacao", "hora_renovacao")))
    with _lock:
        state = _load()
        mine = len([e for e in state["events"] if e["t"] >= start and e["model"] == model])
        _model_state(state, model)["offset"] = {"window": start, "requests": max(0, n - mine)}
        _save(state)
    _notify({"type": "usage"})


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


def _configured_limits(cfg, model: str) -> dict:
    """Limites escritos por você em `limites.por_modelo` (lista 'modelo=por_dia,por_minuto,tokens_por_minuto')."""
    raw = ((cfg or {}).get("limites") or {}).get("por_modelo") or []
    out = {}
    if isinstance(raw, dict):
        d = raw.get(model) or {}
        for key, name in (("rpd", "requisicoes_por_dia"), ("rpm", "requisicoes_por_minuto"), ("tpm", "tokens_por_minuto")):
            if d.get(name):
                out[key] = int(d[name])
        return out
    for item in raw:
        name, _, rest = str(item).partition("=")
        if name.strip() != model:
            continue
        nums = [x.strip() for x in rest.split(",")]
        for key, val in zip(("rpd", "rpm", "tpm"), nums):
            if val.isdigit() and int(val) > 0:
                out[key] = int(val)
    return out


def _model_names(cfg, events_today) -> list:
    ia = (cfg or {}).get("ia") or {}
    names = []
    for m in [ia.get("modelo")] + list(ia.get("modelos_reserva") or []):
        if m and m not in names:
            names.append(m)
    for e in events_today:
        if e["model"] not in names:
            names.append(e["model"])
    return names


def _per_model(cfg, state, now, start, events_today, minute_events, limits) -> list:
    flags = state.get("models") or {}
    current = state.get("current")
    out = []
    for name in _model_names(cfg, events_today):
        f = flags.get(name) or {}
        mine_day = [e for e in events_today if e["model"] == name]
        mine_min = [e for e in minute_events if e["model"] == name]
        offset = f.get("offset") or {}
        calibrated = offset.get("window") == start
        used = len(mine_day) + (int(offset.get("requests", 0)) if calibrated else 0)
        lim = {"rpd": limits["requisicoes_por_dia"], "rpm": limits["requisicoes_por_minuto"], "tpm": limits["tokens_por_minuto"]}
        source = {"rpd": "estimado", "rpm": "estimado", "tpm": "estimado"}
        for key, val in _configured_limits(cfg, name).items():
            lim[key], source[key] = val, "seu config"
        for key, val in (f.get("learned") or {}).items():
            if key in lim:
                lim[key], source[key] = val, "Google"
        day_blocked = (f.get("day_exhausted_until") or 0) > now
        min_blocked = (f.get("minute_until") or 0) > now
        if day_blocked:
            status, label = "esgotado", "Esgotado hoje (o Google recusou)"
        elif min_blocked:
            status, label = "espera", f"Limite por minuto (volta em {int(f['minute_until'] - now)}s)"
        elif used >= lim["rpd"]:
            status, label = "cheio", "No limite, pela contagem (ainda não recusado pelo Google)"
        elif name == current:
            status, label = "em_uso", "Em uso agora"
        else:
            status, label = "disponivel", "Disponível"
        pct = lambda a, b: round(min(100.0, 100.0 * a / b), 1) if b else 0.0
        tok_min = sum(e["in"] + e["out"] for e in mine_min)
        rejections = [t for t in (f.get("rejections") or []) if t >= start]
        out.append({
            "model": name, "in_use": name == current, "status": status, "status_label": label,
            "requests_day": {"used": used, "limit": lim["rpd"], "remaining": max(0, lim["rpd"] - used),
                             "percent": pct(used, lim["rpd"]), "limit_source": source["rpd"]},
            "requests_minute": {"used": len(mine_min), "limit": lim["rpm"], "percent": pct(len(mine_min), lim["rpm"]),
                                "limit_source": source["rpm"]},
            "tokens_minute": {"used": tok_min, "limit": lim["tpm"], "percent": pct(tok_min, lim["tpm"]),
                              "limit_source": source["tpm"]},
            "tokens_day": sum(e["in"] + e["out"] for e in mine_day),
            "rejections_day": len(rejections),
            "last_used": max([e["t"] for e in mine_day], default=None),
            "calibrated": calibrated,
        })
    return out


def summary(cfg: dict = None, now: float = None) -> dict:
    """Resumo pronto para a interface."""
    now = time.time() if now is None else now
    limits = _limits(cfg)
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

    models = _per_model(cfg, state, now, start, today, minute, limits)
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
        "models": models,
        "current_model": state.get("current") or (models[0]["model"] if models else None),
        "switches": list(reversed(state.get("switches") or []))[:8],
    }
