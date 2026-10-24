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


# Coordenadas da IA: SEMPRE de 0 a 1000 nos dois eixos, em relação à tela inteira
# (0,0 = canto superior esquerdo; 1000,1000 = canto inferior direito). É a escala em que o Gemini enxerga
# melhor, e não depende da resolução nem do zoom do Windows.
SCALE = 1000
_marker = None               # último clique (x, y de 0 a 1000), desenhado nas capturas seguintes


def _font(size):
    from PIL import ImageFont

    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


_last_sig = None             # miniatura da última captura da tela inteira (para saber se a tela mudou)
CHANGE_EPS = 1.5             # diferença média (0-255) abaixo da qual a tela é considerada igual


def _signature(img):
    return img.convert("L").resize((48, 27)).tobytes()


def _diff(a, b) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _grab():
    if _grab_override:
        return _grab_override()
    from PIL import ImageGrab

    return ImageGrab.grab()


def settle(min_wait: float = 0.2, timeout: float = 1.6, every: float = 0.15) -> float:
    """Espera a tela parar de mudar (animação de janela, página carregando) em vez de um atraso fixo.
    Devolve quanto esperou. Nunca passa de `timeout`."""
    start = time.time()
    _sleep(min_wait)
    try:
        prev = _signature(_grab())
        for _ in range(max(1, round(timeout / every))):
            if time.time() - start >= timeout:
                break
            _sleep(every)
            cur = _signature(_grab())
            if _diff(prev, cur) <= CHANGE_EPS:
                break
            prev = cur
    except Exception:
        pass
    return round(time.time() - start, 2)


def _nice_step(span: float) -> int:
    for step in (10, 20, 25, 50, 100):
        if span / step <= 10:
            return step
    return 100


