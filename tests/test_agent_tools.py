import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_tools as at  # noqa: E402
import pc_control as pc  # noqa: E402
import permissions as perm  # noqa: E402
import shutil  # noqa: E402


class FakeSpotify:
    def __init__(self):
        self.calls = []

    def play(self, q, kind="faixa"):
        self.calls.append(("play", q, kind))
        return {"ok": True, "tocando": "X"}

    def pause(self):
        self.calls.append(("pause",))
        return {"ok": True}

    def set_volume(self, v):
        self.calls.append(("volume", v))
        return {"ok": True, "volume": v}

    def now_playing(self):
        return {"tocando": False}


class ToolsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copytree(ROOT / "memory_example", "memory_example")
        self.docs = Path(self.tmp.name) / "docs"
        self.docs.mkdir()
        self.cfg = {"arquivos": {"pastas_permitidas": [str(self.docs)]},
                    "projetos": {"pasta": str(Path(self.tmp.name) / "projetos"), "repos_permitidos": []},
                    "pc": {"aplicativos": {}}}
        self.sp = FakeSpotify()
        self.hooks = {}
        self._pc_saved = {n: getattr(pc, n) for n in ("media", "open_app", "open_url", "screenshot", "click",
                                                      "type_text", "hotkey", "scroll", "wait")}

    def tearDown(self):
        for n, f in self._pc_saved.items():
            setattr(pc, n, f)
        os.chdir(self.old)
        self.tmp.cleanup()

    def reg(self, mode="chat", project=None):
        ctx = at.ToolContext(self.cfg, mode=mode, project=project, spotify=self.sp, hooks=self.hooks)
        return at.Registry(ctx), ctx


class DeclarationsTest(ToolsBase):
    VALID_TYPES = {"STRING", "INTEGER", "NUMBER", "ARRAY", "OBJECT", "BOOLEAN"}

    def test_declaracoes_validas(self):
        reg, _ = self.reg("task")
        names = set()
        for d in reg.declarations():
            self.assertNotIn(d["name"], names)
            names.add(d["name"])
            self.assertTrue(d["description"])
            json.dumps(d)
            params = d.get("parameters")
            if params:
                self.assertEqual(params["type"], "OBJECT")
                self.assertTrue(params["properties"], d["name"])  # a API recusa 'properties' vazio
                self.assertLessEqual(set(params.get("required", [])), set(params["properties"]), d["name"])
                for prop in params["properties"].values():
                    self.assertIn(prop["type"], self.VALID_TYPES)
                    if prop["type"] == "ARRAY":
                        self.assertIn("items", prop)

    def test_toda_ferramenta_tem_categoria_conhecida(self):
        reg, _ = self.reg("task")
        for name, tool in reg.tools.items():
            cat = reg.category(name, {"comando": "npm test"})
            self.assertIn(cat, perm.CATEGORIES, name)

    def test_ferramentas_de_tarefa_so_aparecem_em_tarefas(self):
        chat = {d["name"] for d in self.reg("chat")[0].declarations()}
        task = {d["name"] for d in self.reg("task")[0].declarations()}
        for n in ("definir_plano", "atualizar_passo", "concluir_tarefa", "pedir_ajuda"):
            self.assertNotIn(n, chat)
            self.assertIn(n, task)

    def test_categoria_dinamica_do_comando(self):
        reg, _ = self.reg()
        self.assertEqual(reg.category("executar_comando", {"comando": "git push origin main"}), "git_push")
        self.assertEqual(reg.category("executar_comando", {"comando": "npm test"}), "comandos")

    def test_acoes_de_alto_risco_estao_na_categoria_certa(self):
        reg, _ = self.reg()
        expected = {"ver_tela": "tela", "clicar": "entrada", "digitar": "entrada", "teclas": "entrada",
                    "rolar": "entrada", "git_commit": "comandos", "git_enviar": "git_push",
                    "abrir_aplicativo": "abrir", "abrir_site": "abrir", "projeto_escrever": "projeto_escrever"}
        for name, cat in expected.items():
            self.assertEqual(reg.category(name, {}), cat, name)


