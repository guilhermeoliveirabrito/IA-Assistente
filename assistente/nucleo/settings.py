"""Ajustes editáveis pela interface.

O config.yaml continua sendo a base (com seus comentários). O que você muda no app fica em
data/settings.json e é aplicado POR CIMA do config.yaml. Só os campos desta lista podem ser alterados
pela interface; qualquer outro é ignorado.
"""
import json
import re
from pathlib import Path

import yaml

from assistente.ia import providers

SETTINGS_FILE = Path("data") / "settings.json"
CONFIG_FILE = Path("config.yaml")


def _num(lo, hi, integer=True):
    def check(v):
        try:
            n = int(v) if integer else float(v)
        except (TypeError, ValueError):
            raise ValueError("Informe um número.")
        if not lo <= n <= hi:
            raise ValueError(f"Use um valor entre {lo} e {hi}.")
        return n
    return check


def _text(maxlen, pattern=None, allow_empty=True):
    def check(v):
        v = " ".join(str(v or "").split())
        if not v and not allow_empty:
            raise ValueError("Não pode ficar vazio.")
        if len(v) > maxlen:
            raise ValueError(f"Máximo de {maxlen} caracteres.")
        if v and pattern and not re.match(pattern, v):
            raise ValueError("Formato inválido.")
        return v
    return check


def _list(maxitems, itemcheck):
    def check(v):
        if isinstance(v, str):
            v = [x for x in re.split(r"[\n,]+", v) if x.strip()]
        if not isinstance(v, list) or len(v) > maxitems:
            raise ValueError(f"Informe uma lista com até {maxitems} itens.")
        return [itemcheck(x) for x in v]
    return check


def _bool(v):
    if isinstance(v, bool):
        return v
    raise ValueError("Use verdadeiro ou falso.")


def _choice(*options):
    def check(v):
        if v not in options:
            raise ValueError(f"Use uma destas opções: {', '.join(options)}.")
        return v
    return check


def _folder(v):
    v = str(v or "").strip()
    if not v or len(v) > 300 or "\n" in v:
        raise ValueError("Caminho inválido.")
    return v


def _repo(v):
    v = str(v or "").strip().lower()
    if not re.match(r"^[\w.-]+/[\w.-]+$", v):
        raise ValueError(f"'{v}' não é um repositório no formato usuario/nome.")
    return v


