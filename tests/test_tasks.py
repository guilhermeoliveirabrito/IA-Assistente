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

from assistente.nucleo import activity  # noqa: E402
from assistente.nucleo import bus as busmod  # noqa: E402
from assistente.nucleo import context  # noqa: E402
from assistente.ia import gemini  # noqa: E402
from assistente.pc import pc_control as pc  # noqa: E402
from assistente.nucleo import permissions as perm  # noqa: E402
from assistente.servicos import tasks  # noqa: E402


def text(*t):
    return [{"candidates": [{"content": {"parts": [{"text": x}]}}]} for x in t]


def call(name, args):
    return [{"candidates": [{"content": {"parts": [{"functionCall": {"name": name, "args": args}}]}}]}]


def quota(retry=None):
    return gemini.GeminiError("cota", 429, "quota", retry)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify(self, kind, title, message, priority=3):
        self.sent.append((kind, title, message))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        shutil.copytree(ROOT / "memory_example", "memory_example")
        activity.configure({})
        self.cfg = {"ia": {"modelo": "m"}, "arquivos": {"pastas_permitidas": []}, "pc": {},
                    "projetos": {"pasta": str(Path(self.tmp.name) / "proj"), "repos_permitidos": []},
                    "tarefas": {"orcamento_de_requisicoes": 30, "espera_de_aprovacao_minutos": 0.01}}
        self.script = []
        self.sent = []
        self._stream = gemini.stream

        def fake_stream(contents, models, system=None, tools=None, temperature=0.2, **kw):
            self.sent.append(list(contents))
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            yield {"_model": models[0]}
            for ch in item:
                yield ch

        gemini.stream = fake_stream
        self.now = [time.time()]
        self.slept = []
        self.notifier = FakeNotifier()
        self.bus = busmod.Bus()
        self.events = self.bus.subscribe()
        self.managers = []

    def tearDown(self):
        gemini.stream = self._stream
        for m in self.managers:
            m.shutdown(1)
        os.chdir(self.old)
        self.tmp.cleanup()

    def mgr(self, **kw):
        m = tasks.TaskManager(self.cfg, bus=self.bus, notifier=self.notifier, clock=lambda: self.now[0],
                              sleep=lambda s: self.slept.append(s), start_thread=False, **kw)
        self.managers.append(m)
        return m

    def run_task(self, m, tid=None):
        self.assertTrue(m.run_once())
        return m.get(tid) if tid else None

    def new(self, m, prompt="faça algo", profile="projeto", budget=None, title="Tarefa teste"):
        return m.create(title, prompt, profile, budget)["id"]


class CreateTest(Base):
    def test_validacoes(self):
        m = self.mgr()
        for args in (("", "", "leitura"), ("t", "  ", "leitura"), ("t", "x" * (tasks.MAX_PROMPT + 1), "leitura"),
                     ("t", "ok", "super-admin")):
            with self.assertRaises(tasks.TaskError, msg=args):
                m.create(*args)

    def test_criacao_padrao(self):
        m = self.mgr()
        t = m.create("", "Crie um site de portfólio com três páginas", "projeto")
        self.assertEqual(t["status"], "queued")
        self.assertEqual(t["budget"], 30)
        self.assertTrue(t["title"].startswith("Crie um site"))
        self.assertIn("projeto_escrever", t["granted"])
        self.assertNotIn("entrada", t["granted"])
        self.assertRegex(t["project"], r"^crie-um-site.*-[0-9a-f]{4}$")

    def test_id_invalido(self):
        m = self.mgr()
        for bad in ("../x", "abc", None, "ZZZZZZZZZZ"):
            with self.assertRaises(tasks.TaskError):
                m.get(bad)

    def test_persistencia(self):
        m = self.mgr()
        tid = self.new(m)
        m2 = self.mgr()
        self.assertEqual(m2.get(tid)["title"], "Tarefa teste")


