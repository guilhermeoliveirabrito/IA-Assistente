"""Outros provedores de IA, como reserva do Gemini.

O app conversa internamente no formato do Gemini (partes, functionCall, functionResponse). Aqui cada provedor
recebe esse mesmo histórico, convertido para o formato dele, e devolve pedaços NO FORMATO DO GEMINI. Assim o
restante do app (agente, ferramentas, tarefas) não precisa saber quem respondeu.

Tipos: "openai" (qualquer API compatível com /chat/completions: Groq, OpenRouter, Cerebras, Mistral, GitHub Models,
NVIDIA, DeepSeek, OpenAI, Ollama local…) e "anthropic" (API nativa do Claude).

A ordem de tentativa vem de `ia.ordem_provedores` (inclua "gemini" onde quiser). Um provedor sem chave é pulado em
silêncio. Os nomes de modelo abaixo são padrões e podem ser trocados em Ajustes: os provedores mudam seus catálogos.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import gemini
import usage

GeminiError = gemini.GeminiError
TIMEOUT = 90
_urlopen = urllib.request.urlopen      # os testes trocam por uma versão falsa
ENV_FILE = Path(".env")

# id -> definição. "gratis": tem plano gratuito (os limites mudam, confira no site). "visao": enxerga imagens.
PRESETS = {
    "groq": {"nome": "Groq", "tipo": "openai", "url": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY",
             "modelo": "llama-3.3-70b-versatile", "visao": False, "gratis": True,
             "link": "https://console.groq.com/keys", "nota": "Muito rápido; plano grátis sem cartão."},
    "cerebras": {"nome": "Cerebras", "tipo": "openai", "url": "https://api.cerebras.ai/v1", "env": "CEREBRAS_API_KEY",
                 "modelo": "llama-3.3-70b", "visao": False, "gratis": True,
                 "link": "https://cloud.cerebras.ai", "nota": "Muito rápido; plano grátis sem cartão."},
    "openrouter": {"nome": "OpenRouter", "tipo": "openai", "url": "https://openrouter.ai/api/v1",
                   "env": "OPENROUTER_API_KEY", "modelo": "meta-llama/llama-3.3-70b-instruct:free", "visao": False,
                   "gratis": True, "link": "https://openrouter.ai/keys",
                   "nota": "Uma chave, vários modelos; os que terminam em :free não custam nada."},
    "mistral": {"nome": "Mistral", "tipo": "openai", "url": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY",
                "modelo": "mistral-small-latest", "visao": True, "gratis": True,
                "link": "https://console.mistral.ai/api-keys", "nota": "Plano grátis (Experiment); enxerga imagens."},
    "github": {"nome": "GitHub Models", "tipo": "openai", "url": "https://models.github.ai/inference",
               "env": "GITHUB_MODELS_TOKEN", "modelo": "openai/gpt-4o-mini", "visao": True, "gratis": True,
               "link": "https://github.com/settings/personal-access-tokens",
               "nota": "Usa um token do GitHub com a permissão 'models'; grátis com limites."},
    "nvidia": {"nome": "NVIDIA NIM", "tipo": "openai", "url": "https://integrate.api.nvidia.com/v1",
               "env": "NVIDIA_API_KEY", "modelo": "meta/llama-3.3-70b-instruct", "visao": False, "gratis": True,
               "link": "https://build.nvidia.com", "nota": "Créditos/limites grátis para desenvolvedores."},
    "deepseek": {"nome": "DeepSeek", "tipo": "openai", "url": "https://api.deepseek.com/v1", "env": "DEEPSEEK_API_KEY",
                 "modelo": "deepseek-chat", "visao": False, "gratis": False,
                 "link": "https://platform.deepseek.com/api_keys", "nota": "Pago, mas muito barato."},
    "openai": {"nome": "OpenAI (ChatGPT)", "tipo": "openai", "url": "https://api.openai.com/v1",
               "env": "OPENAI_API_KEY", "modelo": "gpt-4o-mini", "visao": True, "gratis": False,
               "link": "https://platform.openai.com/api-keys", "nota": "Pago por uso."},
    "anthropic": {"nome": "Anthropic (Claude)", "tipo": "anthropic", "url": "https://api.anthropic.com/v1",
                  "env": "ANTHROPIC_API_KEY", "modelo": "claude-haiku-4-5", "visao": True, "gratis": False,
                  "link": "https://console.anthropic.com/settings/keys", "nota": "Pago por uso."},
    "ollama": {"nome": "Ollama (local)", "tipo": "openai", "url": "http://localhost:11434/v1", "env": "",
               "modelo": "llama3.2", "visao": False, "gratis": True, "local": True,
               "link": "https://ollama.com/download",
               "nota": "Roda no seu PC, sem limite e sem internet. Instale o Ollama e baixe um modelo (ollama pull llama3.2)."},
}
DEFAULT_ORDER = ["gemini", "groq", "cerebras", "openrouter", "mistral", "github", "nvidia", "deepseek"]
# Erros do provedor anterior depois dos quais vale tentar o próximo.
FALLBACK_KINDS = ("quota", "model", "server", "network", "auth")


# ---------------------------------------------------------------- configuração

def _ia(cfg):
    return (cfg or {}).get("ia") or {}


def _pconf(cfg, pid):
    return (((cfg or {}).get("provedores") or {}).get(pid)) or {}


def definition(cfg, pid):
    """Preset do provedor com as trocas feitas em Ajustes/config (modelo, url, visão)."""
    base = PRESETS.get(pid)
    if not base:
        return None
    d = dict(base)
    over = _pconf(cfg, pid)
    for key in ("modelo", "url", "visao"):
        if over.get(key) not in (None, ""):
            d[key] = over[key]
    d["id"] = pid
    return d


def key_for(d) -> str:
    if not d.get("env"):
        return ""
    gemini.load_dotenv()
    return (os.environ.get(d["env"]) or "").strip()


def configured(d) -> bool:
    return bool(d.get("local")) or bool(key_for(d))


def order(cfg) -> list:
    raw = _ia(cfg).get("ordem_provedores")
    ids = [x for x in (raw if isinstance(raw, list) else DEFAULT_ORDER) if x == "gemini" or x in PRESETS]
    seen, out = set(), []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out or ["gemini"]


def extras(cfg) -> list:
    """Provedores (além do Gemini) que vão ser tentados: na ordem, os que têm chave."""
    out = []
    for pid in order(cfg):
        d = definition(cfg, pid) if pid != "gemini" else None
        if d and configured(d):
            out.append(d)
    return out


def gemini_first(cfg) -> bool:
    return order(cfg)[0] == "gemini" if "gemini" in order(cfg) else True


def status(cfg) -> list:
    """Para a tela de Ajustes: cada provedor com se tem chave, o modelo e a posição na fila."""
    ordered = order(cfg)
    out = []
    for pid in ["gemini"] + list(PRESETS):
        if pid == "gemini":
            ok = bool(os.environ.get("GEMINI_API_KEY"))
            if not ok:
                try:
                    gemini.api_key()
                    ok = True
                except GeminiError:
                    ok = False
            out.append({"id": "gemini", "nome": "Google Gemini", "configurada": ok, "modelo": _ia(cfg).get("modelo", ""),
                        "gratis": True, "visao": True, "posicao": ordered.index("gemini") + 1 if "gemini" in ordered else 0,
                        "link": "https://aistudio.google.com/apikey", "nota": "Principal. Chave em GEMINI_API_KEY.",
                        "env": "GEMINI_API_KEY", "local": False})
            continue
        d = definition(cfg, pid)
        out.append({"id": pid, "nome": d["nome"], "configurada": configured(d), "modelo": d["modelo"],
                    "gratis": d["gratis"], "visao": bool(d["visao"]), "link": d["link"], "nota": d["nota"],
                    "posicao": ordered.index(pid) + 1 if pid in ordered else 0, "env": d["env"],
                    "local": bool(d.get("local"))})
    return out


def save_key(pid: str, key: str):
    """Guarda a chave no .env (nunca é devolvida à interface) e já vale nesta execução."""
    d = PRESETS.get(pid) if pid != "gemini" else {"env": "GEMINI_API_KEY"}
    if not d or not d.get("env"):
        raise ValueError("Este provedor não usa chave.")
    key = str(key or "").strip()
    if key and (not re.match(r"^[\w.\-:+/=]{8,400}$", key)):
        raise ValueError("A chave tem caracteres inválidos ou é curta demais.")
    name = d["env"]
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [ln for ln in lines if not re.match(rf"^\s*{re.escape(name)}\s*=", ln)]
    if key:
        lines.append(f"{name}={key}")
        os.environ[name] = key
    else:
        os.environ.pop(name, None)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- erros

def _error(status_code: int, body: str, who: str) -> GeminiError:
    try:
        obj = json.loads(body)
        err = obj.get("error", obj)
        message = err.get("message") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        message = None
    message = (message or body[:300] or f"Erro HTTP {status_code}").strip()
    if status_code == 429:
        return GeminiError(f"Limite de uso de {who} atingido. {message}", status_code, "quota")
    if status_code in (401, 403):
        return GeminiError(f"{who} recusou a chave: {message}", status_code, "auth")
    if status_code in (404, 400) and re.search(r"model|not found|does not exist|unknown", message, re.I):
        return GeminiError(f"Modelo indisponível em {who}: {message}", status_code, "model")
    if status_code >= 500:
        return GeminiError(f"{who} está fora do ar ou sobrecarregado agora.", status_code, "server")
    return GeminiError(f"{who}: {message}", status_code, "other")


def _post(url, headers, payload, who, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        return _urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise _error(e.code, e.read().decode("utf-8", errors="replace"), who) from None
    except urllib.error.URLError as e:
        raise GeminiError(f"Sem conexão com {who}: {e.reason}", kind="network") from None
    except OSError as e:
        raise GeminiError(f"Sem conexão com {who}: {e}", kind="network") from None


# ---------------------------------------------------------------- conversão Gemini -> provedores

def _lower_schema(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            out[k] = v.lower() if k == "type" and isinstance(v, str) else _lower_schema(v)
        return out
    if isinstance(node, list):
        return [_lower_schema(x) for x in node]
    return node


def _schema(decl):
    params = _lower_schema(decl.get("parameters") or {"type": "object", "properties": {}})
    params.setdefault("type", "object")
    params.setdefault("properties", {})
    return params


def has_image(contents) -> bool:
    """A última mensagem do usuário traz imagem (o provedor precisa enxergar para ajudar)?"""
    for c in reversed(contents or []):
        if c.get("role") == "user":
            return any("inlineData" in p and str(p["inlineData"].get("mimeType", "")).startswith("image/")
                       for p in c.get("parts") or [])
    return False


def _tool_result_text(response) -> str:
    try:
        return json.dumps(response, ensure_ascii=False)[:20000]
    except (TypeError, ValueError):
        return str(response)[:20000]


def to_openai(contents, system=None, vision=True) -> list:
    msgs = [{"role": "system", "content": system}] if system else []
    pending, n = [], 0
    for c in contents or []:
        parts = c.get("parts") or []
        if c.get("role") == "model":
            text = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))
            calls = []
            for p in parts:
                fc = p.get("functionCall")
                if fc:
                    n += 1
                    calls.append({"id": fc.get("id") or f"call_{n}", "type": "function",
                                  "function": {"name": fc.get("name", ""),
                                               "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False)}})
            pending = [(x["id"], x["function"]["name"]) for x in calls]
            if not text and not calls:
                continue
            m = {"role": "assistant", "content": text or None}
            if calls:
                m["tool_calls"] = calls
            msgs.append(m)
            continue
        content, loose = [], []
        for p in parts:
            fr = p.get("functionResponse")
            if fr:
                cid = None
                for i, (pid, pname) in enumerate(pending):
                    if (fr.get("id") and fr["id"] == pid) or pname == fr.get("name"):
                        cid = pid
                        pending.pop(i)
                        break
                if cid:
                    msgs.append({"role": "tool", "tool_call_id": cid, "content": _tool_result_text(fr.get("response"))})
                else:
                    loose.append({"type": "text", "text": f"[resultado de {fr.get('name')}] {_tool_result_text(fr.get('response'))}"})
            elif p.get("text"):
                content.append({"type": "text", "text": p["text"]})
            elif "inlineData" in p:
                mime = str(p["inlineData"].get("mimeType", ""))
                if vision and mime.startswith("image/"):
                    content.append({"type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{p['inlineData'].get('data', '')}"}})
                else:
                    content.append({"type": "text", "text": f"[anexo {mime or 'desconhecido'} omitido: este modelo não o lê]"})
        content = loose + content
        if content:
            msgs.append({"role": "user", "content": content if len(content) > 1 or content[0]["type"] != "text"
                         else content[0]["text"]})
    return _sanitize_openai(msgs)


def _sanitize_openai(msgs):
    """Chamadas de ferramenta sem resposta (tarefa interrompida) fariam a API recusar o histórico: tira-as."""
    out = []
    for i, m in enumerate(msgs):
        if m["role"] == "assistant" and m.get("tool_calls"):
            answered = set()
            for nxt in msgs[i + 1:]:
                if nxt["role"] != "tool":
                    break
                answered.add(nxt["tool_call_id"])
            calls = [c for c in m["tool_calls"] if c["id"] in answered]
            m = {**m}
            if calls:
                m["tool_calls"] = calls
            else:
                m.pop("tool_calls")
                if not m.get("content"):
                    continue
        elif m["role"] == "tool":
            if not out or not (out[-1]["role"] == "tool" or (out[-1]["role"] == "assistant" and out[-1].get("tool_calls"))):
                continue
        out.append(m)
    return out


def to_anthropic(contents, vision=True) -> list:
    msgs, pending, n = [], [], 0

    def push(role, blocks):
        if not blocks:
            return
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"].extend(blocks)
        else:
            msgs.append({"role": role, "content": list(blocks)})

    for c in contents or []:
        parts = c.get("parts") or []
        if c.get("role") == "model":
            blocks = []
            pending = []
            for p in parts:
                if p.get("text") and not p.get("thought"):
                    blocks.append({"type": "text", "text": p["text"]})
                elif p.get("functionCall"):
                    fc = p["functionCall"]
                    n += 1
                    cid = fc.get("id") or f"toolu_{n}"
                    pending.append((cid, fc.get("name", "")))
                    blocks.append({"type": "tool_use", "id": cid, "name": fc.get("name", ""), "input": fc.get("args") or {}})
            push("assistant", blocks)
            continue
        results, rest = [], []
        for p in parts:
            fr = p.get("functionResponse")
            if fr:
                cid = None
                for i, (pid, pname) in enumerate(pending):
                    if (fr.get("id") and fr["id"] == pid) or pname == fr.get("name"):
                        cid = pid
                        pending.pop(i)
                        break
                if cid:
                    results.append({"type": "tool_result", "tool_use_id": cid, "content": _tool_result_text(fr.get("response"))})
                else:
                    rest.append({"type": "text", "text": f"[resultado de {fr.get('name')}] {_tool_result_text(fr.get('response'))}"})
            elif p.get("text"):
                rest.append({"type": "text", "text": p["text"]})
            elif "inlineData" in p:
                mime = str(p["inlineData"].get("mimeType", ""))
                if vision and mime in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    rest.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                             "data": p["inlineData"].get("data", "")}})
                else:
                    rest.append({"type": "text", "text": f"[anexo {mime or 'desconhecido'} omitido: este modelo não o lê]"})
        push("user", results + rest)
    # tool_use sem tool_result logo depois: a API recusa; tira o bloco
    answered = {b["tool_use_id"] for m in msgs if m["role"] == "user" for b in m["content"] if b["type"] == "tool_result"}
    clean = []
    for m in msgs:
        if m["role"] == "assistant":
            m = {**m, "content": [b for b in m["content"] if b["type"] != "tool_use" or b["id"] in answered]}
            if not m["content"]:
                continue
        clean.append(m)
    if clean and clean[0]["role"] != "user":
        clean.insert(0, {"role": "user", "content": [{"type": "text", "text": "(início da conversa)"}]})
    return clean


# ---------------------------------------------------------------- respostas -> formato Gemini

def _chunk(parts):
    return {"candidates": [{"content": {"role": "model", "parts": parts}}]}


def _args(raw: str) -> dict:
    try:
        v = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _sse(resp):
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    yield json.loads(data)
                except ValueError:
                    continue


def stream_openai(d, contents, system=None, tools=None, temperature=0.2, timeout=None):
    who, model = d["nome"], d["modelo"]
    payload = {"model": model, "messages": to_openai(contents, system, bool(d.get("visao"))), "stream": True,
               "temperature": temperature, "stream_options": {"include_usage": True}}
    if tools:
        payload["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                              "parameters": _schema(t)}} for t in tools]
    headers = {}
    if key_for(d):
        headers["Authorization"] = "Bearer " + key_for(d)
    if d["id"] == "openrouter":
        headers["X-Title"] = "Assistente"
    resp = _post(d["url"].rstrip("/") + "/chat/completions", headers, payload, who,
                 timeout or (300 if d.get("local") else TIMEOUT))
    calls, tin, tout = {}, 0, 0
    key = f"{d['id']}:{model}"
    try:
        yield {"_model": key}
        with resp:
            for ev in _sse(resp):
                if "error" in ev:
                    err = ev["error"]
                    raise _error(int(err.get("code", 500)) if str(err.get("code", "")).isdigit() else 500,
                                 json.dumps(ev), who)
                u = ev.get("usage")
                if u:
                    tin, tout = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
                for ch in ev.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        yield _chunk([{"text": delta["content"]}])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "args": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
        done = []
        for i in sorted(calls):
            c = calls[i]
            if c["name"]:
                fc = {"name": c["name"], "args": _args(c["args"])}
                if c["id"]:
                    fc["id"] = c["id"]
                done.append({"functionCall": fc})
        if done:
            yield _chunk(done)
    finally:
        usage.record(key, tin, tout)


def stream_anthropic(d, contents, system=None, tools=None, temperature=0.2, timeout=None):
    who, model = d["nome"], d["modelo"]
    payload = {"model": model, "max_tokens": 4096, "stream": True, "temperature": min(1.0, temperature),
               "messages": to_anthropic(contents, bool(d.get("visao")))}
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": _schema(t)}
                            for t in tools]
    headers = {"x-api-key": key_for(d), "anthropic-version": "2023-06-01"}
    resp = _post(d["url"].rstrip("/") + "/messages", headers, payload, who, timeout or TIMEOUT)
    blocks, tin, tout = {}, 0, 0
    key = f"{d['id']}:{model}"
    try:
        yield {"_model": key}
        with resp:
            for ev in _sse(resp):
                kind = ev.get("type")
                if kind == "error":
                    err = ev.get("error") or {}
                    t = err.get("type", "")
                    code = 429 if "rate" in t else 529 if "overload" in t else 401 if "auth" in t else 500
                    raise _error(code, json.dumps({"error": {"message": err.get("message", t)}}), who)
                if kind == "message_start":
                    tin = int(((ev.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
                elif kind == "message_delta":
                    tout = int((ev.get("usage") or {}).get("output_tokens") or tout)
                elif kind == "content_block_start":
                    cb = ev.get("content_block") or {}
                    if cb.get("type") == "tool_use":
                        blocks[ev.get("index", 0)] = {"id": cb.get("id"), "name": cb.get("name", ""), "args": ""}
                elif kind == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield _chunk([{"text": delta["text"]}])
                    elif delta.get("type") == "input_json_delta":
                        slot = blocks.get(ev.get("index", 0))
                        if slot is not None:
                            slot["args"] += delta.get("partial_json") or ""
        done = [{"functionCall": {"name": b["name"], "args": _args(b["args"]), **({"id": b["id"]} if b["id"] else {})}}
                for _, b in sorted(blocks.items()) if b["name"]]
        if done:
            yield _chunk(done)
    finally:
        usage.record(key, tin, tout)


def stream_one(d, contents, system=None, tools=None, temperature=0.2, timeout=None):
    fn = stream_anthropic if d["tipo"] == "anthropic" else stream_openai
    return fn(d, contents, system, tools, temperature, timeout)


def collect(gen) -> dict:
    """Junta um stream no formato de `gemini.generate`: {'candidates': [...], '_model': ...}."""
    parts, model = [], ""
    for ch in gen:
        if "_model" in ch:
            model = ch["_model"]
            continue
        for p in gemini.parts_of(ch):
            if p.get("text") and parts and parts[-1].get("text") is not None and "functionCall" not in parts[-1]:
                parts[-1]["text"] += p["text"]
            else:
                parts.append(dict(p))
    return {"candidates": [{"content": {"role": "model", "parts": parts}}], "_model": model}


def ping(cfg, pid: str) -> dict:
    """Pergunta algo mínimo ao provedor para provar que chave, modelo e rede funcionam."""
    t0 = time.time()
    msg = [{"role": "user", "parts": [{"text": "Responda apenas: ok"}]}]
    if pid == "gemini":
        obj = gemini.generate(msg, gemini.models_for(_ia(cfg).get("modelo", "gemini-3.8-flash")))
    else:
        d = definition(cfg, pid)
        if not d:
            raise ValueError("Provedor desconhecido.")
        if not configured(d):
            raise GeminiError("Falta a chave deste provedor.", kind="auth")
        obj = collect(stream_one(d, msg, None, None, 0.0, 30))
    return {"ok": True, "modelo": obj.get("_model", ""), "segundos": round(time.time() - t0, 1),
            "resposta": gemini.text_of(obj).strip()[:80]}
