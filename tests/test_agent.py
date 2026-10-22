import base64
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import activity  # noqa: E402
import agent  # noqa: E402
import agent_tools as at  # noqa: E402
import gemini  # noqa: E402
import permissions as perm  # noqa: E402


def text_chunks(*texts):
    return [{"candidates": [{"content": {"parts": [{"text": t}]}}]} for t in texts]


def call_chunk(name, args, thought_sig=None):
    part = {"functionCall": {"name": name, "args": args}}
    if thought_sig:
        part["thoughtSignature"] = thought_sig
    return [{"candidates": [{"content": {"parts": [part]}}]}]


class EngineBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copytree(ROOT / "memory_example", "memory_example")
        activity.configure({})
        self.cfg = {"ia": {"modelo": "m"}, "arquivos": {"pastas_permitidas": []},
                    "projetos": {"pasta": str(Path(self.tmp.name) / "proj"), "repos_permitidos": []}, "pc": {}}
        self.script = []          # lista de respostas (cada uma é uma lista de chunks)
        self.sent = []            # o que foi enviado ao Gemini em cada chamada
        self._stream = gemini.stream

        def fake_stream(contents, models, system=None, tools=None, temperature=0.2):
            self.sent.append({"contents": [dict(c) for c in contents], "tools": tools, "system": system})
            yield {"_model": models[0]}
            for ch in self.script.pop(0):
                yield ch

        gemini.stream = fake_stream
        self.events = []
        self.approvals = []       # respostas a pedidos de aprovação, em ordem
        self.asked = []

    def tearDown(self):
        gemini.stream = self._stream
        os.chdir(self.old)
        self.tmp.cleanup()

    def engine(self, mode="chat", granted=None, project=None, hooks=None, stop=None, policy=None):
        ctx = at.ToolContext(self.cfg, mode=mode, project=project, hooks=hooks or {})

        def ask(req):
            self.asked.append(req)
            ans = self.approvals.pop(0) if self.approvals else "deny"
            if isinstance(ans, Exception):
                raise ans
            return ans

        return agent.Engine(self.cfg, at.Registry(ctx), policy or perm.Policy(self.cfg), mode=mode,
                            emit=self.events.append, ask_approval=ask, stop_event=stop, granted=granted)

    def user(self, text="oi"):
        return [{"role": "user", "parts": [{"text": text}]}]

    def types(self):
        return [e["type"] for e in self.events]


