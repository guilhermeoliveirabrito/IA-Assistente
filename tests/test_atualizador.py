import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from assistente.servicos import atualizador as at


def make_zip(files: dict, top="ia-assistente-main") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"{top}/{name}" if top else name, content)
    return buf.getvalue()


BASE = {"app.py": "print('novo')", "assistente/__init__.py": "", "assistente/x.py": "v2", "requirements.txt": "pyyaml\n",
        "config.yaml": "a: 2\n", "data/lixo.txt": "não deve entrar", "memory/perfil.md": "não deve entrar", ".env": "SEGREDO=novo"}


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "settings.json").write_text('{"meu": 1}')
        (self.root / "memory").mkdir()
        (self.root / "memory" / "perfil.md").write_text("meu perfil")
        (self.root / ".env").write_text("GEMINI_API_KEY=minha")
        (self.root / "assistente").mkdir()
        (self.root / "assistente" / "x.py").write_text("v1")
        (self.root / "requirements.txt").write_text("pyyaml\n")
        (self.root / "config.yaml").write_text("a: 1\n")
        self.deps = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, files=None, **kw):
        raw = make_zip(files or BASE)
        return at.apply(self.root, sha="abc1234567", fetch_zip=lambda: raw,
                        install_deps=lambda root: self.deps.append(root) or "", say=lambda *_: None, **kw)

    def test_atualiza_o_codigo_e_preserva_os_dados(self):
        r = self.run_apply()
        self.assertEqual((self.root / "assistente" / "x.py").read_text(), "v2")
        self.assertEqual((self.root / ".env").read_text(), "GEMINI_API_KEY=minha")
        self.assertEqual((self.root / "memory" / "perfil.md").read_text(), "meu perfil")
        self.assertEqual(json.loads((self.root / "data" / "settings.json").read_text()), {"meu": 1})
        self.assertFalse((self.root / "data" / "lixo.txt").exists())
        self.assertGreaterEqual(r["arquivos"], 4)

    def test_guarda_o_config_editado_e_registra_a_versao(self):
        r = self.run_apply()
        self.assertTrue(r["config_anterior"])
        self.assertEqual((self.root / "config.yaml.anterior").read_text(), "a: 1\n")
        self.assertEqual((self.root / "config.yaml").read_text(), "a: 2\n")
        self.assertEqual(at.installed(self.root)["sha"], "abc1234567")

    def test_config_igual_nao_gera_copia(self):
        (self.root / "config.yaml").write_text("a: 2\n")
        self.assertFalse(self.run_apply()["config_anterior"])
        self.assertFalse((self.root / "config.yaml.anterior").exists())

    def test_so_reinstala_dependencias_se_mudaram(self):
        self.run_apply()
        self.assertEqual(self.deps, [])
        self.run_apply({**BASE, "requirements.txt": "pyyaml\npillow\n"})
        self.assertEqual(len(self.deps), 1)

    def test_zip_invalido_ou_de_outro_projeto(self):
        with self.assertRaises(at.UpdateError):
            at.apply(self.root, sha="x", fetch_zip=lambda: b"<html>bloqueado</html>", say=lambda *_: None)
        with self.assertRaises(at.UpdateError):
            at.apply(self.root, sha="x", fetch_zip=lambda: make_zip({"readme.txt": "oi"}), say=lambda *_: None)
        self.assertEqual((self.root / "assistente" / "x.py").read_text(), "v1")

    def test_recusa_caminho_fora_da_pasta(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../fora.txt", "x")
        with self.assertRaises(at.UpdateError):
            at.apply(self.root, sha="x", fetch_zip=lambda: buf.getvalue(), say=lambda *_: None)
        self.assertFalse((self.root.parent / "fora.txt").exists())

    def test_zip_sem_pasta_raiz(self):
        raw = make_zip(BASE | {"assistente/x.py": "v3"}, top="")
        at.apply(self.root, sha="s", fetch_zip=lambda: raw, install_deps=lambda r: "", say=lambda *_: None)
        self.assertEqual((self.root / "assistente" / "x.py").read_text(), "v3")


class CheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = 0
        self.now = 1000.0

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self):
        self.calls += 1
        return {"sha": "f" * 40, "mensagem": "feat: algo", "data": "2026-11-11T10:00:00Z"}

    def checker(self):
        return at.Checker(self.root, fetch=self.fetch, clock=lambda: self.now)

    def test_versao_desconhecida_pode_atualizar(self):
        r = self.checker().check()
        self.assertTrue(r["desconhecida"])
        self.assertFalse(r["nova"])
        self.assertEqual(r["ultima"], "fffffff")

    def test_detecta_versao_nova_e_atual(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "versao.json").write_text(json.dumps({"sha": "a" * 40}))
        self.assertTrue(self.checker().check()["nova"])
        (self.root / "data" / "versao.json").write_text(json.dumps({"sha": "f" * 40}))
        r = self.checker().check()
        self.assertFalse(r["nova"])
        self.assertFalse(r["desconhecida"])

    def test_cache_de_6_horas_e_forcar(self):
        c = self.checker()
        c.check()
        c.check()
        self.assertEqual(self.calls, 1)
        c.check(force=True)
        self.assertEqual(self.calls, 2)
        self.now += at.CACHE_SECONDS + 1
        c.check()
        self.assertEqual(self.calls, 3)

    def test_sem_internet_da_erro_legivel(self):
        def boom():
            raise at.UpdateError("Sem conexão com o GitHub agora.")
        with self.assertRaises(at.UpdateError):
            at.Checker(self.root, fetch=boom).check()


class CliTest(unittest.TestCase):
    def test_main_usa_a_pasta_do_projeto(self):
        old = os.getcwd()
        orig = at.apply
        seen = {}
        at.apply = lambda *a, **k: seen.update(cwd=os.getcwd()) or {"arquivos": 1, "dependencias": False, "config_anterior": False,
                                                                     "erro_dependencias": ""}
        try:
            self.assertEqual(at.main(), 0)
        finally:
            at.apply = orig
            os.chdir(old)
        self.assertEqual(Path(seen["cwd"]).resolve(), at.ROOT.resolve())


if __name__ == "__main__":
    unittest.main()
