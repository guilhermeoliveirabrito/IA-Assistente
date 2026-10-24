import base64
import http.client
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from assistente import server
from assistente.ia import gemini
from assistente.nucleo import settings

ROOT = Path(__file__).resolve().parent.parent

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

        def fake(contents, models, system=None, tools=None, temperature=0.2, **kw):
            yield {"_model": models[0]}
            yield from self.script.pop(0)

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
        self.assertEqual(st["google"], {"credentials": False, "connected": False, "running": False,
                                         "calendar_write": False, "send_email": False})
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

    def test_lembretes_rotas_disparo_e_tarefa(self):


        self.assertEqual(self.req("POST", "/api/reminders", {"text": "x", "when": "ontem"})[0], 400)
        st, r, _ = self.req("POST", "/api/reminders", {"text": "tomar água", "in_minutes": 10, "alarm": True})
        self.assertEqual(st, 200)
        rid = r["item"]["id"]
        self.assertEqual(self.req("GET", "/api/state")[1]["reminders"], {"count": 1, "ringing": 0})
        self.assertTrue([j for j in self.req("GET", "/api/state")[1]["checks"]["jobs"] if j["id"] == "lembretes"])
        q = self.srv.app.bus.subscribe()
        sent = []
        self.srv.app.notifier.notify = lambda kind, title, msg, priority=3: sent.append((kind, msg, priority)) or True
        rem = self.srv.app.reminders
        rem.clock = lambda: time.time() + 700                     # passa o tempo
        rem.check_due()
        events = []
        while not q.empty():
            events.append(q.get())
        ev = [e for e in events if e["type"] == "reminder"][0]
        self.assertTrue(ev["alarm"] and ev["ringing"])
        self.assertEqual(sent, [("lembrete", "tomar água", 5)])
        self.assertEqual(self.req("GET", "/api/state")[1]["reminders"]["ringing"], 1)
        self.assertEqual(self.req("POST", f"/api/reminders/{rid}/snooze", {"minutes": 5})[0], 200)
        self.assertEqual(self.req("POST", f"/api/reminders/{rid}/dismiss")[0], 200)
        self.assertEqual(self.req("DELETE", f"/api/reminders/{rid}")[0], 200)
        self.assertEqual(self.req("DELETE", f"/api/reminders/{rid}")[0], 404)
        # lembrete que manda o assistente executar vira uma tarefa de leitura
        rem.clock = time.time
        self.assertEqual(self.req("POST", "/api/reminders", {"text": "resuma meus e-mails", "in_minutes": 5, "run": True})[0], 200)
        rem.clock = lambda: time.time() + 700
        rem.check_due()
        titles = [t["title"] for t in self.req("GET", "/api/tasks")[1]["tasks"]]
        self.assertTrue(any("resuma meus e-mails" in t for t in titles))

    def test_busca_e_exporta_conversa(self):
        self.script = [text("Claro, em São Paulo faz sol.")]
        cid = self.req("POST", "/api/chat", {"text": "tempo em sao paulo?"})[1]["conversation_id"]
        time.sleep(0.8)
        r = self.req("GET", "/api/conversations/search?q=S%C3%A3o%20Paulo")[1]["results"]
        self.assertEqual([x["id"] for x in r], [cid])
        self.assertEqual(self.req("GET", "/api/conversations/search?q=a")[1]["results"], [])
        st, body, resp = self.req("GET", f"/api/conversations/{cid}/export")
        self.assertEqual(st, 200)
        self.assertIn("attachment", resp.getheader("Content-Disposition"))
        self.assertIn(b"sao paulo", body.lower())
        self.assertEqual(self.req("GET", "/api/conversations/search?q=x", auth=False)[0], 401)

    def test_resumo_do_dia(self):
        from assistente.ia import ai
        from assistente.servicos import briefing

        saved = ai.ask_text
        ai.ask_text = lambda prompt, model: "## Bom dia, teste"
        try:
            self.assertEqual(self.req("GET", "/api/briefing")[1]["latest"], {})
            self.req("POST", "/api/reminders", {"text": "tomar água", "in_minutes": 5})
            self.srv.app.bus.subscribe()
            sent = []
            self.srv.app.notifier.notify = lambda kind, title, msg, priority=3: sent.append((kind, msg)) or True
            rec = self.srv.app.briefing.run()
            self.assertEqual(rec["text"], "## Bom dia, teste")
            self.assertEqual(self.req("GET", "/api/briefing")[1]["latest"]["text"], "## Bom dia, teste")
            self.assertEqual(sent, [("resumo", "Bom dia, teste")])
            self.assertTrue([j for j in self.req("GET", "/api/state")[1]["checks"]["jobs"] if j["id"] == "resumo_do_dia"])
            data = self.srv.app._briefing_data()                      # sem Google: agenda e e-mails indisponíveis, o resto vem
            self.assertIsNone(data["agenda"])
            self.assertEqual(data["encomendas"], [])
            self.assertEqual(self.req("POST", "/api/briefing/run")[0], 200)
            self.assertEqual(briefing.default(), self.srv.app.briefing)
        finally:
            ai.ask_text = saved

    def test_provedores_rotas_chave_nunca_volta(self):

        st, r, _ = self.req("GET", "/api/providers")
        self.assertEqual(st, 200)
        self.assertEqual(r["order"][0], "gemini")
        self.assertFalse([p for p in r["providers"] if p["id"] == "groq"][0]["configurada"])
        st, r, _ = self.req("POST", "/api/providers/key", {"id": "groq", "key": "gsk_segredo12345"})
        self.assertEqual(st, 200)
        self.assertNotIn("gsk_segredo12345", json.dumps(r))
        self.assertTrue([p for p in r["providers"] if p["id"] == "groq"][0]["configurada"])
        self.assertIn("GROQ_API_KEY=gsk_segredo12345", Path(".env").read_text())
        self.assertEqual(self.req("POST", "/api/providers/key", {"id": "groq", "key": "x y"})[0], 400)
        self.assertEqual(self.req("POST", "/api/providers/key", {"id": "ollama", "key": "abcdefgh12"})[0], 400)
        # a ordem e o modelo passam pelos ajustes
        st, r, _ = self.req("POST", "/api/settings", {"changes": {"ia.ordem_provedores": ["groq", "gemini"],
                                                                  "provedores.groq.modelo": "llama-x"}})
        self.assertEqual(st, 200)
        self.assertEqual(self.req("GET", "/api/providers")[1]["order"], ["groq", "gemini"])
        self.assertEqual(self.req("POST", "/api/settings", {"changes": {"ia.ordem_provedores": ["nada"]}})[0], 400)
        os.environ.pop("GROQ_API_KEY", None)

    def test_rastreio_rotas_e_estado(self):
        from assistente.servicos import tracking

        class P:
            configured = True
            n = 0

            def fetch(self, code):
                P.n += 1
                ev = [{"time_iso": "2026-10-21T08:00:00Z", "description": "Postado", "location": "SP"}]
                if P.n > 1:
                    ev.append({"time_iso": "2026-10-22T08:00:00Z", "description": "Saiu para entrega", "location": "SP"})
                return tracking.parse_info({"track_info": {"latest_status": {"status": "InTransit"}, "tracking": {
                    "providers": [{"provider": {"name": "Correios"}, "events": ev}]}}})

        app = self.srv.app
        app.tracker.provider = P()
        self.assertEqual(self.req("POST", "/api/tracking", {"code": "x"})[0], 400)
        status, r, _ = self.req("POST", "/api/tracking", {"code": "aa123456789br", "name": "Fone"})
        self.assertEqual(status, 200)
        tid = r["item"]["id"]
        for _ in range(100):                       # a primeira consulta roda em segundo plano
            it = self.req("GET", "/api/tracking")[1]["items"][0]
            if it["found"]:
                break
            time.sleep(0.05)
        self.assertTrue(it["found"])
        self.assertEqual(self.req("GET", "/api/state")[1]["tracking"], {"unread": 1, "configured": True, "count": 1})
        self.assertEqual(self.req("POST", "/api/tracking", {"code": "AA123456789BR"})[0], 400)   # duplicado
        self.assertEqual(self.req("POST", f"/api/tracking/{tid}/check")[0], 200)
        for _ in range(100):
            if len(self.req("GET", "/api/tracking")[1]["items"][0]["events"]) == 2:
                break
            time.sleep(0.05)
        self.assertEqual(self.req("GET", "/api/tracking")[1]["items"][0]["events"][0]["text"], "Saiu para entrega")
        checks = self.req("GET", "/api/state")[1]["checks"]
        self.assertIn("rastreio", [j["id"] for j in checks["jobs"]])
        self.assertEqual(self.req("POST", f"/api/tracking/{tid}/read")[0], 200)
        self.assertEqual(self.req("GET", "/api/state")[1]["tracking"]["unread"], 0)
        self.assertEqual(self.req("POST", f"/api/tracking/{tid}/rename", {"name": "Tênis"})[1]["item"]["name"], "Tênis")
        self.assertEqual(self.req("POST", "/api/tracking/ffffffffffff/check")[0], 404)
        self.assertEqual(self.req("DELETE", f"/api/tracking/{tid}")[0], 200)
        self.assertEqual(self.req("DELETE", f"/api/tracking/{tid}")[0], 404)

    def test_rastreio_sem_chave(self):
        os.environ.pop("TRACK17_KEY", None)
        self.assertFalse(self.req("GET", "/api/tracking")[1]["configured"])
        self.assertEqual(self.req("POST", "/api/tracking/check")[0], 400)

    def test_consumo_por_modelo_e_ajuste(self):
        u = self.req("GET", "/api/usage")[1]
        self.assertEqual([m["model"] for m in u["models"]][:1], ["gemini-3.8-flash"])
        status, u, _ = self.req("POST", "/api/usage/calibrate", {"model": "gemini-3.8-flash", "requests": 12})
        self.assertEqual((status, u["models"][0]["requests_day"]["used"]), (200, 12))
        self.assertEqual(self.req("POST", "/api/usage/calibrate", {"model": "gemini-3.8-flash", "requests": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/usage/calibrate", {"model": "../x", "requests": 1})[0], 400)

    def test_troca_de_modelo_chega_a_interface_em_tempo_real(self):
        from assistente.nucleo import usage
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
