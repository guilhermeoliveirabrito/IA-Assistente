import base64
import os
import tempfile
import unittest
from pathlib import Path

from assistente.nucleo import storage


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
        storage.new_conversation("B")
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


class BuscaEExportacaoTest(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        import os

        os.chdir(self.old)
        self.tmp.cleanup()

    def conv(self, title, *msgs):
        c = storage.new_conversation(title)
        c["messages"] = [{"role": r, "text": t} for r, t in msgs]
        storage.save(c)
        return c


    def test_indice_acompanha_edicao_e_exclusao(self):
        c = storage.new_conversation("Viagem")
        c["messages"].append({"role": "user", "text": "quero ver o Pão de Açúcar"})
        storage.save(c)
        self.assertEqual([r["id"] for r in storage.search("pao de acucar")], [c["id"]])
        self.assertEqual(storage.list_all()[0]["count"], 1)
        c["messages"].append({"role": "model", "text": "Machu Picchu é lindo"})
        storage.save(c)
        self.assertEqual([r["id"] for r in storage.search("machu")], [c["id"]])
        self.assertEqual(storage.list_all()[0]["count"], 2)
        storage.delete(c["id"])
        self.assertEqual(storage.search("machu"), [])
        self.assertEqual(storage.list_all(), [])
    def test_busca_ignora_acento_e_maiuscula_e_mostra_trecho(self):
        a = self.conv("Viagem", ("user", "Quero ir para São Paulo em dezembro"), ("assistant", "Boa ideia"))
        self.conv("Outra", ("user", "nada a ver"))
        r = storage.search("SAO PAULO")
        self.assertEqual([x["id"] for x in r], [a["id"]])
        self.assertIn("São Paulo", r[0]["trecho"])
        self.assertEqual(storage.search("viagem")[0]["trecho"], "")           # achou pelo título
        self.assertEqual(storage.search("x"), [])                            # curto demais
        self.assertEqual(storage.search("inexistente"), [])

    def test_exportar_markdown(self):
        c = self.conv("Plano", ("user", "oi"), ("assistant", "olá **mundo**"))
        c["messages"][1]["tools"] = [{"summary": "Abrir o Spotify"}]
        md = storage.to_markdown(c)
        for trecho in ("# Plano", "## Você", "oi", "## Assistente", "olá **mundo**", "Abrir o Spotify"):
            self.assertIn(trecho, md)


class FixarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_fixadas_ficam_no_topo_sem_mudar_a_data(self):
        a = storage.new_conversation("Antiga")
        b = storage.new_conversation("Nova")
        b["messages"].append({"role": "user", "text": "x"})
        storage.save(b)
        self.assertEqual([c["title"] for c in storage.list_all()], ["Nova", "Antiga"])
        before = storage.load(a["id"])["updated"]
        storage.set_pinned(a["id"], True)
        self.assertEqual(storage.load(a["id"])["updated"], before)
        lst = storage.list_all()
        self.assertEqual([c["title"] for c in lst], ["Antiga", "Nova"])
        self.assertTrue(lst[0]["pinned"])
        storage.set_pinned(a["id"], False)
        self.assertEqual([c["title"] for c in storage.list_all()], ["Nova", "Antiga"])
