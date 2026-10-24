import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.nucleo import permissions as perm  # noqa: E402


class PermissionsTest(unittest.TestCase):
    def test_todo_perfil_so_tem_categorias_conhecidas(self):
        for name, cats in perm.PROFILES.items():
            self.assertFalse(set(cats) - set(perm.CATEGORIES), name)

    def test_perfis_sao_progressivos(self):
        leitura, projeto, total = (set(perm.PROFILES[n]) for n in ("leitura", "projeto", "total"))
        self.assertLess(leitura, projeto)
        self.assertLess(projeto, total)
        self.assertNotIn("entrada", projeto)
        self.assertNotIn("tela", projeto)
        self.assertNotIn("comandos", leitura)

    def test_chat_risco_baixo_roda_direto(self):
        p = perm.Policy()
        for cat in ("memoria", "midia", "ler_arquivos", "email_agenda", "projeto_ler"):
            self.assertEqual(p.decide(cat, "chat"), "allow", cat)

    def test_chat_risco_medio_e_alto_perguntam(self):
        p = perm.Policy()
        for cat in ("abrir", "projeto_escrever", "comandos", "git_push", "tela", "entrada"):
            self.assertEqual(p.decide(cat, "chat"), "ask", cat)

    def test_lista_de_confianca_so_vale_para_risco_medio(self):
        p = perm.Policy({"pc": {"confiar_sem_perguntar": ["abrir", "entrada", "comandos", "tela", "git_push", "banana"]}})
        self.assertEqual(p.decide("abrir", "chat"), "allow")
        for cat in ("entrada", "comandos", "tela", "git_push"):
            self.assertEqual(p.decide(cat, "chat"), "ask", cat)
        self.assertEqual(p.trusted, {"abrir"})

    def test_janela_temporaria_libera_tudo_ate_expirar(self):
        now = [1000.0]
        p = perm.Policy({"pc": {"janela_de_permissao_minutos": 5}}, clock=lambda: now[0])
        until = p.new_window()
        self.assertEqual(until, 1300.0)
        self.assertEqual(p.decide("entrada", "chat", window_until=until), "allow")
        now[0] = 1301.0
        self.assertEqual(p.decide("entrada", "chat", window_until=until), "ask")

    def test_tarefa_roda_so_o_que_o_perfil_concede(self):
        p = perm.Policy()
        granted = perm.grants_for("projeto")
        self.assertEqual(p.decide("comandos", "task", granted), "allow")
        self.assertEqual(p.decide("projeto_escrever", "task", granted), "allow")
        self.assertEqual(p.decide("entrada", "task", granted), "ask")
        self.assertEqual(p.decide("tela", "task", granted), "ask")

    def test_modo_autonomo_libera_tudo_menos_regra(self):
        p = perm.Policy({"pc": {"modo_autonomo": True}})
        for cat in ("abrir", "projeto_escrever", "comandos", "git_push", "tela", "entrada"):
            self.assertEqual(p.decide(cat, "chat"), "allow", cat)
            self.assertEqual(p.decide(cat, "task", set()), "allow", cat)
        self.assertEqual(p.decide("regra", "chat"), "ask")
        self.assertEqual(p.decide("regra", "task", perm.grants_for("total")), "ask")

    def test_modo_autonomo_muda_sem_reabrir(self):
        cfg = {"pc": {"modo_autonomo": False}}
        p = perm.Policy(cfg)
        self.assertEqual(p.decide("tela", "chat"), "ask")
        cfg["pc"]["modo_autonomo"] = True
        self.assertEqual(p.decide("tela", "chat"), "allow")

    def test_sem_modo_autonomo_regra_tambem_pergunta(self):
        self.assertEqual(perm.Policy().decide("regra", "chat"), "ask")

    def test_tarefa_sem_concessao_pergunta_ate_para_risco_baixo(self):
        self.assertEqual(perm.Policy().decide("midia", "task", set()), "ask")

    def test_planejar_sempre_pode(self):
        p = perm.Policy()
        self.assertEqual(p.decide("tarefa", "task", set()), "allow")
        self.assertEqual(p.decide("tarefa", "chat"), "allow")

    def test_categoria_desconhecida_pede_aprovacao(self):
        self.assertEqual(perm.Policy().decide("inventada", "chat"), "ask")
        self.assertEqual(perm.Policy().decide("inventada", "task", {"inventada"}), "ask")

    def test_grants_por_lista_e_erros(self):
        self.assertEqual(perm.grants_for(["abrir"]), {"abrir", "tarefa"})
        with self.assertRaises(ValueError):
            perm.grants_for("super")
        with self.assertRaises(ValueError):
            perm.grants_for(["abrir", "root"])


if __name__ == "__main__":
    unittest.main()
