import tempfile
import unittest
from pathlib import Path

from assistente.nucleo import sessoes as ss


class SessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "s.json"
        self.now = 1_000_000.0
        self.s = ss.Sessions(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cria_e_verifica(self):
        c = self.s.create("iPhone", "1.2.3.4")
        self.assertIsNotNone(self.s.verify(c))
        self.assertIsNone(self.s.verify(c + "x"))
        self.assertIsNone(self.s.verify(""))
        self.assertIsNone(self.s.verify("abc"))

    def test_so_o_hash_vai_para_o_disco(self):
        c = self.s.create("iPhone", "1.2.3.4")
        self.assertNotIn(c.split(".", 1)[1], self.path.read_text())

    def test_persistencia(self):
        c = self.s.create("Mac", "ip")
        again = ss.Sessions(self.path, clock=lambda: self.now)
        self.assertIsNotNone(again.verify(c))

    def test_expira_sem_uso(self):
        c = self.s.create("Mac", "ip")
        self.now += ss.MAX_AGE + 5
        self.assertIsNone(self.s.verify(c))
        self.assertEqual(self.s.listing(), [])

    def test_uso_renova_o_visto(self):
        c = self.s.create("Mac", "ip")
        self.now += ss.MAX_AGE - 10
        self.assertIsNotNone(self.s.verify(c))
        self.now += ss.MAX_AGE - 10
        self.assertIsNotNone(self.s.verify(c))

    def test_revogar(self):
        a, b = self.s.create("A", "ip"), self.s.create("B", "ip")
        sid = self.s.verify(a)
        self.assertTrue(self.s.revoke(sid))
        self.assertFalse(self.s.revoke(sid))
        self.assertIsNone(self.s.verify(a))
        self.assertIsNotNone(self.s.verify(b))

    def test_limite_de_sessoes_mantem_as_mais_recentes(self):
        cookies = []
        for i in range(ss.MAX_SESSIONS + 3):
            self.now += 10
            cookies.append(self.s.create(f"d{i}", "ip"))
        self.assertEqual(len(self.s.listing()), ss.MAX_SESSIONS)
        self.assertIsNone(self.s.verify(cookies[0]))
        self.assertIsNotNone(self.s.verify(cookies[-1]))

    def test_nome_do_aparelho(self):
        self.assertEqual(ss.device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1"), "iPhone · Safari")
        self.assertEqual(ss.device_name("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120"), "Windows · Edge")
        self.assertEqual(ss.device_name(""), "Aparelho")


class AuditTest(unittest.TestCase):
    def test_registra_lista_e_apara(self):
        with tempfile.TemporaryDirectory() as d:
            a = ss.Audit(Path(d) / "a.jsonl")
            a.log("entrada", "x", "1.1.1.1", "iPhone")
            a.log("foto_da_tela", "y")
            r = a.recent()
            self.assertEqual([x["evento"] for x in r], ["foto_da_tela", "entrada"])
            for i in range(ss.AUDIT_MAX + 5):
                a.log("e", str(i))
            self.assertLessEqual(len((Path(d) / "a.jsonl").read_text().splitlines()), ss.AUDIT_MAX)
            self.assertEqual(a.recent(1)[0]["detalhe"], str(ss.AUDIT_MAX + 4))

    def test_arquivo_ilegivel_nao_quebra(self):
        with tempfile.TemporaryDirectory() as d:
            a = ss.Audit(Path(d) / "naoexiste" / "a.jsonl")
            self.assertEqual(a.recent(), [])


if __name__ == "__main__":
    unittest.main()
