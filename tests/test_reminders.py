import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from assistente.servicos import reminders as R


def ts(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi).timestamp()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.now = ts(2026, 10, 23, 15, 0)          # sexta-feira
        self.fired, self.changes = [], []
        self.r = R.Reminders(on_fire=lambda it, late: self.fired.append((it, late)), on_change=lambda: self.changes.append(1),
                             clock=lambda: self.now)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()


class HorarioTest(unittest.TestCase):
    def test_parse(self):
        now = ts(2026, 10, 23, 15, 0)
        self.assertEqual(R.parse_when("2026-10-24 18:30", now), ts(2026, 10, 24, 18, 30))
        self.assertEqual(R.parse_when("2026-10-24T08:05", now), ts(2026, 10, 24, 8, 5))
        self.assertEqual(R.parse_when("18:00", now), ts(2026, 10, 23, 18, 0))
        self.assertEqual(R.parse_when("09:00", now), ts(2026, 10, 24, 9, 0))      # já passou hoje: amanhã
        for bad in ("amanhã", "2026-13-40 10:00", "25:99", ""):
            with self.assertRaises(R.ReminderError, msg=bad):
                R.parse_when(bad, now)

    def test_proximas_ocorrencias(self):
        base = {"due": ts(2026, 10, 23, 8, 0), "repeat": {"tipo": "diario"}}
        self.assertEqual(R.next_due(base, ts(2026, 10, 23, 9, 0)), ts(2026, 10, 24, 8, 0))
        self.assertEqual(R.next_due(base, ts(2026, 10, 27, 9, 0)), ts(2026, 10, 28, 8, 0))
        uteis = {"due": ts(2026, 10, 23, 8, 0), "repeat": {"tipo": "dias_uteis"}}           # sexta -> segunda
        self.assertEqual(R.next_due(uteis, ts(2026, 10, 23, 9, 0)), ts(2026, 10, 26, 8, 0))
        sem = {"due": ts(2026, 10, 23, 8, 0), "repeat": {"tipo": "semanal"}}
        self.assertEqual(R.next_due(sem, ts(2026, 10, 23, 9, 0)), ts(2026, 10, 30, 8, 0))
        mes = {"due": ts(2026, 1, 31, 8, 0), "repeat": {"tipo": "mensal"}}                  # 31/jan -> 28/fev (sem estourar)
        self.assertEqual(R.next_due(mes, ts(2026, 1, 31, 9, 0)), ts(2026, 2, 28, 8, 0))
        inter = {"due": ts(2026, 10, 23, 8, 0), "repeat": {"tipo": "intervalo", "minutos": 30}}
        self.assertEqual(R.next_due(inter, ts(2026, 10, 23, 8, 45)), ts(2026, 10, 23, 9, 0))

    def test_hora_do_relogio_se_mantem_diariamente(self):
        it = {"due": ts(2026, 3, 1, 7, 30), "repeat": {"tipo": "diario"}}
        for _ in range(3):
            it["due"] = R.next_due(it, it["due"])
            self.assertEqual(datetime.fromtimestamp(it["due"]).strftime("%H:%M"), "07:30")


