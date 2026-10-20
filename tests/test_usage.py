import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import usage  # noqa: E402


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_conta_requisicoes_e_tokens_do_dia(self):
        now = utc(2026, 10, 20, 12, 0)  # 05:00 em Los Angeles (PDT)
        usage.record("m", 100, 50, now=now - 3600)
        usage.record("m", 200, 30, now=now - 60)
        s = usage.summary({}, now=now)
        self.assertEqual(s["requests_day"]["used"], 2)
        self.assertEqual(s["tokens_day"], 380)
        self.assertEqual(s["requests_day"]["remaining"], 248)

    def test_reset_a_meia_noite_do_pacifico(self):
        now = utc(2026, 10, 20, 12, 0)
        s = usage.summary({}, now=now)
        # meia-noite PDT (UTC-7) do dia 21 = 07:00 UTC do dia 21 -> faltam 19h
        self.assertEqual(s["seconds_to_reset"], 19 * 3600)

    def test_evento_antes_do_reset_nao_conta(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record("m", 10, 10, now=utc(2026, 10, 20, 6, 59))  # ontem para o Pacífico
        usage.record("m", 10, 10, now=utc(2026, 10, 20, 7, 1))   # hoje
        self.assertEqual(usage.summary({}, now=now)["requests_day"]["used"], 1)

    def test_horario_de_verao_termina_dia_tem_25h(self):
        now = utc(2026, 11, 1, 12, 0)  # DST acabou; já é PST (UTC-8)
        s = usage.summary({}, now=now)
        # próximo reset: 2 nov 00:00 PST = 08:00 UTC
        self.assertEqual(s["seconds_to_reset"], 20 * 3600)

    def test_limites_do_config_e_percentual(self):
        now = utc(2026, 10, 20, 12, 0)
        for i in range(5):
            usage.record("m", 10, 0, now=now - 100 - i)
        cfg = {"limites": {"requisicoes_por_dia": 20}}
        s = usage.summary(cfg, now=now)
        self.assertEqual(s["requests_day"]["limit"], 20)
        self.assertEqual(s["requests_day"]["percent"], 25.0)

    def test_janela_de_um_minuto(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record("m", 100, 100, now=now - 30)
        usage.record("m", 100, 100, now=now - 90)
        s = usage.summary({}, now=now)
        self.assertEqual(s["requests_minute"]["used"], 1)
        self.assertEqual(s["tokens_minute"]["used"], 200)

    def test_percentual_nunca_passa_de_100(self):
        now = utc(2026, 10, 20, 12, 0)
        for i in range(30):
            usage.record("m", 1, 1, now=now - 10 - i)
        cfg = {"limites": {"requisicoes_por_dia": 10}}
        self.assertEqual(usage.summary(cfg, now=now)["requests_day"]["percent"], 100.0)

    def test_erro_de_cota_marca_limite_atingido(self):
        now = utc(2026, 10, 20, 12, 0)
        self.assertFalse(usage.summary({}, now=now)["quota_hit"])
        usage.record_quota_error(30, now=now - 120)
        self.assertTrue(usage.summary({}, now=now)["quota_hit"])
        self.assertFalse(usage.summary({}, now=now + 3600)["quota_hit"])

    def test_eventos_antigos_sao_podados(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record("m", 1, 1, now=now - 10 * 24 * 3600)
        usage.record("m", 1, 1, now=now)
        import json
        events = json.loads(Path("data/usage.json").read_text())["events"]
        self.assertEqual(len(events), 1)

    def test_arquivo_corrompido_nao_quebra(self):
        Path("data").mkdir()
        Path("data/usage.json").write_text("{lixo", encoding="utf-8")
        self.assertEqual(usage.summary({}, now=utc(2026, 10, 20, 12))["requests_day"]["used"], 0)


if __name__ == "__main__":
    unittest.main()
