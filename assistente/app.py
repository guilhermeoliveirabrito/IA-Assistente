"""Abre o Assistente como um aplicativo (janela própria).

  python app.py          # janela do app (usa pywebview; sem ele abre no navegador)
  python app.py --no-window   # só o servidor (útil para deixar rodando e usar pelo celular)
"""
import os
import sys
import threading
import time
import webbrowser

from assistente.ia import gemini
from assistente import server
from assistente.nucleo import settings


def make_tray(on_open, on_quit):
    """Ícone na bandeja do Windows (para o app continuar ouvindo a frase de chamada com a janela fechada).
    Retorna o ícone ou None se o pystray/Pillow não estiver instalado."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(217, 119, 87, 255))
    d.rounded_rectangle((26, 16, 38, 38), radius=6, fill=(255, 255, 255, 255))
    d.arc((20, 26, 44, 48), 0, 180, fill=(255, 255, 255, 255), width=3)
    d.line((32, 48, 32, 54), fill=(255, 255, 255, 255), width=3)
    menu = pystray.Menu(pystray.MenuItem("Abrir o Assistente", lambda icon, item: on_open(), default=True),
                        pystray.MenuItem("Sair", lambda icon, item: on_quit()))
    return pystray.Icon("assistente", img, "Assistente", menu)


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
    holder = {"quit": False}

    def reveal():
        w = holder.get("w")
        if w:
            try:
                w.show()
                w.restore()
            except Exception:
                pass

    hooks = {"hide_window": lambda: holder["w"].minimize() if holder.get("w") else None,
             "show_window": lambda: holder["w"].restore() if holder.get("w") else None,
             "reveal_window": reveal}
    try:
        srv = server.start(cfg, window_hooks=hooks)
    except OSError:
        port = (cfg.get("app") or {}).get("porta", 8765)
        print(f"A porta {port} já está em uso — o Assistente provavelmente já está aberto.")
        if show_window:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return 1

    auto = srv.app.automation
    if auto.start():
        print("Rotina de e-mails e agenda ligada.")
    else:
        print("Rotina de e-mails e agenda desligada (conecte em Ajustes › Gmail e Agenda).")

    print(f"Assistente em http://127.0.0.1:{srv.port}/")
    if srv.mode == "rede":
        print("Acesso pelo celular LIGADO. Código de acesso:", srv.token)
        for ip in server.lan_addresses():
            print(f"  http://{ip}:{srv.port}/?k={srv.token}")

    try:
        if show_window and webview is not None:
            holder["w"] = webview.create_window("Assistente", srv.url, width=1180, height=800, min_size=(420, 560),
                                                background_color="#1f1e1d")
            tray = make_tray(reveal, lambda: (holder.update(quit=True), holder["w"].destroy()))
            if tray is not None:
                tray.run_detached()
                holder["tray"] = tray

                def on_closing():
                    # com a voz ligada, fechar a janela só a esconde: o app segue ouvindo (Sair fica na bandeja)
                    if srv.app.voice.enabled and not holder["quit"]:
                        holder["w"].hide()
                        return False
                    return True

                holder["w"].events.closing += on_closing
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
        if holder.get("tray"):
            holder["tray"].stop()
        auto.stop()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
