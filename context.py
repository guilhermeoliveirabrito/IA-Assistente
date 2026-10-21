"""Memória de curto prazo: mantém a conversa leve resumindo o começo quando ela cresce.

Conversas longas ficam lentas e gastam a cota gratuita (cada chamada reenvia o histórico).
Este módulo troca os turnos mais antigos por um resumo, mantendo os mais recentes intactos.
O corte nunca separa uma chamada de ferramenta da sua resposta nem descarta as assinaturas de
raciocínio dos turnos recentes, porque a API exige esses pares íntegros.
"""
import json

import ai

IMAGE_TOKENS = 1500           # custo estimado de uma imagem ou arquivo anexado
DEFAULT_LIMIT_TOKENS = 24000  # acima disso o histórico é resumido
KEEP_TURNS = 8                # turnos recentes preservados
MAX_TRANSCRIPT_CHARS = 60000  # limite do texto enviado para resumir
SUMMARY_MARK = "[Resumo da conversa até aqui]"


def estimate_tokens(contents: list) -> int:
    total = 0
    for c in contents:
        for p in c.get("parts", []):
            if "inlineData" in p or "x_file" in p:
                total += IMAGE_TOKENS
            else:
                total += len(json.dumps({k: v for k, v in p.items() if k != "thoughtSignature"},
                                        ensure_ascii=False)) // 3
    return total


def needs_compaction(contents: list, limit: int = DEFAULT_LIMIT_TOKENS) -> bool:
    return len(contents) > KEEP_TURNS + 2 and estimate_tokens(contents) > limit


def _is_plain_user_turn(content: dict) -> bool:
    if content.get("role") != "user":
        return False
    parts = content.get("parts", [])
    return bool(parts) and not any("functionResponse" in p for p in parts)


def split_point(contents: list, keep: int = KEEP_TURNS):
    """Índice onde começa a parte recente. Só corta antes de um turno de usuário "de verdade".

    Retorna None se não houver um corte seguro.
    """
    for i in range(max(len(contents) - keep, 1), 0, -1):
        if _is_plain_user_turn(contents[i]):
            return i
    return None


def render_transcript(contents: list, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    lines = []
    for c in contents:
        who = "Usuário" if c.get("role") == "user" else "Assistente"
        for p in c.get("parts", []):
            if p.get("thought"):
                continue
            if "text" in p and p["text"].strip():
                lines.append(f"{who}: {p['text'].strip()}")
            elif "functionCall" in p:
                fc = p["functionCall"]
                lines.append(f"Assistente usou {fc.get('name')}({json.dumps(fc.get('args', {}), ensure_ascii=False)[:200]})")
            elif "functionResponse" in p:
                resp = json.dumps(p["functionResponse"].get("response", {}), ensure_ascii=False)
                lines.append(f"  resultado: {resp[:300]}")
            elif "inlineData" in p or "x_file" in p:
                lines.append(f"{who}: [anexo: {p.get('x_name') or p.get('inlineData', {}).get('mimeType', 'arquivo')}]")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit // 3] + "\n[...]\n" + text[-(2 * limit) // 3:]


def summarize(contents: list, model: str, previous_summary: str = "") -> str:
    prompt = (
        "Resuma a conversa abaixo para que o assistente continue depois sem reler tudo. "
        "Em português, em tópicos curtos, mantendo: o que o usuário pediu, decisões tomadas, "
        "fatos e preferências citados, o que já foi feito (arquivos, comandos, resultados), "
        "e o que ainda está pendente. Não invente nada.\n\n"
        + (f"RESUMO ANTERIOR:\n{previous_summary}\n\n" if previous_summary else "")
        + f"CONVERSA:\n{render_transcript(contents)}"
    )
    return ai.ask_text(prompt, model).strip()


def summary_turns(summary: str):
    return [
        {"role": "user", "parts": [{"text": f"{SUMMARY_MARK}\n{summary}"}]},
        {"role": "model", "parts": [{"text": "Entendido. Sigo a partir desse resumo."}]},
    ]


def compact(contents: list, model: str, keep: int = KEEP_TURNS):
    """Retorna (novo_conteudo, resumo) ou (contents, None) se não deu para compactar.

    Mantém o primeiro turno do usuário (o pedido original) e resume o meio.
    """
    cut = split_point(contents, keep)
    if cut is None or cut < 2:
        return contents, None
    head = contents[:cut]
    previous = ""
    if head and head[0].get("parts") and head[0]["parts"][0].get("text", "").startswith(SUMMARY_MARK):
        previous = head[0]["parts"][0]["text"][len(SUMMARY_MARK):].strip()
        head = head[2:]
    if not head:
        return contents, None
    summary = summarize(head, model, previous)
    if not summary:
        return contents, None
    return summary_turns(summary) + contents[cut:], summary


def seed_for_new_conversation(contents: list, model: str):
    """Texto de abertura para uma conversa nova que continua a atual ("refresh")."""
    summary = summarize(contents, model)
    return summary_turns(summary), summary


def drop_old_images(contents: list, keep: int = 1) -> int:
    """Troca capturas de tela antigas (inlineData) por um aviso, mantendo só as `keep` mais recentes.

    Cada captura tem centenas de KB; sem isso o histórico de uma tarefa longa incharia sem limite.
    Retorna quantas foram removidas.
    """
    seen = removed = 0
    for content in reversed(contents):
        parts = content.get("parts", [])
        for i in range(len(parts) - 1, -1, -1):
            inline = parts[i].get("inlineData")
            if inline and str(inline.get("mimeType", "")).startswith("image/"):
                seen += 1
                if seen > keep:
                    parts[i] = {"text": "[captura de tela antiga removida para economizar espaço]"}
                    removed += 1
    return removed


def repair_contents(contents: list) -> bool:
    """Conserta um histórico interrompido no meio de uma ação (ex.: o app foi fechado).

    Se o último turno do modelo chamou ferramentas sem receber resposta, devolve uma resposta de erro
    para cada chamada, porque a API recusa histórico com chamadas sem resposta.
    """
    if not contents or contents[-1].get("role") != "model":
        return False
    calls = [p["functionCall"] for p in contents[-1].get("parts", []) if "functionCall" in p]
    if not calls:
        return False
    contents.append({"role": "user", "parts": [
        {"functionResponse": {"name": c.get("name", ""),
                              "response": {"erro": "A ação foi interrompida (o app foi fechado) e não terminou. "
                                                   "Verifique o estado antes de repeti-la."}}}
        for c in calls]})
    return True
