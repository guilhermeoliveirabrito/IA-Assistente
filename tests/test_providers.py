import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from assistente.ia import gemini, llm, providers
from assistente.nucleo import usage


class FakeResp:
    def __init__(self, lines):
        self.lines = [(l if isinstance(l, bytes) else l.encode()) for l in lines]

    def __iter__(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sse(*events):
    out = []
    for e in events:
        out += ["data: " + json.dumps(e) + "\n", "\n"]
    out.append("data: [DONE]\n")
    return FakeResp(out)


def http_error(code, message="x"):
    return urllib.error.HTTPError("u", code, "err", {}, __import__("io").BytesIO(json.dumps({"error": {"message": message}}).encode()))


HIST = [
    {"role": "user", "parts": [{"text": "abre o bloco de notas"}]},
    {"role": "model", "parts": [{"text": "ok", "thought": True}, {"functionCall": {"name": "abrir_aplicativo", "args": {"nome": "notepad"}}}]},
    {"role": "user", "parts": [{"functionResponse": {"name": "abrir_aplicativo", "response": {"ok": True}}},
                               {"inlineData": {"mimeType": "image/jpeg", "data": "QUJD"}}, {"text": "(captura)"}]},
]
TOOLS = [{"name": "abrir_aplicativo", "description": "abre",
          "parameters": {"type": "OBJECT", "properties": {"nome": {"type": "STRING", "enum": ["a"]}}, "required": ["nome"]}}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.saved = (providers._urlopen, providers.ENV_FILE, dict(os.environ), llm._cfg, gemini._urlopen, gemini.api_key)
        self.reqs = []
        providers.ENV_FILE = Path(".env")
        for k in [p["env"] for p in providers.PRESETS.values() if p["env"]] + ["GEMINI_API_KEY"]:
            os.environ.pop(k, None)
        gemini.load_dotenv = lambda path=".env": None
        usage.configure({})

    def tearDown(self):
        providers._urlopen, providers.ENV_FILE, env, llm._cfg, gemini._urlopen, gemini.api_key = self.saved
        os.environ.clear()
        os.environ.update(env)
        os.chdir(self.old)
        self.tmp.cleanup()


class ConversaoTest(Base):
    def test_openai_ferramentas_e_imagem(self):
        msgs = providers.to_openai(HIST, "sistema", vision=True)
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant", "tool", "user"])
        a = msgs[2]
        self.assertIsNone(a["content"])                               # o pensamento (thought) não vai
        self.assertEqual(json.loads(a["tool_calls"][0]["function"]["arguments"]), {"nome": "notepad"})
        self.assertEqual(msgs[3]["tool_call_id"], a["tool_calls"][0]["id"])
        self.assertEqual(msgs[4]["content"][0]["type"], "image_url")
        self.assertTrue(msgs[4]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_sem_visao_troca_imagem_por_aviso(self):
        msgs = providers.to_openai(HIST, None, vision=False)
        self.assertIn("omitido", json.dumps(msgs[-1], ensure_ascii=False))
        self.assertNotIn("image_url", json.dumps(msgs))

    def test_chamada_sem_resposta_e_removida(self):
        hist = HIST[:2] + [{"role": "user", "parts": [{"text": "esquece"}]}]
        msgs = providers.to_openai(hist, None)
        self.assertFalse(any(m.get("tool_calls") for m in msgs))
        self.assertEqual(msgs[-1]["role"], "user")

    def test_resposta_orfa_vira_texto(self):
        hist = [{"role": "user", "parts": [{"functionResponse": {"name": "x", "response": {"a": 1}}}]}]
        msgs = providers.to_openai(hist, None)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertIn("resultado de x", msgs[0]["content"])

    def test_esquema_em_minusculas(self):
        s = providers._schema(TOOLS[0])
        self.assertEqual(s["type"], "object")
        self.assertEqual(s["properties"]["nome"]["type"], "string")
        self.assertEqual(providers._schema({"name": "t"}), {"type": "object", "properties": {}})

    def test_anthropic_blocos(self):
        msgs = providers.to_anthropic(HIST)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[1]["content"][0]["type"], "tool_use")
        types = [b["type"] for b in msgs[2]["content"]]
        self.assertEqual(types[0], "tool_result")                      # resultado de ferramenta sempre primeiro
        self.assertIn("image", types)

    def test_has_image(self):
        self.assertTrue(providers.has_image(HIST))
        self.assertFalse(providers.has_image(HIST[:1]))


class StreamTest(Base):
    def cfg(self, **ia):
        os.environ["GROQ_API_KEY"] = "gsk_testkey123"
        return {"ia": {"ordem_provedores": ["groq"], **ia}}

    def test_openai_texto_e_ferramenta_em_formato_gemini(self):
        d = providers.definition(self.cfg(), "groq")
        providers._urlopen = lambda req, timeout=0: (self.reqs.append(req), sse(
            {"choices": [{"delta": {"content": "Oi"}}]}, {"choices": [{"delta": {"content": " tudo"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "abrir_aplicativo", "arguments": "{\"nome\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"x\"}"}}]}}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}))[1]
        chunks = list(providers.stream_one(d, HIST[:1], "sys", TOOLS))
        self.assertEqual(chunks[0], {"_model": "groq:llama-3.3-70b-versatile"})
        self.assertEqual(gemini.text_of({"candidates": [{"content": {"parts": [p for c in chunks[1:] for p in gemini.parts_of(c)]}}]}), "Oi tudo")
        fc = [p["functionCall"] for c in chunks[1:] for p in gemini.parts_of(c) if "functionCall" in p]
        self.assertEqual(fc, [{"name": "abrir_aplicativo", "args": {"nome": "x"}, "id": "c1"}])
        req = self.reqs[0]
        self.assertTrue(req.full_url.endswith("/openai/v1/chat/completions"))
        self.assertEqual(req.get_header("Authorization"), "Bearer gsk_testkey123")
        body = json.loads(req.data)
        self.assertEqual(body["tools"][0]["function"]["parameters"]["type"], "object")

    def test_anthropic(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test1234"
        d = providers.definition({}, "anthropic")
        providers._urlopen = lambda req, timeout=0: (self.reqs.append(req), sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Olá"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "abrir_aplicativo"}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"nome\": \"y\"}"}},
            {"type": "message_delta", "usage": {"output_tokens": 3}}))[1]
        chunks = list(providers.stream_one(d, HIST[:1], "sys", TOOLS))
        parts = [p for c in chunks[1:] for p in gemini.parts_of(c)]
        self.assertEqual(parts[0], {"text": "Olá"})
        self.assertEqual(parts[1]["functionCall"], {"name": "abrir_aplicativo", "args": {"nome": "y"}, "id": "tu1"})
        self.assertEqual(self.reqs[0].get_header("X-api-key"), "sk-ant-test1234")
        body = json.loads(self.reqs[0].data)
        self.assertEqual(body["system"], "sys")
        self.assertEqual(body["tools"][0]["input_schema"]["type"], "object")

    def test_erros_viram_tipos_conhecidos(self):
        d = providers.definition(self.cfg(), "groq")
        for code, kind in ((429, "quota"), (401, "auth"), (503, "server"), (404, "model")):
            def boom(req, timeout=0, c=code):
                raise http_error(c, "model not found" if c == 404 else "x")
            providers._urlopen = boom
            with self.assertRaises(gemini.GeminiError) as cm:
                next(providers.stream_one(d, HIST[:1]))
            self.assertEqual(cm.exception.kind, kind, code)

    def test_collect_junta_texto(self):
        d = providers.definition(self.cfg(), "groq")
        providers._urlopen = lambda req, timeout=0: sse({"choices": [{"delta": {"content": "a"}}]}, {"choices": [{"delta": {"content": "b"}}]})
        obj = providers.collect(providers.stream_one(d, HIST[:1]))
        self.assertEqual(gemini.text_of(obj), "ab")