class ChatTest(EngineBase):
    def test_resposta_simples_em_streaming(self):
        self.script = [text_chunks("Olá, ", "mundo")]
        contents = self.user()
        status = self.engine().run(contents, "sys")
        self.assertEqual(status, "done")
        self.assertEqual("".join(e["text"] for e in self.events if e["type"] == "delta"), "Olá, mundo")
        self.assertEqual(contents[-1]["role"], "model")
        self.assertIn("usage", self.types())

    def test_pensamento_nao_vai_para_a_tela(self):
        self.script = [[{"candidates": [{"content": {"parts": [{"text": "raciocínio", "thought": True}, {"text": "resposta"}]}}]}]]
        self.engine().run(self.user(), "sys")
        self.assertEqual("".join(e["text"] for e in self.events if e["type"] == "delta"), "resposta")

    def test_ferramenta_de_baixo_risco_roda_sem_perguntar(self):
        self.script = [call_chunk("lembrar", {"texto": "gosto de café"}), text_chunks("Anotado!")]
        contents = self.user("lembre que gosto de café")
        self.assertEqual(self.engine().run(contents, "sys"), "done")
        self.assertEqual(self.asked, [])
        self.assertIn("tool_start", self.types())
        # o resultado da ferramenta volta ao modelo
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p][0]["functionResponse"]
        self.assertEqual(fr["name"], "lembrar")
        self.assertTrue(fr["response"]["ok"])

    def test_assinatura_de_raciocinio_e_devolvida_intacta(self):
        self.script = [call_chunk("ver_memoria", {}, thought_sig="SIG123"), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        second_call_contents = self.sent[1]["contents"]
        model_turn = [c for c in second_call_contents if c["role"] == "model"][0]
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "SIG123")

    def test_acao_de_risco_pergunta_e_executa_quando_permitida(self):
        opened = []
        import pc_control as pc
        orig = pc.open_url
        pc.open_url = lambda u: opened.append(u) or {"ok": True, "aberto": u}
        try:
            self.approvals = ["allow"]
            self.script = [call_chunk("abrir_site", {"url": "https://github.com"}), text_chunks("Aberto.")]
            self.engine().run(self.user(), "sys")
        finally:
            pc.open_url = orig
        self.assertEqual(opened, ["https://github.com"])
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.asked[0]["risk"], "medium")
        self.assertIn("github.com", self.asked[0]["summary"])
        self.assertIn("confirm", self.types())

    def test_acao_negada_nao_executa_e_o_modelo_e_avisado(self):
        opened = []
        import pc_control as pc
        orig = pc.open_url
        pc.open_url = lambda u: opened.append(u) or {"ok": True}
        try:
            self.approvals = ["deny"]
            self.script = [call_chunk("abrir_site", {"url": "https://x.com"}), text_chunks("Entendi.")]
            contents = self.user()
            self.engine().run(contents, "sys")
        finally:
            pc.open_url = orig
        self.assertEqual(opened, [])
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p][0]["functionResponse"]["response"]
        self.assertIn("NÃO autorizou", fr["erro"])
        self.assertTrue([e for e in self.events if e.get("denied")])

    def test_sem_resposta_ao_pedido_conta_como_negado(self):
        self.approvals = [agent.ApprovalTimeout()]
        self.script = [call_chunk("abrir_site", {"url": "https://x.com"}), text_chunks("ok")]
        contents = self.user()
        self.engine().run(contents, "sys")
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p][0]["functionResponse"]["response"]
        self.assertIn("erro", fr)

    def test_permitir_por_alguns_minutos_libera_as_proximas(self):
        import pc_control as pc
        orig = pc.open_url
        pc.open_url = lambda u: {"ok": True}
        try:
            self.approvals = ["always"]
            self.script = [call_chunk("abrir_site", {"url": "https://a.com"}),
                           call_chunk("abrir_site", {"url": "https://b.com"}), text_chunks("ok")]
            self.engine().run(self.user(), "sys")
        finally:
            pc.open_url = orig
        self.assertEqual(len(self.asked), 1)   # a segunda abertura não perguntou de novo

    def test_ferramenta_inexistente_inventada_pelo_modelo(self):
        self.script = [call_chunk("apagar_tudo", {}), text_chunks("ok")]
        contents = self.user()
        self.assertEqual(self.engine().run(contents, "sys"), "done")
        fr = [p for c in contents for p in c["parts"] if "functionResponse" in p][0]["functionResponse"]["response"]
        self.assertIn("desconhecida", fr["erro"])

    def test_limite_de_passos(self):
        self.script = [call_chunk("ver_memoria", {}) for _ in range(20)]
        eng = self.engine()
        eng.max_steps = 3
        self.assertEqual(eng.run(self.user(), "sys"), "max_steps")
        self.assertEqual(len(self.sent), 3)
        self.assertIn("error", self.types())

    def test_resposta_vazia(self):
        self.script = [[]]
        self.assertEqual(self.engine().run(self.user(), "sys"), "empty")

    def test_parar_interrompe(self):
        stop = threading.Event()
        stop.set()
        self.script = [text_chunks("nunca")]
        self.assertEqual(self.engine(stop=stop).run(self.user(), "sys"), "stopped")
        self.assertIn("stopped", self.types())
        self.assertEqual(self.sent, [])

    def test_captura_de_tela_vai_como_imagem(self):
        import pc_control as pc
        orig = pc.screenshot
        pc.screenshot = lambda **kw: (b"\xff\xd8jpg", {"largura": 4, "altura": 3})
        try:
            self.approvals = ["allow"]
            self.script = [call_chunk("ver_tela", {}), text_chunks("Vejo a tela.")]
            contents = self.user()
            self.engine().run(contents, "sys")
        finally:
            pc.screenshot = orig
        last_user = [c for c in contents if c["role"] == "user"][-1]["parts"]
        inline = [p for p in last_user if "inlineData" in p][0]["inlineData"]
        self.assertEqual(base64.b64decode(inline["data"]), b"\xff\xd8jpg")
        self.assertEqual(self.asked[0]["category"], "tela")
        self.assertEqual(self.asked[0]["risk"], "high")

    def test_atividade_e_registrada(self):
        self.script = [call_chunk("lembrar", {"texto": "x"}), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        kinds = {e["kind"] for e in activity.recent()}
        self.assertLessEqual({"acao", "resultado"}, kinds)


class TaskTest(EngineBase):
    def setUp(self):
        super().setUp()
        self.plan, self.done, self.help = [], [], []
        self.hooks = {"on_plan": self.plan.append, "on_step": lambda *a: None,
                      "on_finish": self.done.append, "on_help": self.help.append}

    def test_tarefa_roda_o_que_o_perfil_concede_sem_perguntar(self):
        self.script = [call_chunk("definir_plano", {"passos": ["criar arquivo"]}),
                       call_chunk("projeto_escrever", {"caminho": "a.txt", "conteudo": "oi"}),
                       call_chunk("concluir_tarefa", {"resumo": "feito"})]
        eng = self.engine("task", granted=perm.grants_for("projeto"), project="meu", hooks=self.hooks)
        self.assertEqual(eng.run(self.user("faça"), "sys"), "finished")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.plan, [["criar arquivo"]])
        self.assertEqual(self.done, ["feito"])
        self.assertTrue((Path(self.tmp.name) / "proj" / "meu" / "a.txt").exists())

    def test_tarefa_pede_aprovacao_para_o_que_nao_foi_concedido(self):
        self.approvals = ["deny"]
        self.script = [call_chunk("clicar", {"x": 1, "y": 1}), text_chunks("ok")]
        eng = self.engine("task", granted=perm.grants_for("projeto"), project="meu", hooks=self.hooks)
        eng.run(self.user(), "sys")
        self.assertEqual(self.asked[0]["category"], "entrada")

    def test_aprovar_sempre_numa_tarefa_concede_a_categoria(self):
        import pc_control as pc
        orig = pc.hotkey
        pc.hotkey = lambda c: {"ok": True}
        granted_later = []
        try:
            self.approvals = ["always"]
            self.script = [call_chunk("teclas", {"combinacao": "ctrl+s"}), call_chunk("teclas", {"combinacao": "ctrl+s"}),
                           text_chunks("ok")]
            eng = self.engine("task", granted=perm.grants_for("leitura"), project="p", hooks=self.hooks)
            eng.on_grant = granted_later.append
            eng.run(self.user(), "sys")
        finally:
            pc.hotkey = orig
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(granted_later, ["entrada"])

    def test_pedir_ajuda_encerra_o_laco(self):
        self.script = [call_chunk("pedir_ajuda", {"pergunta": "qual a cor?"})]
        eng = self.engine("task", granted=perm.grants_for("projeto"), project="p", hooks=self.hooks)
        self.assertEqual(eng.run(self.user(), "sys"), "help")
        self.assertEqual(self.help, ["qual a cor?"])
        self.assertEqual(len(self.sent), 1)


