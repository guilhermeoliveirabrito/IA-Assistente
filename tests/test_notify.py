import unittest
import urllib.error

from assistente.integracoes import notify


class FakeResp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.reqs = []
        self.fail = None
        self._orig = notify._urlopen

        def fake(req, timeout=None):
            self.reqs.append(req)
            if self.fail:
                raise self.fail
            return FakeResp()

        notify._urlopen = fake

    def tearDown(self):
        notify._urlopen = self._orig

    def test_topico_gerado_e_valido(self):
        t = notify.new_topic()
        self.assertTrue(notify.valid_topic(t), t)
        self.assertNotEqual(t, notify.new_topic())

    def test_topicos_invalidos(self):
        for bad in ("", "curto", "tem espaço no meio do nome", "../../x" * 4, None, "a" * 100):
            self.assertFalse(notify.valid_topic(bad), bad)

    def test_envia_com_titulo_ascii_e_corpo_utf8(self):
        topic = "assistente-" + "a" * 20
        self.assertTrue(notify.send(topic, "Aprovação pendente", "Abrir o site x — ok?", "http://192.168.0.5:8765"))
        req = self.reqs[0]
        self.assertTrue(req.full_url.endswith("/" + topic))
        self.assertEqual(req.get_header("Title"), "Aprovao pendente")
        self.assertEqual(req.data.decode(), "Abrir o site x — ok?")
        self.assertEqual(req.get_header("Click"), "http://192.168.0.5:8765")

    def test_nao_envia_sem_topico_valido(self):
        self.assertFalse(notify.send("x", "t", "m"))
        self.assertEqual(self.reqs, [])

    def test_click_so_http(self):
        notify.send("assistente-" + "b" * 20, "t", "m", "javascript:alert(1)")
        self.assertIsNone(self.reqs[0].get_header("Click"))

    def test_falha_de_rede_nao_levanta(self):
        self.fail = urllib.error.URLError("sem rede")
        self.assertFalse(notify.send("assistente-" + "c" * 20, "t", "m"))

    def test_mensagem_longa_e_cortada(self):
        notify.send("assistente-" + "d" * 20, "t", "x" * 5000)
        self.assertEqual(len(self.reqs[0].data), 500)

    def test_notifier_respeita_preferencias(self):
        topic = "assistente-" + "e" * 20
        n = notify.Notifier({"notificacoes": {"ntfy_topico": topic, "avisar_conclusao": False}})
        self.assertTrue(n.enabled)
        self.assertFalse(n.notify("pronta", "t", "m"))
        self.assertTrue(n.notify("pedido", "t", "m"))
        self.assertEqual(len(self.reqs), 1)

    def test_notifier_desligado_sem_topico(self):
        n = notify.Notifier({})
        self.assertFalse(n.enabled)
        self.assertFalse(n.notify("pedido", "t", "m"))
        self.assertEqual(self.reqs, [])


if __name__ == "__main__":
    unittest.main()
