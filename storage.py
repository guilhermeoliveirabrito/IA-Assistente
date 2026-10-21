"""Conversas salvas em disco (data/conversations) e anexos (data/uploads)."""
import base64
import copy
import json
import re
import threading
import time
import uuid
from pathlib import Path

DATA = Path("data")
ID_RE = re.compile(r"^[0-9a-f]{12}$")
_lock = threading.RLock()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024        # por arquivo
MAX_INLINE_BYTES = 18 * 1024 * 1024        # total enviado ao Gemini por requisição


def _conv_dir() -> Path:
    d = DATA / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_id(cid: str):
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise KeyError("Conversa inválida.")


def _write_json(path: Path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def make_title(text: str, limit: int = 48) -> str:
    text = " ".join((text or "").split())
    if not text:
        return "Nova conversa"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def new_conversation(title: str = "Nova conversa") -> dict:
    now = time.time()
    conv = {"id": uuid.uuid4().hex[:12], "title": title, "created": now, "updated": now,
            "messages": [], "contents": []}
    save(conv)
    return conv


def load(cid: str) -> dict:
    _check_id(cid)
    path = _conv_dir() / f"{cid}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KeyError("Conversa não encontrada.")


def save(conv: dict):
    _check_id(conv["id"])
    with _lock:
        conv["updated"] = time.time()
        _write_json(_conv_dir() / f"{conv['id']}.json", conv)


def list_all():
    items = []
    for p in _conv_dir().glob("*.json"):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            items.append({"id": c["id"], "title": c.get("title", ""), "updated": c.get("updated", 0),
                          "created": c.get("created", 0), "count": len(c.get("messages", []))})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(items, key=lambda i: i["updated"], reverse=True)


def rename(cid: str, title: str) -> dict:
    with _lock:
        conv = load(cid)
        conv["title"] = make_title(title, 80)
        save(conv)
        return conv


def delete(cid: str):
    _check_id(cid)
    with _lock:
        (_conv_dir() / f"{cid}.json").unlink(missing_ok=True)
        up = DATA / "uploads" / cid
        if up.is_dir():
            for f in up.iterdir():
                f.unlink(missing_ok=True)
            up.rmdir()


# ---- anexos ---------------------------------------------------------------

def safe_filename(name: str) -> str:
    name = Path(name or "arquivo").name
    name = re.sub(r"[^\w.\- ()]", "_", name, flags=re.UNICODE).strip(" .") or "arquivo"
    return name[:80]


def save_upload(cid: str, name: str, data: bytes) -> str:
    """Salva o anexo e devolve o nome guardado (com prefixo único)."""
    _check_id(cid)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{name}: arquivo maior que {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    folder = DATA / "uploads" / cid
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex[:8]}_{safe_filename(name)}"
    (folder / stored).write_bytes(data)
    return stored


def read_upload(cid: str, stored: str) -> bytes:
    _check_id(cid)
    path = (DATA / "uploads" / cid / Path(stored).name)
    return path.read_bytes()


def resolve_contents(cid: str, contents: list, max_bytes: int = MAX_INLINE_BYTES) -> list:
    """Converte marcadores de arquivo ({'x_file': ...}) em dados inline para o Gemini.

    Se o total passar do limite, os anexos MAIS ANTIGOS viram um aviso em texto.
    """
    out = copy.deepcopy(contents)
    refs = []  # (content_idx, part_idx, size)
    for ci, content in enumerate(out):
        for pi, part in enumerate(content.get("parts", [])):
            if "x_file" in part:
                try:
                    size = (DATA / "uploads" / cid / Path(part["x_file"]).name).stat().st_size
                except OSError:
                    size = -1
                refs.append((ci, pi, size))
    total = sum(max(s, 0) for _, _, s in refs)
    drop = set()
    for ci, pi, size in refs:  # mais antigos primeiro
        if size < 0 or total > max_bytes:
            drop.add((ci, pi))
            total -= max(size, 0)
    for ci, pi, size in refs:
        part = out[ci]["parts"][pi]
        label = part.get("x_name") or part["x_file"]
        if (ci, pi) in drop:
            out[ci]["parts"][pi] = {"text": f"[Anexo '{label}' não está mais disponível nesta conversa.]"}
        else:
            raw = read_upload(cid, part["x_file"])
            out[ci]["parts"][pi] = {"inlineData": {"mimeType": part["mimeType"],
                                                   "data": base64.b64encode(raw).decode("ascii")}}
    return out