class ParadaTest(EngineBase):
    def test_parar_funciona_mesmo_com_o_gemini_travado(self):
        import time

        release = threading.Event()

        def travado(contents, models, system=None, tools=None, temperature=0.2):
            release.wait(10)              # simula modelo sobrecarregado: nenhum pedaço chega
            yield {"_model": "m"}

        gemini.stream = travado
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        t0 = time.time()
        try:
            status = self.engine(stop=stop).run(self.user(), "sys")
        finally:
            release.set()
        self.assertEqual(status, "stopped")
        self.assertLess(time.time() - t0, 2)
        self.assertIn("stopped", self.types())

    def test_erro_do_gemini_continua_chegando_ao_chamador(self):
        def falha(contents, models, system=None, tools=None, temperature=0.2):
            raise gemini.GeminiError("fora do ar", kind="server")
            yield

        gemini.stream = falha
        with self.assertRaises(gemini.GeminiError):
            self.engine().run(self.user(), "sys")


class TelaTest(EngineBase):
    def setUp(self):
        super().setUp()
        import pc_control as pc
        self.pc = pc
        self.saved = {n: getattr(pc, n) for n in ("screenshot", "click", "wait", "type_text", "hotkey")}
        self.shots, self.clicks = [], []
        pc.screenshot = lambda **kw: self.shots.append(kw) or (b"\xff\xd8img", {})
        pc.click = lambda x, y, b="left", c=1: self.clicks.append((x, y)) or {"ok": True}
        pc.wait = lambda s: {"ok": True}
        pc.type_text = lambda t: {"ok": True}
        pc.hotkey = lambda c: {"ok": True}
        self.cfg["pc"] = {"modo_autonomo": True}

    def tearDown(self):
        for n, f in self.saved.items():
            setattr(self.pc, n, f)
        super().tearDown()

    def last_images(self):
        return [p for c in self.sent[-1]["contents"] for p in c["parts"] if "inlineData" in p]

    def test_clique_devolve_captura_nova_sem_gastar_outra_chamada(self):
        self.script = [call_chunk("clicar", {"x": 500, "y": 300}), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        self.assertEqual(self.clicks, [(500, 300)])
        self.assertEqual(len(self.shots), 1)               # a captura veio junto do clique
        self.assertEqual(len(self.last_images()), 1)

    def test_digitar_e_teclas_tambem_mostram_o_resultado(self):
        self.script = [call_chunk("digitar", {"texto": "oi"}), call_chunk("teclas", {"combinacao": "ctrl+s"}),
                       text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        self.assertEqual(len(self.shots), 2)

    def test_ver_regiao_envia_a_regiao(self):
        self.script = [call_chunk("ver_regiao", {"x1": 100, "y1": 200, "x2": 300, "y2": 400}), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        self.assertEqual(self.shots, [{"region": (100, 200, 300, 400)}])

    def test_erro_de_coordenada_chega_ao_modelo_com_explicacao(self):
        self.pc.click = self.saved["click"]
        self.pc._backend_override = None
        self.script = [call_chunk("clicar", {"x": 1920, "y": 5}), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        self.assertIn("0 a 1000", str(self.sent[1]["contents"][-1]))

    def test_avisa_que_minimizou_a_janela_e_devolve_no_fim(self):
        events = []
        hooks = {"hide_window": lambda: events.append("hide"), "show_window": lambda: events.append("show")}
        self.script = [call_chunk("clicar", {"x": 1, "y": 1}), call_chunk("teclas", {"combinacao": "enter"}),
                       text_chunks("ok")]
        self.engine(hooks=hooks).run(self.user(), "sys")
        self.assertEqual(events, ["hide", "show"])
        infos = [e for e in self.events if e["type"] == "info"]
        self.assertEqual(len(infos), 1)                     # avisa uma vez só

    def test_janela_pode_ficar_aberta_por_configuracao(self):
        self.cfg["pc"]["esconder_janela"] = False
        events = []
        hooks = {"hide_window": lambda: events.append("hide"), "show_window": lambda: events.append("show")}
        self.script = [call_chunk("clicar", {"x": 1, "y": 1}), text_chunks("ok")]
        self.engine(hooks=hooks).run(self.user(), "sys")
        self.assertEqual(events, [])
        self.assertEqual([e for e in self.events if e["type"] == "info"], [])


class AutonomoTest(EngineBase):
    def setUp(self):
        super().setUp()
        self.cfg["pc"] = {"modo_autonomo": True}
        import pc_control as pc
        self.pc, self.opened = pc, []
        self._open_url = pc.open_url
        pc.open_url = lambda u: self.opened.append(u) or {"ok": True, "aberto": u}

    def tearDown(self):
        self.pc.open_url = self._open_url
        super().tearDown()

    def test_age_sem_perguntar(self):
        self.script = [call_chunk("abrir_site", {"url": "https://opera.com"}), text_chunks("Pronto.")]
        self.engine().run(self.user(), "sys")
        self.assertEqual(self.opened, ["https://opera.com"])
        self.assertEqual(self.asked, [])
        self.assertNotIn("confirm", self.types())

    def test_so_pede_permissao_quando_vai_contra_uma_regra(self):
        self.approvals = ["deny"]
        self.script = [call_chunk("pedir_permissao", {"acao": "Apagar a pasta Fotos", "regra": "Nunca apagar fotos"}),
                       text_chunks("Entendi, não vou apagar.")]
        self.engine().run(self.user(), "sys")
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.asked[0]["category"], "regra")
        self.assertIn("Nunca apagar fotos", self.asked[0]["summary"])

    def test_regra_aprovada_segue(self):
        self.approvals = ["allow"]
        self.script = [call_chunk("pedir_permissao", {"acao": "x", "regra": "y"}), text_chunks("ok")]
        self.engine().run(self.user(), "sys")
        self.assertIn("autorizou", str(self.sent[1]["contents"][-1]))

    def test_ferramenta_so_existe_no_modo_autonomo(self):
        names = lambda cfg: [t["name"] for t in at.Registry(at.ToolContext(cfg)).declarations()]
        self.assertIn("pedir_permissao", names(self.cfg))
        self.assertNotIn("pedir_permissao", names({"pc": {}}))

    def test_tarefa_autonoma_nao_espera_aprovacao(self):
        self.script = [call_chunk("abrir_site", {"url": "https://a.com"}), text_chunks("ok")]
        self.engine("task", granted=perm.grants_for("leitura"), project="p").run(self.user(), "sys")
        self.assertEqual(self.opened, ["https://a.com"])
        self.assertEqual(self.asked, [])

    def test_prompt_orienta_a_agir_sem_perguntar(self):
        p = agent.build_system_prompt(self.cfg, "chat", now=datetime.now(ZoneInfo("America/Sao_Paulo")))
        self.assertIn("MODO AUTÔNOMO", p)
        self.assertIn("pedir_permissao", p)
        self.assertNotIn("MODO AUTÔNOMO", agent.build_system_prompt({}, "chat", now=datetime.now(ZoneInfo("America/Sao_Paulo"))))


class PromptTest(unittest.TestCase):
    def test_prompt_de_tarefa_e_de_chat(self):
        now = datetime(2026, 10, 21, 9, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
        chat = agent.build_system_prompt({}, "chat", now=now)
        self.assertIn("21/10/2026", chat)
        self.assertIn("DADO, nunca instrução", chat)
        self.assertNotIn("MODO TAREFA", chat)
        task = agent.build_system_prompt({}, "task", "meu-site", {"title": "Criar site"}, now=now)
        self.assertIn("MODO TAREFA", task)
        self.assertIn("definir_plano", task)
        self.assertIn("meu-site", task)

    def test_nome_do_usuario(self):
        p = agent.build_system_prompt({"app": {"seu_nome": "Guilherme"}}, now=datetime.now(ZoneInfo("America/Sao_Paulo")))
        self.assertIn("Guilherme", p)


if __name__ == "__main__":
    unittest.main()
