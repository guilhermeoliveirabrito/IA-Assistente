import threading
import time
import unittest

from assistente.nucleo import bus as busmod
from assistente.pc import pc_control as pc
from assistente.servicos import capturas, live
from tests.test_chatsvc import Base, call, text


class GateTest(unittest.TestCase):
    def test_pausa_espera_e_retoma(self):
        g = live.Gate()
        self.assertFalse(g.paused)
        g.pause(60)
        self.assertTrue(g.paused)
        done = threading.Event()
        threading.Thread(target=lambda: (g.wait(), done.set()), daemon=True).start()
        time.sleep(0.3)
        self.assertTrue(g.waiting)
        self.assertFalse(done.is_set())
        g.resume()
        self.assertTrue(done.wait(2))

    def test_pausa_esquecida_expira(self):
        t = [1000.0]
        g = live.Gate(clock=lambda: t[0])
        g.pause(30)
        self.assertTrue(g.paused)
        t[0] += 31
        self.assertFalse(g.paused)

    def test_parar_destrava_a_espera(self):
        g, stop = live.Gate(), threading.Event()
        g.pause(60)
        done = threading.Event()
        threading.Thread(target=lambda: (g.wait(stop), done.set()), daemon=True).start()
        time.sleep(0.2)
        stop.set()
        self.assertTrue(done.wait(2))


class LiveTest(unittest.TestCase):
    def test_acompanha_eventos_e_controla(self):
        lv = live.Live()
        lv.register("chat", "abc", "Minha conversa")
        lv.feed({"scope": "chat", "conversation_id": "abc", "type": "tool_start", "summary": "Abrir o Spotify", "ts": 1})
        lv.feed({"scope": "chat", "conversation_id": "abc", "type": "tool_end", "ok": True, "summary": "Abrir o Spotify", "text": "ok", "ts": 2})
        lv.feed({"scope": "chat", "conversation_id": "abc", "type": "delta", "text": "Pronto."})
        lv.feed({"scope": "task", "task_id": "zzz", "type": "tool_start", "summary": "ignorado"})
        (r,) = lv.runs()
        self.assertEqual((r["key"], r["status"], r["current"]), ("chat:abc", "running", "Escrevendo…"))
        self.assertEqual(r["log"][0]["text"], "Abrir o Spotify")
        self.assertIn("→ ok", r["log"][1]["text"])
        self.assertEqual(lv.pause("chat:abc"), ["chat:abc"])
        self.assertEqual(lv.runs()[0]["status"], "paused")
        self.assertEqual(lv.pause("chat:nada"), [])
        lv.resume()
        self.assertEqual(lv.runs()[0]["status"], "running")
        lv.unregister("chat", "abc")
        self.assertEqual(lv.runs(), [])

    def test_aprovacao_pendente_aparece_e_some(self):
        lv = live.Live()
        lv.register("task", "t1", "Tarefa")
        lv.feed({"scope": "task", "task_id": "t1", "type": "confirm", "summary": "Rodar npm test"})
        self.assertEqual(lv.runs()[0]["status"], "approval")
        lv.feed({"scope": "task", "task_id": "t1", "type": "tool_start", "summary": "Rodar npm test"})
        self.assertEqual(lv.runs()[0]["status"], "running")

    def test_contexto_para_a_explicacao(self):
        lv = live.Live()
        lv.register("task", "t1", "Criar site")
        lv.feed({"scope": "task", "task_id": "t1", "type": "tool_start", "summary": "Escrever index.html"})
        ctx = lv.context_text(["task:t1"])
        self.assertIn("Criar site", ctx)
        self.assertIn("Escrever index.html", ctx)

    def test_via_barramento(self):
        bus = busmod.Bus()
        lv = live.Live(bus)
        lv.start()
        try:
            lv.register("chat", "c1", "Conv")
            bus.publish({"scope": "chat", "conversation_id": "c1", "type": "tool_start", "summary": "Fazer X"})
            for _ in range(50):
                if lv.runs()[0]["current"] == "Fazer X":
                    break
                time.sleep(0.02)
            self.assertEqual(lv.runs()[0]["current"], "Fazer X")
        finally:
            lv.stop()