class ServicoTest(Base):
    def add(self, **kw):
        args = dict(text="ligar pro João", when_ts=self.now + 600)
        args.update(kw)
        return self.r.add(args.pop("text"), args.pop("when_ts"), **args)

    def test_valida_entrada(self):
        for kw in (dict(text=" "), dict(text="x" * 401), dict(when_ts=self.now - 3600), dict(kind="x"), dict(repeat="x"),
                   dict(repeat="intervalo"), dict(repeat="intervalo", every_minutes=1), dict(when_ts=self.now + 4 * 365 * 86400)):
            with self.assertRaises(R.ReminderError, msg=str(kw)):
                self.add(**kw)
        self.assertEqual(self.r.items(), [])

    def test_dispara_na_hora_e_espera_dispensar(self):
        it = self.add()
        self.assertEqual(self.r.check_due(), 0)
        self.now += 601
        self.assertEqual(self.r.check_due(), 1)
        self.assertEqual(self.fired[0][0]["text"], "ligar pro João")
        self.assertEqual(self.r.get(it["id"])["status"], "tocando")
        self.now += 60
        self.assertEqual(self.r.check_due(), 0)                         # não repete sozinho
        self.r.dismiss(it["id"])
        self.assertEqual(self.r.get(it["id"])["status"], "concluido")
        self.assertEqual(self.r.items(), [])

    def test_soneca_de_lembrete_unico(self):
        it = self.add()
        self.now += 601
        self.r.check_due()
        self.r.snooze(it["id"], 5)
        self.assertEqual(self.r.get(it["id"])["status"], "ativo")
        self.now += 301
        self.assertEqual(self.r.check_due(), 1)
        self.assertEqual(len(self.fired), 2)

    def test_recorrente_reagenda_e_soneca_nao_desloca_a_serie(self):
        it = self.add(when_ts=ts(2026, 10, 24, 8, 0), repeat="diario", kind="alarme")
        self.now = ts(2026, 10, 24, 8, 0, ) + 5
        self.assertEqual(self.r.check_due(), 1)
        cur = self.r.get(it["id"])
        self.assertEqual(cur["status"], "tocando")
        self.assertEqual(cur["due"], ts(2026, 10, 25, 8, 0))
        self.r.snooze(it["id"], 10)
        self.now += 601
        self.assertEqual(self.r.check_due(), 1)
        self.assertEqual(self.r.get(it["id"])["due"], ts(2026, 10, 25, 8, 0))   # a série segue no horário
        self.r.dismiss(it["id"])
        self.assertEqual(self.r.get(it["id"])["status"], "ativo")

    def test_lembrete_recorrente_so_avisa_e_segue(self):
        it = self.add(when_ts=self.now + 60, repeat="intervalo", every_minutes=30)
        self.now += 61
        self.r.check_due()
        self.assertEqual(self.r.get(it["id"])["status"], "ativo")
        self.assertEqual(self.r.get(it["id"])["due"], it["due"] + 1800)

    def test_atrasado_por_app_fechado(self):
        aviso = self.add(when_ts=self.now + 60, repeat="diario")
        tarefa = self.add(text="resumir noticias", when_ts=self.now + 60, repeat="diario", run=True)
        self.now += 5 * 3600                                        # app ficou fechado 5 h
        self.assertEqual(self.r.check_due(), 1)                     # aviso ainda vale; a tarefa velha é só reagendada
        self.assertEqual(self.fired[0][0]["id"], aviso["id"])
        self.assertGreater(self.r.get(tarefa["id"])["due"], self.now)
        unico = self.add(when_ts=self.now + 60)
        self.now += 3 * 86400
        self.assertEqual(self.r.check_due(), 1)                     # o único atrasado dispara (com `late` alto); o diário velho só reagenda
        self.assertTrue(any(i["id"] == unico["id"] and late > 86400 for i, late in self.fired))

    def test_tarefa_unica_conclui_sozinha(self):
        it = self.add(text="resumir", run=True)
        self.now += 601
        self.r.check_due()
        self.assertTrue(self.fired[-1][0]["run"])
        self.assertEqual(self.r.get(it["id"])["status"], "concluido")

    def test_cancelar_e_ids_invalidos(self):
        it = self.add()
        self.r.cancel(it["id"])
        for bad in (it["id"], "../x", "", None):
            with self.assertRaises(R.ReminderError):
                self.r.get(bad)
        with self.assertRaises(R.ReminderError):
            self.r.cancel("zzzzzzzz")

    def test_concluidos_antigos_somem(self):
        it = self.add()
        self.now += 601
        self.r.check_due()
        self.r.dismiss(it["id"])
        self.now += 8 * 86400
        self.r.check_due()
        with self.assertRaises(R.ReminderError):
            self.r.get(it["id"])

    def test_status_para_o_painel(self):
        self.assertEqual(self.r.status()["next_ts"], None)
        self.add(when_ts=self.now + 900)
        self.add(when_ts=self.now + 300)
        st = self.r.status()
        self.assertEqual(st["next_ts"], self.now + 300)
        self.assertEqual(st["id"], "lembretes")
        self.assertFalse(st["can_run"])

    def test_sobrevive_a_arquivo_corrompido(self):
        Path("data").mkdir(exist_ok=True)
        (Path("data") / "lembretes.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(self.r.items(), [])
        self.add()
        self.assertEqual(len(self.r.items()), 1)

    def test_public(self):
        it = self.add(when_ts=ts(2026, 10, 24, 18, 30), repeat="semanal", kind="alarme")
        p = R.public(it)
        self.assertEqual((p["quando"], p["repete"], p["tipo"]), ("2026-10-24 18:30", "toda semana", "alarme"))


if __name__ == "__main__":
    unittest.main()
