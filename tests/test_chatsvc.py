import base64
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import activity  # noqa: E402
import bus as busmod  # noqa: E402
import chatsvc  # noqa: E402
import context  # noqa: E402
import gemini  # noqa: E402
import pc_control as pc  # noqa: E402
import storage  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 30


def text(*t):
    return [{"candidates": [{"content": {"parts": [{"text": x}]}}]} for x in t]


def call(name, args):
    return [{"candidates": [{"content": {"parts": [{"functionCall": {"name": name, "args": args}}]}}]}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copytree(ROOT / "memory_example", "memory_example")
        activity.configure({})
        self.cfg = {"ia": {"modelo": "m"}, "arquivos": {"pastas_permitidas": []}, "pc": {},
                    "projetos": {"pasta": str(Path(self.tmp.name) / "p")}}
        self.script, self.sent = [], []
        self._stream = gemini.stream

        def fake(contents, models, system=None, tools=None, temperature=0.2, **kw):
            self.sent.append({"contents": [dict(c) for c in contents], "system": system})
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            yield {"_model": models[0]}
            for ch in item:
                yield ch

        gemini.stream = fake
        self.bus = busmod.Bus()
        self.q = self.bus.subscribe()
        self.svc = chatsvc.ChatService(self.cfg, self.bus)

    def tearDown(self):
        gemini.stream = self._stream
        self.svc.shutdown()
        for _ in range(100):
            if not self.svc.running():
                break
            time.sleep(0.02)
        os.chdir(self.old)
        self.tmp.cleanup()

    def wait_done(self, cid, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            if not self.svc.is_running(cid):
                return
            time.sleep(0.01)
        self.fail("o chat não terminou")

    def events(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out

    def ask(self, text_, files=None, conv=None):
        cid = self.svc.send(conv, text_, files)
        self.wait_done(cid)
        return cid


class SendTest(Base):
    def test_conversa_nova_resposta_salva_e_titulo(self):
        self.script = [text("Olá, ", "tudo bem!")]
        cid = self.ask("oi, tudo bem com você hoje?")
        conv = storage.load(cid)
        self.assertEqual(conv["title"], "oi, tudo bem com você hoje?")
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])
        self.assertEqual(conv["messages"][1]["text"], "Olá, tudo bem!")
        self.assertEqual(len(conv["contents"]), 2)
        types = [e["type"] for e in self.events()]
        self.assertEqual(types[0], "start")
        self.assertIn("delta", types)
        self.assertEqual(types[-1], "done")

    def test_continua_a_mesma_conversa_com_historico(self):
        self.script = [text("Prazer, Thor."), text("Seu cachorro é o Thor.")]
        cid = self.ask("meu cachorro é o Thor")
        self.ask("qual o nome do meu cachorro?", conv=cid)
        self.assertEqual(len(self.sent[1]["contents"]), 3)
        self.assertEqual(len(storage.load(cid)["messages"]), 4)

    def test_ferramentas_aparecem_na_mensagem_salva(self):
        self.script = [call("lembrar", {"texto": "gosto de café"}), text("Anotado!")]
        cid = self.ask("lembre que gosto de café")
        tools = storage.load(cid)["messages"][1]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertTrue(tools[0]["ok"])
        self.assertIn("café", tools[0]["summary"])

    def test_texto_vazio_sem_anexo(self):
        with self.assertRaises(chatsvc.ChatError):
            self.svc.send(None, "   ")

    def test_mensagem_gigante(self):
        with self.assertRaises(chatsvc.ChatError):
            self.svc.send(None, "x" * 30001)

    def test_conversa_ocupada(self):
        gate = threading.Event()

        def slow(contents, models, system=None, tools=None, temperature=0.2, **kw):
            gate.wait(5)
            yield {"_model": "m"}
            for ch in text("ok"):
                yield ch

        gemini.stream = slow
        cid = self.svc.send(None, "primeira")
        with self.assertRaises(chatsvc.ChatBusy):
            self.svc.send(cid, "segunda")
        gate.set()
        self.wait_done(cid)

    def test_conversa_inexistente(self):
        with self.assertRaises(KeyError):
            self.svc.send("0" * 12, "oi")


class AttachmentTest(Base):
    def test_imagem_vai_como_arquivo_e_texto_como_texto(self):
        self.script = [text("Vejo um quadrado.")]
        cid = self.ask("o que é isto?", [("foto.png", PNG), ("notas.txt", "lembrete: ligar".encode())])
        sent_parts = self.sent[0]["contents"][0]["parts"]
        inline = [p for p in sent_parts if "inlineData" in p][0]["inlineData"]
        self.assertEqual(inline["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(inline["data"]), PNG)
        self.assertTrue(any("lembrete: ligar" in p.get("text", "") for p in sent_parts))
        shown = storage.load(cid)["messages"][0]["attachments"]
        self.assertEqual([a["name"] for a in shown], ["foto.png", "notas.txt"])

    def test_so_anexo_gera_pedido_padrao(self):
        self.script = [text("ok")]
        self.ask("", [("a.png", PNG)])
        self.assertIn("Analise", self.sent[0]["contents"][0]["parts"][-1]["text"])

    def test_anexo_invalido_nao_cria_mensagem(self):
        with self.assertRaises(chatsvc.ChatError):
            self.svc.send(None, "veja", [("virus.exe", b"MZ\x90")])

    def test_limite_de_arquivos(self):
        with self.assertRaises(chatsvc.ChatError):
            self.svc.send(None, "x", [(f"{i}.txt", b"a") for i in range(7)])

    def test_anexo_antigo_continua_disponivel_nas_proximas_mensagens(self):
        self.script = [text("é um quadrado"), text("sim, ainda vejo")]
        cid = self.ask("veja", [("a.png", PNG)])
        self.ask("e agora?", conv=cid)
        first = self.sent[1]["contents"][0]["parts"][0]
        self.assertIn("inlineData", first)


class ErrorTest(Base):
    def test_erro_do_gemini_vira_mensagem_de_erro(self):
        self.script = [gemini.GeminiError("Limite de uso do Gemini atingido.", 429, "quota")]
        cid = self.ask("oi")
        msg = storage.load(cid)["messages"][-1]
        self.assertIn("Limite de uso", msg["error"])
        err = [e for e in self.events() if e["type"] == "error"][0]
        self.assertEqual(err["kind"], "quota")
        # a conversa continua utilizável depois do erro
        self.script = [text("voltei")]
        self.ask("tente de novo", conv=cid)
        self.assertEqual(storage.load(cid)["messages"][-1]["text"], "voltei")

    def test_erro_inesperado(self):
        def boom(*a, **k):
            raise RuntimeError("bug")
            yield

        gemini.stream = boom
        cid = self.ask("oi")
        self.assertIn("inesperado", storage.load(cid)["messages"][-1]["error"])

    def test_parar_resposta(self):
        gate = threading.Event()

        def slow(contents, models, system=None, tools=None, temperature=0.2, **kw):
            yield {"_model": "m"}
            yield text("começo ")[0]
            gate.wait(5)
            yield text("fim")[0]

        gemini.stream = slow
        cid = self.svc.send(None, "fale muito")
        for _ in range(200):
            if any(e["type"] == "delta" for e in self.events()):
                break
            time.sleep(0.01)
        self.svc.stop(cid)
        gate.set()
        self.wait_done(cid)
        msg = storage.load(cid)["messages"][-1]
        self.assertTrue(msg.get("stopped"))
        self.assertNotIn("fim", msg["text"])


class ApprovalTest(Base):
    def setUp(self):
        super().setUp()
        self.opened = []
        self._open = pc.open_url
        pc.open_url = lambda u: self.opened.append(u) or {"ok": True, "aberto": u}

    def tearDown(self):
        pc.open_url = self._open
        super().tearDown()

    def wait_pending(self):
        for _ in range(300):
            if self.svc.pending():
                return self.svc.pending()[0]
            time.sleep(0.01)
        self.fail("sem pedido de aprovação")

    def test_pedido_aparece_na_lista_e_na_interface(self):
        self.script = [call("abrir_site", {"url": "https://github.com"}), text("Abri.")]
        cid = self.svc.send(None, "abra o github")
        req = self.wait_pending()
        self.assertEqual(req["conversation_id"], cid)
        self.assertEqual(req["risk"], "medium")
        self.assertIn("confirm", [e["type"] for e in self.events()])
        self.assertTrue(self.svc.approve(req["id"], "allow"))
        self.wait_done(cid)
        self.assertEqual(self.opened, ["https://github.com"])
        self.assertEqual(self.svc.pending(), [])
        tool = storage.load(cid)["messages"][-1]["tools"][0]
        self.assertTrue(tool["ok"])

    def test_negar(self):
        self.script = [call("abrir_site", {"url": "https://x.com"}), text("Ok, não abri.")]
        cid = self.svc.send(None, "abra")
        self.svc.approve(self.wait_pending()["id"], "deny")
        self.wait_done(cid)
        self.assertEqual(self.opened, [])
        tool = storage.load(cid)["messages"][-1]["tools"][0]
        self.assertTrue(tool["denied"])

    def test_sem_resposta_no_prazo_nega(self):
        self.svc.approval_timeout = 0.2
        self.script = [call("abrir_site", {"url": "https://x.com"}), text("segui")]
        cid = self.ask("abra")
        self.assertEqual(self.opened, [])

    def test_parar_enquanto_espera_aprovacao(self):
        self.script = [call("abrir_site", {"url": "https://x.com"})]
        cid = self.svc.send(None, "abra")
        self.wait_pending()
        self.svc.stop(cid)
        self.wait_done(cid)
        self.assertEqual(self.opened, [])

    def test_resposta_invalida_e_pedido_inexistente(self):
        self.assertFalse(self.svc.approve("nada", "allow"))
        with self.assertRaises(chatsvc.ChatError):
            self.svc.approve("x", "talvez")


class CompactAndRefreshTest(Base):
    def test_compacta_conversa_longa_antes_de_responder(self):
        cid = storage.new_conversation()["id"]
        conv = storage.load(cid)
        for i in range(14):
            conv["contents"] += [{"role": "user", "parts": [{"text": f"p{i} " + "x" * 4000}]},
                                 {"role": "model", "parts": [{"text": f"r{i} " + "y" * 4000}]}]
        storage.save(conv)
        orig = context.ai.ask_text
        context.ai.ask_text = lambda p, model: "- resumo"
        try:
            self.script = [text("certo")]
            self.ask("continue", conv=cid)
        finally:
            context.ai.ask_text = orig
        self.assertTrue(self.sent[0]["contents"][0]["parts"][0]["text"].startswith(context.SUMMARY_MARK))
        notes = [m for m in storage.load(cid)["messages"] if m["role"] == "note"]
        self.assertEqual(len(notes), 1)

    def test_recomecar_com_resumo(self):
        self.script = [text("Anotei.")]
        cid = self.ask("Estou criando um site de padaria")
        orig = context.ai.ask_text
        context.ai.ask_text = lambda p, model: "- site de padaria em andamento"
        try:
            new_id = self.svc.refresh(cid)
        finally:
            context.ai.ask_text = orig
        new = storage.load(new_id)
        self.assertNotEqual(new_id, cid)
        self.assertTrue(new["title"].startswith("Continuação"))
        self.assertIn("site de padaria", new["contents"][0]["parts"][0]["text"])
        self.assertEqual(new["messages"][0]["role"], "note")
        self.script = [text("Vamos continuar o site.")]
        self.ask("onde paramos?", conv=new_id)
        self.assertIn("RESUMO", self.sent[-1]["contents"][0]["parts"][0]["text"].upper())

    def test_nao_resume_conversa_vazia(self):
        cid = storage.new_conversation()["id"]
        with self.assertRaises(chatsvc.ChatError):
            self.svc.refresh(cid)


if __name__ == "__main__":
    unittest.main()
