import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.nucleo import activity  # noqa: E402
from assistente.servicos import tracking  # noqa: E402


def ev(t, text, place=""):
    return {"time_iso": t, "description": text, "location": place}


def accepted(status, *events):
    return {"code": 0, "data": {"accepted": [{"number": "X", "track_info": {
        "latest_status": {"status": status},
        "tracking": {"providers": [{"provider": {"name": "Correios"}, "events": list(events)}]}}}], "rejected": []}}


class FakeProvider:
    configured = True

    def __init__(self):
        self.results = []
        self.calls = 0

    def fetch(self, code):
        self.calls += 1
        r = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(r, Exception):
            raise r
        return r


def res(status, *events):
    return tracking.parse_info(accepted(status, *events)["data"]["accepted"][0])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        activity.configure({})
        self.t = [1000.0]
        self.p = FakeProvider()
        self.ups = []
        self.tr = tracking.Tracker({}, self.p, on_update=lambda i, text, kind="info": self.ups.append((text, kind)),
                                   clock=lambda: self.t[0])

    def tearDown(self):
        self.tr.stop()
        os.chdir(self.old)
        self.tmp.cleanup()

    def add(self, code="AA123456789BR", name="Fone"):
        return self.tr.add(code, name, check=False)


class ParseTest(unittest.TestCase):
    def test_codigo(self):
        self.assertEqual(tracking.valid_code(" aa123 456789br "), "AA123456789BR")
        for bad in ("", "ab", "a b;c", "x" * 50, "../../etc"):
            with self.assertRaises(ValueError):
                tracking.valid_code(bad)

    def test_parse_ordena_e_traduz(self):
        r = res("InTransit", ev("2026-10-20T10:00:00-03:00", "Objeto postado", "SÃO PAULO"),
                ev("2026-10-21T08:00:00-03:00", "Objeto em trânsito", "CURITIBA"))
        self.assertEqual(r["events"][0]["text"], "Objeto em trânsito")
        self.assertEqual(r["events"][0]["place"], "CURITIBA")
        self.assertEqual(r["carrier"], "Correios")

    def test_status_desconhecido_vira_em_transito(self):
        self.assertEqual(res("Qualquer")["status"], "InTransit")

    def test_endereco_como_dicionario(self):
        r = tracking.parse_info({"track_info": {"latest_status": {"status": "InTransit"}, "latest_event": {
            "time_iso": "2026-10-20T10:00:00Z", "description": "x", "address": {"city": "Recife", "state": "PE"}}}})
        self.assertEqual(r["events"][0]["place"], "Recife, PE")


class TrackerTest(Base):
    def test_adicionar_e_duplicado(self):
        i = self.add()
        self.assertEqual((i["code"], i["name"], i["status"]), ("AA123456789BR", "Fone", "Pending"))
        with self.assertRaises(ValueError):
            self.add("aa123456789br")
        self.assertEqual(len(self.tr.items()), 1)

    def test_primeira_consulta_nao_achou_avisa_uma_vez(self):
        i = self.add()
        self.p.results = [res("NotFound")]
        self.tr.check(i["id"], first=True)
        self.assertEqual(len(self.ups), 1)
        self.assertIn("Ainda não encontrei", self.ups[0][0])
        self.tr.check(i["id"])                    # de novo, nada mudou: não repete
        self.assertEqual(len(self.ups), 1)
        self.assertFalse(self.tr.get(i["id"])["found"])

    def test_achou_depois_avisa(self):
        i = self.add()
        self.p.results = [res("NotFound"), res("InTransit", ev("2026-10-21T08:00:00Z", "Objeto postado", "SP"))]
        self.tr.check(i["id"], first=True)
        self.t[0] += 3600
        item = self.tr.check(i["id"])
        self.assertTrue(item["found"])
        self.assertTrue(item["unread"])
        self.assertTrue(self.ups[-1][0].startswith("Encontrei!"))
        self.assertIn("Objeto postado", self.ups[-1][0])

    def test_novo_evento_avisa_e_sem_mudanca_nao(self):
        i = self.add()
        a = res("InTransit", ev("2026-10-21T08:00:00Z", "Postado", "SP"))
        b = res("InTransit", ev("2026-10-21T08:00:00Z", "Postado", "SP"), ev("2026-10-22T09:00:00Z", "Em trânsito", "PR"))
        self.p.results = [a, a, b]
        self.tr.check(i["id"], first=True)
        n = len(self.ups)
        self.tr.check(i["id"])
        self.assertEqual(len(self.ups), n)
        self.tr.check(i["id"])
        self.assertEqual(len(self.ups), n + 1)
        self.assertIn("Em trânsito", self.ups[-1][0])
        self.assertEqual(len(self.tr.get(i["id"])["updates"]), 2)

    def test_entregue_avisa_bom_e_para_de_consultar(self):
        i = self.add()
        self.p.results = [res("Delivered", ev("2026-10-22T09:00:00Z", "Entregue ao destinatário"))]
        self.tr.check(i["id"], first=True)
        self.assertEqual(self.ups[-1][1], "pronta")
        self.assertEqual(self.tr.active(), [])

    def test_erro_nao_derruba_e_nao_repete_aviso(self):
        i = self.add()
        self.p.results = [tracking.TrackingError("Sem conexão", "network")]
        item = self.tr.check(i["id"])
        self.assertEqual(item["error"], "Sem conexão")
        self.tr.check(i["id"])
        self.assertEqual([k for _t, k in self.ups], ["erro"])
        self.p.results = [res("InTransit", ev("2026-10-21T08:00:00Z", "Postado"))]
        self.assertEqual(self.tr.check(i["id"])["error"], "")

    def test_ler_remover_renomear(self):
        i = self.add()
        self.p.results = [res("InTransit", ev("2026-10-21T08:00:00Z", "Postado"))]
        self.tr.check(i["id"], first=True)
        self.assertEqual(self.tr.unread(), 1)
        self.tr.mark_read(i["id"])
        self.assertEqual(self.tr.unread(), 0)
        self.assertEqual(self.tr.rename(i["id"], "  Tênis  novo ")["name"], "Tênis novo")
        with self.assertRaises(ValueError):
            self.tr.rename(i["id"], " ")
        self.tr.remove(i["id"])
        with self.assertRaises(KeyError):
            self.tr.get(i["id"])
        with self.assertRaises(KeyError):
            self.tr.remove(i["id"])

    def test_check_all_e_proxima(self):
        a, b = self.add("AA111111111BR"), self.add("BB222222222BR")
        self.p.results = [res("InTransit", ev("2026-10-21T08:00:00Z", "x"))]
        self.assertEqual(self.tr.check_all(), 2)
        self.tr._next = None
        self.tr.run_now()
        self.assertEqual(self.tr._next, self.t[0] + 3600)

    def test_status_para_o_painel(self):
        st = self.tr.status()
        self.assertEqual(st["note"], "Nenhuma encomenda para acompanhar.")
        self.assertIsNone(st["next_ts"])
        self.add()
        self.tr.start()
        st = self.tr.status()
        self.assertEqual((st["next_ts"], st["can_run"], st["every"]), (1030.0, True, "a cada 60 min"))

    def test_sem_chave_nao_consulta(self):
        class NoKey(FakeProvider):
            configured = False

        tr = tracking.Tracker({}, NoKey(), clock=lambda: self.t[0])
        self.add()
        tr.run_now()
        self.assertEqual(tr.provider.calls, 0)
        self.assertIn("chave", tr.status()["note"])

    def test_intervalo_minimo(self):
        self.assertEqual(tracking.Tracker({"rastreio": {"verificar_a_cada_minutos": 1}}, self.p).interval, 900)

    def test_persiste_e_arquivo_corrompido(self):
        self.add()
        self.assertEqual(len(tracking.Tracker({}, self.p).items()), 1)
        tracking.FILE.write_text("{ruim")
        self.assertEqual(tracking.Tracker({}, self.p).items(), [])


