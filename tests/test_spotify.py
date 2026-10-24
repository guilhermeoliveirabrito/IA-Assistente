import base64
import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistente.integracoes import spotify_control as sp  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeHTTP:
    """Responde em ordem; guarda cada requisição feita."""

    def __init__(self):
        self.queue = []
        self.requests = []

    def add(self, status=200, body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.queue.append((status, headers or {}, raw))

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.requests.append({"method": method, "url": url, "headers": headers or {},
                              "body": body.decode() if isinstance(body, bytes) else body})
        return self.queue.pop(0)


TRACK = {"tracks": {"items": [{"name": "Faixa", "uri": "spotify:track:1", "artists": [{"name": "Banda"}]}]}}
DEVICE_ACTIVE = {"devices": [{"id": "d1", "name": "PC", "is_active": True}]}
DEVICE_IDLE = {"devices": [{"id": "d1", "name": "PC", "is_active": False}]}


class SpotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.http = FakeHTTP()
        self.now = 1_000_000.0
        self.sleeps = []
        self.s = sp.Spotify(client_id="cid", http=self.http, sleep=lambda x: self.sleeps.append(x),
                            clock=lambda: self.now, open_browser=lambda url: None)
        self.s._token = {"access_token": "tok", "refresh_token": "ref", "expires_at": self.now + 3600}

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    # ---- login
    def test_pkce_challenge_bate_com_o_verifier(self):
        verifier, challenge = sp.make_pkce()
        self.assertTrue(43 <= len(verifier) <= 128)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_url_de_autorizacao(self):
        url = self.s.build_auth_url("CH", "ST")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(q["client_id"], ["cid"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:8888/callback"])
        self.assertEqual(q["state"], ["ST"])
        self.assertIn("user-modify-playback-state", q["scope"][0])

    def _callback(self, port, query):
        def go():
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{query}", timeout=3).read()
                    return
                except OSError:
                    threading.Event().wait(0.05)
        t = threading.Thread(target=go)
        t.start()
        return t

    def test_servidor_de_callback_recebe_o_codigo(self):
        port = free_port()
        s = sp.Spotify(client_id="cid", port=port)
        t = self._callback(port, "code=ABC&state=XYZ")
        self.assertEqual(s.wait_for_callback("XYZ", timeout=5), "ABC")
        t.join()

    def test_callback_com_state_errado_e_recusado(self):
        port = free_port()
        s = sp.Spotify(client_id="cid", port=port)
        t = self._callback(port, "code=ABC&state=OUTRO")
        with self.assertRaises(sp.SpotifyError) as cm:
            s.wait_for_callback("XYZ", timeout=5)
        self.assertEqual(cm.exception.kind, "auth")
        t.join()

    def test_callback_com_erro_do_spotify(self):
        port = free_port()
        s = sp.Spotify(client_id="cid", port=port)
        t = self._callback(port, "error=access_denied&state=XYZ")
        with self.assertRaises(sp.SpotifyError):
            s.wait_for_callback("XYZ", timeout=5)
        t.join()

    def test_sem_client_id(self):
        os.environ.pop("SPOTIFY_CLIENT_ID", None)
        s = sp.Spotify(client_id="", http=self.http)
        with self.assertRaises(sp.SpotifyError) as cm:
            s.pause()
        self.assertEqual(cm.exception.kind, "config")
        self.assertEqual(self.http.requests, [])

    def test_token_expirado_e_renovado_e_mantem_refresh_token(self):
        self.s._token["expires_at"] = self.now - 10
        self.http.add(200, {"access_token": "novo", "expires_in": 3600})   # refresh sem novo refresh_token
        self.http.add(204)
        self.s.pause()
        refresh_req = self.http.requests[0]
        self.assertIn("grant_type=refresh_token", refresh_req["body"])
        self.assertEqual(self.http.requests[1]["headers"]["Authorization"], "Bearer novo")
        saved = json.loads(Path("data/spotify_token.json").read_text())
        self.assertEqual(saved["refresh_token"], "ref")

    def test_401_renova_e_tenta_de_novo_uma_vez(self):
        self.http.add(401, {"error": {"message": "expired"}})
        self.http.add(200, {"access_token": "novo2", "expires_in": 3600})
        self.http.add(204)
        self.s.pause()
        self.assertEqual(len(self.http.requests), 3)

    # ---- ações
    def test_tocar_faixa_no_dispositivo_ativo(self):
        self.http.add(200, TRACK)
        self.http.add(200, DEVICE_ACTIVE)
        self.http.add(204)
        res = self.s.play("faixa banda")
        self.assertEqual(res["tocando"], "Faixa — Banda")
        req = self.http.requests[2]
        self.assertEqual(req["method"], "PUT")
        self.assertIn("/me/player/play?device_id=d1", req["url"])
        self.assertEqual(json.loads(req["body"]), {"uris": ["spotify:track:1"]})

    def test_dispositivo_inativo_recebe_transferencia_antes(self):
        self.http.add(200, TRACK)
        self.http.add(200, DEVICE_IDLE)
        self.http.add(204)   # transferir
        self.http.add(204)   # tocar
        self.s.play("x")
        self.assertEqual(self.http.requests[2]["url"], sp.API + "/me/player")
        self.assertEqual(json.loads(self.http.requests[2]["body"])["device_ids"], ["d1"])

    def test_abre_o_spotify_quando_nao_ha_dispositivo(self):
        launched = []
        self.s.launch_app = lambda: launched.append(1)
        self.http.add(200, TRACK)
        self.http.add(200, {"devices": []})
        self.http.add(200, DEVICE_IDLE)
        self.http.add(204)
        self.http.add(204)
        self.s.play("x")
        self.assertEqual(launched, [1])
        self.assertTrue(self.sleeps)

    def test_sem_dispositivo_apos_esperar(self):
        self.http.add(200, TRACK)
        for _ in range(12):
            self.http.add(200, {"devices": []})
        with self.assertRaises(sp.SpotifyError) as cm:
            self.s.play("x")
        self.assertEqual(cm.exception.kind, "no_device")

    def test_playlist_usa_context_uri(self):
        self.http.add(200, {"playlists": {"items": [None, {"name": "Foco", "uri": "spotify:playlist:9",
                                                          "owner": {"display_name": "eu"}}]}})
        self.http.add(200, DEVICE_ACTIVE)
        self.http.add(204)
        self.s.play("foco", "playlist")
        self.assertEqual(json.loads(self.http.requests[2]["body"]), {"context_uri": "spotify:playlist:9"})

    def test_nao_encontrado(self):
        self.http.add(200, {"tracks": {"items": []}})
        with self.assertRaises(sp.SpotifyError) as cm:
            self.s.play("zzz")
        self.assertEqual(cm.exception.kind, "not_found")

    def test_exige_premium(self):
        self.http.add(403, {"error": {"status": 403, "message": "Player command failed: Premium required",
                                      "reason": "PREMIUM_REQUIRED"}})
        with self.assertRaises(sp.SpotifyError) as cm:
            self.s.pause()
        self.assertEqual(cm.exception.kind, "premium")

    def test_limite_de_requisicoes_espera_e_repete(self):
        self.http.add(429, None, {"Retry-After": "3"})
        self.http.add(204)
        self.s.next()
        self.assertEqual(self.sleeps, [3.0])

    def test_busca_pede_no_maximo_10(self):
        self.http.add(200, TRACK)
        self.s.search("x", limit=99)
        self.assertIn("limit=10", self.http.requests[0]["url"])

    def test_volume_limitado(self):
        self.http.add(204)
        self.assertEqual(self.s.set_volume(500)["volume"], 100)
        self.assertIn("volume_percent=100", self.http.requests[0]["url"])

    def test_o_que_esta_tocando(self):
        self.http.add(200, {"is_playing": True, "item": {"name": "Faixa", "artists": [{"name": "Banda"}]},
                            "device": {"name": "PC", "volume_percent": 40}})
        np = self.s.now_playing()
        self.assertEqual((np["tocando"], np["faixa"], np["volume"]), (True, "Faixa", 40))

    def test_nada_tocando(self):
        self.http.add(204)
        self.assertEqual(self.s.now_playing(), {"tocando": False})


if __name__ == "__main__":
    unittest.main()
