import os
import tempfile
import unittest

from assistente.nucleo import atalhos


class AtalhosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_criar_listar_apagar(self):
        a = atalhos.create("/Standup", "Resuma o que fiz ontem: {}")
        self.assertEqual(a["nome"], "standup")
        self.assertEqual([x["nome"] for x in atalhos.all_shortcuts()], ["standup"])
        atalhos.delete(a["id"])
        self.assertEqual(atalhos.all_shortcuts(), [])

    def test_validacoes(self):
        for nome, texto in [("a", "texto ok"), ("tem espaco", "texto ok"), ("debate", "texto ok"), ("ok", "x")]:
            with self.assertRaises(atalhos.ShortcutError, msg=nome):
                atalhos.create(nome, texto)
        atalhos.create("ok", "texto ok")
        with self.assertRaises(atalhos.ShortcutError):
            atalhos.create("ok", "outro texto")
        with self.assertRaises(atalhos.ShortcutError):
            atalhos.delete("../x")
        with self.assertRaises(atalhos.ShortcutError):
            atalhos.delete("00000000")

    def test_expandir(self):
        self.assertEqual(atalhos.expand("Resuma: {}", " o texto "), "Resuma: o texto")
        self.assertEqual(atalhos.expand("Bom dia", "equipe"), "Bom dia equipe")
        self.assertEqual(atalhos.expand("Bom dia", ""), "Bom dia")
