"""Atualização do app a partir do GitHub, sem mexer nos seus dados.

Baixa o ZIP da versão mais recente e copia os arquivos do programa por cima da pasta atual. Nunca toca em
`.env`, `credentials.json`, `token.json`, `data/`, `memory/` nem no ambiente virtual (`.venv`). Se o `config.yaml`
tiver sido editado à mão, a sua versão é guardada como `config.yaml.anterior`. As dependências são reinstaladas só
quando o `requirements.txt` mudou.

Também funciona sem o app aberto:  python -m assistente.servicos.atualizador
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "guilhermeoliveirabrito/ia-assistente"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = Path("data") / "versao.json"
CACHE_SECONDS = 6 * 3600
# nunca sobrescritos nem apagados (dados, segredos e ambiente do usuário)
PROTEGIDOS = {".env", "credentials.json", "token.json", "data", "memory", ".venv", "venv", ".git", "__pycache__"}
MAX_ZIP = 80 * 1024 * 1024


class UpdateError(Exception):
    pass


def _get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "assistente-pessoal-atualizador", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_ZIP + 1)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"Não encontrei a versão nova no GitHub (HTTP {e.code}).") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("Sem conexão com o GitHub agora. Tente de novo mais tarde.") from e


def latest(timeout: float = 10.0) -> dict:
    """Último commit da branch principal: {sha, mensagem, data}."""
    try:
        obj = json.loads(_get(API_URL, timeout).decode("utf-8"))
        return {"sha": str(obj["sha"]), "mensagem": str((obj.get("commit") or {}).get("message", "")).split("\n")[0][:140],
                "data": str(((obj.get("commit") or {}).get("committer") or {}).get("date", ""))}
    except (ValueError, KeyError, TypeError) as e:
        raise UpdateError("Resposta inesperada do GitHub.") from e


def installed(root: Path = None) -> dict:
    """Versão instalada: {sha, atualizado_em} (vazio se nunca atualizou por aqui)."""
    try:
        data = json.loads(((root or Path.cwd()) / STATE_FILE).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_installed(info: dict, root: Path):
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


class Checker:
    """Pergunta ao GitHub se há versão nova, no máximo uma vez a cada 6 horas (a não ser que peçam para forçar)."""

    def __init__(self, root: Path = None, fetch=latest, clock=time.time):
        self.root, self.fetch, self.clock = root or Path.cwd(), fetch, clock
        self._cache = None
        self._at = 0.0
        self._lock = threading.Lock()

    def check(self, force: bool = False) -> dict:
        with self._lock:
            if not force and self._cache and self.clock() - self._at < CACHE_SECONDS:
                remote = self._cache
            else:
                remote = self.fetch()
                self._cache, self._at = remote, self.clock()
        local = installed(self.root).get("sha")
        return {
            "atual": (local or "")[:7] or None,
            "ultima": remote["sha"][:7],
            "mensagem": remote.get("mensagem", ""),
            "data": remote.get("data", ""),
            "nova": bool(local) and local != remote["sha"],
            "desconhecida": not local,          # instalado por ZIP: não dá para comparar, mas dá para atualizar
        }


def _safe_members(zf: zipfile.ZipFile, dest: Path):
    base = dest.resolve()
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if base != target and base not in target.parents:
            raise UpdateError("O arquivo baixado tem caminhos suspeitos e foi recusado.")
        if info.file_size > MAX_ZIP:
            raise UpdateError("O arquivo baixado é grande demais.")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_deps(root: Path) -> str:
    """Reinstala as dependências; devolve '' se deu certo ou a mensagem do problema."""
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(root / "requirements.txt"), "--disable-pip-version-check", "-q"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=root)
    except (OSError, subprocess.SubprocessError) as e:
        return f"não consegui rodar o pip ({e})"
    return "" if done.returncode == 0 else (done.stderr or done.stdout or "erro do pip").strip().splitlines()[-1][:200]


def apply(root: Path = None, sha: str = None, fetch_zip=None, install_deps=_install_deps, say=print) -> dict:
    """Baixa e instala a versão mais recente. Devolve {arquivos, dependencias, config_anterior, erro_dependencias}."""
    root = Path(root or Path.cwd()).resolve()
    say("Baixando a versão mais recente…")
    raw = (fetch_zip or (lambda: _get(ZIP_URL, 60.0)))()
    if len(raw) > MAX_ZIP:
        raise UpdateError("O arquivo baixado é grande demais.")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = tmp / "novo.zip"
        zpath.write_bytes(raw)
        try:
            with zipfile.ZipFile(zpath) as zf:
                _safe_members(zf, tmp / "x")
                zf.extractall(tmp / "x")
        except zipfile.BadZipFile as e:
            raise UpdateError("O arquivo baixado não é um ZIP válido (download incompleto ou bloqueado). Tente de novo.") from e
        tops = [p for p in (tmp / "x").iterdir() if p.is_dir()]
        src = tops[0] if len(tops) == 1 else tmp / "x"
        if not (src / "assistente").is_dir() or not (src / "app.py").is_file():
            raise UpdateError("O ZIP baixado não parece ser do Assistente.")
        reqs_before = _digest(root / "requirements.txt") if (root / "requirements.txt").is_file() else ""
        count, config_old = 0, False
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src)
            if rel.parts[0] in PROTEGIDOS or "__pycache__" in rel.parts or path.is_dir():
                continue
            dest = root / rel
            if rel.as_posix() == "config.yaml" and dest.is_file() and _digest(dest) != _digest(path):
                shutil.copy2(dest, root / "config.yaml.anterior")
                config_old = True
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            count += 1
    deps, deps_error = False, ""
    req_file = root / "requirements.txt"
    if req_file.is_file() and _digest(req_file) != reqs_before:
        say("As dependências mudaram; instalando…")
        deps = True
        deps_error = install_deps(root)
    try:
        sha = sha or latest(6.0)["sha"]
    except UpdateError:
        sha = None
    if sha:
        _save_installed({"sha": sha, "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S")}, root)
    return {"arquivos": count, "dependencias": deps, "config_anterior": config_old, "erro_dependencias": deps_error}


def restart():
    """Abre uma nova instância do app e encerra esta (usado pelo botão "Atualizar e reiniciar")."""
    try:
        subprocess.Popen([sys.executable, *sys.argv], cwd=Path.cwd(), close_fds=True)
    finally:
        os._exit(0)


def main() -> int:
    os.chdir(ROOT)
    try:
        result = apply()
    except UpdateError as e:
        print(f"Não deu certo: {e}")
        return 1
    print(f"Pronto: {result['arquivos']} arquivos atualizados. Seus dados foram mantidos.")
    if result["config_anterior"]:
        print("O config.yaml mudou; o seu foi guardado como config.yaml.anterior.")
    if result["erro_dependencias"]:
        print("Atenção: as dependências não instalaram sozinhas:", result["erro_dependencias"])
    print("Abra o Assistente de novo para usar a versão nova.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
