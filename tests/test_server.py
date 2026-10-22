import base64
import http.client
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gemini  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 30


def text(*t):
    return [{"candidates": [{"content": {"parts": [{"text": x}]}}]} for x in t]


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copy(ROOT / "config.yaml", "config.yaml")
        shutil.copytree(ROOT / "memory_example", "memory_example")
        cfg = settings.load_config()
        cfg["projetos"]["pasta"] = str(Path(self.tmp.name) / "proj")
        self.script = []
        self._stream = gemini.stream

        def fake(contents, models, system=None, tools=None, temperature=0.2):
            yield {"_model": models[0]}
            for ch in self.script.pop(0):
                yield ch

        gemini.stream = fake
        server.Handler.fails = {}
        self.srv = server.start(cfg, port=0, mode="local")
        self.token = self.srv.token
        self.port = self.srv.port

    def tearDown(self):
        gemini.stream = self._stream
        self.srv.shutdown()
        os.chdir(self.old)
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, auth=True, host=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if auth:
            h["X-Access-Code"] = self.token
        h.update(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        payload = r.read()
        conn.close()
        try:
            return r.status, json.loads(payload), r
        except ValueError:
            return r.status, payload, r

    # ---- acesso -------------------------------------------------------------------------

    def test_sem_codigo_nao_entra(self):
        self.assertEqual(self.req("GET", "/api/state", auth=False)[0], 401)
        status, _, r = self.req("GET", "/", auth=False)
        self.assertEqual(status, 302)
        self.assertIn("/login", r.getheader("Location"))

    def test_codigo_errado_e_recusado(self):
        status, _, _ = self.req("GET", "/api/state", auth=False, headers={"X-Access-Code": "errado"})
        self.assertEqual(status, 401)

    def test_codigo_na_url_vira_cookie(self):
        status, _, r = self.req("GET", f"/?k={self.token}", auth=False)
        self.assertEqual(status, 302)
        cookie = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        status, body, _ = self.req("GET", "/", auth=False, headers={"Cookie": cookie.split(";")[0]})
        self.assertEqual(status, 200)
        self.assertIn(b"app.js", body)

    def test_host_estranho_e_recusado(self):
        self.assertEqual(self.req("GET", "/api/state", host="atacante.com")[0], 403)

    def test_origem_estranha_nao_muda_nada(self):
        status, _, _ = self.req("POST", "/api/conversations", {}, headers={"Origin": "http://atacante.com"})
        self.assertEqual(status, 403)

    def test_muitas_tentativas_bloqueiam(self):
        for _ in range(server.FAIL_LIMIT):
            self.req("GET", "/api/state", auth=False, headers={"X-Access-Code": "x"})
        self.assertEqual(self.req("GET", f"/?k={self.token}", auth=False)[0], 429)

    def test_arquivos_fora_da_pasta_web_nao_sao_servidos(self):
        for p in ("/../server.py", "/..%2fserver.py", "/%2e%2e/config.yaml", "/static/../server.py"):
            status, _, _ = self.req("GET", p)
            self.assertEqual(status, 404, p)

    def test_estaticos(self):
        for p, ctype in (("/app.js", "javascript"), ("/app.css", "css"), ("/views.js", "javascript"), ("/md.js", "javascript"),
                         ("/manifest.webmanifest", "json"), ("/icon.svg", "svg")):
            status, _, r = self.req("GET", p)
            self.assertEqual(status, 200, p)
            self.assertIn(ctype, r.getheader("Content-Type"))

    # ---- API ------------------------------------------------------------------------------

    def wait_idle(self, cid):
        end = time.time() + 6
        while time.time() < end:
            if cid not in self.srv.app.chat.running():
                return
            time.sleep(0.03)
        self.fail("a resposta não terminou")

    def test_estado(self):
        status, st, _ = self.req("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(st["usage"]["requests_day"]["limit"], 250)
        self.assertIn("permission_window_minutes", st)
        self.assertIn("projeto", st["profiles"])

    def test_chat_completo_com_anexo(self):
        self.script.append(text("Oi, ", "**tudo bem**?"))
        att = {"name": "foto.png", "data": base64.b64encode(PNG).decode()}
        status, r, _ = self.req("POST", "/api/chat", {"text": "olá", "attachments": [att]})
        self.assertEqual(status, 200)
        cid = r["conversation_id"]
        self.wait_idle(cid)
        status, conv, _ = self.req("GET", f"/api/conversations/{cid}")
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])
        self.assertEqual(conv["messages"][1]["text"], "Oi, **tudo bem**?")
        stored = conv["messages"][0]["attachments"][0]["stored"]
        status, data, resp = self.req("GET", f"/api/conversations/{cid}/files/{stored}")
        self.assertEqual((status, resp.getheader("Content-Type")), (200, "image/png"))
        self.assertEqual(data, PNG)
        status, lst, _ = self.req("GET", "/api/conversations")
        self.assertEqual(lst["conversations"][0]["id"], cid)

    def test_anexo_falso_e_recusado(self):
        att = {"name": "x.png", "data": base64.b64encode(b"nao sou imagem").decode()}
        status, r, _ = self.req("POST", "/api/chat", {"text": "oi", "attachments": [att]})
        self.assertEqual(status, 400)
        self.assertIn("error", r)

    def test_base64_invalido(self):
        status, _, _ = self.req("POST", "/api/chat", {"text": "oi", "attachments": [{"name": "a.png", "data": "!!!"}]})
        self.assertEqual(status, 400)

    def test_renomear_e_apagar_conversa(self):
        self.script.append(text("ok"))
        cid = self.req("POST", "/api/chat", {"text": "oi"})[1]["conversation_id"]
        self.wait_idle(cid)
        self.assertEqual(self.req("POST", f"/api/conversations/{cid}/rename", {"title": "Novo nome"})[1]["title"], "Novo nome")
        self.assertEqual(self.req("POST", f"/api/conversations/{cid}/rename", {"title": " "})[0], 400)
        self.assertEqual(self.req("DELETE", f"/api/conversations/{cid}")[0], 200)
        self.assertEqual(self.req("GET", f"/api/conversations/{cid}")[0], 404)

    def test_id_de_conversa_invalido(self):
        self.assertEqual(self.req("GET", "/api/conversations/../../etc")[0], 404)
        self.assertEqual(self.req("GET", "/api/conversations/ZZZZZZZZZZZZ")[0], 404)

    def test_aprovacao_inexistente(self):
        self.assertEqual(self.req("POST", "/api/approve", {"id": "nada", "answer": "allow"})[0], 404)
        self.assertEqual(self.req("POST", "/api/approve", {"answer": "allow"})[0], 400)

    def test_memoria(self):
        status, m, _ = self.req("GET", "/api/memory")
        names = [f["name"] for f in m["files"]]
        self.assertIn("perfil.md", names)
        m = self.req("PUT", "/api/memory/file", {"name": "perfil.md", "content": "Sou o Gui"})[1]
        self.assertEqual(next(f for f in m["files"] if f["name"] == "perfil.md")["content"], "Sou o Gui")
        self.assertEqual(self.req("PUT", "/api/memory/file", {"name": "../x.md", "content": "a"})[0], 400)
        self.assertEqual(self.req("PUT", "/api/memory/file", {"name": "a.txt", "content": "a"})[0], 400)
        self.assertEqual(self.req("DELETE", "/api/memory/file?name=perfil.md")[0], 400)
        self.req("PUT", "/api/memory/file", {"name": "extra.md", "content": "x"})
        self.assertEqual(self.req("DELETE", "/api/memory/file?name=extra.md")[0], 200)
        m = self.req("POST", "/api/memory/notes", {"text": "gosto de café"})[1]
        self.assertTrue(any("café" in n for n in m["notes"]))
        m = self.req("DELETE", "/api/memory/notes/1")[1]
        self.assertFalse(any("café" in n for n in m["notes"]))

    def test_ajustes(self):
        status, s, _ = self.req("GET", "/api/settings")
        self.assertEqual(s["values"]["limites.requisicoes_por_dia"], 250)
        status, r, _ = self.req("POST", "/api/settings", {"changes": {"app.seu_nome": "Gui"}})
        self.assertEqual((status, r["changed"]), (200, ["app.seu_nome"]))
        self.assertEqual(self.req("GET", "/api/state")[1]["name"], "Gui")
        status, r, _ = self.req("POST", "/api/settings", {"changes": {"limites.requisicoes_por_dia": -1}})
        self.assertEqual(status, 400)
        self.assertEqual(self.req("POST", "/api/settings", {"changes": {"ia.chave": "x"}})[0], 400)

    def test_tarefas_e_historico(self):
        status, t, _ = self.req("POST", "/api/tasks", {"title": "Teste", "prompt": "faça algo", "profile": "leitura"})
        self.assertEqual(status, 200)
        self.assertEqual(self.req("POST", "/api/tasks", {"prompt": ""})[0], 400)
        self.assertEqual(self.req("POST", "/api/tasks", {"prompt": "x", "profile": "deus"})[0], 400)
        self.assertEqual(self.req("GET", f"/api/tasks/{t['id']}")[0], 200)
        self.assertEqual(self.req("GET", "/api/tasks/abcdefabcd")[0], 404)
        events = self.req("GET", "/api/activity")[1]["events"]
        self.assertTrue(any("Teste" in e["text"] for e in events))
        self.assertEqual(self.req("DELETE", "/api/activity")[0], 200)
        self.assertEqual(self.req("GET", "/api/activity")[1]["events"], [])

    def test_acesso_em_modo_local_nao_expoe_enderecos_de_rede(self):
        a = self.req("GET", "/api/access")[1]
        self.assertEqual(a["mode"], "local")
        self.assertEqual(a["urls"], [])
        self.assertEqual(a["code"], self.token)

    def test_google_sem_credenciais_explica_o_que_fazer(self):
        st = self.req("GET", "/api/state")[1]
        self.assertEqual(st["google"], {"credentials": False, "connected": False, "running": False})
        status, r, _ = self.req("POST", "/api/google/connect")
        self.assertEqual(status, 400)
        self.assertIn("credentials.json", r["error"])

    def test_modo_autonomo_aparece_no_estado_e_nos_ajustes(self):
        self.assertTrue(self.req("GET", "/api/state")[1]["autonomous"])
        self.req("POST", "/api/settings", {"changes": {"pc.modo_autonomo": False}})
        self.assertFalse(self.req("GET", "/api/state")[1]["autonomous"])

    def test_voz_estado_e_ajustes(self):
        v = self.req("GET", "/api/state")[1]["voice"]
        self.assertEqual((v["enabled"], v["state"], v["phrase"]), (False, "off", "ei assistente"))
        self.assertEqual(self.req("POST", "/api/settings", {"changes": {"voz.frase_de_ativacao": "ok <b>"}})[0], 400)
        status, r, _ = self.req("POST", "/api/settings", {"changes": {"voz.frase_de_ativacao": "oi jarvis"}})
        self.assertEqual(status, 200)
        self.assertEqual(self.req("GET", "/api/voice")[1]["phrase"], "oi jarvis")
        # ativar sem as bibliotecas/modelo: informa o motivo em vez de quebrar
        self.req("POST", "/api/settings", {"changes": {"voz.ativada": True}})
        v = self.req("GET", "/api/voice")[1]
        self.assertTrue(v["enabled"])
        if not v["deps_ok"] or not v["model_ready"]:
            self.assertEqual(v["state"], "error")
            self.assertTrue(v["detail"])
        self.assertEqual(self.req("POST", "/api/voice/pause", {"paused": True})[0], 200)

    def test_comando_de_voz_abre_conversa_e_fala_a_resposta(self):
        spoken = []
        self.srv.app.chat.on_voice_reply = spoken.append
        self.script = [text("Pronto, abri o Spotify.")]
        self.srv.app.voice_command("abre o Spotify")
        cid = self.srv.app._voice_conv["id"]
        for _ in range(100):
            if not self.srv.app.chat.is_running(cid):
                break
            time.sleep(0.05)
        for _ in range(100):
            if spoken:
                break
            time.sleep(0.05)
        self.assertEqual(spoken, ["Pronto, abri o Spotify."])
        conv = self.req("GET", f"/api/conversations/{cid}")[1]
        self.assertEqual(conv["messages"][0]["text"], "abre o Spotify")
        # segundo comando logo depois continua a mesma conversa
        self.script = [text("Feito.")]
        self.srv.app.voice_command("e agora toca rock")
        self.assertEqual(self.srv.app._voice_conv["id"], cid)

    def test_consumo_por_modelo_e_ajuste(self):
        u = self.req("GET", "/api/usage")[1]
        self.assertEqual([m["model"] for m in u["models"]][:1], ["gemini-3.8-flash"])
        status, u, _ = self.req("POST", "/api/usage/calibrate", {"model": "gemini-3.8-flash", "requests": 12})
        self.assertEqual((status, u["models"][0]["requests_day"]["used"]), (200, 12))
        self.assertEqual(self.req("POST", "/api/usage/calibrate", {"model": "gemini-3.8-flash", "requests": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/usage/calibrate", {"model": "../x", "requests": 1})[0], 400)

    def test_troca_de_modelo_chega_a_interface_em_tempo_real(self):
        import usage
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{self.port}", "X-Access-Code": self.token})
        r = conn.getresponse()
        r.fp.readline(); r.fp.readline(); r.fp.readline(); r.fp.readline()
        usage.note_model("gemini-3.8-flash")
        usage.note_model("gemini-3.6-flash", [("gemini-3.8-flash", "quota")])
        seen = b""
        end = time.time() + 5
        while time.time() < end and b"model_switch" not in seen:
            seen += r.fp.readline()
        conn.close()
        self.assertIn(b"model_switch", seen)
        self.assertIn(b"Troquei de gemini-3.8-flash para gemini-3.6-flash", seen)

    def test_json_invalido(self):
        status, _, _ = self.req("POST", "/api/chat", raw=b"{nao", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_corpo_gigante_e_recusado(self):
        status, _, _ = self.req("POST", "/api/chat", raw=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(server.MAX_JSON + 1)})
        self.assertEqual(status, 413)

    def test_eventos_em_tempo_real(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{self.port}", "X-Access-Code": self.token})
        r = conn.getresponse()
        self.assertEqual(r.getheader("Content-Type").split(";")[0], "text/event-stream")
        self.assertIn(b"hello", r.fp.readline() + r.fp.readline() + r.fp.readline() + r.fp.readline())
        self.script.append(text("pronto"))
        self.req("POST", "/api/chat", {"text": "oi"})
        seen = b""
        end = time.time() + 6
        while time.time() < end and b'"done"' not in seen:
            seen += r.fp.readline()
        conn.close()
        self.assertIn(b'"delta"', seen)
        self.assertIn(b'"done"', seen)


if __name__ == "__main__":
    unittest.main()
