import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.nucleo import activity  # noqa: E402

DAY = 86400


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        activity.configure({})
        activity._last_prune = time.time()  # evita limpeza automática atrapalhar os testes

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_registra_e_lista_mais_novo_primeiro(self):
        activity.log("plano", "primeiro", task="t1")
        activity.log("acao", "segundo", task="t1")
        ev = activity.recent()
        self.assertEqual([e["text"] for e in ev], ["segundo", "primeiro"])

    def test_filtros(self):
        activity.log("acao", "a", task="t1")
        activity.log("erro", "b", task="t2")
        self.assertEqual(len(activity.recent(task="t1")), 1)
        self.assertEqual(activity.recent(kinds={"erro"})[0]["text"], "b")
        self.assertEqual(len(activity.recent(limit=1)), 1)

    def test_tipo_desconhecido_vira_info(self):
        self.assertEqual(activity.log("banana", "x")["kind"], "info")

    def test_dados_extras_e_texto_truncado(self):
        e = activity.log("acao", "x" * 5000, ferramenta="abrir_site")
        self.assertEqual(len(e["text"]), activity.MAX_TEXT)
        self.assertEqual(e["data"]["ferramenta"], "abrir_site")

    def test_apaga_sozinho_eventos_vencidos(self):
        now = time.time()
        activity.log("info", "velho", now=now - 10 * DAY)
        activity.log("info", "recente", now=now - 1 * DAY)
        removed = activity.prune(now)
        self.assertEqual(removed, 1)
        self.assertEqual([e["text"] for e in activity.recent()], ["recente"])

    def test_retencao_vem_do_config(self):
        activity.configure({"historico": {"dias_de_retencao": 1}})
        now = time.time()
        activity.log("info", "dois dias", now=now - 2 * DAY)
        activity.log("info", "agora", now=now)
        activity.prune(now)
        self.assertEqual([e["text"] for e in activity.recent()], ["agora"])

    def test_limpeza_automatica_ao_registrar(self):
        now = time.time()
        activity._last_prune = 0  # força a limpeza no próximo log
        activity.log("info", "velho", now=now - 30 * DAY)
        activity.log("info", "novo", now=now)
        self.assertEqual([e["text"] for e in activity.recent()], ["novo"])

    def test_teto_de_eventos(self):
        activity.configure({"historico": {"maximo_de_eventos": 3}})
        now = time.time()
        for i in range(6):
            activity.log("info", f"e{i}", now=now + i)
        activity.prune(now + 10)
        self.assertEqual([e["text"] for e in activity.recent()], ["e5", "e4", "e3"])

    def test_linha_corrompida_e_ignorada(self):
        activity.log("info", "ok")
        with activity.FILE.open("a", encoding="utf-8") as f:
            f.write("{quebrada\n")
        self.assertEqual(len(activity.recent()), 1)

    def test_limpar_tudo(self):
        activity.log("info", "x")
        activity.clear()
        self.assertEqual(activity.recent(), [])


if __name__ == "__main__":
    unittest.main()
