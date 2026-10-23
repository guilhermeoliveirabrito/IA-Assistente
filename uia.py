"""Janelas e elementos da interface (Windows): o jeito PRECISO de usar o computador.

Clicar por coordenada de imagem é o último recurso: o Windows sabe exatamente onde está cada botão, campo e menu
da janela em primeiro plano (UI Automation). Aqui o assistente:
  - lista as janelas abertas e traz uma para frente pelo título (sem "alt+tab no escuro");
  - lista os elementos clicáveis da janela ativa, cada um com um NÚMERO, nome e posição, e a captura de tela sai
    com esses números desenhados em caixas (clicar_elemento(7) em vez de adivinhar x e y).

Precisa do pacote opcional `uiautomation` (pip install uiautomation) e só funciona no Windows; sem ele o assistente
continua usando a grade de coordenadas.
"""
import re
import sys
import time
import unicodedata

SCALE = 1000
MAX_ELEMENTS = 80
WALK_SECONDS = 2.5
OWN_TITLE = "Assistente"

INTERACTIVE = {
    "ButtonControl": "botão", "EditControl": "campo de texto", "ComboBoxControl": "lista suspensa",
    "CheckBoxControl": "caixa de seleção", "RadioButtonControl": "opção", "HyperlinkControl": "link",
    "ListItemControl": "item de lista", "MenuItemControl": "menu", "TabItemControl": "aba",
    "TreeItemControl": "item de árvore", "SplitButtonControl": "botão", "SliderControl": "controle deslizante",
}


class UIError(Exception):
    pass


_backend = None            # objeto com windows(), focus(handle), elements(), screen_size(); os testes trocam por um falso
_elements = []             # última lista entregue ao modelo (os números valem só para ela)
_sleep = time.sleep


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def available() -> bool:
    if _backend is not None:
        return True
    if sys.platform != "win32":
        return False
    import importlib.util

    return importlib.util.find_spec("uiautomation") is not None


def _be():
    global _backend
    if _backend is not None:
        return _backend
    if sys.platform != "win32":
        raise UIError("Janelas e elementos só estão disponíveis no Windows. Use a grade de coordenadas.")
    _backend = _WinBackend()
    return _backend


# ---------------------------------------------------------------- janelas

def list_windows() -> list:
    out = []
    for w in _be().windows():
        title = str(w.get("title") or "").strip()
        if not title or title == OWN_TITLE:
            continue
        out.append({"titulo": title[:120], "em_primeiro_plano": bool(w.get("fg")), "minimizada": bool(w.get("min")),
                    "_handle": w["handle"]})
    return out


def focus_window(title_part: str, wait: float = 5.0) -> dict:
    """Traz para frente a primeira janela cujo título contém o texto (ignora acentos e maiúsculas).
    Espera até `wait` segundos a janela aparecer (ex.: logo depois de abrir um programa)."""
    want = norm(title_part)
    if not want or len(want) > 80:
        raise UIError("Informe parte do título da janela (até 80 caracteres).")
    deadline = time.time() + max(0.0, min(float(wait or 0), 15.0))
    while True:
        wins = [w for w in list_windows() if want in norm(w["titulo"])]
        if wins:
            w = wins[0]
            if not _be().focus(w["_handle"]):
                raise UIError(f"Achei a janela “{w['titulo']}”, mas o Windows não deixou trazê-la para frente.")
            _sleep(0.15)
            return {"ok": True, "janela": w["titulo"]}
        if time.time() >= deadline:
            break
        _sleep(0.25)
    shown = ", ".join(f"“{w['titulo'][:40]}”" for w in list_windows()[:8]) or "nenhuma"
    raise UIError(f"Não achei uma janela com “{title_part}” no título. Janelas abertas: {shown}.")


# ---------------------------------------------------------------- elementos

def _to_scale(rect, size):
    w, h = size
    l, t, r, b = rect
    return (max(0, min(SCALE, round(l / w * SCALE))), max(0, min(SCALE, round(t / h * SCALE))),
            max(0, min(SCALE, round(r / w * SCALE))), max(0, min(SCALE, round(b / h * SCALE))))


def list_elements(limit: int = 60) -> list:
    """Elementos clicáveis visíveis da janela ativa, de cima para baixo e da esquerda para a direita."""
    global _elements
    be = _be()
    size = be.screen_size()
    raw = be.elements(max(5, min(int(limit or 60), MAX_ELEMENTS)), WALK_SECONDS)
    out = []
    for e in raw:
        kind = INTERACTIVE.get(e.get("type"))
        if not kind:
            continue
        l, t, r, b = _to_scale(e["rect"], size)
        if r - l < 4 or b - t < 4 or r <= 0 or b <= 0 or l >= SCALE or t >= SCALE:
            continue
        name = " ".join(str(e.get("name") or "").split())[:80]
        out.append({"tipo": kind, "nome": name, "box": [l, t, r, b], "x": round((l + r) / 2), "y": round((t + b) / 2)})
    out.sort(key=lambda e: (e["box"][1] // 25, e["box"][0]))
    out = out[:max(5, min(int(limit or 60), MAX_ELEMENTS))]
    for i, e in enumerate(out, 1):
        e["numero"] = i
    _elements = out
    return [dict(e) for e in out]


def get_element(number) -> dict:
    try:
        n = int(number)
    except (TypeError, ValueError):
        raise UIError("O número do elemento precisa ser um inteiro da última lista.")
    for e in _elements:
        if e["numero"] == n:
            return dict(e)
    raise UIError(f"O elemento {number} não existe. Chame listar_elementos de novo (os números mudam a cada lista).")


def marks() -> list:
    """Caixas numeradas dos elementos da última lista, para desenhar na captura: (número, x1, y1, x2, y2)."""
    return [(e["numero"], *e["box"]) for e in _elements]


def forget():
    global _elements
    _elements = []


# ---------------------------------------------------------------- implementação real (Windows)

class _WinBackend:
    def __init__(self):
        import ctypes

        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32

    def screen_size(self):
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)

    def windows(self):
        from ctypes import wintypes

        user32, ct = self.user32, self.ctypes
        out, fg = [], user32.GetForegroundWindow()

        @ct.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _lp):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ct.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    out.append({"title": buf.value, "handle": int(hwnd), "fg": hwnd == fg, "min": bool(user32.IsIconic(hwnd))})
            return True

        user32.EnumWindows(cb, 0)
        return out

    def focus(self, handle):
        user32 = self.user32
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)           # SW_RESTORE
        user32.keybd_event(0x12, 0, 0, 0)          # tecla Alt: destrava o SetForegroundWindow
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(handle)
        return user32.GetForegroundWindow() == handle

    def elements(self, limit, seconds):
        import uiautomation as auto

        top = auto.GetForegroundControl()
        if top is None:
            return []
        top = top.GetTopLevelControl() or top
        deadline = time.time() + seconds
        out, queue = [], [(top, 0)]
        while queue and len(out) < limit * 3 and time.time() < deadline:
            ctrl, depth = queue.pop(0)
            try:
                children = ctrl.GetChildren()
            except Exception:
                continue
            for c in children:
                try:
                    kind = c.ControlTypeName
                    if kind in INTERACTIVE and not c.IsOffscreen and c.IsEnabled:
                        r = c.BoundingRectangle
                        out.append({"type": kind, "name": c.Name, "rect": (r.left, r.top, r.right, r.bottom)})
                    if depth < 12:
                        queue.append((c, depth + 1))
                except Exception:
                    continue
        return out
