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
                        "_backend_override", "_grab_override", "_key_sender", "_marker", "_paste")}
        self.started, self.popen, self.browser, self.keys = [], [], [], []
        self.pg = FakePG()
        pc._platform = "win32"
        pc._startfile = lambda p: self.started.append(p)
        pc._popen = lambda args, *a, **k: self.popen.append(args)
        pc._open_browser = lambda url, new=0: self.browser.append(url)
        pc._sleep = lambda s: None
        pc._backend_override = self.pg
        pc._key_sender = lambda vk: self.keys.append(vk)
        pc._marker = None

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
    def test_captura_tem_grade_e_info_em_0_a_1000(self):
        from PIL import Image

        pc._grab_override = lambda: Image.new("RGB", (2560, 1440), "red")
        data, info = pc.screenshot()
        self.assertEqual(data[:2], b"\xff\xd8")  # JPEG
        self.assertEqual(info["tela_real"], "2560x1440")
        self.assertEqual(info["regiao"], [0, 0, 1000, 1000])
        import io
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.size, (1400, 788))          # reduzida
        # a grade foi desenhada: a imagem deixou de ser vermelha lisa
        self.assertGreater(len({img.getpixel((x, 300)) for x in range(0, 1400, 7)}), 3)

    def test_clique_converte_0_a_1000_para_pixels_reais(self):
        res = pc.click(500, 250)
        self.assertEqual(res["pixel_real"], [1280, 360])
        self.assertEqual(self.pg.calls[-1], ("click", 1280, 360, 1, "left"))
        pc.click(1000, 1000)                              # canto: nunca passa da tela
        self.assertEqual(self.pg.calls[-1], ("click", 2559, 1439, 1, "left"))
        pc.click(0, 0)
        self.assertEqual(self.pg.calls[-1], ("click", 0, 0, 1, "left"))

    def test_clique_fora_da_escala_explica_o_erro(self):
        for bad in ((1200, 5), (5, 1920), (-1, 5), ("a", 5)):
            with self.assertRaises(pc.PCError, msg=str(bad)) as cm:
                pc.click(*bad)
            self.assertIn("0 a 1000", str(cm.exception))
        self.assertEqual(self.pg.calls, [])

    def test_clique_aparece_marcado_na_proxima_captura(self):
        from PIL import Image

        pc._grab_override = lambda: Image.new("RGB", (1000, 1000), (0, 0, 0))
        pc.click(500, 500)
        data, _ = pc.screenshot(grid=False)               # sem grade: só o marcador
        import io
        img = Image.open(io.BytesIO(data)).convert("RGB")
        reds = sum(1 for x in range(1000) for y in range(0, 1000, 3) if img.getpixel((x, y))[0] > 150 and img.getpixel((x, y))[1] < 90)
        self.assertGreater(reds, 20)
        pc.clear_marker()
        data, _ = pc.screenshot(grid=False)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        self.assertLess(max(img.getpixel((x, y))[0] for x in range(0, 1000, 5) for y in range(0, 1000, 5)), 40)

    def test_zoom_de_regiao(self):
        from PIL import Image
        import io

        pc._grab_override = lambda: Image.new("RGB", (1920, 1080), "blue")
        data, info = pc.screenshot(region=(400, 400, 600, 600))
        self.assertEqual(info["regiao"], [400, 400, 600, 600])
        img = Image.open(io.BytesIO(data))
        self.assertGreater(img.size[0], 384)               # ampliada (a região real tem 384 px de largura)
        for bad in ((600, 400, 400, 600), (0, 0, 1500, 10), (0, 0, 5, 5), ("a", 1, 2, 3), (-1, 0, 10, 100)):
            with self.assertRaises(pc.PCError, msg=str(bad)):
                pc.screenshot(region=bad)

    def test_diz_se_a_tela_mudou_entre_capturas(self):
        from PIL import Image

        pc._last_sig = None
        pc._grab_override = lambda: Image.new("RGB", (800, 600), "black")
        self.assertIsNone(pc.screenshot()[1]["mudou"])                 # primeira captura: não há com o que comparar
        self.assertIs(pc.screenshot()[1]["mudou"], False)
        pc._grab_override = lambda: Image.new("RGB", (800, 600), "white")
        self.assertIs(pc.screenshot()[1]["mudou"], True)
        self.assertNotIn("mudou", pc.screenshot(region=(0, 0, 500, 500))[1])   # zoom não conta

    def test_settle_espera_a_tela_parar(self):
        from PIL import Image

        frames = iter([Image.new("RGB", (100, 100), c) for c in ("black", "gray", "white", "white", "white", "white")])
        pc._grab_override = lambda: next(frames)
        slept = []
        pc._sleep = lambda s: slept.append(s)
        pc.settle(min_wait=0.2, timeout=5)
        self.assertEqual(len(slept), 1 + 3)                             # mínimo + 3 comparações até estabilizar

    def test_settle_tem_teto_mesmo_com_tela_sempre_mudando(self):
        from PIL import Image

        n = [0]

        def grab():
            n[0] += 1
            return Image.new("RGB", (100, 100), (n[0] * 40 % 256,) * 3)

        pc._grab_override = grab
        pc.settle(min_wait=0, timeout=1.0, every=0.25)
        self.assertLessEqual(n[0], 6)

    def test_caixas_numeradas_aparecem_na_captura(self):
        from PIL import Image
        import io

        pc._grab_override = lambda: Image.new("RGB", (1000, 1000), (0, 0, 0))
        data, _ = pc.screenshot(grid=False, marks=[(7, 100, 100, 300, 200)])
        img = Image.open(io.BytesIO(data)).convert("RGB")
        r, g, b = img.getpixel((200, 100))                              # borda de cima da caixa rosa
        self.assertGreater(r, 150)
        self.assertGreater(b, 100)
        self.assertLess(g, 80)

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
