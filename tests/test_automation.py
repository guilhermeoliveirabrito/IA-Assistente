import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.nucleo import activity  # noqa: E402
from assistente.servicos import automation  # noqa: E402


class AutomationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        activity.configure({})

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_sem_login_do_google_fica_quieta(self):
        a = automation.Automation({"automatico": {}})
        self.assertFalse(a.start())
        a.stop()

    def test_erro_na_rotina_vai_para_o_historico_e_nao_derruba(self):
        from assistente.integracoes import triage

        original = triage.digest
        triage.digest = lambda cfg: (_ for _ in ()).throw(RuntimeError("sem internet"))
        try:
            automation.job_digest({})
        finally:
            triage.digest = original
        events = activity.recent(10)
        self.assertTrue(any(e["kind"] == "erro" and "sem internet" in e["text"] for e in events))

    def test_resumo_salva_relatorio(self):
        from assistente.integracoes import triage

        original = triage.digest
        triage.digest = lambda cfg: "tudo certo"
        try:
            automation.job_digest({})
        finally:
            triage.digest = original
        self.assertTrue(list(Path("data").glob("resumo_*.txt")))


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        activity.configure({})
        Path("token.json").write_text("{}")
        self.t = [1000.0]
        self.events = []
        self.a = automation.Automation({"automatico": {"triagem_a_cada_minutos": 15}}, lambda: self.events.append(1),
                                       clock=lambda: self.t[0])

    def tearDown(self):
        self.a.stop()
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_status_antes_de_ligar(self):
        st = self.a.status()
        self.assertFalse(st["running"])
        self.assertTrue(st["connected"])
        self.assertTrue(all(j["next_ts"] is None for j in st["jobs"]))

    def test_contagem_e_resultado_da_triagem(self):
        self.a.JOBS = {**self.a.JOBS, "triagem": ("Triagem", lambda cfg: (True, "2 e-mail(s) novo(s)"))}
        self.a._thread = type("T", (), {"is_alive": lambda s: True})()
        self.a._next_triage = 1020.0
        self.assertEqual(self.a.status()["jobs"][0]["next_ts"], 1020.0)
        self.t[0] = 1100.0
        self.assertTrue(self.a.run_job("triagem"))
        j = self.a.status()["jobs"][0]
        self.assertEqual((j["last_ts"], j["last_ok"], j["last_text"], j["runs"]), (1100.0, True, "2 e-mail(s) novo(s)", 1))
        self.assertEqual(j["next_ts"], 1100.0 + 900)        # próxima = agora + 15 min
        self.assertFalse(j["running"])
        self.assertGreaterEqual(len(self.events), 2)        # avisou ao começar e ao terminar

    def test_falha_nao_derruba_e_aparece(self):
        def boom(cfg):
            raise RuntimeError("x")

        self.a.JOBS = {**self.a.JOBS, "agenda": ("Agenda", boom)}
        self.a.run_job("agenda")
        j = [j for j in self.a.status()["jobs"] if j["id"] == "agenda"][0]
        self.assertFalse(j["last_ok"])
        self.assertIn("Falhou", j["last_text"])

    def test_nao_roda_duas_vezes_ao_mesmo_tempo(self):
        import threading
        gate, started = threading.Event(), threading.Event()

        def slow(cfg):
            started.set()
            gate.wait(2)
            return True, "ok"

        self.a.JOBS = {**self.a.JOBS, "triagem": ("T", slow)}
        th = threading.Thread(target=self.a.run_job, args=("triagem",))
        th.start()
        started.wait(2)
        self.assertFalse(self.a.run_job("triagem"))
        gate.set()
        th.join()

    def test_start_agenda_proximas_execucoes(self):
        self.assertTrue(self.a.start())
        st = self.a.status()
        by = {j["id"]: j for j in st["jobs"]}
        self.assertEqual(by["triagem"]["next_ts"], 1020.0)
        self.assertIsNotNone(by["agenda"]["next_ts"])
        self.assertIsNotNone(by["resumo"]["next_ts"])
        with self.assertRaises(KeyError):
            self.a.run_job_async("nada")

    def test_desligada_nao_roda_pelo_botao(self):
        with self.assertRaises(RuntimeError):
            self.a.run_job_async("triagem")


class DailyTest(unittest.TestCase):
    def test_proximo_horario(self):
        from datetime import datetime
        base = datetime(2026, 10, 22, 7, 0).timestamp()
        self.assertEqual(datetime.fromtimestamp(automation.next_daily("07:30", base)), datetime(2026, 10, 22, 7, 30))
        self.assertEqual(datetime.fromtimestamp(automation.next_daily("06:00", base)), datetime(2026, 10, 23, 6, 0))
        self.assertEqual(datetime.fromtimestamp(automation.next_daily("07:00", base)), datetime(2026, 10, 23, 7, 0))

    def test_rotina_diaria_roda_uma_vez(self):
        t = [1000.0]
        a = automation.Automation({"automatico": {}}, clock=lambda: t[0])
        calls = []
        a.JOBS = {k: (v[0], (lambda cfg, k=k: calls.append(k) or (True, "ok"))) for k, v in a.JOBS.items()}
        a._at = {"agenda": "07:30", "resumo": "08:00"}
        a._next_daily = {"agenda": 1500.0, "resumo": 9e12}
        a._next_triage = None
        a._stop.set()
        t[0] = 2000.0
        # um passo do laço, na mão
        for key, due in list(a._next_daily.items()):
            if t[0] >= due:
                a._next_daily[key] = automation.next_daily(a._at[key], t[0])
                a.run_job(key)
        self.assertEqual(calls, ["agenda"])
        self.assertGreater(a._next_daily["agenda"], t[0])


if __name__ == "__main__":
    unittest.main()