class ConfigTest(Base):
    def test_ordem_filtra_invalidos_e_repetidos(self):
        self.assertEqual(providers.order({"ia": {"ordem_provedores": ["groq", "x", "groq", "gemini"]}}), ["groq", "gemini"])
        self.assertEqual(providers.order({}), providers.DEFAULT_ORDER)

    def test_so_usa_quem_tem_chave(self):
        cfg = {"ia": {"ordem_provedores": ["gemini", "groq", "ollama"]}}
        self.assertEqual([d["id"] for d in providers.extras(cfg)], ["ollama"])        # ollama é local, não precisa de chave
        os.environ["GROQ_API_KEY"] = "gsk_abcdefgh"
        self.assertEqual([d["id"] for d in providers.extras(cfg)], ["groq", "ollama"])

    def test_modelo_pode_ser_trocado(self):
        d = providers.definition({"provedores": {"groq": {"modelo": "outro-modelo"}}}, "groq")
        self.assertEqual(d["modelo"], "outro-modelo")

    def test_salvar_chave_no_env_sem_duplicar(self):
        providers.save_key("groq", "gsk_primeira123")
        providers.save_key("groq", "gsk_segunda1234")
        providers.save_key("cerebras", "csk_abcdefgh")
        lines = Path(".env").read_text().splitlines()
        self.assertEqual(sorted(lines), ["CEREBRAS_API_KEY=csk_abcdefgh", "GROQ_API_KEY=gsk_segunda1234"])
        self.assertEqual(os.environ["GROQ_API_KEY"], "gsk_segunda1234")
        providers.save_key("groq", "")
        self.assertNotIn("GROQ_API_KEY", Path(".env").read_text())
        for bad in ("curta", "com espaço dentro 1234", "a\nb=12345678"):
            with self.assertRaises(ValueError):
                providers.save_key("groq", bad)
        with self.assertRaises(ValueError):
            providers.save_key("ollama", "x" * 10)

    def test_status_nao_vaza_a_chave(self):
        os.environ["GROQ_API_KEY"] = "gsk_segredo123"
        st = providers.status({})
        self.assertNotIn("gsk_segredo123", json.dumps(st))
        self.assertTrue([s for s in st if s["id"] == "groq"][0]["configurada"])


