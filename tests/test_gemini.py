import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gemini  # noqa: E402
import usage  # noqa: E402


class FakeResp:
    def __init__(self, body: bytes = b"", lines=None):
        self._body = body
        self._lines = lines or []

    def read(self):
        return self._body

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, message="x", status="", details=None):
    body = json.dumps({"error": {"code": code, "message": message, "status": status, "details": details or []}})
    return urllib.error.HTTPError("http://x", code, message, {}, io.BytesIO(body.encode()))


def ok_response(text="oi", tin=10, tout=5):
    return FakeResp(json.dumps({
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout},
    }).encode())


class GeminiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ["GEMINI_API_KEY"] = "chave-de-teste"
        self.calls = []
        self.queue = []
        gemini._sleep = lambda s: None
        gemini.set_fallbacks([])

        def fake_urlopen(req, timeout=None):
            self.calls.append((req.full_url, json.loads(req.data), dict(req.header_items())))
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        gemini._urlopen = fake_urlopen

    def tearDown(self):
        gemini._urlopen = __import__("urllib.request").request.urlopen
        os.chdir(self.old)
        self.tmp.cleanup()

    def user(self, text="oi"):
        return [{"role": "user", "parts": [{"text": text}]}]

    def test_payload_completo(self):
        p = gemini.build_payload(self.user(), system="sistema", tools=[{"name": "f"}], json_mode=True, temperature=0.5)
        self.assertEqual(p["systemInstruction"]["parts"][0]["text"], "sistema")
        self.assertEqual(p["tools"][0]["functionDeclarations"][0]["name"], "f")
        self.assertEqual(p["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(p["generationConfig"]["temperature"], 0.5)

    def test_generate_ok_registra_consumo_e_envia_chave_no_header(self):
        self.queue.append(ok_response("olá", 12, 8))
        obj = gemini.generate(self.user(), ["modelo-a"])
        self.assertEqual(gemini.text_of(obj), "olá")
        url, _, headers = self.calls[0]
        self.assertIn("modelo-a:generateContent", url)
        self.assertNotIn("chave-de-teste", url)
        self.assertEqual(headers.get("X-goog-api-key"), "chave-de-teste")
        s = usage.summary({})
        self.assertEqual(s["requests_day"]["used"], 1)
        self.assertEqual(s["tokens_day"], 20)

    def test_cota_estourada_usa_modelo_reserva(self):
        self.queue += [http_error(429, "quota", "RESOURCE_EXHAUSTED"), ok_response("do reserva")]
        obj = gemini.generate(self.user(), ["principal", "reserva"])
        self.assertEqual(obj["_model"], "reserva")
        self.assertEqual(gemini.text_of(obj), "do reserva")
        self.assertTrue(usage.summary({})["quota_hit"])

    def test_modelo_inexistente_usa_reserva(self):
        self.queue += [http_error(404, "models/x is not found"), ok_response()]
        self.assertEqual(gemini.generate(self.user(), ["x", "y"])["_model"], "y")

    def test_todos_os_modelos_sem_cota_da_erro_claro(self):
        self.queue += [http_error(429, "q"), http_error(429, "q")]
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.generate(self.user(), ["a", "b"])
        self.assertEqual(cm.exception.kind, "quota")

    def test_chave_invalida_nao_tenta_reserva(self):
        self.queue += [http_error(400, "API key not valid. Please pass a valid API key.")]
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.generate(self.user(), ["a", "b"])
        self.assertEqual(cm.exception.kind, "auth")
        self.assertEqual(len(self.calls), 1)

    def test_erro_de_servidor_tenta_de_novo(self):
        self.queue += [http_error(503, "overloaded"), http_error(503, "overloaded"), ok_response("voltou")]
        self.assertEqual(gemini.text_of(gemini.generate(self.user(), ["a"])), "voltou")
        self.assertEqual(len(self.calls), 3)

    def test_sem_internet(self):
        self.queue += [urllib.error.URLError("sem rede")] * 3
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.generate(self.user(), ["a"])
        self.assertEqual(cm.exception.kind, "network")

    def test_retry_delay_e_lido(self):
        err = gemini.error_from_response(429, json.dumps({"error": {"code": 429, "message": "m", "status": "RESOURCE_EXHAUSTED",
                                                                    "details": [{"retryDelay": "34s"}]}}))
        self.assertEqual(err.retry_after, 34.0)

    def test_pedido_bloqueado(self):
        self.queue.append(FakeResp(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode()))
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.generate(self.user(), ["a"])
        self.assertEqual(cm.exception.kind, "blocked")

    def test_sem_chave(self):
        del os.environ["GEMINI_API_KEY"]
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.api_key()
        self.assertEqual(cm.exception.kind, "auth")

    def test_dotenv_le_chave(self):
        del os.environ["GEMINI_API_KEY"]
        Path(".env").write_text('# comentário\nGEMINI_API_KEY="abc"\n', encoding="utf-8")
        self.assertEqual(gemini.api_key(), "abc")

    def test_stream_entrega_pedacos_e_registra_uso_final(self):
        chunks = [
            {"candidates": [{"content": {"parts": [{"text": "Olá "}]}}], "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 1}},
            {"candidates": [{"content": {"parts": [{"text": "mundo"}]}}], "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 4}},
        ]
        self.queue.append(FakeResp(lines=[f"data: {json.dumps(c)}\r\n".encode() if k % 2 == 0 else b"\r\n"
                                          for c in chunks for k in (0, 1)]))
        out = list(gemini.stream(self.user(), ["m"]))
        self.assertEqual(out[0], {"_model": "m"})
        self.assertEqual("".join(gemini.text_of(c) for c in out[1:]), "Olá mundo")
        self.assertIn("alt=sse", self.calls[0][0])
        s = usage.summary({})
        self.assertEqual((s["requests_day"]["used"], s["tokens_day"]), (1, 34))

    def test_stream_interrompido_ainda_conta_a_requisicao(self):
        chunk = {"candidates": [{"content": {"parts": [{"text": "a"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}}
        self.queue.append(FakeResp(lines=[f"data: {json.dumps(chunk)}\n".encode()] * 5))
        gen = gemini.stream(self.user(), ["m"])
        next(gen)
        next(gen)
        gen.close()
        self.assertEqual(usage.summary({})["requests_day"]["used"], 1)

    def test_stream_ignora_linhas_que_nao_sao_dados(self):
        chunk = {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}
        self.queue.append(FakeResp(lines=[b": comentario\n", b"\n", f"data: {json.dumps(chunk)}\n".encode(), b"data: [DONE]\n"]))
        out = list(gemini.stream(self.user(), ["m"]))
        self.assertEqual(len(out), 2)

    def test_stream_erro_no_meio(self):
        err = {"error": {"code": 429, "message": "acabou", "status": "RESOURCE_EXHAUSTED"}}
        self.queue.append(FakeResp(lines=[f"data: {json.dumps(err)}\n".encode()]))
        with self.assertRaises(gemini.GeminiError) as cm:
            list(gemini.stream(self.user(), ["m"]))
        self.assertEqual(cm.exception.kind, "quota")

    def test_modelos_com_reserva_sem_duplicar(self):
        gemini.set_fallbacks(["b", "a", ""])
        self.assertEqual(gemini.models_for("a"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