def _annotate(img, x1, y1, x2, y2, marker=None, grid=True, marks=None):
    """Desenha a grade (com os números 0-1000 da TELA INTEIRA) e o último clique sobre a captura."""
    from PIL import Image, ImageDraw

    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    font = _font(max(12, round(w / 90)))
    step = _nice_step(max(x2 - x1, y2 - y1))

    def label(xy, text, anchor):
        box = d.textbbox(xy, text, font=font, anchor=anchor)
        d.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill=(0, 0, 0, 200))
        d.text(xy, text, font=font, fill=(255, 224, 70, 255), anchor=anchor)

    v = (int(x1) // step + 1) * step if x1 % step else int(x1)
    while grid and v <= x2:
        px = round((v - x1) / (x2 - x1) * (w - 1))
        d.line((px, 0, px, h), fill=(0, 220, 255, 90), width=1)
        label((px, 2), str(v), "mt")
        label((px, h - 2), str(v), "mb")
        v += step
    v = (int(y1) // step + 1) * step if y1 % step else int(y1)
    while grid and v <= y2:
        py = round((v - y1) / (y2 - y1) * (h - 1))
        d.line((0, py, w, py), fill=(0, 220, 255, 90), width=1)
        label((2, py), str(v), "lm")
        label((w - 2, py), str(v), "rm")
        v += step
    for n, bx1, by1, bx2, by2 in (marks or []):
        if bx2 < x1 or bx1 > x2 or by2 < y1 or by1 > y2:
            continue
        px1, px2 = ((v - x1) / (x2 - x1) * (w - 1) for v in (bx1, bx2))
        py1, py2 = ((v - y1) / (y2 - y1) * (h - 1) for v in (by1, by2))
        d.rectangle((px1, py1, px2, py2), outline=(255, 0, 200, 230), width=2)
        label((round(max(0, px1)) + 1, round(max(0, py1)) + 1), str(n), "la")
    if marker and x1 <= marker[0] <= x2 and y1 <= marker[1] <= y2:
        mx = round((marker[0] - x1) / (x2 - x1) * (w - 1))
        my = round((marker[1] - y1) / (y2 - y1) * (h - 1))
        r = max(10, round(w / 80))
        d.ellipse((mx - r, my - r, mx + r, my + r), outline=(255, 40, 40, 255), width=3)
        d.line((mx - r - 6, my, mx + r + 6, my), fill=(255, 40, 40, 255), width=2)
        d.line((mx, my - r - 6, mx, my + r + 6), fill=(255, 40, 40, 255), width=2)
        label((mx + r + 8, my - r - 8), "último clique", "lb")
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def screenshot(region=None, max_width: int = 1400, grid: bool = True, marks=None):
    """Captura a tela (ou só uma região, ampliada) com uma grade numerada de 0 a 1000.

    region: (x1, y1, x2, y2) nas mesmas coordenadas 0-1000 da tela inteira. Retorna (bytes JPEG, info).
    """
    _set_dpi_aware()
    try:
        if _grab_override:
            img = _grab_override()
        else:
            from PIL import ImageGrab

            img = ImageGrab.grab()
    except Exception as e:
        raise PCError(f"Não consegui capturar a tela: {e}") from e
    img = img.convert("RGB")
    real_w, real_h = img.size
    sig = _signature(img) if region is None else None
    x1, y1, x2, y2 = 0.0, 0.0, float(SCALE), float(SCALE)
    if region is not None:
        try:
            x1, y1, x2, y2 = (float(v) for v in region)
        except (TypeError, ValueError) as e:
            raise PCError("A região precisa de 4 números: x1, y1, x2, y2 (de 0 a 1000).") from e
        if not (0 <= x1 < x2 <= SCALE and 0 <= y1 < y2 <= SCALE) or (x2 - x1) < 20 or (y2 - y1) < 20:
            raise PCError("Região inválida: use x1<x2 e y1<y2 entre 0 e 1000, com pelo menos 20 de largura e altura.")
        img = img.crop((round(x1 / SCALE * real_w), round(y1 / SCALE * real_h),
                        round(x2 / SCALE * real_w), round(y2 / SCALE * real_h)))
    w, h = img.size
    if w > max_width or region is not None:
        factor = max_width / w if region is None else min(max_width / w, 3.0)
        img = img.resize((max(1, round(w * factor)), max(1, round(h * factor))))
    if grid or _marker or marks:
        img = _annotate(img, x1, y1, x2, y2, _marker, grid, marks)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    info = {"tela_real": f"{real_w}x{real_h}", "regiao": [round(x1), round(y1), round(x2), round(y2)],
            "coordenadas": "0 a 1000 nos dois eixos, lidas nos números amarelos da grade; (0,0) = canto superior esquerdo"}
    if sig is not None:
        global _last_sig
        info["mudou"] = None if _last_sig is None else _diff(_last_sig, sig) > CHANGE_EPS
        _last_sig = sig
    return buf.getvalue(), info


def click(x, y, button: str = "left", clicks: int = 1) -> dict:
    """Clica em (x, y) em coordenadas de 0 a 1000 da tela inteira."""
    global _marker
    if button not in ("left", "right", "middle"):
        raise PCError("Botão inválido (left, right ou middle).")
    try:
        nx, ny = float(x), float(y)
    except (TypeError, ValueError) as e:
        raise PCError("x e y precisam ser números de 0 a 1000.") from e
    if not (0 <= nx <= SCALE and 0 <= ny <= SCALE):
        raise PCError(f"Coordenada ({x}, {y}) fora da escala: x e y vão de 0 a {SCALE} "
                      "(use os números amarelos da grade da captura).")
    clicks = max(1, min(int(clicks or 1), 3))
    pg = _pg()
    w, h = pg.size()
    real_x, real_y = min(w - 1, round(nx / SCALE * w)), min(h - 1, round(ny / SCALE * h))
    pg.click(real_x, real_y, clicks=clicks, button=button)
    _marker = (nx, ny)
    return {"ok": True, "clicou_em": [nx, ny], "pixel_real": [real_x, real_y], "botao": button, "cliques": clicks}


def clear_marker():
    global _marker
    _marker = None


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


_run = subprocess.run                  # os testes trocam por uma versão falsa
_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def clipboard_get() -> str:
    """Texto da área de transferência."""
    try:
        if _platform == "win32":
            r = _run(_PS + ["[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); Get-Clipboard -Raw"],
                     capture_output=True, timeout=10, check=False)
            return r.stdout.decode("utf-8", errors="replace").rstrip("\r\n")[:20000]
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()[:20000]
        except tkinter.TclError:
            return ""
        finally:
            root.destroy()
    except Exception as e:
        raise PCError(f"Não consegui ler a área de transferência: {e}") from e


def clipboard_set(text: str) -> dict:
    text = str(text if text is not None else "")
    if len(text) > 100000:
        raise PCError("Texto grande demais para a área de transferência (máximo 100000 caracteres).")
    try:
        if _platform == "win32":
            r = _run(_PS + ["[Console]::InputEncoding=[Text.UTF8Encoding]::new(); $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
                     input=text.encode("utf-8"), capture_output=True, timeout=10, check=False)
            if r.returncode != 0:
                raise PCError("O Windows recusou gravar na área de transferência.")
        else:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
            finally:
                root.destroy()
    except PCError:
        raise
    except Exception as e:
        raise PCError(f"Não consegui gravar na área de transferência: {e}") from e
    return {"ok": True, "caracteres": len(text)}


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
