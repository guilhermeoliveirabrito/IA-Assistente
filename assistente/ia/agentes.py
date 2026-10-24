"""Agentes especializados: o mesmo assistente com um jeito de trabalhar e um conjunto de ferramentas para cada função.

O "Geral" faz de tudo e é o padrão. Os especialistas recebem instruções próprias (e perdem as ferramentas que não
combinam com a função, como controle de teclado e mouse num redator). Você também pode criar os seus em Ajustes ou no
seletor do chat. A "Mesa de debate" é diferente: ela roda um debate entre um defensor, um opositor e um juiz e
devolve só o parecer do juiz (veja debate.py).
"""
import json
import re
import threading
import uuid
from pathlib import Path

FILE = Path("data") / "agentes.json"
DEFAULT = "geral"
DEBATE = "debate"
MAX_CUSTOM = 20
_lock = threading.Lock()

# categorias de ferramentas que o agente NÃO recebe (veja permissions.CATEGORIES)
_SEM_PC = ["tela", "entrada"]
_SEM_PC_E_CODIGO = _SEM_PC + ["comandos", "git_push", "projeto_escrever"]

BUILTIN = [
    {"id": "geral", "nome": "Geral", "icone": "✨", "resumo": "Faz de tudo: conversa, pesquisa, arquivos, e-mail, agenda, PC.",
     "instrucao": "", "fora": []},
    {"id": "programador", "nome": "Programador", "icone": "💻",
     "resumo": "Escreve, revisa e depura código; trabalha nos projetos e no git.",
     "instrucao": "Você é um engenheiro de software sênior. Entenda o problema antes de mexer; leia os arquivos relevantes; "
                  "faça mudanças pequenas e verificáveis; rode os testes quando existirem e relate o resultado real. Explique "
                  "a causa de um bug, não só o conserto. Prefira código simples e legível, sem dependências desnecessárias. "
                  "Aponte riscos (segurança, desempenho, casos de borda) e diga honestamente o que não conseguiu testar.",
     "fora": _SEM_PC},
    {"id": "pesquisador", "nome": "Pesquisador", "icone": "🔎",
     "resumo": "Pesquisa na internet, confere fontes e entrega um resumo com referências.",
     "instrucao": "Você é um pesquisador rigoroso. Para qualquer fato que possa ter mudado ou seja incerto, pesquise na internet "
                  "(pesquisar_web) e leia as fontes importantes (ler_pagina). Confira pelo menos duas fontes quando o assunto "
                  "for relevante; diferencie fato, estimativa e opinião; informe datas; aponte contradições entre fontes e o "
                  "que continua incerto. Termine com a lista de fontes. Nunca invente citações.",
     "fora": _SEM_PC_E_CODIGO},
    {"id": "redator", "nome": "Redator", "icone": "✍️",
     "resumo": "Escreve, revisa, resume e traduz textos no tom que você quiser.",
     "instrucao": "Você é um redator e revisor profissional. Descubra o público, o objetivo e o tom (pergunte só se faltar algo "
                  "essencial). Entregue o texto pronto para usar, claro e sem enrolação; ao revisar, preserve a voz do autor "
                  "e explique em poucas linhas o que mudou. Para traduzir, mantenha o sentido e o registro. Quando o usuário "
                  "quiser o resultado num arquivo, use arquivo_gravar.",
     "fora": _SEM_PC_E_CODIGO},
    {"id": "organizador", "nome": "Organizador", "icone": "🗓️",
     "resumo": "Cuida de agenda, e-mails, lembretes e encomendas; planeja o seu dia.",
     "instrucao": "Você é um assistente executivo. Cuide da agenda, dos e-mails, dos lembretes e das encomendas do usuário: "
                  "proponha horários sem conflito, resuma o que importa, priorize o que é urgente e transforme pedidos em "
                  "lembretes ou eventos. Antes de criar, alterar ou apagar algo, confirme os detalhes (data, hora, "
                  "destinatário) quando houver dúvida. Nunca envie e-mail por conta própria: prepare rascunhos.",
     "fora": _SEM_PC_E_CODIGO},
    {"id": "analista", "nome": "Analista", "icone": "📊",
     "resumo": "Faz contas, analisa números, planilhas e finanças, mostrando o raciocínio.",
     "instrucao": "Você é um analista de dados e finanças pessoais. Mostre os cálculos passo a passo, confira as contas "
                  "(rode código quando ajudar) e deixe as premissas explícitas. Apresente comparações em tabelas, "
                  "destaque o que importa para a decisão e diga o grau de incerteza. Você não é consultor financeiro "
                  "licenciado: dê os fatos e cenários, e a decisão é do usuário.",
     "fora": _SEM_PC},
    {"id": "professor", "nome": "Professor", "icone": "🎓",
     "resumo": "Explica qualquer assunto no seu nível, com exemplos e exercícios.",
     "instrucao": "Você é um professor paciente. Descubra o nível do aluno e explique do simples para o complexo, com "
                  "analogias e exemplos do dia a dia. Quebre o assunto em passos, cheque se ficou claro e proponha 2 ou 3 "
                  "exercícios curtos no fim (com o gabarito separado). Corrija erros com gentileza e diga o porquê.",
     "fora": _SEM_PC_E_CODIGO},
    {"id": "operador", "nome": "Operador do PC", "icone": "🖱️",
     "resumo": "Usa o computador por você: abre programas, preenche telas e automatiza tarefas.",
     "instrucao": "Você é um operador de computador metódico. Prefira o caminho mais confiável (atalhos, janelas e elementos "
                  "numerados) a adivinhar coordenadas, confira na tela se cada ação funcionou e conte no final o que fez. "
                  "Em qualquer dúvida sobre uma ação irreversível (apagar, enviar, pagar), pare e pergunte.",
     "fora": []},
    {"id": "debate", "nome": "Mesa de debate", "icone": "⚖️",
     "resumo": "Um agente defende, outro contesta e um juiz decide. Você recebe só o parecer do juiz.",
     "instrucao": "", "fora": [], "especial": "debate"},
]
_BY_ID = {a["id"]: a for a in BUILTIN}


