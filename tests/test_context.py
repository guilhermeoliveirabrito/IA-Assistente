import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import context as ctx  # noqa: E402


def u(text):
    return {"role": "user", "parts": [{"text": text}]}


def m(text, sig=None):
    p = {"text": text}
    if sig:
        p["thoughtSignature"] = sig
    return {"role": "model", "parts": [p]}


def call(name="lembrar"):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": {"a": 1}}, "thoughtSignature": "S"}]}


def resp(name="lembrar"):
    return {"role": "user", "parts": [{"functionResponse": {"name": name, "response": {"ok": True}}}]}


class ContextTest(unittest.TestCase):
    def setUp(self):
        self._ask = ctx.ai.ask_text
        self.asked = []
        ctx.ai.ask_text = lambda p, model: (self.asked.append(p), "- pediu X\n- fez Y")[1]

    def tearDown(self):
        ctx.ai.ask_text = self._ask

    def long_chat(self, n=12):
        out = []
        for i in range(n):
            out += [u(f"pergunta {i} " + "x" * 400), m(f"resposta {i} " + "y" * 400)]
        return out

    def test_estimativa_conta_imagens_por_valor_fixo(self):
        big = {"role": "user", "parts": [{"inlineData": {"mimeType": "image/png", "data": "A" * 5_000_000}}]}
        self.assertEqual(ctx.estimate_tokens([big]), ctx.IMAGE_TOKENS)
        self.assertEqual(ctx.estimate_tokens([{"role": "user", "parts": [{"x_file": "a.png"}]}]), ctx.IMAGE_TOKENS)

    def test_assinatura_de_raciocinio_nao_pesa_na_estimativa(self):
        a = ctx.estimate_tokens([m("oi", sig="Z" * 10000)])
        b = ctx.estimate_tokens([m("oi")])
        self.assertEqual(a, b)

    def test_so_compacta_quando_passa_do_limite(self):
        short = [u("oi"), m("olá")] * 3
        self.assertFalse(ctx.needs_compaction(short, limit=10))          # poucos turnos
        self.assertFalse(ctx.needs_compaction(self.long_chat(), 10**9))  # abaixo do limite
        self.assertTrue(ctx.needs_compaction(self.long_chat(), 500))

    def test_corte_comeca_em_turno_de_usuario_e_nunca_separa_ferramenta_da_resposta(self):
        contents = [u("a"), m("b"), u("c"), call(), resp(), m("d"), u("e"), call(), resp(), m("f")]
        for keep in range(1, 9):
            cut = ctx.split_point(contents, keep)
            if cut is None:
                continue
            self.assertEqual(contents[cut]["role"], "user")
            self.assertFalse(any("functionResponse" in p for p in contents[cut]["parts"]), keep)
            self.assertGreaterEqual(cut, 1)

    def test_compactar_resume_o_comeco_e_preserva_o_final_intacto(self):
        contents = self.long_chat(12)
        tail = contents[-6:]
        new, summary = ctx.compact(contents, "m", keep=6)
        self.assertEqual(summary, "- pediu X\n- fez Y")
        self.assertTrue(new[0]["parts"][0]["text"].startswith(ctx.SUMMARY_MARK))
        self.assertEqual(new[1]["role"], "model")
        self.assertEqual(new[2:], tail)
        self.assertLess(len(new), len(contents))
        self.assertIn("pergunta 0", self.asked[0])

    def test_compactar_com_turnos_de_ferramenta_mantem_assinaturas_recentes(self):
        contents = self.long_chat(6) + [u("faça"), call(), resp(), m("pronto", sig="SIG")]
        new, _ = ctx.compact(contents, "m", keep=4)
        self.assertEqual(new[-1]["parts"][0]["thoughtSignature"], "SIG")
        self.assertEqual(new[-3]["parts"][0]["thoughtSignature"], "S")

    def test_segunda_compactacao_incorpora_o_resumo_anterior(self):
        contents = self.long_chat(12)
        new, _ = ctx.compact(contents, "m", keep=6)
        new += self.long_chat(8)
        ctx.compact(new, "m", keep=6)
        self.assertIn("RESUMO ANTERIOR", self.asked[-1])
        self.assertIn("pediu X", self.asked[-1])

    def test_sem_corte_seguro_nao_mexe(self):
        contents = [u("a"), call(), resp(), call(), resp(), m("fim")]
        new, summary = ctx.compact(contents, "m", keep=2)
        self.assertIs(new, contents)
        self.assertIsNone(summary)
        self.assertEqual(self.asked, [])

    def test_transcricao_ignora_pensamentos_e_mostra_ferramentas(self):
        contents = [u("oi"), {"role": "model", "parts": [{"text": "segredo", "thought": True}, {"text": "olá"}]},
                    call(), resp(), {"role": "user", "parts": [{"x_file": "f.pdf", "x_name": "contrato.pdf"}]}]
        text = ctx.render_transcript(contents)
        self.assertNotIn("segredo", text)
        self.assertIn("usou lembrar", text)
        self.assertIn("anexo: contrato.pdf", text)

    def test_transcricao_gigante_e_limitada(self):
        text = ctx.render_transcript([u("z" * 200000)], limit=1000)
        self.assertLess(len(text), 1100)

    def test_semente_de_conversa_nova(self):
        turns, summary = ctx.seed_for_new_conversation(self.long_chat(3), "m")
        self.assertEqual(turns[0]["role"], "user")
        self.assertIn(summary, turns[0]["parts"][0]["text"])


if __name__ == "__main__":
    unittest.main()


class ImagesAndRepairTest(unittest.TestCase):
    def img(self, tag):
        return {"role": "user", "parts": [{"functionResponse": {"name": "ver_tela", "response": {"ok": True}}},
                                          {"inlineData": {"mimeType": "image/jpeg", "data": tag}}]}

    def test_mantem_so_a_captura_mais_recente(self):
        contents = [self.img("A"), m("x"), self.img("B"), m("y"), self.img("C")]
        removed = ctx.drop_old_images(contents)
        self.assertEqual(removed, 2)
        self.assertIn("removida", contents[0]["parts"][1]["text"])
        self.assertIn("removida", contents[2]["parts"][1]["text"])
        self.assertEqual(contents[4]["parts"][1]["inlineData"]["data"], "C")
        self.assertEqual(ctx.drop_old_images(contents), 0)  # idempotente

    def test_nao_mexe_em_outros_tipos_de_dado(self):
        pdf = {"role": "user", "parts": [{"inlineData": {"mimeType": "application/pdf", "data": "P"}}]}
        contents = [pdf, self.img("A"), self.img("B")]
        ctx.drop_old_images(contents, keep=1)
        self.assertIn("inlineData", contents[0]["parts"][0])

    def test_repara_chamada_sem_resposta(self):
        contents = [u("faça"), {"role": "model", "parts": [{"functionCall": {"name": "a", "args": {}}},
                                                           {"functionCall": {"name": "b", "args": {}}}]}]
        self.assertTrue(ctx.repair_contents(contents))
        last = contents[-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual([p["functionResponse"]["name"] for p in last["parts"]], ["a", "b"])
        self.assertIn("interrompida", last["parts"][0]["functionResponse"]["response"]["erro"])

    def test_nao_repara_historico_saudavel(self):
        for contents in ([], [u("oi")], [u("oi"), m("olá")], [u("x"), call(), resp()]):
            self.assertFalse(ctx.repair_contents(contents))
