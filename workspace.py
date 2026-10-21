"""Pasta de projetos do assistente: criar e editar código, rodar comandos permitidos e usar o git.

Tudo acontece dentro de UMA pasta (config `projetos.pasta`), com uma subpasta por projeto.
Os comandos rodam SEM shell, só os programas da lista abaixo, com a pasta do projeto como
diretório de trabalho. Atenção: liberar `python`/`node`/`npm` significa que o assistente pode
executar código no seu PC; a pasta do projeto NÃO é uma caixa de areia. Por isso essa
permissão só existe quando você a concede (por tarefa) ou aprova.
"""
import os
import re
import shlex
import shutil
import subprocess
import unicodedata
from pathlib import Path

ALLOWED_EXECUTABLES = {"git", "python", "python3", "py", "pip", "pip3", "node", "npm", "npx",
                       "pnpm", "yarn", "pytest"}
MAX_READ = 200_000
MAX_WRITE = 500_000
MAX_OUTPUT = 8000
DEFAULT_TIMEOUT = 180

# Só estes subcomandos do git são executados (lista permitida, não lista de bloqueio:
# aliases do git, `git config` livre e opções globais como `-c` poderiam rodar comandos de shell).
GIT_ALLOWED = {"init", "status", "add", "commit", "diff", "log", "show", "branch", "checkout", "switch",
               "restore", "merge", "pull", "fetch", "push", "clone", "remote", "tag", "stash", "rev-parse",
               "ls-files", "mv", "rm", "config"}
GIT_CONFIG_KEYS = {"user.name", "user.email"}
GIT_PUSH_BLOCKED_FLAGS = ("--force", "--delete", "--mirror", "--receive-pack", "--exec", "--prune")
# Opções que fazem o git executar programas ou escrever fora do projeto
GIT_BLOCKED_PREFIXES = ("--upload-pack", "--receive-pack", "--exec", "--config", "--template", "--ext-diff",
                        "--textconv", "--output", "--git-dir", "--work-tree", "--separate-git-dir")


class WorkspaceError(Exception):
    pass


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:50] or "projeto"


def parse_github_repo(url: str):
    """'https://github.com/dono/repo.git' ou 'git@github.com:dono/repo.git' -> 'dono/repo' (minúsculo)."""
    m = re.match(r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
                 (url or "").strip(), re.I)
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


def command_category(command: str) -> str:
    """'git_push' para git push; 'comandos' para o resto."""
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        return "comandos"
    if len(parts) >= 2 and Path(parts[0]).stem.lower() == "git" and parts[1].lower() == "push":
        return "git_push"
    return "comandos"


