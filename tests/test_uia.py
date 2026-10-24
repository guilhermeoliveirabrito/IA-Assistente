import unittest

from assistente.pc import uia


class FakeBackend:
    def __init__(self):
        self.focused = []
        self.can_focus = True
        self.wins = [{"title": "Assistente", "handle": 1, "fg": False, "min": False},
                     {"title": "Bloco de Notas - texto.txt", "handle": 2, "fg": True, "min": False},
                     {"title": "Google Chrome", "handle": 3, "fg": False, "min": True},
                     {"title": "", "handle": 4, "fg": False, "min": False}]
        self.els = [
            {"type": "ButtonControl", "name": "Salvar", "rect": (960, 540, 1056, 594)},
            {"type": "EditControl", "name": "  Buscar\n aqui ", "rect": (100, 100, 900, 150)},
            {"type": "TextControl", "name": "rótulo", "rect": (0, 0, 100, 20)},
            {"type": "ButtonControl", "name": "Minúsculo", "rect": (10, 10, 12, 12)},
            {"type": "ButtonControl", "name": "Fora da tela", "rect": (5000, 5000, 5100, 5100)},
        ]

    def windows(self):
        return list(self.wins)

    def focus(self, handle):
        self.focused.append(handle)
        return self.can_focus

    def elements(self, limit, seconds):
        return list(self.els)

    def screen_size(self):
        return 1920, 1080


class UIATest(unittest.TestCase):
    def setUp(self):
        self.saved = (uia._backend, uia._elements, uia._sleep)
        self.be = uia._backend = FakeBackend()
        uia._elements = []
        uia._sleep = lambda s: None

    def tearDown(self):
        uia._backend, uia._elements, uia._sleep = self.saved

    def test_lista_janelas_sem_o_proprio_app_e_sem_titulo_vazio(self):
        titles = [w["titulo"] for w in uia.list_windows()]
        self.assertEqual(titles, ["Bloco de Notas - texto.txt", "Google Chrome"])

    def test_focar_por_parte_do_titulo_sem_acento_nem_maiuscula(self):
        self.assertEqual(uia.focus_window("BLOCO de notas", wait=0)["janela"], "Bloco de Notas - texto.txt")
        self.assertEqual(self.be.focused, [2])

    def test_focar_janela_inexistente_lista_as_abertas(self):
        with self.assertRaises(uia.UIError) as c:
            uia.focus_window("photoshop", wait=0)
        self.assertIn("Google Chrome", str(c.exception))

    def test_focar_que_o_windows_recusa_vira_erro(self):
        self.be.can_focus = False
        with self.assertRaises(uia.UIError):
            uia.focus_window("chrome", wait=0)

    def test_elementos_numerados_filtrados_e_em_escala_1000(self):
        els = uia.list_elements()
        self.assertEqual([e["nome"] for e in els], ["Buscar aqui", "Salvar"])      # só clicáveis, visíveis e não minúsculos
        self.assertEqual([e["numero"] for e in els], [1, 2])
        salvar = uia.get_element(2)
        self.assertEqual((salvar["x"], salvar["y"]), (round(1008 / 1920 * 1000), round(567 / 1080 * 1000)))
        self.assertEqual(len(uia.marks()), 2)

    def test_numero_invalido_ou_antigo_explica(self):
        uia.list_elements()
        for bad in (99, "x", None):
            with self.assertRaises(uia.UIError):
                uia.get_element(bad)

    def test_esquecer_invalida_os_numeros(self):
        uia.list_elements()
        uia.forget()
        with self.assertRaises(uia.UIError):
            uia.get_element(1)
        self.assertEqual(uia.marks(), [])

    def test_sem_windows_nem_backend_nao_esta_disponivel(self):
        uia._backend = None
        import sys
        if sys.platform != "win32":
            self.assertFalse(uia.available())
            with self.assertRaises(uia.UIError):
                uia.list_windows()


if __name__ == "__main__":
    unittest.main()