class ExecuteTest(ToolsBase):
    def test_ferramenta_desconhecida(self):
        res, _ = self.reg()[0].execute("formatar_disco", {})
        self.assertIn("desconhecida", res["erro"])

    def test_parametro_ausente_da_erro_claro(self):
        res, _ = self.reg()[0].execute("lembrar", {})
        self.assertIn("texto", res["erro"])

    def test_erros_esperados_viram_resultado(self):
        def boom(*a, **k):
            raise pc.PCError("não deu")
        pc.open_app = boom
        res, _ = self.reg()[0].execute("abrir_aplicativo", {"nome": "x"})
        self.assertEqual(res, {"erro": "não deu"})

    def test_erro_inesperado_nao_derruba(self):
        def boom(*a, **k):
            raise RuntimeError("bug")
        pc.open_url = boom
        res, _ = self.reg()[0].execute("abrir_site", {"url": "https://x.com"})
        self.assertIn("inesperado", res["erro"])

    def test_system_exit_vira_erro(self):
        def boom(*a, **k):
            raise SystemExit("Arquivo credentials.json não encontrado.")
        pc.wait = boom
        res, _ = self.reg()[0].execute("esperar", {"segundos": 1})
        self.assertIn("credentials.json", res["erro"])

    def test_memoria(self):
        reg, _ = self.reg()
        self.assertTrue(reg.execute("lembrar", {"texto": "Prefiro respostas curtas"})[0]["ok"])
        self.assertIn("Prefiro respostas curtas", reg.execute("ver_memoria", {})[0]["memoria"])
        self.assertIn("removida", reg.execute("esquecer", {"numero": 1})[0])
        self.assertIn("erro", reg.execute("esquecer", {"numero": 99})[0])

    def test_arquivos_so_nas_pastas_autorizadas(self):
        (self.docs / "nota.txt").write_text("conteúdo secreto", encoding="utf-8")
        (Path(self.tmp.name) / "fora.txt").write_text("não pode", encoding="utf-8")
        reg, _ = self.reg()
        self.assertEqual(reg.execute("ler_arquivo", {"caminho": "nota.txt"})[0]["conteudo"], "conteúdo secreto")
        self.assertIn("negado", reg.execute("ler_arquivo", {"caminho": "../fora.txt"})[0]["erro"])
        self.assertEqual(len(reg.execute("listar_arquivos", {})[0]["arquivos"]), 1)

    def test_midia_e_apps(self):
        calls = []
        pc.media = lambda a, v=1: calls.append(("media", a, v)) or {"ok": True}
        pc.open_app = lambda n, apps=None: calls.append(("app", n)) or {"ok": True}
        pc.open_url = lambda u: calls.append(("url", u)) or {"ok": True}
        reg, _ = self.reg()
        reg.execute("controle_midia", {"acao": "volume_mais", "vezes": 3})
        reg.execute("abrir_aplicativo", {"nome": "Spotify"})
        reg.execute("abrir_site", {"url": "https://github.com"})
        self.assertEqual(calls, [("media", "volume_mais", 3), ("app", "Spotify"), ("url", "https://github.com")])

    def test_spotify(self):
        reg, _ = self.reg()
        reg.execute("spotify_tocar", {"busca": "queen", "tipo": "artista"})
        reg.execute("spotify_controle", {"acao": "pausar"})
        reg.execute("spotify_controle", {"acao": "volume", "volume": 30})
        self.assertEqual(self.sp.calls, [("play", "queen", "artista"), ("pause",), ("volume", 30)])
        self.assertIn("erro", reg.execute("spotify_controle", {"acao": "volume"})[0])
        self.assertIn("erro", reg.execute("spotify_controle", {"acao": "explodir"})[0])
        self.assertEqual(reg.execute("spotify_status", {})[0], {"tocando": False})


