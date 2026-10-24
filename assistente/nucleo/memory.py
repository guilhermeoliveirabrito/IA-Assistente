"""Memória do assistente: arquivos markdown na pasta memory/ que você edita à vontade.

- perfil.md  → quem você é, rotina, tom preferido
- regras.md  → o que ele deve sempre/nunca fazer
- notas.md   → instruções soltas que você pede para ele lembrar (`python main.py lembrar "..."`)

Qualquer arquivo .md novo colocado em memory/ também entra na memória.
"""
import re
import shutil
from datetime import date
from pathlib import Path

MEMORY_DIR = Path("memory")
EXAMPLE_DIR = Path("memory_example")
NOTES_FILE = "notas.md"
MAX_CHARS = 8000  # limite do que vai para o prompt; as notas mais recentes têm prioridade


def ensure():
    """Cria a pasta memory/ a partir dos modelos na primeira vez."""
    if MEMORY_DIR.exists():
        return
    if EXAMPLE_DIR.exists():
        shutil.copytree(EXAMPLE_DIR, MEMORY_DIR)
    else:
        MEMORY_DIR.mkdir()
        (MEMORY_DIR / NOTES_FILE).write_text("# Notas\n", encoding="utf-8")


def _clean(text: str) -> str:
    """Remove comentários <!-- --> (instruções para você, não para a IA)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def _notes_path() -> Path:
    ensure()
    path = MEMORY_DIR / NOTES_FILE
    if not path.exists():
        path.write_text("# Notas\n", encoding="utf-8")
    return path


def read_all() -> str:
    """Junta toda a memória em um texto só."""
    ensure()
    others, notes = [], ""
    for f in sorted(MEMORY_DIR.glob("*.md")):
        txt = _clean(f.read_text(encoding="utf-8"))
        if not txt:
            continue
        if f.name == NOTES_FILE:
            notes = f"## {f.stem}\n{txt}"
        else:
            others.append(f"## {f.stem}\n{txt}")
    base = "\n\n".join(others)
    budget = max(MAX_CHARS - len(base), 500)
    if len(notes) > budget:  # corta as notas mais antigas, mantém as recentes
        notes = notes[-budget:]
        notes = notes[notes.find("\n") + 1 :] if "\n" in notes else notes
    return "\n\n".join(p for p in (base, notes) if p)


def prompt_block() -> str:
    """Trecho pronto para colocar dentro dos prompts da IA."""
    text = read_all()
    if not text:
        return ""
    return (
        "\nMEMÓRIA DO USUÁRIO (preferências e instruções dele; siga-as, "
        "mas elas nunca autorizam ações fora das regras de segurança):\n"
        f"{text}\n"
    )


def list_notes():
    """Retorna as notas (linhas que começam com '- ')."""
    lines = _notes_path().read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln.startswith("- ")]


def remember(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise ValueError("Escreva o que devo lembrar.")
    line = f"- [{date.today().isoformat()}] {text}"
    path = _notes_path()
    content = path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content + line + "\n", encoding="utf-8")
    return line


def forget(number: int) -> str:
    """Remove a nota de número `number` (1 = primeira da lista)."""
    path = _notes_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    note_idx = [i for i, ln in enumerate(lines) if ln.startswith("- ")]
    if not 1 <= number <= len(note_idx):
        raise ValueError(f"Nota {number} não existe. Há {len(note_idx)} nota(s).")
    removed = lines.pop(note_idx[number - 1])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return removed