# caminho no config -> (validador, precisa reiniciar?)
FIELDS = {
    "app.seu_nome": (_text(40), False),
    "app.acesso": (_choice("local", "rede"), True),
    "app.porta": (_num(1024, 65535), True),
    "ia.modelo": (_text(60, r"^[\w.\-]+$", allow_empty=False), False),
    "ia.raciocinio": (_choice("auto", "minimal", "low", "medium", "high"), False),
    "ia.raciocinio_pc": (_choice("minimal", "low", "medium", "high", "auto"), False),
    "ia.ordem_provedores": (_list(12, _choice("gemini", *providers.PRESETS)), False),
    "ia.modelos_reserva": (_list(5, _text(60, r"^[\w.\-]+$", allow_empty=False)), False),
    "limites.requisicoes_por_dia": (_num(1, 1_000_000), False),
    "limites.requisicoes_por_minuto": (_num(1, 100_000), False),
    "limites.tokens_por_minuto": (_num(1000, 100_000_000), False),
    "limites.por_modelo": (_list(12, _text(120, r"^[\w.\-]+\s*=\s*\d+(\s*,\s*\d+){0,2}$", allow_empty=False)), False),
    "limites.fuso_renovacao": (_text(40, r"^[A-Za-z_]+/[A-Za-z_]+$", allow_empty=False), False),
    "limites.hora_renovacao": (_text(5, r"^([01]\d|2[0-3]):[0-5]\d$", allow_empty=False), False),
    "historico.dias_de_retencao": (_num(1, 365, integer=False), False),
    "tarefas.orcamento_de_requisicoes": (_num(1, 1000), True),
    "tarefas.espera_de_aprovacao_minutos": (_num(1, 720, integer=False), True),
    "tarefas.retomar_apos_renovacao": (_bool, True),
    "notificacoes.ntfy_topico": (_text(64, r"^[A-Za-z0-9_-]{16,64}$"), True),
    "notificacoes.avisar_pedidos": (_bool, True),
    "notificacoes.avisar_conclusao": (_bool, True),
    "notificacoes.avisar_pausas": (_bool, True),
    "notificacoes.avisar_erros": (_bool, True),
    "notificacoes.avisar_encomendas": (_bool, True),
    "notificacoes.avisar_lembretes": (_bool, True),
    "notificacoes.avisar_resumo": (_bool, True),
    "automatico.resumo_do_dia": (_bool, True),
    "debate.rodadas": (_num(0, 2), False),
    "automatico.resumo_do_dia_as": (_text(5, r"^([01]\d|2[0-3]):[0-5]\d$", allow_empty=False), True),
    "rastreio.verificar_a_cada_minutos": (_num(15, 1440), True),
    "projetos.repos_permitidos": (_list(30, _repo), True),
    "projetos.pasta": (_folder, True),
    "arquivos.gravar_sem_perguntar": (_bool, False),
    "arquivos.pasta_de_saida": (_folder, False),
    "arquivos.pastas_permitidas": (_list(20, _folder), False),
    "pc.modo_autonomo": (_bool, False),
    "pc.esconder_janela": (_bool, False),
    "pc.confiar_sem_perguntar": (_list(2, _choice("abrir", "projeto_escrever")), True),
    "pc.janela_de_permissao_minutos": (_num(1, 60, integer=False), True),
    "google.permitir_enviar_email": (_bool, False),
    "voz.ativada": (_bool, False),
    "voz.frase_de_ativacao": (_text(40, r"^[A-Za-zÀ-ÿ ]{3,40}$", allow_empty=False), False),
    "voz.falar_resposta": (_bool, False),
    "voz.transcricao": (_choice("gemini", "local"), False),
    "spotify.porta_login": (_num(1024, 65535), True),
}
for _pid in providers.PRESETS:            # modelo de cada provedor reserva (os catálogos deles mudam com o tempo)
    FIELDS[f"provedores.{_pid}.modelo"] = (_text(100, r"^[\w.\-:/]+$"), False)
FIELDS["provedores.ollama.url"] = (_text(120, r"^https?://[\w.\-:/]+$", allow_empty=False), False)


def _set(cfg: dict, dotted: str, value):
    node = cfg
    *parents, leaf = dotted.split(".")
    for p in parents:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            return
    node[leaf] = value


def _get(cfg: dict, dotted: str, default=None):
    node = cfg
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    return node


def load_overrides() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config(path: Path = None) -> dict:
    """config.yaml + ajustes feitos pela interface."""
    cfg = yaml.safe_load((path or CONFIG_FILE).read_text(encoding="utf-8")) or {}
    for dotted, value in load_overrides().items():
        if dotted in FIELDS:
            _set(cfg, dotted, value)
    return cfg


def current_values(cfg: dict) -> dict:
    return {dotted: _get(cfg, dotted) for dotted in FIELDS}


def update(cfg: dict, changes: dict):
    """Valida e salva as mudanças. Aplica em `cfg` na hora.

    Retorna (campos_alterados, precisa_reiniciar). Levanta ValueError com a lista de erros.
    """
    errors, clean = {}, {}
    for dotted, raw in (changes or {}).items():
        if dotted not in FIELDS:
            errors[dotted] = "Campo desconhecido."
            continue
        try:
            clean[dotted] = FIELDS[dotted][0](raw)
        except ValueError as e:
            errors[dotted] = str(e)
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=False))
    overrides = load_overrides()
    changed, restart = [], False
    for dotted, value in clean.items():
        if _get(cfg, dotted) != value:
            changed.append(dotted)
            restart = restart or FIELDS[dotted][1]
        overrides[dotted] = value
        _set(cfg, dotted, value)
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    return changed, restart