class RunTest(Base):
    def test_tarefa_completa(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [call("definir_plano", {"passos": ["criar arquivo", "testar"]}),
                       call("atualizar_passo", {"numero": 1, "status": "andamento"}),
                       call("projeto_escrever", {"caminho": "ola.py", "conteudo": "print('oi')\n"}),
                       call("executar_comando", {"comando": "python3 ola.py"}),
                       call("atualizar_passo", {"numero": 1, "status": "feito", "nota": "ok"}),
                       call("concluir_tarefa", {"resumo": "Criei ola.py e rodei."})]
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["summary"], "Criei ola.py e rodei.")
        self.assertEqual([p["status"] for p in t["plan"]], ["feito", "pendente"])
        self.assertEqual(t["requests"], 6)
        self.assertTrue((Path(self.tmp.name) / "proj" / t["project"] / "ola.py").exists())
        self.assertIn("pronta", [k for k, *_ in self.notifier.sent])
        kinds = {e["kind"] for e in activity.recent(task=tid)}
        self.assertLessEqual({"tarefa", "plano", "acao", "resultado"}, kinds)

    def test_eventos_em_tempo_real(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [call("definir_plano", {"passos": ["a"]}), call("concluir_tarefa", {"resumo": "ok"})]
        self.run_task(m, tid)
        got = []
        while not self.events.empty():
            got.append(self.events.get_nowait())
        types = {e["type"] for e in got}
        self.assertLessEqual({"task_update", "tool_start", "tool_end", "thinking"}, types)
        self.assertTrue(all(e.get("task_id") == tid for e in got if e.get("scope") == "task"))

    def test_resposta_sem_concluir_vira_resumo(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [text("Pronto, ", "tudo certo.")]
        t = self.run_task(m, tid)
        self.assertEqual((t["status"], t["summary"]), ("done", "Pronto, tudo certo."))

    def test_modelo_vazio_duas_vezes_falha(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [[], []]
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "failed")
        self.assertIn("erro", [k for k, *_ in self.notifier.sent])

    def test_so_uma_tarefa_por_vez_na_ordem(self):
        m = self.mgr()
        a = self.new(m, title="A")
        self.now[0] += 1
        b = self.new(m, title="B")
        self.script = [text("A feita"), text("B feita")]
        m.run_once()
        self.assertEqual((m.get(a)["status"], m.get(b)["status"]), ("done", "queued"))
        m.run_once()
        self.assertEqual(m.get(b)["status"], "done")
        self.assertFalse(m.run_once())

    def test_orcamento_pausa_e_retoma_com_mais(self):
        m = self.mgr()
        tid = self.new(m, budget=2)
        self.script = [call("ver_memoria", {}), call("ver_memoria", {}), call("ver_memoria", {})]
        t = self.run_task(m, tid)
        self.assertEqual((t["status"], t["requests"]), ("paused_budget", 2))
        self.assertIn("pausa", [k for k, *_ in self.notifier.sent])
        self.assertFalse(m.run_once())                      # pausada: não roda sozinha
        m.resume(tid, extra_budget=5)
        self.script = [call("concluir_tarefa", {"resumo": "fim"})]
        self.assertEqual(self.run_task(m, tid)["status"], "done")

    def test_retomar_sem_liberar_orcamento_ainda_libera_um_pouco(self):
        m = self.mgr()
        tid = self.new(m, budget=1)
        self.script = [call("ver_memoria", {})]
        self.run_task(m, tid)
        t = m.resume(tid)
        self.assertGreater(t["budget"], t["requests"])

    def test_resume_exige_tarefa_pausada(self):
        m = self.mgr()
        tid = self.new(m)
        with self.assertRaises(tasks.TaskError):
            m.resume(tid)

    def test_compacta_historico_longo(self):
        self.cfg["ia"]["limite_de_contexto_tokens"] = 200
        m = self.mgr()
        tid = self.new(m)
        long = []
        for i in range(10):
            long += [{"role": "user", "parts": [{"text": f"p{i} " + "x" * 300}]},
                     {"role": "model", "parts": [{"text": f"r{i} " + "y" * 300}]}]
        m.tasks[tid]["contents"] = [{"role": "user", "parts": [{"text": "TAREFA"}]}] + long
        orig = context.ai.ask_text
        context.ai.ask_text = lambda p, model: "resumo curto"
        try:
            self.script = [text("fim")]
            self.run_task(m, tid)
        finally:
            context.ai.ask_text = orig
        first = self.sent[0]
        self.assertTrue(first[0]["parts"][0]["text"].startswith(context.SUMMARY_MARK))
        self.assertLess(len(first), 21)


class QuotaAndNetworkTest(Base):
    def test_limite_por_minuto_espera_e_continua(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [quota(retry=10), text("ok depois da espera")]
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "done")
        self.assertEqual(self.slept, [12])
        self.assertEqual(t["requests"], 1)                 # a tentativa que falhou não gastou orçamento

    def test_cota_do_dia_pausa_e_retoma_sozinha_na_renovacao(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [quota(), quota(), quota(), quota()]
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "paused_quota")
        self.assertEqual(len(self.slept), 3)               # 3 esperas curtas antes de desistir do dia
        self.assertGreater(t["resume_at"], self.now[0])
        self.assertIn("pausa", [k for k, *_ in self.notifier.sent])
        self.assertFalse(m.run_once())                     # ainda não renovou
        self.now[0] = t["resume_at"] + 1                   # o relógio passa da renovação
        self.script = [text("terminei depois da renovação")]
        self.assertTrue(m.run_once())
        t2 = m.get(tid)
        self.assertEqual((t2["status"], t2["summary"]), ("done", "terminei depois da renovação"))

    def test_espera_longa_do_gemini_pausa_direto(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [quota(retry=3600)]
        self.assertEqual(self.run_task(m, tid)["status"], "paused_quota")
        self.assertEqual(self.slept, [])

    def test_sem_retomada_automatica_configurada(self):
        self.cfg["tarefas"]["retomar_apos_renovacao"] = False
        m = self.mgr()
        tid = self.new(m)
        self.script = [quota(retry=3600)]
        t = self.run_task(m, tid)
        self.now[0] = t["resume_at"] + 1
        self.assertFalse(m.run_once())
        m.resume(tid)
        self.script = [text("ok")]
        self.assertTrue(m.run_once())

    def test_sem_internet_tenta_de_novo(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [gemini.GeminiError("sem rede", kind="network")] * 2 + [text("voltou")]
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "done")
        self.assertEqual(self.slept, [60, 60])

    def test_sem_internet_por_muito_tempo_falha(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [gemini.GeminiError("sem rede", kind="network")] * (tasks.NETWORK_RETRIES + 2)
        t = self.run_task(m, tid)
        self.assertEqual(t["status"], "failed")
        self.assertIn("Sem conexão", t["error"])

    def test_chave_recusada_falha_sem_insistir(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [gemini.GeminiError("Chave recusada", 403, "auth")]
        t = self.run_task(m, tid)
        self.assertEqual((t["status"], t["error"]), ("failed", "Chave recusada"))
        self.assertEqual(self.slept, [])


class ApprovalTest(Base):
    def setUp(self):
        super().setUp()
        self.opened = []
        self._open = pc.open_url
        pc.open_url = lambda u: self.opened.append(u) or {"ok": True, "aberto": u}

    def tearDown(self):
        pc.open_url = self._open
        super().tearDown()

    def run_in_thread(self, m):
        th = threading.Thread(target=m.run_once)
        th.start()
        return th

    def wait_pending(self, m, tid):
        for _ in range(300):
            if m.get(tid)["pending"]:
                return m.get(tid)["pending"]
            time.sleep(0.01)
        self.fail("o pedido de aprovação não apareceu")

    def test_aprovar_executa_e_continua(self):
        self.cfg["tarefas"]["espera_de_aprovacao_minutos"] = 5
        m = self.mgr()
        tid = self.new(m, profile="leitura")
        self.script = [call("abrir_site", {"url": "https://github.com"}), call("concluir_tarefa", {"resumo": "aberto"})]
        th = self.run_in_thread(m)
        req = self.wait_pending(m, tid)
        self.assertEqual(m.get(tid)["status"], "waiting_approval")
        self.assertEqual(req["category"], "abrir")
        self.assertIn("pedido", [k for k, *_ in self.notifier.sent])
        self.assertTrue(m.approve(req["id"], "allow"))
        th.join(5)
        self.assertEqual(self.opened, ["https://github.com"])
        self.assertEqual(m.get(tid)["status"], "done")

    def test_negar_nao_executa(self):
        self.cfg["tarefas"]["espera_de_aprovacao_minutos"] = 5
        m = self.mgr()
        tid = self.new(m, profile="leitura")
        self.script = [call("abrir_site", {"url": "https://x.com"}), text("ok, sem abrir")]
        th = self.run_in_thread(m)
        m.approve(self.wait_pending(m, tid)["id"], "deny")
        th.join(5)
        self.assertEqual(self.opened, [])
        self.assertEqual(m.get(tid)["status"], "done")

    def test_sem_resposta_no_prazo_nega_e_segue(self):
        m = self.mgr()            # espera de 0,6s (0.01 min)
        tid = self.new(m, profile="leitura")
        self.script = [call("abrir_site", {"url": "https://x.com"}), text("segui sem abrir")]
        t0 = time.time()
        self.run_task(m, tid)
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(self.opened, [])
        self.assertEqual(m.get(tid)["status"], "done")
        self.assertIsNone(m.get(tid)["pending"])

    def test_aprovar_sempre_concede_a_categoria_na_tarefa(self):
        self.cfg["tarefas"]["espera_de_aprovacao_minutos"] = 5
        m = self.mgr()
        tid = self.new(m, profile="leitura")
        self.script = [call("abrir_site", {"url": "https://a.com"}), call("abrir_site", {"url": "https://b.com"}),
                       call("concluir_tarefa", {"resumo": "ok"})]
        th = self.run_in_thread(m)
        m.approve(self.wait_pending(m, tid)["id"], "always")
        th.join(5)
        self.assertEqual(self.opened, ["https://a.com", "https://b.com"])
        self.assertIn("abrir", m.get(tid)["granted"])

    def test_parar_durante_aprovacao(self):
        self.cfg["tarefas"]["espera_de_aprovacao_minutos"] = 5
        m = self.mgr()
        tid = self.new(m, profile="leitura")
        self.script = [call("abrir_site", {"url": "https://x.com"})]
        th = self.run_in_thread(m)
        self.wait_pending(m, tid)
        m.stop(tid)
        th.join(5)
        self.assertEqual(m.get(tid)["status"], "stopped")
        self.assertEqual(self.opened, [])

    def test_aprovacao_inexistente_e_invalida(self):
        m = self.mgr()
        self.assertFalse(m.approve("naoexiste", "allow"))
        with self.assertRaises(tasks.TaskError):
            m.approve("x", "talvez")


class HelpAndControlTest(Base):
    def test_pedir_ajuda_espera_e_continua_com_a_resposta(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [call("pedir_ajuda", {"pergunta": "Qual cor do botão?"})]
        t = self.run_task(m, tid)
        self.assertEqual((t["status"], t["question"]), ("waiting_user", "Qual cor do botão?"))
        self.assertFalse(m.run_once())
        m.answer(tid, "Azul")
        self.script = [call("concluir_tarefa", {"resumo": "usei azul"})]
        self.run_task(m, tid)
        self.assertEqual(m.get(tid)["status"], "done")
        last_user = [c for c in self.sent[-1] if c["role"] == "user"][-1]
        self.assertTrue(any(p.get("text") == "Azul" or "functionResponse" in p for p in last_user["parts"]))
        self.assertTrue(any(p.get("text") == "Azul" for c in self.sent[-1] for p in c["parts"]))

    def test_responder_so_quando_esta_esperando(self):
        m = self.mgr()
        tid = self.new(m)
        with self.assertRaises(tasks.TaskError):
            m.answer(tid, "oi")
        self.script = [call("pedir_ajuda", {"pergunta": "?"})]
        self.run_task(m, tid)
        with self.assertRaises(tasks.TaskError):
            m.answer(tid, "   ")

    def test_parar_tarefa_na_fila(self):
        m = self.mgr()
        tid = self.new(m)
        self.assertEqual(m.stop(tid)["status"], "stopped")
        self.assertFalse(m.run_once())
        m.resume(tid)
        self.script = [text("ok")]
        self.assertTrue(m.run_once())

    def test_apagar(self):
        m = self.mgr()
        tid = self.new(m)
        m.delete(tid)
        self.assertEqual(m.list(), [])
        self.assertFalse(Path("data/tasks", f"{tid}.json").exists())
        m.delete(tid)   # idempotente

    def test_novo_texto_numa_tarefa_concluida_reabre(self):
        m = self.mgr()
        tid = self.new(m)
        self.script = [text("feito")]
        self.run_task(m, tid)
        m.answer(tid, "Agora faça também X")
        self.assertEqual(m.get(tid)["status"], "queued")


class RecoveryTest(Base):
    def test_app_fechado_no_meio_volta_para_a_fila_e_conserta_o_historico(self):
        m = self.mgr()
        tid = self.new(m)
        t = m.tasks[tid]
        t["status"] = "running"
        t["contents"] = [{"role": "user", "parts": [{"text": "TAREFA"}]},
                         {"role": "model", "parts": [{"functionCall": {"name": "executar_comando", "args": {}}}]}]
        m._save(t)
        m2 = self.mgr()                         # "reabriu o app"
        self.assertEqual(m2.get(tid)["status"], "queued")
        self.script = [text("retomei")]
        self.run_task(m2, tid)
        sent_last_turn = self.sent[0][-1]
        self.assertIn("functionResponse", sent_last_turn["parts"][0])
        self.assertEqual(m2.get(tid)["status"], "done")

    def test_limpa_tarefas_antigas_concluidas(self):
        m = self.mgr()
        old = self.new(m, title="velha")
        keep = self.new(m, title="ativa")
        m.tasks[old]["status"] = "done"
        m.tasks[old]["updated"] = self.now[0] - 30 * 86400
        self.assertEqual(m.prune(), 1)
        self.assertEqual([t["id"] for t in m.list()], [keep])

    def test_arquivo_corrompido_e_ignorado(self):
        Path("data/tasks").mkdir(parents=True, exist_ok=True)
        Path("data/tasks/abcdef0123.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(self.mgr().list(), [])


if __name__ == "__main__":
    unittest.main()
