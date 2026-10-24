import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.nucleo import settings  # noqa: E402


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copy(ROOT / "config.yaml", "config.yaml")
        self.cfg = settings.load_config()

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_config_base_carrega(self):
        self.assertEqual(self.cfg["ia"]["modelo"], "gemini-3.8-flash")

    def test_atualiza_valida_e_persiste(self):
        changed, restart = settings.update(self.cfg, {"app.seu_nome": "  Guilherme  ", "limites.requisicoes_por_dia": "100"})
        self.assertEqual(sorted(changed), ["app.seu_nome", "limites.requisicoes_por_dia"])
        self.assertFalse(restart)
        self.assertEqual(self.cfg["app"]["seu_nome"], "Guilherme")
        self.assertEqual(self.cfg["limites"]["requisicoes_por_dia"], 100)
        again = settings.load_config()           # "reabrir o app"
        self.assertEqual(again["app"]["seu_nome"], "Guilherme")
        self.assertEqual(again["ia"]["modelo"], "gemini-3.8-flash")

    def test_avisa_quando_precisa_reiniciar(self):
        _, restart = settings.update(self.cfg, {"tarefas.orcamento_de_requisicoes": 80})
        self.assertTrue(restart)
        _, restart = settings.update(self.cfg, {"tarefas.orcamento_de_requisicoes": 80})
        self.assertFalse(restart)                # nada mudou

    def test_campos_desconhecidos_sao_recusados(self):
        for bad in ("pc.aplicativos", "projetos.tempo_limite_comando_segundos", "__proto__", "ia.chave"):
            with self.assertRaises(ValueError, msg=bad):
                settings.update(self.cfg, {bad: "x"})
        self.assertFalse(Path("data/settings.json").exists())

    def test_nada_e_salvo_se_um_campo_for_invalido(self):
        with self.assertRaises(ValueError) as cm:
            settings.update(self.cfg, {"app.seu_nome": "ok", "limites.requisicoes_por_dia": "-5"})
        self.assertIn("limites.requisicoes_por_dia", json.loads(str(cm.exception)))
        self.assertEqual(self.cfg["app"]["seu_nome"], "")
        self.assertFalse(Path("data/settings.json").exists())

    def test_validadores(self):
        bad = {"app.acesso": "mundo", "app.porta": 80, "ia.modelo": "", "ia.modelo ": "x",
               "limites.hora_renovacao": "25:00", "limites.fuso_renovacao": "Pacifico",
               "notificacoes.ntfy_topico": "curto", "projetos.repos_permitidos": ["sem-barra"],
               "pc.confiar_sem_perguntar": ["comandos"], "tarefas.retomar_apos_renovacao": "sim",
               "arquivos.pastas_permitidas": [""]}
        for k, v in bad.items():
            with self.assertRaises(ValueError, msg=k):
                settings.update(self.cfg, {k: v})
        ok = {"app.acesso": "rede", "limites.hora_renovacao": "03:30", "limites.fuso_renovacao": "America/Los_Angeles",
              "notificacoes.ntfy_topico": "assistente-" + "a" * 20, "projetos.repos_permitidos": ["Dono/Repo"],
              "pc.confiar_sem_perguntar": ["abrir"], "tarefas.retomar_apos_renovacao": False}
        settings.update(self.cfg, ok)
        self.assertEqual(self.cfg["projetos"]["repos_permitidos"], ["dono/repo"])

    def test_limites_por_modelo(self):
        settings.update(self.cfg, {"limites.por_modelo": ["gemini-3.8-flash=20,5,250000", "gemini-3.6-flash = 500"]})
        self.assertEqual(self.cfg["limites"]["por_modelo"], ["gemini-3.8-flash=20,5,250000", "gemini-3.6-flash = 500"])
        for bad in (["sem-igual"], ["m=abc"], ["m=1,2,3,4"], ["=5"]):
            with self.assertRaises(ValueError, msg=str(bad)):
                settings.update(self.cfg, {"limites.por_modelo": bad})

    def test_listas_aceitam_texto_separado_por_virgula_ou_linha(self):
        settings.update(self.cfg, {"arquivos.pastas_permitidas": "C:/a, C:/b\nC:/c"})
        self.assertEqual(self.cfg["arquivos"]["pastas_permitidas"], ["C:/a", "C:/b", "C:/c"])
        with self.assertRaises(ValueError):
            settings.update(self.cfg, {"arquivos.pastas_permitidas": ["x"] * 30})

    def test_ajustes_corrompidos_sao_ignorados(self):
        Path("data").mkdir()
        Path("data/settings.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(settings.load_config()["ia"]["modelo"], "gemini-3.8-flash")
        Path("data/settings.json").write_text(json.dumps({"campo.falso": 1, "app.seu_nome": "Ana"}), encoding="utf-8")
        cfg = settings.load_config()
        self.assertEqual(cfg["app"]["seu_nome"], "Ana")
        self.assertNotIn("campo", cfg)

    def test_valores_atuais(self):
        vals = settings.current_values(self.cfg)
        self.assertEqual(vals["limites.requisicoes_por_dia"], 250)
        self.assertEqual(set(vals), set(settings.FIELDS))


if __name__ == "__main__":
    unittest.main()


class LimitesDoProjetoTest(unittest.TestCase):
    def test_limites_do_config_padrao_batem_com_o_painel(self):
        from assistente.nucleo import usage
        cfg = settings.load_config(ROOT / "config.yaml")
        got = {m: usage._configured_limits(cfg, m) for m in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")}
        self.assertEqual(got["gemini-3.8-flash"], {"rpd": 20, "rpm": 5, "tpm": 250000})
        self.assertEqual(got["gemini-3.6-flash"], {"rpd": 20, "rpm": 5, "tpm": 250000})
        self.assertEqual(got["gemini-3.5-flash-lite"], {"rpd": 500, "rpm": 15, "tpm": 250000})
