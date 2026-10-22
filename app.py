"""Abre o Assistente como um aplicativo (janela própria).

  python app.py          # janela do app (usa pywebview; sem ele abre no navegador)
  python app.py --no-window   # só o servidor (útil para deixar rodando e usar pelo celular)
"""
import os
import sys
import threading
import time
import webbrowser

import automation
import gemini
import server
import settings


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    gemini.load_dotenv()
    cfg = settings.load_config()
    show_window = "--no-window" not in argv

    if show_window:
        try:
            import webview  # noqa: F401
        except ImportError:
            webview = None
    else:
        webview = None

    # esconde a janela enquanto o assistente mexe na tela/teclado, para ela não atrapalhar
    holder = {}
    hooks = {"hide_window": lambda: holder["w"].minimize() if holder.get("w") else None,
             "show_window": lambda: holder["w"].restore() if holder.get("w") else None}
    try:
        srv = server.start(cfg, window_hooks=hooks)
    except OSError:
        port = (cfg.get("app") or {}).get("porta", 8765)
        print(f"A porta {port} já está em uso — o Assistente provavelmente já está aberto.")
        if show_window:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return 1

    auto = automation.Automation(cfg)
    if auto.start():
        print("Rotina de e-mails e agenda ligada.")
    else:
        print("Rotina de e-mails e agenda desligada (faça `python main.py setup` para entrar no Google).")

    print(f"Assistente em http://127.0.0.1:{srv.port}/")
    if srv.mode == "rede":
        print("Acesso pelo celular LIGADO. Código de acesso:", srv.token)
        for ip in server.lan_addresses():
            print(f"  http://{ip}:{srv.port}/?k={srv.token}")

    try:
        if show_window and webview is not None:
            holder["w"] = webview.create_window("Assistente", srv.url, width=1180, height=800, min_size=(420, 560),
                                                background_color="#1f1e1d")
            webview.start()          # bloqueia até fechar a janela
        elif show_window:
            print("pywebview não está instalado: abrindo no navegador. (pip install pywebview para ter a janela própria)")
            webbrowser.open(srv.url)
            while True:
                time.sleep(3600)
        else:
            print("Rodando sem janela. Ctrl+C para fechar.")
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        auto.stop()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