class ProjectToolsTest(ToolsBase):
    def test_chat_pode_escolher_o_projeto(self):
        reg, _ = self.reg("chat", project="atual")
        reg.execute("projeto_escrever", {"caminho": "a.txt", "conteudo": "1", "projeto": "outro"})
        self.assertTrue((Path(self.cfg["projetos"]["pasta"]) / "outro" / "a.txt").exists())

    def test_tarefa_fica_presa_ao_proprio_projeto(self):
        reg, _ = self.reg("task", project="minha-tarefa")
        reg.execute("projeto_escrever", {"caminho": "a.txt", "conteudo": "1", "projeto": "../../etc"})
        root = Path(self.cfg["projetos"]["pasta"])
        self.assertTrue((root / "minha-tarefa" / "a.txt").exists())
        self.assertEqual([p.name for p in root.iterdir()], ["minha-tarefa"])

    def test_sem_projeto_pede_nome(self):
        res, _ = self.reg("chat")[0].execute("projeto_listar", {})
        self.assertIn("projeto", res["erro"].lower())

    def test_escrever_ler_editar_comando_commit(self):
        os.environ.update({"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x.com",
                           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x.com", "GIT_CONFIG_GLOBAL": os.devnull})
        reg, _ = self.reg("task", project="site")
        reg.execute("projeto_escrever", {"caminho": "main.py", "conteudo": "print('a')\n"})
        reg.execute("projeto_editar", {"caminho": "main.py", "buscar": "'a'", "substituir": "'b'"})
        self.assertIn("'b'", reg.execute("projeto_ler", {"caminho": "main.py"})[0]["conteudo"])
        out = reg.execute("executar_comando", {"comando": "python3 main.py"})[0]
        self.assertEqual(out["saida"], "b")
        self.assertEqual(reg.execute("git_commit", {"mensagem": "feat: site"})[0]["codigo"], 0)
        self.assertIn("main.py", reg.execute("projeto_listar", {})[0]["arquivos"])

    def test_git_enviar_sem_repositorio_autorizado_e_recusado(self):
        reg, _ = self.reg("task", project="site")
        reg.execute("projeto_escrever", {"caminho": "a.txt", "conteudo": "x"})
        res, _ = reg.execute("git_enviar", {})
        self.assertIn("erro", res)


class ScreenAndPlanTest(ToolsBase):
    def test_ver_tela_separa_a_imagem_e_esconde_a_janela(self):
        events = []
        self.hooks = {"hide_window": lambda: events.append("hide"), "show_window": lambda: events.append("show")}
        pc.screenshot = lambda: (b"\xff\xd8jpeg", {"largura": 10, "altura": 5})
        pc.click = lambda x, y, b="left", c=1: events.append(("click", x, y)) or {"ok": True}
        reg, ctx = self.reg()
        res, image = reg.execute("ver_tela", {})
        self.assertEqual(image, (b"\xff\xd8jpeg", "image/jpeg"))
        self.assertNotIn("_image", res)
        reg.execute("clicar", {"x": 1, "y": 2})
        self.assertEqual(events, ["hide", ("click", 1, 2)])   # escondeu uma vez só
        ctx.release()
        self.assertEqual(events[-1], "show")
        ctx.release()
        self.assertEqual(events.count("show"), 1)

    def test_plano_e_andamento_chamam_os_ganchos(self):
        got = {}
        self.hooks = {"on_plan": lambda p: got.update(plan=p), "on_step": lambda n, s, note: got.update(step=(n, s, note)),
                      "on_finish": lambda r: got.update(done=r), "on_help": lambda q: got.update(help=q)}
        reg, ctx = self.reg("task")
        reg.execute("definir_plano", {"passos": ["a", " b ", ""]})
        reg.execute("atualizar_passo", {"numero": 2, "status": "feito", "nota": "ok"})
        reg.execute("concluir_tarefa", {"resumo": "pronto"})
        reg.execute("pedir_ajuda", {"pergunta": "qual cor?"})
        self.assertEqual(got["plan"], ["a", "b"])
        self.assertEqual(got["step"], (2, "feito", "ok"))
        self.assertEqual((ctx.control["finished"], ctx.control["help"]), ("pronto", "qual cor?"))

    def test_plano_invalido(self):
        self.hooks = {"on_plan": lambda p: None, "on_step": lambda *a: None}
        reg, _ = self.reg("task")
        self.assertIn("erro", reg.execute("definir_plano", {"passos": []})[0])
        self.assertIn("erro", reg.execute("definir_plano", {"passos": ["x"] * 16})[0])
        self.assertIn("erro", reg.execute("atualizar_passo", {"numero": 1, "status": "quase"})[0])

    def test_ferramenta_de_tarefa_sem_ganchos(self):
        reg, _ = self.reg("task")
        self.assertIn("erro", reg.execute("definir_plano", {"passos": ["a"]})[0])


class MiscTest(ToolsBase):
    def test_resultado_grande_e_cortado(self):
        big = {"conteudo": "x" * 20000}
        out = at._clip(big)
        self.assertLessEqual(len(json.dumps(out)), at.MAX_RESULT_CHARS + 200)
        self.assertIn("cortado", out["conteudo"])

    def test_resumos_mostram_o_que_vai_acontecer(self):
        reg, _ = self.reg()
        self.assertIn("olá mundo", reg.summary("digitar", {"texto": "olá mundo"}))
        self.assertIn("calc.py", reg.summary("projeto_escrever", {"caminho": "calc.py", "conteudo": "x"}))
        self.assertIn("npm test", reg.summary("executar_comando", {"comando": "npm test"}))
        self.assertFalse(reg.has("desconhecida"))


if __name__ == "__main__":
    unittest.main()
