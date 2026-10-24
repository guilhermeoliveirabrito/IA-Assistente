"""Ponto único para falar com a IA: Gemini primeiro (ou na ordem de `ia.ordem_provedores`) e, quando ele não
puder atender (cota, sobrecarga, chave ausente ou recusada), os outros provedores com chave configurada.

Tem a mesma interface de `gemini.stream/generate`, então o agente e o resto do app só trocam o nome do módulo.
"""
from assistente.ia import gemini
from assistente.ia import providers
from assistente.nucleo import usage

GeminiError = gemini.GeminiError
_cfg = {}


def configure(cfg: dict):
    global _cfg
    _cfg = cfg or {}


def _chain():
    return providers.order(_cfg)


def stream(contents, models, system=None, tools=None, temperature=0.2, thinking=None, timeout=None):
    """Pedaços no formato Gemini. O primeiro é {'_model': nome}. Só troca de provedor ANTES de o primeiro pedaço sair."""
    first_error, skipped, need_img = None, [], providers.has_image(contents)
    for pid in _chain():
        if pid == "gemini":
            try:
                extra = {k: v for k, v in (("thinking", thinking), ("timeout", timeout)) if v is not None}
                gen = gemini.stream(contents, models, system=system, tools=tools, temperature=temperature, **extra)
                first = next(gen)
            except GeminiError as e:
                first_error = first_error or e
                if e.kind not in providers.FALLBACK_KINDS:
                    raise
                skipped.append((models[0] if models else "gemini", e.kind))
                continue
            except StopIteration:
                continue
            yield first
            yield from gen
            return
        d = providers.definition(_cfg, pid)
        if not d or not providers.configured(d):
            continue
        label = f"{pid}:{d['modelo']}"
        if need_img and not d.get("visao"):
            skipped.append((label, "sem visão"))
            continue
        try:
            gen = providers.stream_one(d, contents, system, tools, temperature, timeout)
            first = next(gen)
        except GeminiError as e:
            first_error = first_error or e
            if e.kind not in providers.FALLBACK_KINDS:
                raise
            skipped.append((label, e.kind))
            continue
        except StopIteration:
            continue
        usage.note_model(first["_model"], list(skipped))
        yield first
        yield from gen
        return
    if first_error:
        raise first_error
    raise GeminiError("Nenhum provedor de IA está configurado.", kind="auth")


def generate(contents, models, system=None, tools=None, json_mode=False, temperature=0.2, thinking=None) -> dict:
    """Chamada sem streaming, no formato de `gemini.generate`. Se cair num provedor reserva, pede JSON no texto."""
    return _generate_chain(contents, models, system, tools, json_mode, temperature, thinking)


def _generate_chain(contents, models, system, tools, json_mode, temperature, thinking):
    first_error, skipped = None, []
    need_img = providers.has_image(contents)
    for pid in _chain():
        if pid == "gemini":
            try:
                extra = {"thinking": thinking} if thinking is not None else {}
                return gemini.generate(contents, models, system=system, tools=tools, json_mode=json_mode,
                                       temperature=temperature, **extra)
            except GeminiError as e:
                first_error = first_error or e
                if e.kind not in providers.FALLBACK_KINDS:
                    raise
                skipped.append((models[0] if models else "gemini", e.kind))
                continue
        d = providers.definition(_cfg, pid)
        if not d or not providers.configured(d):
            continue
        label = f"{pid}:{d['modelo']}"
        if need_img and not d.get("visao"):
            continue
        msgs = contents
        if json_mode:
            msgs = [dict(c) for c in contents]
            for c in reversed(msgs):
                if c.get("role") == "user":
                    c["parts"] = list(c.get("parts") or []) + [{"text": "Responda SOMENTE com JSON válido, sem texto extra."}]
                    break
        try:
            obj = providers.collect(providers.stream_one(d, msgs, system, tools, temperature, None))
        except GeminiError as e:
            first_error = first_error or e
            if e.kind not in providers.FALLBACK_KINDS:
                raise
            skipped.append((label, e.kind))
            continue
        usage.note_model(obj["_model"], list(skipped))
        return obj
    if first_error:
        raise first_error
    raise GeminiError("Nenhum provedor de IA está configurado.", kind="auth")
