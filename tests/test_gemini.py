import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from assistente.ia import gemini
from assistente.nucleo import usage


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

    def test_modelo_sobrecarregado_usa_reserva(self):
        self.queue += [http_error(503, "high demand"), ok_response("do reserva")]
        obj = gemini.generate(self.user(), ["principal", "reserva"])
        self.assertEqual((obj["_model"], gemini.text_of(obj)), ("reserva", "do reserva"))
        self.assertEqual(len(self.calls), 2)      # não insiste no sobrecarregado quando há reserva

    def test_todos_sobrecarregados_da_erro_de_servidor(self):
        self.queue += [http_error(503, "high demand")] * 4
        with self.assertRaises(gemini.GeminiError) as cm:
            gemini.generate(self.user(), ["a", "b"])
        self.assertEqual(cm.exception.kind, "server")

    def test_429_traz_o_limite_real_e_o_app_aprende(self):
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {"model": "principal", "location": "global"}, "quotaValue": "20"}]}]
        self.queue += [http_error(429, "quota", "RESOURCE_EXHAUSTED", details), ok_response("do reserva")]
        obj = gemini.generate(self.user(), ["principal", "reserva"])
        self.assertEqual(obj["_model"], "reserva")
        s = usage.summary({"ia": {"modelo": "principal", "modelos_reserva": ["reserva"]}})
        p, r = s["models"]
        self.assertEqual((p["status"], p["requests_day"]["limit"], p["requests_day"]["limit_source"]), ("esgotado", 20, "Google"))
        self.assertEqual((r["status"], r["requests_day"]["used"]), ("em_uso", 1))
        self.assertEqual(s["current_model"], "reserva")
        self.assertIn("a cota acabou", s["switches"][0]["reason"])

    def test_modelo_esgotado_nao_e_tentado_primeiro_na_proxima(self):
        usage.record_quota_error(None, model="principal", quota={"scope": "day", "kind": "requests", "limit": 20})
        self.queue += [ok_response("direto")]
        obj = gemini.generate(self.user(), ["principal", "reserva"])
        self.assertEqual(obj["_model"], "reserva")
        self.assertEqual(len(self.calls), 1)                 # nem gastou uma tentativa no esgotado
        self.assertIn("reserva:generateContent", self.calls[0][0])

    def test_se_todos_estao_marcados_esgotados_ainda_tenta(self):
        for m in ("a", "b"):
            usage.record_quota_error(None, model=m, quota={"scope": "day", "kind": "requests", "limit": 20})
        self.queue += [ok_response("voltou")]                # a marca pode estar velha: tenta mesmo assim
        self.assertEqual(gemini.generate(self.user(), ["a", "b"])["_model"], "a")

    def test_voltar_ao_principal_e_registrado(self):
        usage.note_model("reserva")
        self.queue += [ok_response()]
        gemini.generate(self.user(), ["principal", "reserva"])
        sw = usage.summary({})["switches"][0]
        self.assertEqual((sw["from"], sw["to"]), ("reserva", "principal"))

    def test_429_sem_detalhes_continua_funcionando(self):
        self.queue += [http_error(429, "quota"), ok_response("ok")]
        self.assertEqual(gemini.generate(self.user(), ["a", "b"])["_model"], "b")

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


class RaciocinioTest(GeminiTest):
    def level_sent(self, i=0):
        return self.calls[i][1]["generationConfig"].get("thinkingConfig")

    def test_modelo_3_recebe_o_nivel_e_o_2_5_nao(self):
        p = gemini.build_payload(self.user(), thinking="minimal")
        self.assertEqual(p["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertNotIn("thinkingConfig", gemini.build_payload(self.user())["generationConfig"])
        self.assertNotIn("thinkingConfig", gemini._payload_for("gemini-2.5-flash", p)["generationConfig"])
        self.assertEqual(gemini._payload_for("gemini-3.8-flash", p)["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertEqual(gemini._payload_for("gemini-3.8-flash", p, "upper")["generationConfig"]["thinkingConfig"], {"thinkingLevel": "MINIMAL"})

    def test_api_recusa_a_grafia_tenta_outra_e_lembra(self):
        gemini._think_mode.clear()
        self.queue += [http_error(400, "Invalid value at 'generation_config.thinking_config.thinking_level'", "INVALID_ARGUMENT"),
                       ok_response("oi"), ok_response("de novo")]
        gemini.generate(self.user(), ["gemini-3.8-flash"], thinking="minimal")
        self.assertEqual(self.level_sent(0), {"thinkingLevel": "minimal"})
        self.assertEqual(self.level_sent(1), {"thinkingLevel": "MINIMAL"})
        gemini.generate(self.user(), ["gemini-3.8-flash"], thinking="minimal")
        self.assertEqual(self.level_sent(2), {"thinkingLevel": "MINIMAL"})      # já sabe qual grafia vale

    def test_modelo_que_nao_aceita_fica_sem_o_nivel_para_sempre(self):
        gemini._think_mode.clear()
        bad = lambda: http_error(400, "Thinking level is not supported for this model", "INVALID_ARGUMENT")
        self.queue += [bad(), bad(), ok_response("oi"), ok_response("2")]
        gemini.generate(self.user(), ["gemini-3.9-x"], thinking="low")
        self.assertIsNone(self.level_sent(2))
        gemini.generate(self.user(), ["gemini-3.9-x"], thinking="low")
        self.assertIsNone(self.level_sent(3))
        self.assertEqual(len(self.calls), 4)

    def test_erro_400_que_nao_e_de_raciocinio_nao_e_engolido(self):
        gemini._think_mode.clear()
        self.queue += [http_error(400, "texto grande demais", "INVALID_ARGUMENT")]
        with self.assertRaises(gemini.GeminiError):
            gemini.generate(self.user(), ["gemini-3.8-flash"], thinking="low")
        self.assertEqual(len(self.calls), 1)

    def test_tempo_limite_do_passo_chega_ao_urlopen(self):
        seen = []
        orig = gemini._urlopen
        gemini._urlopen = lambda req, timeout=None: seen.append(timeout) or orig(req, timeout)
        self.queue += [ok_response("ok")]
        list(gemini.stream(self.user(), ["gemini-3.8-flash"], timeout=45))
        self.assertEqual(seen, [45])


if __name__ == "__main__":
    unittest.main()
