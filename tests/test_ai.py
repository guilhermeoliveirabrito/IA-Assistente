import base64
import unittest

from assistente.ia import (
    ai,
    gemini,
)


class AiTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.reply = "texto"
        self._orig = gemini.generate

        def fake_generate(contents, models, system=None, tools=None, json_mode=False, temperature=0.2):
            self.calls.append({"contents": contents, "models": models, "json": json_mode, "temp": temperature})
            return {"candidates": [{"content": {"parts": [{"text": self.reply}]}}]}

        gemini.generate = fake_generate
        gemini.set_fallbacks([])

    def tearDown(self):
        gemini.generate = self._orig
        gemini.set_fallbacks([])

    def test_ask_text_usa_modelo_e_reservas(self):
        ai.configure({"ia": {"modelos_reserva": ["reserva-1"]}})
        self.assertEqual(ai.ask_text("oi", "principal"), "texto")
        self.assertEqual(self.calls[0]["models"], ["principal", "reserva-1"])
        self.assertEqual(self.calls[0]["contents"][0]["parts"][0]["text"], "oi")

    def test_ask_json_aceita_cerca_de_codigo(self):
        self.reply = '```json\n[{"id": "1"}]\n```'
        self.assertEqual(ai.ask_json("x", "m"), [{"id": "1"}])
        self.assertTrue(self.calls[0]["json"])

    def test_ask_json_invalido_da_erro_legivel(self):
        self.reply = "não é json"
        with self.assertRaises(ValueError):
            ai.ask_json("x", "m")

    def test_transcribe_envia_audio_em_base64(self):
        self.reply = "  olá mundo \n"
        self.assertEqual(ai.transcribe(b"\x01\x02", "audio/webm", "m"), "olá mundo")
        part = self.calls[0]["contents"][0]["parts"][0]["inlineData"]
        self.assertEqual(part["mimeType"], "audio/webm")
        self.assertEqual(base64.b64decode(part["data"]), b"\x01\x02")
        self.assertEqual(self.calls[0]["temp"], 0.0)

    def test_configure_sem_secao_ia(self):
        ai.configure({})
        self.assertEqual(gemini.models_for("a"), ["a"])


if __name__ == "__main__":
    unittest.main()