class Track17Test(unittest.TestCase):
    def make(self, responses, key="k"):
        calls = []

        def post(path, body, k):
            calls.append((path, body, k))
            return responses[path] if not isinstance(responses[path], list) else responses[path].pop(0)

        return tracking.Track17(lambda: key, post), calls

    def test_sem_chave(self):
        t, _ = self.make({}, key="")
        with self.assertRaises(tracking.TrackingError) as c:
            t.fetch("AA123456789BR")
        self.assertEqual(c.exception.kind, "key")

    def test_registra_e_consulta(self):
        t, calls = self.make({"register": {"code": 0, "data": {"accepted": [{}], "rejected": []}},
                              "gettrackinfo": accepted("InTransit", ev("2026-10-21T08:00:00Z", "Postado", "SP"))})
        r = t.fetch("AA123456789BR")
        self.assertEqual(r["status"], "InTransit")
        self.assertEqual([c[0] for c in calls], ["register", "gettrackinfo"])
        self.assertEqual(calls[0][1], [{"number": "AA123456789BR"}])
        self.assertEqual(calls[0][2], "k")

    def test_ja_cadastrado_segue(self):
        t, _ = self.make({"register": {"code": 0, "data": {"rejected": [{"number": "X", "error": {"code": -18019901}}]}},
                          "gettrackinfo": accepted("Delivered", ev("2026-10-21T08:00:00Z", "Entregue"))})
        self.assertEqual(t.fetch("X")["status"], "Delivered")

    def test_sem_dados_ainda_vira_nao_encontrado(self):
        t, _ = self.make({"register": {"code": 0, "data": {"rejected": []}},
                          "gettrackinfo": {"code": 0, "data": {"accepted": [], "rejected": [{"error": {"code": -18019909}}]}}})
        r = t.fetch("X")
        self.assertEqual(r["status"], "NotFound")
        self.assertTrue(r["note"])

    def test_cota_acabou(self):
        t, _ = self.make({"register": {"code": 0, "data": {"rejected": [{"error": {"code": -18019908}}]}}})
        with self.assertRaises(tracking.TrackingError) as c:
            t.fetch("X")
        self.assertEqual(c.exception.kind, "quota")

    def test_transportadora_nao_reconhecida(self):
        t, _ = self.make({"register": {"code": 0, "data": {"rejected": [{"error": {"code": -18019903}}]}}})
        self.assertEqual(t.fetch("X")["status"], "NotFound")

    def test_chave_invalida(self):
        t, _ = self.make({"register": {"code": -18010002}})
        with self.assertRaises(tracking.TrackingError) as c:
            t.fetch("X")
        self.assertEqual(c.exception.kind, "key")


if __name__ == "__main__":
    unittest.main()
