import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import storage  # noqa: E402


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_criar_salvar_carregar(self):
        c = storage.new_conversation()
        c["messages"].append({"role": "user", "text": "oi"})
        storage.save(c)
        again = storage.load(c["id"])
        self.assertEqual(again["messages"][0]["text"], "oi")

    def test_lista_mais_recente_primeiro(self):
        a = storage.new_conversation("A")
        b = storage.new_conversation("B")
        a["messages"].append({"role": "user", "text": "x"})
        storage.save(a)  # A fica mais recente
        self.assertEqual([i["title"] for i in storage.list_all()], ["A", "B"])

    def test_renomear_e_apagar_remove_anexos(self):
        c = storage.new_conversation()
        storage.save_upload(c["id"], "a.txt", b"x")
        storage.rename(c["id"], "Novo nome")
        self.assertEqual(storage.load(c["id"])["title"], "Novo nome")
        storage.delete(c["id"])
        self.assertEqual(storage.list_all(), [])
        self.assertFalse((Path("data/uploads") / c["id"]).exists())

    def test_id_malicioso_e_recusado(self):
        for bad in ("../../etc/passwd", "abc", "", None, "ZZZZZZZZZZZZ"):
            with self.assertRaises(KeyError):
                storage.load(bad)
        with self.assertRaises(KeyError):
            storage.delete("../x")

    def test_conversa_inexistente(self):
        with self.assertRaises(KeyError):
            storage.load("0" * 12)

    def test_titulo(self):
        self.assertEqual(storage.make_title("  oi   tudo  bem "), "oi tudo bem")
        self.assertEqual(storage.make_title(""), "Nova conversa")
        self.assertTrue(storage.make_title("a" * 100).endswith("…"))
        self.assertLessEqual(len(storage.make_title("a" * 100)), 48)

    def test_nome_de_arquivo_seguro(self):
        self.assertEqual(storage.safe_filename("../../x/relatório final.pdf"), "relatório final.pdf")
        self.assertEqual(storage.safe_filename("a<b>c|d.txt"), "a_b_c_d.txt")
        self.assertEqual(storage.safe_filename(""), "arquivo")

    def test_upload_grande_demais(self):
        c = storage.new_conversation()
        with self.assertRaises(ValueError):
            storage.save_upload(c["id"], "g.bin", b"x" * (storage.MAX_UPLOAD_BYTES + 1))

    def test_resolve_contents_vira_inline(self):
        c = storage.new_conversation()
        stored = storage.save_upload(c["id"], "foto.png", b"\x89PNG")
        contents = [{"role": "user", "parts": [{"x_file": stored, "x_name": "foto.png", "mimeType": "image/png"},
                                                {"text": "o que é isto?"}]}]
        out = storage.resolve_contents(c["id"], contents)
        inline = out[0]["parts"][0]["inlineData"]
        self.assertEqual(inline["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(inline["data"]), b"\x89PNG")
        self.assertIn("x_file", contents[0]["parts"][0])  # original intacto

    def test_resolve_contents_descarta_os_mais_antigos_quando_passa_do_limite(self):
        c = storage.new_conversation()
        old = storage.save_upload(c["id"], "velho.pdf", b"a" * 600)
        new = storage.save_upload(c["id"], "novo.pdf", b"b" * 600)
        contents = [
            {"role": "user", "parts": [{"x_file": old, "x_name": "velho.pdf", "mimeType": "application/pdf"}]},
            {"role": "user", "parts": [{"x_file": new, "x_name": "novo.pdf", "mimeType": "application/pdf"}]},
        ]
        out = storage.resolve_contents(c["id"], contents, max_bytes=1000)
        self.assertIn("não está mais disponível", out[0]["parts"][0]["text"])
        self.assertIn("inlineData", out[1]["parts"][0])

    def test_anexo_sumiu_do_disco(self):
        c = storage.new_conversation()
        contents = [{"role": "user", "parts": [{"x_file": "nao_existe.png", "mimeType": "image/png"}]}]
        out = storage.resolve_contents(c["id"], contents)
        self.assertIn("não está mais disponível", out[0]["parts"][0]["text"])


if __name__ == "__main__":
    unittest.main()
