import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pc_control as pc  # noqa: E402


class FakePG:
    def __init__(self, size=(2560, 1440)):
        self._size = size
        self.calls = []

    def size(self):
        return self._size

    def click(self, x, y, clicks=1, button="left"):
        self.calls.append(("click", x, y, clicks, button))

    def write(self, text, interval=0):
        self.calls.append(("write", text))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def scroll(self, n):
        self.calls.append(("scroll", n))


class PCTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(pc, k) for k in
                       ("_platform", "_startfile", "_popen", "_open_browser", "_sleep",
                        "_backend_override", "_grab_override", "_key_sender", "_last_scale", "_paste")}
        self.started, self.popen, self.browser, self.keys = [], [], [], []
        self.pg = FakePG()
        pc._platform = "win32"
        pc._startfile = lambda p: self.started.append(p)
        pc._popen = lambda args, *a, **k: self.popen.append(args)
        pc._open_browser = lambda url, new=0: self.browser.append(url)
        pc._sleep = lambda s: None
        pc._backend_override = self.pg
        pc._key_sender = lambda vk: self.keys.append(vk)
        pc._last_scale = 1.0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(pc, k, v)

    # sites
    def test_abre_site_https(self):
        self.assertTrue(pc.open_url("https://exemplo.com/a?b=1")["ok"])
        self.assertEqual(self.browser, ["https://exemplo.com/a?b=1"])

    def test_dominio_sem_esquema_ganha_https(self):
        pc.open_url("github.com/guilherme")
        self.assertEqual(self.browser, ["https://github.com/guilherme"])

    def test_bloqueia_esquemas_perigosos(self):
        for bad in ("javascript:alert(1)", "file:///C:/Windows/System32", "ftp://x.com", "",
                    "https://usuario:senha@site.com", "cmd.exe /c calc"):
            with self.assertRaises(pc.PCError, msg=bad):
                pc.open_url(bad)
        self.assertEqual(self.browser, [])

    # apps
    def test_spotify_abre_pelo_protocolo(self):
        pc.open_app("Spotify")
        self.assertEqual(self.started, ["spotify:"])

    def test_alias_do_config(self):
        pc.open_app("meu editor", {"Meu Editor": "notepad.exe"})
        self.assertEqual(self.popen, [["notepad.exe"]])

    def test_procura_no_menu_iniciar(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "Visual Studio Code").mkdir()
            (base / "Visual Studio Code" / "Visual Studio Code.lnk").write_text("")
            (base / "Uninstall Visual Studio Code.lnk").write_text("")
            (base / "Visual Studio Installer.lnk").write_text("")
            found = pc.find_start_menu_shortcut("visual studio code", [base])
            self.assertEqual(found.stem, "Visual Studio Code")
            self.assertEqual(pc.find_start_menu_shortcut("code", [base]).stem, "Visual Studio Code")
            self.assertIsNone(pc.find_start_menu_shortcut("photoshop", [base]))

    def test_app_inexistente(self):
        original = pc.find_start_menu_shortcut
        pc.find_start_menu_shortcut = lambda name, dirs=None: None
        try:
            with self.assertRaises(pc.PCError):
                pc.open_app("programa-que-nao-existe-xyz")
        finally:
            pc.find_start_menu_shortcut = original
        self.assertEqual((self.started, self.popen), ([], []))

    def test_app_achado_no_menu_iniciar_e_aberto_pelo_atalho(self):
        original = pc.find_start_menu_shortcut
        pc.find_start_menu_shortcut = lambda name, dirs=None: Path("C:/Menu/Visual Studio Code.lnk")
        try:
            res = pc.open_app("vscode")
        finally:
            pc.find_start_menu_shortcut = original
        self.assertEqual(res["aberto"], "Visual Studio Code")
        self.assertTrue(self.started[0].endswith("Visual Studio Code.lnk"))

    def test_nomes_de_app_invalidos(self):
        for bad in ("", "calc & del *", "a|b", "x" * 100, "foo;bar"):
            with self.assertRaises(pc.PCError, msg=bad):
                pc.open_app(bad)

    # mídia
    def test_tecla_de_midia(self):
        pc.media("play_pause")
        pc.media("proxima")
        self.assertEqual(self.keys, [0xB3, 0xB0])

    def test_volume_repete_e_tem_limite(self):
        pc.media("volume_mais", 5)
        self.assertEqual(len(self.keys), 5)
        self.keys.clear()
        pc.media("volume_menos", 999)
        self.assertEqual(len(self.keys), 25)
        self.keys.clear()
        pc.media("proxima", 9)   # só volume repete
        self.assertEqual(len(self.keys), 1)

    def test_acao_de_midia_invalida(self):
        with self.assertRaises(pc.PCError):
            pc.media("formatar")

    # tela e mouse
    def test_captura_reduz_e_cliques_voltam_para_escala_real(self):
        from PIL import Image

        pc._grab_override = lambda: Image.new("RGB", (2560, 1440), "red")
        data, info = pc.screenshot(max_width=1280)
        self.assertEqual((info["largura"], info["altura"]), (1280, 720))
        self.assertEqual(data[:2], b"\xff\xd8")  # JPEG
        res = pc.click(100, 50)
        self.assertEqual((res["x"], res["y"]), (200, 100))
        self.assertEqual(self.pg.calls[-1], ("click", 200, 100, 1, "left"))

    def test_clique_fora_da_tela(self):
        with self.assertRaises(pc.PCError):
            pc.click(99999, 5)
        with self.assertRaises(pc.PCError):
            pc.click(-1, 5)
        self.assertEqual(self.pg.calls, [])

    def test_botao_invalido(self):
        with self.assertRaises(pc.PCError):
            pc.click(1, 1, button="foo")

    def test_cliques_limitados(self):
        pc.click(10, 10, clicks=50)
        self.assertEqual(self.pg.calls[-1][3], 3)

    # teclado
    def test_texto_ascii_usa_write(self):
        pc.type_text("hello world")
        self.assertEqual(self.pg.calls, [("write", "hello world")])

    def test_texto_com_acento_usa_colar(self):
        pasted = []
        pc._paste = lambda text, pg: pasted.append(text)
        pc.type_text("olá, ação")
        self.assertEqual(pasted, ["olá, ação"])
        self.assertEqual(self.pg.calls, [])

    def test_texto_vazio_ou_enorme(self):
        for bad in ("", "x" * 3001):
            with self.assertRaises(pc.PCError):
                pc.type_text(bad)

    def test_atalhos(self):
        pc.hotkey("Ctrl+Shift+P")
        self.assertEqual(self.pg.calls[-1], ("hotkey", ("ctrl", "shift", "p")))
        for bad in ("", "ctrl+alt+del+x+y", "ctrl+banana", "printscreen"):
            with self.assertRaises(pc.PCError, msg=bad):
                pc.hotkey(bad)

    def test_rolagem_e_espera_com_limites(self):
        pc.scroll(500)
        self.assertEqual(self.pg.calls[-1], ("scroll", 3000))
        slept = []
        pc._sleep = lambda s: slept.append(s)
        self.assertEqual(pc.wait(99)["esperou_s"], 10.0)


if __name__ == "__main__":
    unittest.main()
