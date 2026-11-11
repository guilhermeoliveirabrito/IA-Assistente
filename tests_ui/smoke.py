"""Teste de fumaça da interface, num navegador de verdade (Playwright + Chromium).

Sobe o servidor do app com uma IA falsa (sem internet, sem chave), abre cada tela no computador e no celular e confere:
nenhuma tela quebra, nenhum erro de JavaScript, o chat responde, o painel Ao vivo e o Diagnóstico funcionam e a página não
estoura a largura no celular.

    pip install playwright && playwright install chromium
    python tests_ui/smoke.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from assistente import server  # noqa: E402
from assistente.ia import gemini  # noqa: E402
from assistente.nucleo import settings  # noqa: E402

VIEWS = ["Início", "Conversa", "Ao vivo", "Tarefas", "Lembretes", "Encomendas", "Automação", "Histórico", "Memória", "Ajustes"]
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FALHA ") + msg)
    if not cond:
        failures.append(msg)


def fake_stream(contents, models, system=None, tools=None, temperature=0.2, **kw):
    yield {"_model": models[0]}
    yield {"candidates": [{"content": {"parts": [{"text": "Olá! Sou a resposta de teste."}]}}]}


def open_view(page, name, mobile):
    if mobile:
        page.evaluate("document.querySelector('.sidebar').classList.add('open')")
    page.locator(f".nav button:has-text('{name}')").first.dispatch_event("click")
    page.wait_for_timeout(250)


def main() -> int:
    tmp = tempfile.TemporaryDirectory()
    old = os.getcwd()
    os.chdir(tmp.name)
    shutil.copy(ROOT / "config.yaml", "config.yaml")
    shutil.copytree(ROOT / "memory_example", "memory_example")
    os.environ["GEMINI_API_KEY"] = "teste"
    gemini.stream = fake_stream
    cfg = settings.load_config()
    cfg["projetos"]["pasta"] = str(Path(tmp.name) / "proj")
    srv = server.start(cfg, port=0, mode="local")
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for label, viewport, mobile in (("desktop", {"width": 1280, "height": 800}, False), ("celular", {"width": 390, "height": 844}, True)):
                ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
                page = ctx.new_page()
                page.on("pageerror", lambda e, lb=label: errors.append(f"[{lb}] {e}"))
                page.on("console", lambda m, lb=label: errors.append(f"[{lb}] {m.text}") if m.type == "error" else None)
                page.goto(srv.url)
                page.wait_for_selector(".nav button", state="attached", timeout=15000)

                for name in VIEWS:
                    open_view(page, name, mobile)
                    visible = page.locator("#content").inner_text()
                    check(len(visible.strip()) > 0, f"{label}: tela '{name}' mostra conteúdo")
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    check(overflow <= 1, f"{label}: tela '{name}' sem rolagem horizontal ({overflow}px)")

                open_view(page, "Conversa", mobile)
                page.fill("textarea[aria-label='Mensagem']", "oi")
                page.click("button.send")
                page.wait_for_selector("text=Sou a resposta de teste", timeout=10000)
                check(True, f"{label}: o chat responde")

                open_view(page, "Ao vivo", mobile)
                check(page.locator("text=Em andamento").count() > 0, f"{label}: painel Ao vivo abre")
                check(page.locator("text=Dar um comando").count() > 0, f"{label}: Ao vivo tem a caixa de comando")

                open_view(page, "Ajustes", mobile)
                page.locator("button:has-text('Verificar agora')").first.click()
                page.wait_for_selector(".diag-item", timeout=15000)
                check(page.locator(".diag-item").count() >= 5, f"{label}: Diagnóstico lista as verificações")
                check(page.locator("text=Aparelhos conectados").count() > 0, f"{label}: Ajustes mostra Aparelhos conectados")
                check(page.locator("text=Atualizações").count() > 0, f"{label}: Ajustes mostra Atualizações")

                if mobile:
                    check(page.locator(".tabbar").is_visible(), "celular: barra de abas visível")
                    small = page.evaluate("""() => [...document.querySelectorAll('.tabbar button')].filter(b => b.getBoundingClientRect().height < 40).length""")
                    check(small == 0, "celular: botões da barra de abas com altura de toque (>= 40px)")
                ctx.close()
            browser.close()
    finally:
        srv.shutdown()
        os.chdir(old)
        tmp.cleanup()
    ignorable = ("favicon", "Failed to load resource: the server responded with a status of 404")
    real = [e for e in errors if not any(i in e for i in ignorable)]
    check(not real, "nenhum erro de JavaScript no console" + (": " + "; ".join(real[:3]) if real else ""))
    print(f"\n{len(failures)} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
