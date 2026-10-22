import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import activity  # noqa: E402
import automation  # noqa: E402


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
        import triage

        original = triage.digest
        triage.digest = lambda cfg: (_ for _ in ()).throw(RuntimeError("sem internet"))
        try:
            automation.job_digest({})
        finally:
            triage.digest = original
        events = activity.recent(10)
        self.assertTrue(any(e["kind"] == "erro" and "sem internet" in e["text"] for e in events))

    def test_resumo_salva_relatorio(self):
        import triage

        original = triage.digest
        triage.digest = lambda cfg: "tudo certo"
        try:
            automation.job_digest({})
        finally:
            triage.digest = original
        self.assertTrue(list(Path("data").glob("resumo_*.txt")))


if __name__ == "__main__":
    unittest.main()
