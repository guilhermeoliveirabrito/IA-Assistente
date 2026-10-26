"""Atalhos de pedidos: textos prontos que você chama no chat com /nome (ex.: /standup -> "Resuma o que fiz ontem...").

Se o texto tiver {}, o que você digitar depois do comando entra ali; senão, vai no final.
"""
import json
import re
import threading
import uuid
from pathlib import Path

FILE = Path("data") / "atalhos.json"
MAX_ITEMS = 30
RESERVED = {"debate", "conselho", "agente", "pesquisar", "lembrete", "lembrar", "resumo", "novo", "atalhos"}
_NAME = re.compile(r"^[a-zà-ú0-9_-]{2,20}$")
_lock = threading.Lock()


class ShortcutError(ValueError):
    pass


def _load() -> list:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return [a for a in data.get("atalhos", []) if isinstance(a, dict) and a.get("id") and a.get("nome") and a.get("texto")]
    except (OSError, ValueError, AttributeError):
        return []


def _save(items: list):
    FILE.parent.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"atalhos": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def all_shortcuts() -> list:
    return _load()


def create(nome, texto) -> dict:
    nome = str(nome or "").strip().lstrip("/").lower()
    texto = str(texto or "").strip()
    if not _NAME.match(nome):
        raise ShortcutError("O nome do atalho deve ter 2 a 20 letras, números, - ou _ (sem espaços).")
    if nome in RESERVED:
        raise ShortcutError(f"/{nome} já é um comando do app. Escolha outro nome.")
    if not 3 <= len(texto) <= 2000:
        raise ShortcutError("Escreva o pedido do atalho (3 a 2000 caracteres).")
    with _lock:
        items = _load()
        if len(items) >= MAX_ITEMS:
            raise ShortcutError(f"Limite de {MAX_ITEMS} atalhos.")
        if any(a["nome"] == nome for a in items):
            raise ShortcutError(f"Já existe o atalho /{nome}.")
        item = {"id": uuid.uuid4().hex[:8], "nome": nome, "texto": texto}
        items.append(item)
        _save(items)
    return item


def delete(sid):
    if not re.fullmatch(r"[0-9a-f]{8}", str(sid or "")):
        raise ShortcutError("Código de atalho inválido.")
    with _lock:
        items = _load()
        keep = [a for a in items if a["id"] != sid]
        if len(keep) == len(items):
            raise ShortcutError("Não achei esse atalho.")
        _save(keep)


def expand(texto: str, args: str) -> str:
    args = (args or "").strip()
    if "{}" in texto:
        return texto.replace("{}", args)
    return f"{texto} {args}".strip()