class Workspace:
    def __init__(self, root: str, allowed_repos=None, timeout: int = DEFAULT_TIMEOUT):
        self.root = Path(root).expanduser().resolve()
        self.allowed_repos = {r.lower() for r in (allowed_repos or [])}
        self.timeout = timeout

    # ---- pastas e caminhos ---------------------------------------------------

    def project_dir(self, project: str, create: bool = True) -> Path:
        slug = slugify(project)
        path = self.root / slug
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def projects(self):
        return sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else []

    def resolve(self, project: str, rel: str = ".") -> Path:
        base = self.project_dir(project, create=False).resolve()
        if not base.is_dir():
            raise WorkspaceError(f"Projeto '{project}' não existe.")
        target = (base / (rel or ".")).resolve()
        if target != base and base not in target.parents:
            raise WorkspaceError("Caminho fora da pasta do projeto.")
        return target

    def _resolve_writable(self, project: str, rel: str) -> Path:
        target = self.resolve(project, rel)
        if ".git" in target.relative_to(self.resolve(project)).parts:
            raise WorkspaceError("Não mexo dentro da pasta .git.")
        return target

    # ---- arquivos --------------------------------------------------------------

    def list_dir(self, project: str, rel: str = ".", limit: int = 200):
        base = self.resolve(project, rel)
        if not base.is_dir():
            raise WorkspaceError("Isso não é uma pasta.")
        out = []
        for p in sorted(base.rglob("*")):
            parts = p.relative_to(base).parts
            if ".git" in parts or "node_modules" in parts or "__pycache__" in parts or ".venv" in parts:
                continue
            out.append(str(Path(*parts)).replace("\\", "/") + ("/" if p.is_dir() else ""))
            if len(out) >= limit:
                break
        return out

    def read_file(self, project: str, rel: str) -> str:
        path = self.resolve(project, rel)
        if not path.is_file():
            raise WorkspaceError(f"Arquivo não encontrado: {rel}")
        data = path.read_bytes()
        text = data[:MAX_READ].decode("utf-8", errors="replace")
        if len(data) > MAX_READ:
            text += "\n[... cortado: arquivo grande ...]"
        return text

    def write_file(self, project: str, rel: str, content: str) -> dict:
        if len(content.encode("utf-8")) > MAX_WRITE:
            raise WorkspaceError("Arquivo grande demais para escrever de uma vez (limite 500 KB).")
        self.project_dir(project, create=True)
        path = self._resolve_writable(project, rel)
        if path.is_dir():
            raise WorkspaceError("O caminho aponta para uma pasta.")
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content, encoding="utf-8", newline="\n")
        return {"ok": True, "arquivo": rel, "bytes": len(content.encode("utf-8")), "sobrescreveu": existed}

    def edit_file(self, project: str, rel: str, search: str, replace: str) -> dict:
        path = self._resolve_writable(project, rel)
        if not path.is_file():
            raise WorkspaceError(f"Arquivo não encontrado: {rel}")
        text = path.read_text(encoding="utf-8")
        count = text.count(search) if search else 0
        if count == 0:
            raise WorkspaceError("O trecho a substituir não foi encontrado (precisa ser idêntico).")
        if count > 1:
            raise WorkspaceError(f"O trecho aparece {count} vezes; inclua mais contexto para ser único.")
        path.write_text(text.replace(search, replace), encoding="utf-8", newline="\n")
        return {"ok": True, "arquivo": rel}

    # ---- comandos --------------------------------------------------------------

    def _split(self, command: str):
        command = (command or "").strip()
        if not command or len(command) > 500 or "\n" in command or "\r" in command:
            raise WorkspaceError("Comando vazio, longo demais ou com várias linhas.")
        if re.search(r"[|&;<>`]|\$\(", command):
            raise WorkspaceError("Envie um comando por vez, sem pipes, redirecionamentos ou encadeamento (| & ; < >).")
        try:
            parts = shlex.split(command, posix=(os.name != "nt"))
        except ValueError as e:
            raise WorkspaceError(f"Comando mal formado: {e}")
        if os.name == "nt":
            parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
        if not parts:
            raise WorkspaceError("Comando vazio.")
        exe = Path(parts[0]).stem.lower()
        if exe not in ALLOWED_EXECUTABLES or Path(parts[0]).name != parts[0]:
            raise WorkspaceError(f"Programa não permitido: {parts[0]}. Permitidos: {', '.join(sorted(ALLOWED_EXECUTABLES))}.")
        if exe == "git":
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub not in GIT_ALLOWED:
                raise WorkspaceError(
                    f"git '{sub or '(vazio)'}' não é permitido. Use: git <{'|'.join(sorted(GIT_ALLOWED))}> ... "
                    "(sem opções antes do subcomando).")
            for a in parts[2:]:
                if any(a.lower().startswith(p) for p in GIT_BLOCKED_PREFIXES):
                    raise WorkspaceError(f"A opção {a.split('=')[0]} do git não é permitida.")
                if sub == "clone" and (a == "-c" or a.startswith("-c") and not a.startswith("--")):
                    raise WorkspaceError("git clone -c não é permitido.")
            if sub == "push":
                positional = [p for p in parts[2:] if not p.startswith("-")]
                flags = [p for p in parts[2:] if p.startswith("-")]
                short_cluster = any(not a.startswith("--") and ("f" in a[1:] or "d" in a[1:]) for a in flags)
                long_bad = any(a == f or a.startswith(f + "=") or (len(f) > 3 and a.startswith(f))
                               for a in flags for f in GIT_PUSH_BLOCKED_FLAGS if f.startswith("--"))
                forced_ref = any(r.startswith(("+", ":")) for r in positional[1:])
                if short_cluster or long_bad or forced_ref:
                    raise WorkspaceError("git push forçado, com exclusão ou opções perigosas não é permitido.")
                if not positional:
                    raise WorkspaceError("Informe o destino: git push origin <branch>.")
            if sub == "config":
                args = [p for p in parts[2:] if not p.startswith("-")]
                if parts[2:3] and parts[2] == "--get" and len(parts) == 4:
                    pass
                elif len(args) != 2 or args[0] not in GIT_CONFIG_KEYS or len(parts) != 4 or parts[2].startswith("-"):
                    raise WorkspaceError("git config só pode definir user.name e user.email.")
        return exe, parts

    def _remote_url(self, cwd: Path, remote: str = "origin") -> str:
        # --push: a URL usada de fato no envio (pode ser diferente da de leitura)
        r = subprocess.run(["git", "remote", "get-url", "--push", remote], cwd=cwd, capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip()

    def run(self, project: str, command: str) -> dict:
        exe, parts = self._split(command)
        cwd = self.resolve(project)
        if exe == "git" and parts[1].lower() == "push":
            self._check_push_allowed(cwd, parts)
        found = shutil.which(parts[0])
        if not found:
            raise WorkspaceError(f"{parts[0]} não está instalado ou não está no PATH.")
        try:
            r = subprocess.run([found] + parts[1:], cwd=cwd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise WorkspaceError(f"O comando passou de {self.timeout}s e foi interrompido.")
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        if len(out) > MAX_OUTPUT:
            out = out[: MAX_OUTPUT // 2] + "\n[... saída cortada ...]\n" + out[-MAX_OUTPUT // 2:]
        return {"codigo": r.returncode, "saida": out.strip()}

    def _check_push_allowed(self, cwd: Path, parts):
        positional = [p for p in parts[2:] if not p.startswith("-")]
        remote = positional[0]
        url = remote if "://" in remote or "@" in remote else self._remote_url(cwd, remote)
        repo = parse_github_repo(url)
        if not self.allowed_repos:
            raise WorkspaceError("Nenhum repositório autorizado para envio. Liste-os em `projetos.repos_permitidos` no config.yaml.")
        if repo not in self.allowed_repos:
            raise WorkspaceError(f"Envio bloqueado: '{repo or url}' não está em projetos.repos_permitidos.")

    # ---- atalhos de git --------------------------------------------------------

    def git_commit(self, project: str, message: str) -> dict:
        message = " ".join((message or "").split())
        if not message or len(message) > 200:
            raise WorkspaceError("Mensagem de commit vazia ou longa demais.")
        cwd = self.project_dir(project, create=True)
        if not (cwd / ".git").exists():
            self.run(project, "git init -b main")
        self.run(project, "git add -A")
        res = self.run(project, f'git commit -m "{message.replace(chr(34), chr(39))}"')
        return res

    def git_push(self, project: str, branch: str = "") -> dict:
        cwd = self.resolve(project)
        branch = branch.strip() or self.run(project, "git rev-parse --abbrev-ref HEAD")["saida"].strip()
        if not re.match(r"^[\w./-]+$", branch):
            raise WorkspaceError("Nome de branch inválido.")
        return self.run(project, f"git push -u origin {branch}")
