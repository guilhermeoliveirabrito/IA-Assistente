import os
import tempfile
import unittest
from datetime import datetime

import ai
import briefing as B

NOW = datetime(2026, 10, 24, 7, 0).timestamp()          # sábado


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.saved = ai.ask_text
        self.prompts = []
        ai.ask_text = lambda prompt, model: (self.prompts.append(prompt), "## Resumo da IA")[1]
        self.ready = []
        self.data = {"agenda": [{"inicio": "2026-10-24T09:00:00-03:00", "titulo": "Dentista", "local": "Centro"}],
                     "emails": [{"de": "Maria", "resumo": "Orçamento aprovado", "precisa_resposta": True}],
                     "encomendas": [{"nome": "Fone", "situacao": "Em trânsito"}],
                     "lembretes": [{"quando": "2026-10-24 18:00", "texto": "ligar pro João"}]}
        self.b = B.Briefing({"ia": {"modelo": "m"}, "automatico": {"resumo_do_dia_as": "08:00"}}, lambda: self.data,
                            on_ready=self.ready.append, clock=lambda: NOW)

    def tearDown(self):
        ai.ask_text = self.saved
        os.chdir(self.old)
        self.tmp.cleanup()


class BriefingTest(Base):
    def test_gera_salva_e_avisa(self):
        rec = self.b.run()
        self.assertEqual(rec["text"], "## Resumo da IA")
        self.assertEqual(self.ready, ["## Resumo da IA"])
        self.assertEqual(self.b.latest()["ts"], NOW)
        self.assertIn("Dentista", self.prompts[0])
        self.assertIn("DADO", self.prompts[0])

    def test_sem_ia_sai_texto_simples_com_tudo(self):
        def boom(*a):
            raise RuntimeError("fora do ar")
        ai.ask_text = boom
        text = self.b.run()["text"]
        for trecho in ("sábado, 24/10", "09:00 — Dentista (Centro)", "Maria: Orçamento aprovado (pede resposta)", "Fone: Em trânsito", "18:00 — ligar pro João"):
            self.assertIn(trecho, text)

    def test_google_indisponivel_e_explicado(self):
        ai.ask_text = lambda *a: ""
        self.data.update(agenda=None, emails=None, encomendas=[], lembretes=[])
        text = self.b.run()["text"]
        self.assertIn("Agenda indisponível", text)
        self.assertIn("E-mails indisponíveis", text)
        self.assertNotIn("Encomendas", text)

    def test_agenda_e_emails_vazios(self):
        ai.ask_text = lambda *a: ""
        self.data.update(agenda=[], emails=[])
        text = self.b.run()["text"]
        self.assertIn("Nenhum compromisso hoje", text)
        self.assertIn("Nada importante novo", text)

    def test_falha_ao_juntar_dados_nao_derruba(self):
        def boom():
            raise RuntimeError("x")
        self.b.gather = boom
        self.assertIn("text", self.b.run())

    def test_horario_e_status(self):
        self.b.start()
        self.assertEqual(datetime.fromtimestamp(self.b.status()["next_ts"]), datetime(2026, 10, 24, 8, 0))
        self.b.stop()
        self.assertEqual(self.b.status()["id"], "resumo_do_dia")
        self.b.cfg["automatico"]["resumo_do_dia"] = False
        self.assertIn("Desligado", self.b.status()["note"])

    def test_nao_dispara_antes_nem_repete(self):
        t = [NOW]
        self.b.clock = lambda: t[0]
        self.b._next = datetime(2026, 10, 24, 8, 0).timestamp()
        calls = []
        self.b.run = lambda notify=True: calls.append(1)
        for when, expect in ((NOW, 0), (datetime(2026, 10, 24, 8, 0, 5).timestamp(), 1)):
            t[0] = when
            if self.b.clock() >= self.b._next:
                self.b._next = B.automation.next_daily(self.b.at, self.b.clock())
                self.b.run()
            self.assertEqual(len(calls), expect)
        self.assertEqual(datetime.fromtimestamp(self.b._next), datetime(2026, 10, 25, 8, 0))


if __name__ == "__main__":
    unittest.main()