class CadeiaTest(Base):
    """llm.stream: Gemini primeiro; se ele não puder, o próximo provedor com chave."""

    def setUp(self):
        super().setUp()
        self.gem = []
        self._g = (gemini.stream, gemini.generate)
        gemini.stream = lambda *a, **k: self.gen()
        os.environ["GROQ_API_KEY"] = "gsk_abcdefgh"
        llm.configure({"ia": {"ordem_provedores": ["gemini", "groq"]}})

    def tearDown(self):
        gemini.stream, gemini.generate = self._g
        super().tearDown()

    def gen(self):
        if isinstance(self.gem, Exception):
            raise self.gem
        yield {"_model": "gemini-x"}
        yield {"candidates": [{"content": {"parts": [{"text": "gemini"}]}}]}

    def groq_ok(self):
        providers._urlopen = lambda req, timeout=0: sse({"choices": [{"delta": {"content": "groq"}}]})

    def run_stream(self, contents=None):
        chunks = list(llm.stream(contents or HIST[:1], ["gemini-x"]))
        return chunks[0]["_model"], gemini.text_of({"candidates": [{"content": {"parts": [p for c in chunks[1:] for p in gemini.parts_of(c)]}}]})

    def test_gemini_ok_nao_chama_outros(self):
        providers._urlopen = lambda *a, **k: self.fail("não devia chamar")
        self.assertEqual(self.run_stream(), ("gemini-x", "gemini"))

    def test_cota_do_gemini_cai_para_o_groq(self):
        self.gem = gemini.GeminiError("cota", 429, "quota")
        self.groq_ok()
        model, text = self.run_stream()
        self.assertEqual((model, text), ("groq:llama-3.3-70b-versatile", "groq"))

    def test_sem_chave_do_gemini_tambem_cai(self):
        self.gem = gemini.GeminiError("sem chave", kind="auth")
        self.groq_ok()
        self.assertEqual(self.run_stream()[1], "groq")

    def test_erro_nao_recuperavel_nao_troca(self):
        self.gem = gemini.GeminiError("bloqueado", kind="blocked")
        providers._urlopen = lambda *a, **k: self.fail("não devia chamar")
        with self.assertRaises(gemini.GeminiError):
            self.run_stream()

    def test_tudo_falhou_levanta_o_erro_do_gemini(self):
        self.gem = gemini.GeminiError("cota do gemini", 429, "quota", retry_after=30)

        def boom(req, timeout=0):
            raise http_error(429)
        providers._urlopen = boom
        with self.assertRaises(gemini.GeminiError) as cm:
            self.run_stream()
        self.assertEqual(cm.exception.retry_after, 30)                 # a pausa das tarefas depende do erro do Gemini

    def test_imagem_pula_provedor_sem_visao(self):
        self.gem = gemini.GeminiError("cota", 429, "quota")
        providers._urlopen = lambda *a, **k: self.fail("groq não enxerga")
        with self.assertRaises(gemini.GeminiError):
            self.run_stream(HIST)

    def test_imagem_usa_provedor_com_visao(self):
        self.gem = gemini.GeminiError("cota", 429, "quota")
        os.environ["MISTRAL_API_KEY"] = "mis_abcdefgh"
        llm.configure({"ia": {"ordem_provedores": ["gemini", "groq", "mistral"]}})
        providers._urlopen = lambda req, timeout=0: sse({"choices": [{"delta": {"content": "vi"}}]})
        self.assertEqual(self.run_stream(HIST), ("mistral:mistral-small-latest", "vi"))

    def test_principal_pode_ser_outro_provedor(self):
        llm.configure({"ia": {"ordem_provedores": ["groq", "gemini"]}})
        self.groq_ok()
        self.assertEqual(self.run_stream()[1], "groq")

    def test_generate_json_pede_json_no_texto(self):
        gemini.generate = lambda *a, **k: (_ for _ in ()).throw(gemini.GeminiError("cota", 429, "quota"))
        providers._urlopen = lambda req, timeout=0: (self.reqs.append(req), sse({"choices": [{"delta": {"content": "{\"a\": 1}"}}]}))[1]
        obj = llm.generate(HIST[:1], ["m"], json_mode=True)
        self.assertEqual(gemini.text_of(obj), '{"a": 1}')
        self.assertIn("JSON", json.dumps(json.loads(self.reqs[0].data)["messages"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
