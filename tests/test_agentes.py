import os
import tempfile
import threading
import unittest

from assistente.ia import agent, agent_tools, agentes, debate, gemini


class Chdir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()


class AgentesTest(Chdir):
    def test_lista_tem_geral_primeiro_e_debate(self):
        ids = [a["id"] for a in agentes.all_agents()]
        self.assertEqual(ids[0], "geral")
        self.assertIn("debate", ids)
        self.assertGreaterEqual(len(ids), 8)

    def test_desconhecido_cai_no_geral(self):
        self.assertEqual(agentes.get("nao-existe")["id"], "geral")
        self.assertEqual(agentes.get(None)["id"], "geral")

    def test_prompt_do_geral_vazio_e_do_especialista_tem_instrucao(self):
        self.assertEqual(agentes.prompt_block("geral"), "")
        self.assertIn("Programador", agentes.prompt_block("programador"))
        self.assertIn("regras de segurança", agentes.prompt_block("programador"))

    def test_agente_personalizado_criar_listar_apagar(self):
        a = agentes.create("Chef", "Você é um chef que sugere receitas com o que tenho em casa.", "🍳")
        self.assertTrue(a["personalizado"])
        self.assertEqual(agentes.get(a["id"])["nome"], "Chef")
        self.assertIn(a["id"], [x["id"] for x in agentes.all_agents()])
        self.assertEqual(agentes.get(a["id"])["fora"], ["tela", "entrada"])
        agentes.delete(a["id"])
        self.assertFalse(agentes.exists(a["id"]))

    def test_validacoes(self):
        for nome, ins in [("", "x" * 20), ("Chef", "curto"), ("Geral", "x" * 20)]:
            with self.assertRaises(agentes.AgentError):
                agentes.create(nome, ins)
        agentes.create("Chef", "x" * 20)
        with self.assertRaises(agentes.AgentError):
            agentes.create("chef", "y" * 20)
        with self.assertRaises(agentes.AgentError):
            agentes.delete("geral")

    def test_prompt_do_sistema_inclui_especialidade(self):
        cfg = {"app": {}}
        self.assertNotIn("ESPECIALIDADE", agent.build_system_prompt(cfg))
        self.assertIn("ESPECIALIDADE", agent.build_system_prompt(cfg, agent="redator"))

    def test_ferramentas_filtradas_por_agente(self):
        cfg = {"pc": {}, "projetos": {"pasta": "p"}}
        ctx = agent_tools.ToolContext(cfg, mode="chat")
        geral = agent_tools.Registry(ctx)
        red = agent_tools.Registry(ctx, agentes.get("redator")["fora"])
        self.assertTrue(geral.has("ver_tela") and geral.has("debater"))
        self.assertFalse(red.has("ver_tela") or red.has("clicar"))
        self.assertTrue(red.has("pesquisar_web"))


class ConselhoTest(unittest.TestCase):
    def setUp(self):
        self.calls, self._ask = [], debate._ask

    def tearDown(self):
        debate._ask = self._ask

    def fake(self, escolha):
        def f(cfg, system, prompt, temperature, **kw):
            self.calls.append(system)
            if "monta conselhos" in system:
                return escolha
            if "PRESIDENTE" in system:
                return "**Veredito:** siga."
            return "análise do especialista"
        debate._ask = f

    def test_fluxo_escolhe_consulta_e_decide(self):
        self.fake("1. Contador | impostos e custos\n2. Médico | saúde e rotina\n3. Coach | motivação e metas")
        notes = []
        out = debate.run_council({}, "Devo abrir um negócio?", progress=notes.append)
        self.assertEqual(out["parecer"], "**Veredito:** siga.")
        self.assertEqual([x["nome"] for x in out["lados"]], ["Contador", "Médico", "Coach"])
        self.assertEqual(out["chamadas"], 5)
        self.assertEqual(len(notes), 3)
        self.assertTrue(any("Contador" in c for c in self.calls))

    def test_escolha_ruim_cai_nos_especialistas_padrao(self):
        self.fake("não sei")
        out = debate.run_council({}, "Tema")
        self.assertEqual(len(out["lados"]), 3)
        self.assertEqual(out["lados"][0]["nome"], debate.DEFAULT_COUNCIL[0][0])

    def test_etapas_e_estagios(self):
        self.assertEqual([s[0] for s in debate.steps({}, "conselho")], ["conselho", "argumentos", "juiz"])
        self.assertEqual(debate.stage_of("Escolhendo os especialistas do conselho…"), "conselho")
        self.assertEqual(debate.stage_of("O presidente do conselho está decidindo…"), "juiz")

    def test_parse_ignora_duplicados_e_lixo(self):
        got = debate._parse_council("- **Chef** | cozinha e sabor\nsem barra\n- chef | repetido de novo\n3) Nutri | saúde e dieta")
        self.assertEqual([n for n, _ in got], ["Chef", "Nutri"])


