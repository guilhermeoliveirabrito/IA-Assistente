import os
import unittest

from assistente.servicos import diagnostico as dg


def estado(res, id_):
    return next(i for i in res["itens"] if i["id"] == id_)["estado"]


class DiagnosticoTest(unittest.TestCase):
    def setUp(self):
        self.key = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("GEMINI_API_KEY", None)
        if self.key:
            os.environ["GEMINI_API_KEY"] = self.key

    def run_all(self, cfg=None, **kw):
        kw.setdefault("addresses", lambda: ["192.168.0.5"])
        kw.setdefault("grab", lambda w: b"x" * 2048)
        kw.setdefault("devices", lambda: [{"name": "Mic", "max_input_channels": 1}])
        return dg.run(cfg or {}, **kw)

    def test_estrutura_e_resumo(self):
        res = self.run_all()
        ids = [i["id"] for i in res["itens"]]
        for esperado in ("python", "pacotes", "gemini", "tela", "microfone", "voz", "rede", "ntfy", "pastas", "versao"):
            self.assertIn(esperado, ids)
        self.assertEqual(sum(res["resumo"].values()), len(res["itens"]))
        for i in res["itens"]:
            self.assertIn(i["estado"], ("ok", "aviso", "erro", "info"))

    def test_sem_chave_do_gemini_e_erro_com_dica(self):
        res = self.run_all()
        item = next(i for i in res["itens"] if i["id"] == "gemini")
        if item["estado"] == "erro":
            self.assertIn("aistudio", item["dica"])
            self.assertFalse(res["ok"])

    def test_com_chave_ok(self):
        os.environ["GEMINI_API_KEY"] = "abc"
        self.assertEqual(estado(self.run_all(), "gemini"), "ok")

    def test_nao_mostra_a_chave(self):
        os.environ["GEMINI_API_KEY"] = "SEGREDO-123"
        self.assertNotIn("SEGREDO-123", str(self.run_all()))

    def test_tela_falha_vira_erro_legivel(self):
        def boom(w):
            raise RuntimeError("sem display")
        item = next(i for i in self.run_all(grab=boom)["itens"] if i["id"] == "tela")
        self.assertEqual(item["estado"], "erro")
        self.assertIn("sem display", item["detalhe"])

    def test_microfone_ausente_avisa(self):
        res = self.run_all(devices=lambda: [{"name": "Alto-falante", "max_input_channels": 0}])
        self.assertIn(estado(res, "microfone"), ("aviso", "info"))

    def test_rede_sem_tailscale_avisa_sobre_http(self):
        item = next(i for i in self.run_all({"app": {"acesso": "rede", "porta": 8765}})["itens"] if i["id"] == "rede")
        self.assertEqual(item["estado"], "aviso")
        self.assertIn("http://192.168.0.5:8765", item["detalhe"])
        self.assertIn("Tailscale", item["dica"])

    def test_rede_com_tailscale_ok(self):
        res = self.run_all({"app": {"acesso": "rede", "porta": 8765}}, addresses=lambda: ["100.64.0.2"])
        self.assertEqual(estado(res, "rede"), "ok")

    def test_rede_local_e_informativo(self):
        self.assertEqual(estado(self.run_all({"app": {"acesso": "local"}}), "rede"), "info")

    def test_uma_verificacao_quebrada_nao_derruba_as_outras(self):
        orig = dg.check_fala
        dg.check_fala = lambda: 1 / 0
        try:
            res = self.run_all()
        finally:
            dg.check_fala = orig
        self.assertEqual(estado(res, "fala"), "erro")
        self.assertEqual(estado(res, "python"), "ok")

    def test_teste_de_conexao_so_quando_pedido(self):
        calls = []
        self.assertNotIn("conexao", [i["id"] for i in self.run_all(ping=lambda: calls.append(1))["itens"]])
        self.assertEqual(calls, [])
        res = self.run_all(deep=True, ping=lambda: calls.append(1))
        self.assertEqual(estado(res, "conexao"), "ok")
        self.assertEqual(calls, [1])

    def test_conexao_com_erro(self):
        def boom():
            raise RuntimeError("401 chave inválida")
        res = self.run_all(deep=True, ping=boom)
        self.assertEqual(estado(res, "conexao"), "erro")
        self.assertIn("401", next(i for i in res["itens"] if i["id"] == "conexao")["detalhe"])


if __name__ == "__main__":
    unittest.main()
