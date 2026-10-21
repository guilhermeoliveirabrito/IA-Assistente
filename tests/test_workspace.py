import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import workspace as ws  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "Teste", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "Teste", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projetos"
        self.w = ws.Workspace(str(self.root), allowed_repos=["dono/repo"], timeout=60)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    # ---- utilidades
    def test_slug(self):
        self.assertEqual(ws.slugify("Meu Site Incrível!"), "meu-site-incrivel")
        self.assertEqual(ws.slugify("../../etc"), "etc")
        self.assertEqual(ws.slugify("???"), "projeto")

    def test_parse_repo(self):
        for url in ("https://github.com/Dono/Repo.git", "https://github.com/dono/repo", "git@github.com:dono/repo.git",
                    "https://token@github.com/dono/repo.git/"):
            self.assertEqual(ws.parse_github_repo(url), "dono/repo", url)
        for bad in ("", "https://gitlab.com/dono/repo", "/tmp/repo.git", "https://github.com.evil.com/dono/repo"):
            self.assertIsNone(ws.parse_github_repo(bad), bad)

    def test_categoria_do_comando(self):
        self.assertEqual(ws.command_category("git push origin main"), "git_push")
        self.assertEqual(ws.command_category("git commit -m x"), "comandos")
        self.assertEqual(ws.command_category("npm test"), "comandos")

    # ---- arquivos
    def test_escrever_ler_editar_listar(self):
        self.w.write_file("Meu App", "src/app.py", "print('oi')\n")
        self.assertEqual(self.w.read_file("Meu App", "src/app.py"), "print('oi')\n")
        self.w.edit_file("Meu App", "src/app.py", "oi", "olá")
        self.assertIn("olá", self.w.read_file("Meu App", "src/app.py"))
        self.assertEqual(self.w.list_dir("Meu App"), ["src/", "src/app.py"])

    def test_nao_escapa_da_pasta_do_projeto(self):
        self.w.write_file("p", "a.txt", "x")
        for bad in ("../outro/a.txt", "../../fora.txt", "/etc/passwd"):
            with self.assertRaises(ws.WorkspaceError, msg=bad):
                self.w.write_file("p", bad, "x")
        self.assertFalse((self.root / "fora.txt").exists())

    def test_symlink_para_fora_e_bloqueado(self):
        self.w.write_file("p", "a.txt", "x")
        secret = Path(self.tmp.name) / "segredo.txt"
        secret.write_text("senha")
        link = self.root / "p" / "atalho.txt"
        try:
            link.symlink_to(secret)
        except OSError:
            self.skipTest("sem symlink")
        with self.assertRaises(ws.WorkspaceError):
            self.w.read_file("p", "atalho.txt")

    def test_nao_escreve_na_pasta_git(self):
        self.w.write_file("p", "a.txt", "x")
        (self.root / "p" / ".git" / "hooks").mkdir(parents=True)
        with self.assertRaises(ws.WorkspaceError):
            self.w.write_file("p", ".git/hooks/pre-commit", "#!/bin/sh\nrm -rf ~")

    def test_edicao_ambigua_ou_inexistente(self):
        self.w.write_file("p", "a.txt", "aa aa")
        with self.assertRaises(ws.WorkspaceError):
            self.w.edit_file("p", "a.txt", "aa", "b")
        with self.assertRaises(ws.WorkspaceError):
            self.w.edit_file("p", "a.txt", "zzz", "b")
        with self.assertRaises(ws.WorkspaceError):
            self.w.edit_file("p", "a.txt", "", "b")

    def test_arquivo_grande_demais(self):
        with self.assertRaises(ws.WorkspaceError):
            self.w.write_file("p", "g.txt", "x" * (ws.MAX_WRITE + 1))

    def test_projeto_inexistente_na_leitura(self):
        with self.assertRaises(ws.WorkspaceError):
            self.w.read_file("nao-existe", "a.txt")

    # ---- comandos
    def test_roda_programa_permitido(self):
        self.w.project_dir("p")
        res = self.w.run("p", 'python3 -c "print(1+1)"')
        self.assertEqual((res["codigo"], res["saida"]), (0, "2"))

    def test_roda_na_pasta_do_projeto(self):
        self.w.write_file("p", "marca.txt", "x")
        res = self.w.run("p", 'python3 -c "print(__import__(\'os\').listdir())"')
        self.assertIn("marca.txt", res["saida"])

    def test_programas_fora_da_lista(self):
        self.w.project_dir("p")
        for bad in ("rm -rf /", "powershell -c calc", "curl http://x", "cmd /c dir", "bash -c ls",
                    "/usr/bin/python3 -c 1", "..\\python3 x"):
            with self.assertRaises(ws.WorkspaceError, msg=bad):
                self.w.run("p", bad)

    def test_sem_encadeamento_nem_redirecionamento(self):
        self.w.project_dir("p")
        for bad in ("python3 -c 1 && rm x", "python3 -c 1 | cat", "python3 -c 1 > out", "python3 -c 1; ls",
                    "", "python3 -c 1\nls", "x" * 600):
            with self.assertRaises(ws.WorkspaceError, msg=bad):
                self.w.run("p", bad)

    def test_timeout(self):
        w = ws.Workspace(str(self.root), timeout=1)
        w.project_dir("p")
        with self.assertRaises(ws.WorkspaceError):
            w.run("p", 'python3 -c "import time;time.sleep(5)"')

    def test_saida_longa_e_cortada(self):
        self.w.project_dir("p")
        res = self.w.run("p", 'python3 -c "print(\'a\'*30000)"')
        self.assertLess(len(res["saida"]), ws.MAX_OUTPUT + 100)
        self.assertIn("cortada", res["saida"])

    def test_programa_nao_instalado(self):
        self.w.project_dir("p")
        import shutil
        if shutil.which("pnpm"):
            self.skipTest("pnpm instalado")
        with self.assertRaises(ws.WorkspaceError):
            self.w.run("p", "pnpm --version")

    # ---- git
    def test_git_bloqueios(self):
        self.w.project_dir("p")
        bad = [
            "git -c core.sshCommand=calc push origin main",
            "git config alias.x !calc",
            "git config core.editor calc",
            "git clean -fd",
            "git reset --hard",
            "git push",
            "git push --force origin main",
            "git push --force-with-lease origin main",
            "git push -fu origin main",
            "git push origin +main",
            "git push origin :main",
            "git push --delete origin main",
            "git clone -c core.sshCommand=x https://github.com/a/b",
            "git clone --upload-pack=calc https://github.com/a/b",
            "git --git-dir=x status",
            "git status --git-dir=/etc",
        ]
        for cmd in bad:
            with self.assertRaises(ws.WorkspaceError, msg=cmd):
                self.w.run("p", cmd)

    def test_git_config_de_identidade_e_permitido(self):
        self.w.project_dir("p")
        self.w.run("p", "git init -b main")
        self.assertEqual(self.w.run("p", 'git config user.name "Fulano"')["codigo"], 0)

    def test_commit_inicializa_repo(self):
        self.w.write_file("p", "a.txt", "x")
        res = self.w.git_commit("p", "feat: primeiro commit")
        self.assertEqual(res["codigo"], 0)
        log = self.w.run("p", "git log --oneline")["saida"]
        self.assertIn("feat: primeiro commit", log)

    def test_commit_mensagem_invalida(self):
        with self.assertRaises(ws.WorkspaceError):
            self.w.git_commit("p", "  ")

    def _repo_com_remoto(self, w):
        bare = Path(self.tmp.name) / "remoto.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
        w.write_file("p", "a.txt", "x")
        w.git_commit("p", "init")
        w.run("p", f"git remote add origin {bare}")
        return bare

    def test_push_so_para_repositorio_autorizado(self):
        bare = self._repo_com_remoto(self.w)
        self.w._remote_url = lambda cwd, remote="origin": "https://github.com/dono/repo.git"
        res = self.w.git_push("p")
        self.assertEqual(res["codigo"], 0, res["saida"])
        heads = subprocess.run(["git", "--git-dir", str(bare), "branch"], capture_output=True, text=True).stdout
        self.assertIn("main", heads)

    def test_push_bloqueado_para_outro_repositorio(self):
        self._repo_com_remoto(self.w)
        self.w._remote_url = lambda cwd, remote="origin": "https://github.com/outro/coisa.git"
        with self.assertRaises(ws.WorkspaceError):
            self.w.git_push("p")

    def test_push_bloqueado_sem_lista_de_repositorios(self):
        w = ws.Workspace(str(self.root), allowed_repos=[])
        self._repo_com_remoto(w)
        w._remote_url = lambda cwd, remote="origin": "https://github.com/dono/repo.git"
        with self.assertRaises(ws.WorkspaceError):
            w.git_push("p")

    def test_push_direto_para_url_nao_autorizada(self):
        self.w.project_dir("p")
        with self.assertRaises(ws.WorkspaceError):
            self.w.run("p", "git push https://github.com/outro/coisa.git main")

    def test_nome_de_branch_invalido(self):
        self.w.project_dir("p")
        with self.assertRaises(ws.WorkspaceError):
            self.w.git_push("p", "main; rm -rf /")


if __name__ == "__main__":
    unittest.main()
