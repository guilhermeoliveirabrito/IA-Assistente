"""Cliente REST do Gemini usando só a biblioteca padrão do Python.

Por que REST e não o SDK: menos dependências para instalar, e as partes da resposta
(incluindo assinaturas de raciocínio dos modelos Gemini 3) são guardadas e devolvidas
exatamente como chegaram, que é o que a API exige em conversas com ferramentas.
"""
import json
import os
import time
import urllib.error
import urllib.request

import usage

BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}"
TIMEOUT = 120
_fallbacks = []                     # modelos reserva, na ordem de tentativa
_urlopen = urllib.request.urlopen   # os testes trocam por uma versão falsa
_sleep = time.sleep


class GeminiError(Exception):
    """kind: quota | model | auth | blocked | network | server | other"""

    def __init__(self, message, status=None, kind="other", retry_after=None, quota=None):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.retry_after = retry_after
        self.quota = quota          # em erro de cota: {"scope": day|minute, "kind": requests|tokens, "limit": int, "model": str}


def load_dotenv(path: str = ".env"):
    """Lê o arquivo .env (se existir) sem precisar de biblioteca extra."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError(
            "Chave do Gemini não encontrada. Crie uma em https://aistudio.google.com/apikey "
            "e coloque em GEMINI_API_KEY (arquivo .env).",
            kind="auth",
        )
    return key


def set_fallbacks(models):
    global _fallbacks
    _fallbacks = [m for m in (models or []) if m]


def models_for(primary: str):
    return [primary] + [m for m in _fallbacks if m != primary]


def _parse_retry_delay(error_obj: dict):
    for d in error_obj.get("details", []) or []:
        delay = d.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    return None


def _parse_quota(error_obj: dict):
    """Lê do erro 429 qual limite foi atingido (por dia/minuto, requisições/tokens) e o valor REAL dele."""
    for d in error_obj.get("details", []) or []:
        for v in d.get("violations", []) or []:
            qid = str(v.get("quotaId") or v.get("quotaMetric") or "").lower()
            if not qid:
                continue
            scope = "day" if "perday" in qid or "per_day" in qid else "minute" if "perminute" in qid or "per_minute" in qid else None
            kind = "tokens" if "token" in qid else "requests"
            try:
                limit = int(v.get("quotaValue"))
            except (TypeError, ValueError):
                limit = None
            return {"scope": scope, "kind": kind, "limit": limit, "id": v.get("quotaId"),
                    "model": (v.get("quotaDimensions") or {}).get("model")}
    return None


def error_from_response(status: int, body: str) -> GeminiError:
    try:
        err = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        err = {}
    message = err.get("message") or body[:300] or f"Erro HTTP {status}"
    code = err.get("status", "")
    low = message.lower()
    if status == 429 or code == "RESOURCE_EXHAUSTED":
        quota = _parse_quota(err)
        extra = ""
        if quota:
            what = ("requisições" if quota["kind"] == "requests" else "tokens") + (
                " por dia" if quota["scope"] == "day" else " por minuto" if quota["scope"] == "minute" else "")
            extra = f" (limite de {what}" + (f": {quota['limit']}" if quota["limit"] else "") + ")"
        return GeminiError("Limite de uso do Gemini atingido" + extra + ". " + message, status, "quota",
                           _parse_retry_delay(err), quota)
    if status == 404 or "is not found" in low or "not supported for generatecontent" in low:
        return GeminiError(f"Modelo indisponível: {message}", status, "model")
    if status in (401, 403) or "api key" in low:
        return GeminiError(f"Chave do Gemini recusada: {message}", status, "auth")
    if status >= 500:
        return GeminiError("O Gemini está sobrecarregado ou fora do ar agora (problema do lado do Google, costuma passar em poucos minutos). Tente de novo daqui a pouco.", status, "server")
    return GeminiError(message, status, "other")


def build_payload(contents, system=None, tools=None, json_mode=False, temperature=0.2):
    payload = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    return payload


def _open(model: str, method: str, payload: dict, stream: bool, attempts: int = 3):
    url = BASE.format(model=model, method=method) + ("?alt=sse" if stream else "")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key()},
        method="POST",
    )
    last = None
    for attempt in range(attempts):  # tenta de novo em erro de servidor/rede
        try:
            return _urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            last = error_from_response(e.code, e.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as e:
            last = GeminiError(f"Sem conexão com o Gemini: {e.reason}", kind="network")
        if last.kind not in ("server", "network"):
            break
        _sleep(2 * (attempt + 1))
    raise last


def _open_with_fallback(models, method, payload, stream):
    last = None
    ordered = usage.prefer_order(models)
    # os que o Google acabou de recusar por cota e ficaram para o fim da fila também contam como "pulados"
    pre_skipped = [(m, "quota") for m in usage.blocked_models(models)]
    skipped = []                 # (modelo, motivo) dos que não puderam atender antes do escolhido
    for i, model in enumerate(ordered):
        try:
            # com reservas disponíveis, não perde tempo insistindo num modelo sobrecarregado
            resp = _open(model, method, payload, stream, attempts=3 if i == len(ordered) - 1 else 1)
        except GeminiError as e:
            last = e
            if e.kind == "quota":
                usage.record_quota_error(e.retry_after, model=model, quota=e.quota)
            if e.kind in ("quota", "model", "server"):
                skipped.append((model, e.kind))
                continue  # cota é por modelo e a sobrecarga costuma ser de um modelo só: tenta o reserva
            raise
        usage.note_model(model, skipped + [p for p in pre_skipped if p[0] != model and p not in skipped])
        return model, resp
    raise last


def _usage_of(obj: dict):
    meta = obj.get("usageMetadata") or {}
    return int(meta.get("promptTokenCount", 0)), int(meta.get("candidatesTokenCount", 0)) + int(
        meta.get("thoughtsTokenCount", 0)
    )


def _check_blocked(obj: dict):
    block = (obj.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise GeminiError(f"O Gemini bloqueou o pedido ({block}).", kind="blocked")


def generate(contents, models, system=None, tools=None, json_mode=False, temperature=0.2) -> dict:
    """Chamada sem streaming. Retorna a resposta completa (dict) com a chave extra '_model'."""
    model, resp = _open_with_fallback(
        models, "generateContent", build_payload(contents, system, tools, json_mode, temperature), False
    )
    with resp:
        obj = json.loads(resp.read().decode("utf-8"))
    tin, tout = _usage_of(obj)
    usage.record(model, tin, tout)
    _check_blocked(obj)
    obj["_model"] = model
    return obj


def stream(contents, models, system=None, tools=None, temperature=0.2):
    """Gera os pedaços (dicts) da resposta em streaming. O primeiro item é {'_model': nome}."""
    model, resp = _open_with_fallback(
        models, "streamGenerateContent", build_payload(contents, system, tools, False, temperature), True
    )
    tin = tout = 0
    try:
        yield {"_model": model}
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if "error" in chunk:
                    raise error_from_response(int(chunk["error"].get("code", 500)), json.dumps(chunk))
                _check_blocked(chunk)
                if chunk.get("usageMetadata"):
                    tin, tout = _usage_of(chunk)
                yield chunk
    finally:
        usage.record(model, tin, tout)  # a requisição consumiu cota mesmo se foi interrompida


def parts_of(obj: dict):
    """Partes da primeira resposta (lista de dicts)."""
    try:
        return obj["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError, AttributeError):
        return []


def text_of(obj: dict) -> str:
    return "".join(p.get("text", "") for p in parts_of(obj) if not p.get("thought"))
