"""Controle do PC: abrir apps e sites, teclas de mídia, teclado, mouse e captura de tela.

Pensado para Windows. As funções recebem o que fazer e NÃO decidem se pode: quem decide é
`permissions.py` (confirmações e perfis). Aqui só ficam as ações e as validações básicas.
Nada aqui executa comandos de shell.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


class PCError(Exception):
    pass


# Pontos de injeção (os testes trocam por versões falsas)
_platform = sys.platform
_startfile = getattr(os, "startfile", None)
_popen = subprocess.Popen
_open_browser = webbrowser.open
_sleep = time.sleep
_backend_override = None     # objeto com a mesma interface do pyautogui
_grab_override = None        # função que devolve uma imagem PIL
_key_sender = None           # função(vk) que envia uma tecla de mídia

_last_scale = 1.0            # captura enviada à IA / tela real (para converter cliques)
_dpi_done = False

DEFAULT_APPS = {
    "spotify": "spotify:",
    "calculadora": "calc.exe",
    "bloco de notas": "notepad.exe",
    "explorador": "explorer.exe",
}

MEDIA_KEYS = {  # códigos de tecla virtual do Windows
    "play_pause": 0xB3,
    "proxima": 0xB0,
    "anterior": 0xB1,
    "volume_mais": 0xAF,
    "volume_menos": 0xAE,
    "mudo": 0xAD,
}


# ---- sites -----------------------------------------------------------------

def open_url(url: str) -> dict:
    url = (url or "").strip()
    if "://" not in url and re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PCError("Só abro endereços http:// ou https:// válidos.")
    if parsed.username or parsed.password:
        raise PCError("Endereços com usuário e senha embutidos não são permitidos.")
    _open_browser(url, new=2)
    return {"ok": True, "aberto": url}


# ---- aplicativos -----------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _start_menu_dirs():
    dirs = []
    for var in ("ProgramData", "APPDATA"):
        base = os.environ.get(var)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return dirs


def find_start_menu_shortcut(name: str, dirs=None):
    """Procura um atalho (.lnk) no Menu Iniciar pelo nome. Retorna o Path ou None."""
    target = _norm(name)
    if not target:
        return None
    best, best_rank = None, None
    for base in (dirs if dirs is not None else _start_menu_dirs()):
        if not base.is_dir():
            continue
        for lnk in base.rglob("*.lnk"):
            stem = _norm(lnk.stem)
            if "uninstall" in stem or "desinstal" in stem:
                continue
            if stem == target:
                rank = (0, len(stem))
            elif stem.startswith(target):
                rank = (1, len(stem))
            elif target in stem:
                rank = (2, len(stem))
            else:
                continue
            if best_rank is None or rank < best_rank:
                best, best_rank = lnk, rank
    return best


def open_app(name: str, extra_apps: dict = None) -> dict:
    """Abre um aplicativo pelo nome (atalhos do config, Menu Iniciar ou PATH)."""
    name = (name or "").strip()
    if not name or len(name) > 80 or re.search(r"[|&;<>`$\n\r]", name):
        raise PCError("Nome de aplicativo inválido.")
    apps = {**DEFAULT_APPS, **{k.lower(): v for k, v in (extra_apps or {}).items()}}
    alias = apps.get(name.lower())
    if _platform == "win32":
        if alias:
            if alias.endswith(":") or "://" in alias:       # protocolo (ex.: spotify:)
                _startfile(alias)
            elif Path(alias).is_file():
                _startfile(alias)
            else:
                _popen([alias])
            return {"ok": True, "aberto": name}
        lnk = find_start_menu_shortcut(name)
        if lnk:
            _startfile(str(lnk))
            return {"ok": True, "aberto": lnk.stem}
        exe = shutil.which(name)
        if exe:
            _popen([exe])
            return {"ok": True, "aberto": exe}
        raise PCError(f"Não encontrei o aplicativo '{name}' no Menu Iniciar.")
    if _platform == "darwin":
        _popen(["open", "-a", alias or name])
        return {"ok": True, "aberto": name}
    exe = shutil.which(alias or name)
    if not exe:
        raise PCError(f"Não encontrei o aplicativo '{name}'.")
    _popen([exe])
    return {"ok": True, "aberto": name}


# ---- teclas de mídia -------------------------------------------------------

def _send_media_key(vk: int):
    if _key_sender:
        return _key_sender(vk)
    if _platform != "win32":
        raise PCError("Teclas de mídia só estão implementadas para Windows.")
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0x0001, 0)           # pressiona (tecla estendida)
    user32.keybd_event(vk, 0, 0x0001 | 0x0002, 0)  # solta


def media(action: str, times: int = 1) -> dict:
    if action not in MEDIA_KEYS:
        raise PCError(f"Ação de mídia desconhecida: {action}. Use: {', '.join(MEDIA_KEYS)}.")
    times = max(1, min(int(times or 1), 25 if action.startswith("volume") else 1))
    for _ in range(times):
        _send_media_key(MEDIA_KEYS[action])
        _sleep(0.03)
    return {"ok": True, "acao": action, "vezes": times}


# ---- teclado, mouse e tela (pyautogui) --------------------------------------

def _set_dpi_aware():
    global _dpi_done
    if _dpi_done or _platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    _dpi_done = True


def _pg():
    if _backend_override is not None:
        return _backend_override
    _set_dpi_aware()
    try:
        import pyautogui
    except ImportError as e:
        raise PCError("Falta instalar o pyautogui: pip install -r requirements.txt") from e
    pyautogui.FAILSAFE = True   # mover o mouse para um canto da tela interrompe tudo
    pyautogui.PAUSE = 0.15
    return pyautogui


def screenshot(max_width: int = 1280):
    """Captura a tela inteira. Retorna (bytes JPEG, info). Guarda a escala para os cliques."""
    global _last_scale
    _set_dpi_aware()
    try:
        if _grab_override:
            img = _grab_override()
        else:
            from PIL import ImageGrab

            img = ImageGrab.grab()
    except Exception as e:
        raise PCError(f"Não consegui capturar a tela: {e}") from e
    real_w, real_h = img.size
    img = img.convert("RGB")
    if real_w > max_width:
        new_h = round(real_h * max_width / real_w)
        img = img.resize((max_width, new_h))
    _last_scale = real_w / img.size[0]
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    info = {"largura": img.size[0], "altura": img.size[1], "largura_real": real_w, "altura_real": real_h}
    return buf.getvalue(), info


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """Clica em (x, y) nas coordenadas da ÚLTIMA captura de tela enviada à IA."""
    if button not in ("left", "right", "middle"):
        raise PCError("Botão inválido (left, right ou middle).")
    clicks = max(1, min(int(clicks or 1), 3))
    pg = _pg()
    real_x, real_y = round(float(x) * _last_scale), round(float(y) * _last_scale)
    w, h = pg.size()
    if not (0 <= real_x < w and 0 <= real_y < h):
        raise PCError(f"Coordenada fora da tela ({real_x}, {real_y}); a tela é {w}x{h}.")
    pg.click(real_x, real_y, clicks=clicks, button=button)
    return {"ok": True, "x": real_x, "y": real_y, "botao": button, "cliques": clicks}


def _paste(text: str, pg):
    """Digita texto com acentos colando pela área de transferência (e restaura o conteúdo anterior)."""
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    try:
        try:
            previous = root.clipboard_get()
        except tkinter.TclError:
            previous = None
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        pg.hotkey("ctrl", "v")
        _sleep(0.3)
        if previous is not None:
            root.clipboard_clear()
            root.clipboard_append(previous)
            root.update()
    finally:
        root.destroy()


def type_text(text: str) -> dict:
    text = str(text or "")
    if not text or len(text) > 3000:
        raise PCError("Texto vazio ou longo demais (máximo 3000 caracteres).")
    pg = _pg()
    if text.isascii():
        pg.write(text, interval=0.02)
    else:
        _paste(text, pg)
    return {"ok": True, "caracteres": len(text)}


_ALLOWED_KEYS = (
    {chr(c) for c in range(ord("a"), ord("z") + 1)} | {str(d) for d in range(10)}
    | {f"f{i}" for i in range(1, 13)}
    | {"ctrl", "alt", "shift", "win", "enter", "tab", "esc", "space", "backspace", "delete",
       "up", "down", "left", "right", "home", "end", "pageup", "pagedown"}
)


def hotkey(combo: str) -> dict:
    """Pressiona uma combinação, por exemplo 'ctrl+s' ou 'win+d'."""
    keys = [k.strip().lower() for k in str(combo or "").split("+") if k.strip()]
    if not keys or len(keys) > 4:
        raise PCError("Informe de 1 a 4 teclas separadas por +, por exemplo ctrl+s.")
    bad = [k for k in keys if k not in _ALLOWED_KEYS]
    if bad:
        raise PCError(f"Tecla não permitida: {', '.join(bad)}.")
    _pg().hotkey(*keys)
    return {"ok": True, "teclas": keys}


def scroll(amount: int) -> dict:
    amount = max(-30, min(int(amount), 30))
    _pg().scroll(amount * 100)
    return {"ok": True, "rolagem": amount}


def wait(seconds: float) -> dict:
    seconds = max(0.0, min(float(seconds), 10.0))
    _sleep(seconds)
    return {"ok": True, "esperou_s": seconds}