class DebateTest(unittest.TestCase):
    def setUp(self):
        self.calls, self._ask = [], debate._ask
        lock = threading.Lock()

        def fake(cfg, system, prompt, temperature, **kw):
            with lock:
                self.calls.append((system, prompt))
            if "JUIZ" in system:
                return "**Veredito:** faça."
            return "argumento do defensor" if "DEFENSOR" in system else "argumento do opositor"

        debate._ask = fake

    def tearDown(self):
        debate._ask = self._ask

    def test_fluxo_padrao_cinco_chamadas_e_so_o_parecer(self):
        notes = []
        out = debate.run({}, "Devo trocar de emprego?", "Usuário: estou entediado", progress=notes.append)
        self.assertEqual(out["parecer"], "**Veredito:** faça.")
        self.assertEqual(len(self.calls), 5)
        judge_system, judge_prompt = self.calls[-1]
        self.assertIn("JUIZ", judge_system)
        self.assertIn("argumento do defensor", judge_prompt)
        self.assertIn("argumento do opositor", judge_prompt)
        self.assertEqual(len(notes), 3)

    def test_lados_nao_veem_o_outro_na_primeira_rodada(self):
        debate.run({"debate": {"rodadas": 0}}, "Comprar um carro?")
        self.assertEqual(len(self.calls), 3)
        for _system, prompt in self.calls[:2]:
            self.assertNotIn("argumento do", prompt)

    def test_replica_mostra_o_argumento_do_outro(self):
        debate.run({"debate": {"rodadas": 1}}, "Tema")
        rebuttals = self.calls[2:4]
        self.assertTrue(any("Argumento do OPOSITOR:\nargumento do opositor" in p for _, p in rebuttals))
        self.assertTrue(any("Argumento do DEFENSOR:\nargumento do defensor" in p for _, p in rebuttals))

    def test_rodadas_limitadas(self):
        self.assertEqual(debate.rodadas({"debate": {"rodadas": 99}}), 2)
        self.assertEqual(debate.rodadas({"debate": {"rodadas": "x"}}), 1)
        self.assertEqual(debate.rodadas({}), 1)

    def test_tema_vazio_e_parada(self):
        with self.assertRaises(ValueError):
            debate.run({}, "   ")
        ev = threading.Event()
        ev.set()
        with self.assertRaises(debate.DebateStopped):
            debate.run({}, "Tema", stop=ev)
        self.assertEqual(self.calls, [])

    def test_pesquisa_opcional_entrega_os_mesmos_fatos_aos_tres(self):
        orig = debate.web_tools.search
        debate.web_tools.search = lambda cfg, q: {"resposta": "O preço subiu 10% em 2026.", "fontes": [{"titulo": "Site", "url": "https://x.org"}]}
        try:
            out = debate.run({"debate": {"pesquisar": True}}, "Vale comprar agora?", progress=lambda t: None)
        finally:
            debate.web_tools.search = orig
        self.assertEqual(out["chamadas"], 6)
        self.assertTrue(out["pesquisou"])
        self.assertEqual(out["fontes"][0]["url"], "https://x.org")
        self.assertTrue(all("subiu 10%" in p for _, p in self.calls))

    def test_pesquisa_que_falha_nao_derruba_o_debate(self):
        orig = debate.web_tools.search

        def boom(cfg, q):
            raise RuntimeError("sem rede")

        debate.web_tools.search = boom
        try:
            out = debate.run({"debate": {"pesquisar": True}}, "Tema")
        finally:
            debate.web_tools.search = orig
        self.assertFalse(out["pesquisou"])
        self.assertEqual(out["chamadas"], 5)

    def test_resultado_traz_argumentos_e_juiz_pede_confianca(self):
        out = debate.run({}, "Tema")
        self.assertIn("argumento do defensor", out["argumentos"]["defensor"])
        self.assertIn("Confiança", self.calls[-1][0])

    def test_erro_do_modelo_sobe(self):
        def boom(cfg, system, prompt, temperature, **kw):
            raise gemini.GeminiError("cota", "quota")

        debate._ask = boom
        with self.assertRaises(gemini.GeminiError):
            debate.run({}, "Tema")