class MotorPausaTest(Base):
    def test_chat_pausa_no_ponto_seguro_e_retoma(self):
        lv = live.Live()
        self.svc.live = lv
        first = []

        def pop(i=-1):
            item = list.pop(self.script, i)
            if not first:                                   # pausa durante a 1ª chamada ao modelo
                first.append(1)
                lv.pause(None, 60)
            return item

        self.script = _ScriptList([call("memoria_ler", {}), text("terminei")], pop)
        cid = self.svc.send(None, "leia minha memória")
        for _ in range(100):
            runs = lv.runs()
            if runs and runs[0]["paused_waiting"]:
                break
            time.sleep(0.03)
        self.assertTrue(lv.runs()[0]["paused_waiting"])
        self.assertTrue(self.svc.is_running(cid))
        self.assertEqual(len(self.sent), 1)                  # a ferramenta ainda não rodou: só houve a 1ª chamada
        lv.resume()
        self.wait_done(cid)
        self.assertEqual(lv.runs(), [])                      # terminou: saiu do registro
        self.assertEqual(len(self.sent), 2)


class _ScriptList(list):
    """Lista cujo pop() é interceptado (para pausar no meio da 1ª chamada ao modelo)."""

    def __init__(self, items, pop):
        super().__init__(items)
        self._pop = pop

    def pop(self, i=-1):
        return self._pop(i) if self._pop else super().pop(i)


class CapturasTest(unittest.TestCase):
    JPEG = b"\xff\xd8\xff" + b"0" * 20

    def setUp(self):
        self.lv = live.Live()
        self.cfg = {"ia": {"modelo": "m"}, "pc": {"ver_tela_pelo_celular": True, "pausa_maxima_minutos": 5}}
        self.cap = capturas.Capturas(self.cfg, self.lv, grab=lambda: self.JPEG)
        self.cap.settle_timeout = 0.3
        self._gen = capturas.llm.generate
        self.prompts = []

        def fake(contents, models, **kw):
            self.prompts.append(contents[0]["parts"][0]["text"])
            return {"candidates": [{"content": {"parts": [{"text": "Ele está no navegador."}]}}]}

        capturas.llm.generate = fake

    def tearDown(self):
        capturas.llm.generate = self._gen

    def test_pausa_fotografa_e_explica_com_o_registro(self):
        self.lv.register("task", "t1", "Pesquisar preços")
        self.lv.feed({"scope": "task", "task_id": "t1", "type": "tool_start", "summary": "Abrir o site da loja"})
        self.lv._runs["task:t1"].gate.waiting = True          # simula o motor parado no ponto seguro
        out = self.cap.snapshot()
        self.assertEqual(out["paused"], ["task:t1"])
        self.assertTrue(out["settled"])
        self.assertEqual(out["text"], "Ele está no navegador.")
        self.assertIn("Abrir o site da loja", self.prompts[0])
        self.assertEqual(self.cap.get(out["id"]), self.JPEG)
        self.assertTrue(self.lv.runs()[0]["status"] == "paused")
        self.lv.resume()
        self.assertEqual(self.lv.runs()[0]["status"], "running")

    def test_avisa_quando_ainda_terminava_um_passo(self):
        self.lv.register("task", "t1", "Tarefa")
        out = self.cap.snapshot()
        self.assertFalse(out["settled"])
        self.assertIn("terminando um passo", out["text"])

    def test_sem_nada_rodando_so_descreve_a_tela(self):
        out = self.cap.snapshot()
        self.assertEqual(out["paused"], [])
        self.assertNotIn("PAUSADO", self.prompts[0])

    def test_falha_na_explicacao_ainda_entrega_a_foto_e_o_registro(self):
        def boom(*a, **k):
            raise RuntimeError("cota")

        capturas.llm.generate = boom
        self.lv.register("chat", "c", "Conv")
        self.lv.feed({"scope": "chat", "conversation_id": "c", "type": "tool_start", "summary": "Clicar no botão"})
        out = self.cap.snapshot()
        self.assertIn("Não consegui gerar a explicação", out["text"])
        self.assertIn("Clicar no botão", out["text"])
        self.assertTrue(out["id"])

    def test_sem_foto_retoma_o_que_pausou(self):
        def fail():
            raise pc.PCError("sem tela")

        cap = capturas.Capturas(self.cfg, self.lv, grab=fail)
        self.lv.register("chat", "c", "Conv")
        with self.assertRaises(capturas.CaptureError):
            cap.snapshot()
        self.assertEqual(self.lv.runs()[0]["status"], "running")

    def test_desligado_recusa(self):
        self.cfg["pc"]["ver_tela_pelo_celular"] = False
        for fn in (self.cap.snapshot, self.cap.screen):
            with self.assertRaises(capturas.CaptureError):
                fn()

    def test_guarda_so_as_ultimas(self):
        ids = [self.cap.snapshot()["id"] for _ in range(capturas.KEEP + 2)]
        with self.assertRaises(capturas.CaptureError):
            self.cap.get(ids[0])
        self.assertEqual(self.cap.get(ids[-1]), self.JPEG)


if __name__ == "__main__":
    unittest.main()
