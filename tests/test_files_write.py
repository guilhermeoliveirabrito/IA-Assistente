import os
import tempfile
import unittest
from pathlib import Path

from assistente.nucleo import permissions as perm
from assistente.pc import files
from assistente.pc import pc_control as pc


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.out, self.other = self.root / "saida", self.root / "docs"
        self.other.mkdir()
        self.cfg = {"arquivos": {"pasta_de_saida": str(self.out), "pastas_permitidas": [str(self.other)]}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_relativo_cai_na_pasta_de_saida_e_cria_subpastas(self):
        r = files.write_text(self.cfg, "notas/ideias.md", "# oi")
        self.assertEqual(Path(r["arquivo"]), self.out / "notas" / "ideias.md")
        self.assertEqual((self.out / "notas" / "ideias.md").read_text(encoding="utf-8"), "# oi")

    def test_criar_nao_sobrescreve_substituir_guarda_backup_acrescentar_soma(self):
        files.write_text(self.cfg, "a.txt", "um")
        with self.assertRaises(files.FileAccessError):
            files.write_text(self.cfg, "a.txt", "dois")
        r = files.write_text(self.cfg, "a.txt", "dois", "substituir")
        self.assertEqual((self.out / "a.txt.bak").read_text(), "um")
        self.assertEqual(r["modo"], "substituir")
        files.write_text(self.cfg, "a.txt", "+tres", "acrescentar")
        self.assertEqual((self.out / "a.txt").read_text(), "dois+tres")

    def test_acentos_e_quebras_de_linha_intactos(self):
        files.write_text(self.cfg, "b.txt", "coração\nlinha2\n")
        self.assertEqual((self.out / "b.txt").read_bytes(), "coração\nlinha2\n".encode())

    def test_nunca_sai_das_pastas_autorizadas(self):
        for bad in ("../fora.txt", str(self.root / "fora.txt"), "/etc/passwd.txt", "a/../../x.txt"):
            with self.assertRaises(files.FileAccessError, msg=bad):
                files.write_text(self.cfg, bad, "x")
        self.assertFalse((self.root / "fora.txt").exists())
        files.write_text(self.cfg, str(self.other / "ok.txt"), "x")                 # pasta autorizada: pode

    def test_symlink_para_fora_e_barrado(self):
        self.out.mkdir()
        outside = self.root / "alvo"
        outside.mkdir()
        os.symlink(outside, self.out / "atalho")
        with self.assertRaises(files.FileAccessError):
            files.write_text(self.cfg, "atalho/x.txt", "x")

    def test_extensoes_perigosas_e_limites(self):
        for bad in ("a.bat", "a.exe", "a.ps1", "a.lnk", "a.sh", "semextensao", "a.py.exe"):
            with self.assertRaises(files.FileAccessError, msg=bad):
                files.write_text(self.cfg, bad, "x")
        with self.assertRaises(files.FileAccessError):
            files.write_text(self.cfg, "grande.txt", "x" * (files.MAX_WRITE_BYTES + 1))
        with self.assertRaises(files.FileAccessError):
            files.write_text(self.cfg, "a.txt", "x", "apagar")
        self.out.mkdir(exist_ok=True)
        (self.out / "pasta.txt").mkdir()
        with self.assertRaises(files.FileAccessError):
            files.write_text(self.cfg, "pasta.txt", "x", "substituir")

    def test_pasta_de_saida_tambem_pode_ser_lida(self):
        self.assertIn(str(self.out), files.readable_dirs(self.cfg))
        files.write_text(self.cfg, "r.txt", "lido")
        self.assertEqual(files.read_text(files.resolve_allowed("r.txt", files.readable_dirs(self.cfg))), "lido")


class PermissaoTest(unittest.TestCase):
    def test_chave_de_ajustes_libera_gravar_sem_perguntar(self):
        cfg = {"arquivos": {}, "pc": {"modo_autonomo": False}}
        p = perm.Policy(cfg)
        self.assertEqual(p.decide("arquivos_escrever", "chat"), "ask")
        self.assertEqual(p.decide("arquivos_escrever", "task", granted=[]), "ask")
        cfg["arquivos"]["gravar_sem_perguntar"] = True                               # vale na hora, sem reabrir
        self.assertEqual(p.decide("arquivos_escrever", "chat"), "allow")
        self.assertEqual(p.decide("arquivos_escrever", "task", granted=[]), "allow")
        self.assertEqual(p.decide("comandos", "chat"), "ask")                        # só vale para gravar arquivos

    def test_perfis(self):
        self.assertNotIn("arquivos_escrever", perm.PROFILES["leitura"])
        self.assertIn("arquivos_escrever", perm.PROFILES["projeto"])


class ClipboardTest(unittest.TestCase):
    def setUp(self):
        self.saved = (pc._run, pc._platform)
        self.calls = []
        pc._platform = "win32"

        class R:
            returncode, stdout = 0, "olá mundo\r\n".encode()
        self.R = R
        pc._run = lambda args, **kw: (self.calls.append((args, kw)), self.R)[1]

    def tearDown(self):
        pc._run, pc._platform = self.saved

    def test_ler(self):
        self.assertEqual(pc.clipboard_get(), "olá mundo")
        self.assertIn("Get-Clipboard", self.calls[0][0][-1])

    def test_escrever_manda_utf8_pela_entrada_padrao(self):
        r = pc.clipboard_set("coração")
        self.assertEqual(self.calls[0][1]["input"], "coração".encode())
        self.assertEqual(r["caracteres"], 7)
        self.assertNotIn("coração", " ".join(self.calls[0][0]))                     # o texto nunca vai na linha de comando

    def test_falha_e_limite(self):
        self.R.returncode = 1
        with self.assertRaises(pc.PCError):
            pc.clipboard_set("x")
        with self.assertRaises(pc.PCError):
            pc.clipboard_set("x" * 100001)


if __name__ == "__main__":
    unittest.main()