class DebateStreamTest(unittest.TestCase):
    """_ask lê em streaming: não limita o raciocínio e mostra o andamento (pensando/escrevendo/pronto)."""

    def setUp(self):
        self.orig = debate.llm.stream
        self.kw = {}

    def tearDown(self):
        debate.llm.stream = self.orig

    def patch(self, chunks):
        def fake(contents, models, **kw):
            self.kw = kw
            yield {"_model": "m"}
            yield from chunks
        debate.llm.stream = fake

    @staticmethod
    def part(text, thought=False):
        return {"candidates": [{"content": {"parts": [{"text": text, **({"thought": True} if thought else {})}]}}]}

    def test_junta_o_texto_ignora_o_pensamento_e_avisa(self):
        self.patch([self.part("Estou pesando os riscos", True), self.part("Parte 1. "), self.part("Parte 2.")])
        feed = []
        out = debate._ask({}, "s", "p", 0.5, who="pro", feed=lambda *a: feed.append(a))
        self.assertEqual(out, "Parte 1. Parte 2.")
        kinds = [k for _, k, _ in feed]
        self.assertEqual(kinds[0], "start")
        self.assertIn("thought", kinds)
        self.assertEqual(feed[-1], ("Defensor", "done", "Parte 1. Parte 2."))

    def test_nao_limita_o_raciocinio_e_pede_resumo_do_pensamento(self):
        self.patch([self.part("ok")])
        debate._ask({}, "s", "p", 0.5)
        self.assertNotIn("thinking", self.kw)
        self.assertTrue(self.kw["thoughts"])
        self.assertGreaterEqual(self.kw["timeout"], 300)

    def test_nivel_escolhido_em_ajustes_vale(self):
        self.patch([self.part("ok")])
        debate._ask({"ia": {"raciocinio_debate": "high"}}, "s", "p", 0.5)
        self.assertEqual(self.kw["thinking"], "high")

    def test_cai_de_rede_no_meio_tenta_de_novo_uma_vez(self):
        calls = []

        def fake(contents, models, **kw):
            calls.append(1)
            yield {"_model": "m"}
            if len(calls) == 1:
                yield self.part("meio")
                raise debate.gemini.GeminiError("caiu", kind="network")
            yield self.part("inteiro")
        debate.llm.stream = fake
        self.assertEqual(debate._ask({}, "s", "p", 0.5), "inteiro")
        self.assertEqual(len(calls), 2)

    def test_resposta_vazia_da_erro(self):
        self.patch([self.part("só pensando", True)])
        with self.assertRaises(debate.gemini.GeminiError):
            debate._ask({}, "s", "p", 0.5)

    def test_total_de_falas_para_a_barra(self):
        self.assertEqual(debate.total_calls({"debate": {"rodadas": 1}}), 5)
        self.assertEqual(debate.total_calls({"debate": {"rodadas": 0}}), 3)
        self.assertEqual(debate.total_calls({}, "conselho"), 5)

    def test_both_atende_o_parar_enquanto_espera(self):
        import time as _t
        stop = threading.Event()
        orig = debate._ask
        debate._ask = lambda *a, **k: _t.sleep(5) or "x"
        try:
            threading.Timer(0.4, stop.set).start()
            with self.assertRaises(debate.DebateStopped):
                debate._both({}, {"a": ("s", "p")}, check=debate._checker(stop))
        finally:
            debate._ask = orig


if __name__ == "__main__":
    unittest.main()
