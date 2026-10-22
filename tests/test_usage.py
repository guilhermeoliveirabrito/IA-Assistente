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


class PorModeloTest(UsageTest):
    CFG = {"ia": {"modelo": "a", "modelos_reserva": ["b"]}}

    def test_contagem_separada_por_modelo(self):
        now = utc(2026, 10, 20, 12, 0)
        for _ in range(3):
            usage.record("a", 100, 10, now=now - 600)
        usage.record("b", 50, 5, now=now - 30)
        s = usage.summary(self.CFG, now=now)
        a, b = s["models"]
        self.assertEqual((a["model"], a["requests_day"]["used"], a["tokens_day"]), ("a", 3, 330))
        self.assertEqual((b["model"], b["requests_day"]["used"], b["requests_minute"]["used"]), ("b", 1, 1))
        self.assertEqual(s["requests_day"]["used"], 4)             # o total continua existindo

    def test_modelo_fora_da_lista_tambem_aparece(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record("z", 1, 1, now=now - 5)
        self.assertEqual([m["model"] for m in usage.summary(self.CFG, now=now)["models"]], ["a", "b", "z"])

    def test_google_recusou_por_dia_marca_esgotado_e_aprende_o_limite(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record_quota_error(None, now=now, model="a", quota={"scope": "day", "kind": "requests", "limit": 20})
        a, b = usage.summary(self.CFG, now=now + 5)["models"]
        self.assertEqual(a["status"], "esgotado")
        self.assertEqual(a["requests_day"]["limit"], 20)
        self.assertEqual(a["requests_day"]["limit_source"], "Google")
        self.assertEqual(a["rejections_day"], 1)
        self.assertEqual(b["requests_day"]["limit_source"], "estimado")
        self.assertNotEqual(b["status"], "esgotado")

    def test_esgotado_acaba_na_renovacao(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record_quota_error(None, now=now, model="a", quota={"scope": "day", "kind": "requests", "limit": 20})
        later = utc(2026, 10, 21, 7, 5)                           # logo depois da meia-noite do Pacífico
        self.assertNotEqual(usage.summary(self.CFG, now=later)["models"][0]["status"], "esgotado")

    def test_limite_por_minuto_e_temporario(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record_quota_error(30, now=now, model="a", quota={"scope": "minute", "kind": "requests", "limit": 5})
        a = usage.summary(self.CFG, now=now + 10)["models"][0]
        self.assertEqual(a["status"], "espera")
        self.assertEqual(a["requests_minute"]["limit"], 5)
        self.assertEqual(usage.summary(self.CFG, now=now + 40)["models"][0]["status"], "disponivel")

    def test_recusa_sem_detalhes_curta_e_de_minuto_longa_e_de_dia(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record_quota_error(20, now=now, model="a")
        usage.record_quota_error(None, now=now, model="b")
        a, b = usage.summary(self.CFG, now=now + 1)["models"]
        self.assertEqual((a["status"], b["status"]), ("espera", "esgotado"))
        self.assertEqual(a["requests_day"]["limit_source"], "estimado")   # sem o limite, não inventa "confirmado"

    def test_limites_do_config_por_modelo(self):
        now = utc(2026, 10, 20, 12, 0)
        cfg = {**self.CFG, "limites": {"por_modelo": ["a=20,5,1000", "b = 1000"]}}
        a, b = usage.summary(cfg, now=now)["models"]
        self.assertEqual((a["requests_day"]["limit"], a["requests_minute"]["limit"], a["tokens_minute"]["limit"]), (20, 5, 1000))
        self.assertEqual((b["requests_day"]["limit"], b["requests_day"]["limit_source"]), (1000, "seu config"))
        self.assertEqual(b["requests_minute"]["limit"], 10)               # o resto cai no padrão

    def test_o_que_o_google_disse_vale_mais_que_o_config(self):
        now = utc(2026, 10, 20, 12, 0)
        cfg = {**self.CFG, "limites": {"por_modelo": ["a=999"]}}
        usage.record_quota_error(None, now=now, model="a", quota={"scope": "day", "kind": "requests", "limit": 20})
        self.assertEqual(usage.summary(cfg, now=now + 1)["models"][0]["requests_day"]["limit"], 20)

    def test_no_limite_pela_contagem(self):
        now = utc(2026, 10, 20, 12, 0)
        cfg = {**self.CFG, "limites": {"por_modelo": ["a=2"]}}
        usage.record("a", 1, 1, now=now - 100)
        usage.record("a", 1, 1, now=now - 90)
        self.assertEqual(usage.summary(cfg, now=now)["models"][0]["status"], "cheio")

    def test_troca_de_modelo_fica_registrada_com_motivo(self):
        events = []
        usage.subscribe(events.append)
        try:
            now = utc(2026, 10, 20, 12, 0)
            usage.note_model("a", now=now)
            usage.note_model("b", [("a", "quota")], now=now + 60)
            usage.note_model("b", now=now + 90)                       # sem troca: nada novo
            usage.note_model("a", now=now + 120)
        finally:
            usage.unsubscribe(events.append)
        s = usage.summary(self.CFG, now=now + 130)
        self.assertEqual(s["current_model"], "a")
        self.assertEqual([(x["from"], x["to"]) for x in reversed(s["switches"])], [(None, "a"), ("a", "b"), ("b", "a")])
        self.assertIn("a cota acabou", s["switches"][1]["reason"])
        self.assertIn("voltou ao modelo principal", s["switches"][0]["reason"])
        self.assertEqual(sum(1 for e in events if e["type"] == "model_switch"), 2)   # a primeira escolha não é "troca"
        self.assertEqual(s["models"][0]["status"], "em_uso")

    def test_ajuste_com_o_painel_soma_a_diferenca_so_no_dia(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record("a", 1, 1, now=now - 100)
        usage.calibrate("a", 17, now=now)
        a = usage.summary(self.CFG, now=now + 1)["models"][0]
        self.assertEqual((a["requests_day"]["used"], a["calibrated"]), (17, True))
        usage.record("a", 1, 1, now=now + 5)
        self.assertEqual(usage.summary(self.CFG, now=now + 6)["models"][0]["requests_day"]["used"], 18)
        amanha = utc(2026, 10, 21, 12, 0)
        self.assertFalse(usage.summary(self.CFG, now=amanha)["models"][0]["calibrated"])
        with self.assertRaises(ValueError):
            usage.calibrate("a", -3)

    def test_ordem_poe_os_recusados_no_fim_sem_perde_los(self):
        usage.record_quota_error(None, model="a", quota={"scope": "day", "kind": "requests", "limit": 20})
        self.assertEqual(usage.prefer_order(["a", "b", "c"]), ["b", "c", "a"])
        self.assertEqual(usage.blocked_models(["a", "b"]), ["a"])

    def test_modelo_que_responde_limpa_a_marca_de_esgotado(self):
        now = utc(2026, 10, 20, 12, 0)
        usage.record_quota_error(None, now=now, model="a", quota={"scope": "day", "kind": "requests", "limit": 20})
        usage.note_model("a")
        self.assertNotEqual(usage.summary(self.CFG, now=now + 5)["models"][0]["status"], "esgotado")


if __name__ == "__main__":
    unittest.main()