class AgentError(ValueError):
    pass


def _load_custom() -> list:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return [a for a in data.get("agentes", []) if isinstance(a, dict) and a.get("id") and a.get("nome")]
    except (OSError, ValueError, AttributeError):
        return []


def _save_custom(items: list):
    FILE.parent.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"agentes": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def _full(a: dict, custom=False) -> dict:
    return {"id": a["id"], "nome": a["nome"], "icone": a.get("icone") or "🤖", "resumo": a.get("resumo") or "",
            "instrucao": a.get("instrucao") or "", "fora": list(a.get("fora") or []), "especial": a.get("especial"),
            "personalizado": custom}


def all_agents() -> list:
    return [_full(a) for a in BUILTIN] + [_full(a, True) for a in _load_custom()]


def get(agent_id) -> dict:
    """O agente pedido; se o código não existe (ex.: apagado), o Geral."""
    agent_id = str(agent_id or DEFAULT)
    if agent_id in _BY_ID:
        return _full(_BY_ID[agent_id])
    for a in _load_custom():
        if a["id"] == agent_id:
            return _full(a, True)
    return _full(_BY_ID[DEFAULT])


def exists(agent_id) -> bool:
    return str(agent_id) in _BY_ID or any(a["id"] == str(agent_id) for a in _load_custom())


def create(nome, instrucao, icone="🤖") -> dict:
    nome = " ".join(str(nome or "").split())
    instrucao = str(instrucao or "").strip()
    if not 2 <= len(nome) <= 40:
        raise AgentError("Dê um nome ao agente (2 a 40 caracteres).")
    if not 10 <= len(instrucao) <= 3000:
        raise AgentError("Descreva como ele deve trabalhar (10 a 3000 caracteres).")
    icone = str(icone or "🤖").strip()[:4] or "🤖"
    with _lock:
        items = _load_custom()
        if len(items) >= MAX_CUSTOM:
            raise AgentError(f"Limite de {MAX_CUSTOM} agentes personalizados.")
        if any(a["nome"].lower() == nome.lower() for a in items + BUILTIN):
            raise AgentError("Já existe um agente com esse nome.")
        item = {"id": "p" + uuid.uuid4().hex[:8], "nome": nome, "icone": icone, "resumo": instrucao[:90],
                "instrucao": instrucao, "fora": list(_SEM_PC)}
        items.append(item)
        _save_custom(items)
    return _full(item, True)


def delete(agent_id):
    if not re.fullmatch(r"p[0-9a-f]{8}", str(agent_id or "")):
        raise AgentError("Só os agentes criados por você podem ser apagados.")
    with _lock:
        items = _load_custom()
        keep = [a for a in items if a["id"] != agent_id]
        if len(keep) == len(items):
            raise AgentError("Não achei esse agente.")
        _save_custom(keep)


def prompt_block(agent_id) -> str:
    """Trecho acrescentado ao prompt do sistema para o agente escolhido ('' para o Geral)."""
    a = get(agent_id)
    if not a["instrucao"]:
        return ""
    return (f"ESPECIALIDADE: nesta conversa você atua como {a['nome']}. {a['instrucao']} "
            "Continue seguindo todas as regras de segurança e de permissão acima.")
