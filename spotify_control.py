"""Spotify pela API oficial (login OAuth com PKCE: não precisa de "client secret").

Requisitos (regras do Spotify em 2026): conta Premium (o dono do app de desenvolvedor também
precisa ter Premium), um app criado em https://developer.spotify.com/dashboard com o
Redirect URI exatamente igual a `http://127.0.0.1:8888/callback`, e o Client ID em
SPOTIFY_CLIENT_ID (arquivo .env). Modo de desenvolvimento: até 5 usuários autorizados.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "user-modify-playback-state user-read-playback-state"
TOKEN_FILE = Path("data") / "spotify_token.json"
SEARCH_TYPES = {"faixa": "track", "album": "album", "playlist": "playlist", "artista": "artist"}


class SpotifyError(Exception):
    """kind: config | auth | premium | no_device | not_found | api"""

    def __init__(self, message, kind="api"):
        super().__init__(message)
        self.kind = kind


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce():
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def default_http(method, url, headers=None, body=None, timeout=30):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except urllib.error.URLError as e:
        raise SpotifyError(f"Sem conexão com o Spotify: {e.reason}")


class Spotify:
    def __init__(self, client_id=None, port=8888, http=default_http, open_browser=webbrowser.open,
                 sleep=time.sleep, clock=time.time, launch_app=None):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "")
        self.port = port
        self._http = http
        self._open_browser = open_browser
        self._sleep = sleep
        self._clock = clock
        self.launch_app = launch_app          # função que abre o aplicativo do Spotify
        self._token = None

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    # ---- login ---------------------------------------------------------------

    def _require_client_id(self):
        if not self.client_id:
            raise SpotifyError(
                "Falta o Client ID do Spotify. Crie um app em https://developer.spotify.com/dashboard, "
                f"cadastre o Redirect URI {self.redirect_uri} e coloque o ID em SPOTIFY_CLIENT_ID no .env.",
                "config",
            )

    def build_auth_url(self, challenge: str, state: str) -> str:
        q = {"client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
             "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state}
        return AUTH_URL + "?" + urllib.parse.urlencode(q)

    def wait_for_callback(self, state: str, timeout: float = 180) -> str:
        """Abre um servidor local por um instante e espera o Spotify devolver o código."""
        result = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                result["state"] = (qs.get("state") or [""])[0]
                result["code"] = (qs.get("code") or [""])[0]
                result["error"] = (qs.get("error") or [""])[0]
                ok = bool(result["code"]) and not result["error"]
                body = ("<meta charset=utf-8><body style='font-family:sans-serif;background:#1d1c1a;color:#ece8e1;"
                        "padding:3rem'><h2>" + ("Spotify conectado." if ok else "Não foi possível conectar.") +
                        "</h2><p>Pode fechar esta aba.</p>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", self.port), Handler)
        server.timeout = timeout
        try:
            server.handle_request()
        finally:
            server.server_close()
        if not result:
            raise SpotifyError("Tempo esgotado esperando a autorização do Spotify.", "auth")
        if result.get("error"):
            raise SpotifyError(f"O Spotify recusou a autorização: {result['error']}", "auth")
        if result.get("state") != state:
            raise SpotifyError("Resposta de autorização inválida (state diferente).", "auth")
        return result["code"]

    def _token_request(self, form: dict) -> dict:
        body = urllib.parse.urlencode(form).encode()
        status, _, raw = self._http("POST", TOKEN_URL,
                                    {"Content-Type": "application/x-www-form-urlencoded"}, body)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            data = {}
        if status != 200 or "access_token" not in data:
            raise SpotifyError(f"Falha no login do Spotify: {data.get('error_description') or data.get('error') or status}", "auth")
        return data

    def authorize(self):
        """Fluxo completo de login (abre o navegador uma vez)."""
        self._require_client_id()
        verifier, challenge = make_pkce()
        state = secrets.token_urlsafe(16)
        url = self.build_auth_url(challenge, state)
        box = {}
        t = threading.Thread(target=lambda: box.update(code=self._safe_wait(state)), daemon=True)
        t.start()
        self._open_browser(url)
        t.join(200)
        if isinstance(box.get("code"), Exception):
            raise box["code"]
        if not box.get("code"):
            raise SpotifyError("Autorização do Spotify não concluída.", "auth")
        data = self._token_request({"grant_type": "authorization_code", "code": box["code"],
                                    "redirect_uri": self.redirect_uri, "client_id": self.client_id,
                                    "code_verifier": verifier})
        self._store(data)

    def _safe_wait(self, state):
        try:
            return self.wait_for_callback(state)
        except Exception as e:  # devolve o erro para a thread principal
            return e

    def _store(self, data: dict, previous: dict = None):
        tok = {"access_token": data["access_token"],
               "refresh_token": data.get("refresh_token") or (previous or {}).get("refresh_token"),
               "expires_at": self._clock() + int(data.get("expires_in", 3600))}
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")
        self._token = tok

    def _load_token(self):
        if self._token is None and TOKEN_FILE.exists():
            try:
                self._token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            except ValueError:
                self._token = None
        return self._token

    def _refresh(self):
        tok = self._load_token()
        if not tok or not tok.get("refresh_token"):
            return False
        data = self._token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                    "client_id": self.client_id})
        self._store(data, previous=tok)
        return True

    def _access_token(self) -> str:
        self._require_client_id()
        tok = self._load_token()
        if not tok:
            self.authorize()
            tok = self._token
        elif tok["expires_at"] - 60 < self._clock():
            if not self._refresh():
                self.authorize()
            tok = self._token
        return tok["access_token"]

    # ---- chamadas à API -------------------------------------------------------

    def _api(self, method, path, params=None, body=None, _retry=True):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": "Bearer " + self._access_token()}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        status, hdrs, raw = self._http(method, url, headers, data)
        if status == 401 and _retry:
            if self._refresh():
                return self._api(method, path, params, body, _retry=False)
            self._token = None
            TOKEN_FILE.unlink(missing_ok=True)
            raise SpotifyError("Login do Spotify expirou. Tente de novo para autorizar.", "auth")
        if status == 429 and _retry:
            wait = min(float({k.lower(): v for k, v in hdrs.items()}.get("retry-after", 2)), 10)
            self._sleep(wait)
            return self._api(method, path, params, body, _retry=False)
        text = raw.decode("utf-8", errors="replace") if raw else ""
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = None
        if status in (200, 201, 202, 204):
            return payload
        message = ((payload or {}).get("error") or {}).get("message", text[:200]) if isinstance(payload, dict) else text[:200]
        reason = ((payload or {}).get("error") or {}).get("reason", "") if isinstance(payload, dict) else ""
        if reason == "NO_ACTIVE_DEVICE" or (status == 404 and "device" in message.lower()):
            raise SpotifyError("Nenhum dispositivo do Spotify ativo. Abra o Spotify no PC.", "no_device")
        if status == 403 and ("premium" in message.lower() or reason == "PREMIUM_REQUIRED"):
            raise SpotifyError("Controlar a reprodução exige Spotify Premium.", "premium")
        if status == 403:
            raise SpotifyError(f"O Spotify negou o acesso: {message}", "auth")
        raise SpotifyError(f"Erro do Spotify ({status}): {message}", "api")

    # ---- ações ----------------------------------------------------------------

    def search(self, query: str, kind: str = "faixa", limit: int = 5):
        api_type = SEARCH_TYPES.get(kind, "track")
        data = self._api("GET", "/search", {"q": query, "type": api_type, "limit": max(1, min(limit, 10))})
        items = [i for i in ((data or {}).get(api_type + "s", {}).get("items") or []) if i]
        out = []
        for i in items:
            artists = ", ".join(a["name"] for a in i.get("artists", []) if a) or (i.get("owner", {}) or {}).get("display_name", "")
            out.append({"nome": i.get("name", ""), "artista": artists, "uri": i["uri"], "tipo": api_type})
        return out

    def devices(self):
        return (self._api("GET", "/me/player/devices") or {}).get("devices", [])

    def ensure_device(self, tries: int = 12, delay: float = 1.5):
        launched = False
        for _ in range(tries):
            devs = [d for d in self.devices() if not d.get("is_restricted")]
            if devs:
                return next((d for d in devs if d.get("is_active")), devs[0])
            if not launched and self.launch_app:
                self.launch_app()
                launched = True
            self._sleep(delay)
        raise SpotifyError("O Spotify não apareceu como dispositivo. Abra o app e tente de novo.", "no_device")

    def play(self, query: str, kind: str = "faixa") -> dict:
        results = self.search(query, kind)
        if not results:
            raise SpotifyError(f"Não encontrei '{query}' no Spotify.", "not_found")
        item = results[0]
        device = self.ensure_device()
        if not device.get("is_active"):
            self._api("PUT", "/me/player", body={"device_ids": [device["id"]], "play": False})
            self._sleep(0.8)
        body = {"uris": [item["uri"]]} if item["tipo"] == "track" else {"context_uri": item["uri"]}
        self._api("PUT", "/me/player/play", {"device_id": device["id"]}, body)
        label = item["nome"] + (f" — {item['artista']}" if item["artista"] else "")
        return {"ok": True, "tocando": label, "dispositivo": device.get("name", "")}

    def pause(self):
        self._api("PUT", "/me/player/pause")
        return {"ok": True}

    def resume(self):
        self._api("PUT", "/me/player/play")
        return {"ok": True}

    def next(self):
        self._api("POST", "/me/player/next")
        return {"ok": True}

    def previous(self):
        self._api("POST", "/me/player/previous")
        return {"ok": True}

    def set_volume(self, percent: int):
        percent = max(0, min(int(percent), 100))
        self._api("PUT", "/me/player/volume", {"volume_percent": percent})
        return {"ok": True, "volume": percent}

    def now_playing(self) -> dict:
        data = self._api("GET", "/me/player")
        if not data or not data.get("item"):
            return {"tocando": False}
        item = data["item"]
        return {"tocando": bool(data.get("is_playing")), "faixa": item.get("name", ""),
                "artista": ", ".join(a["name"] for a in item.get("artists", [])),
                "dispositivo": (data.get("device") or {}).get("name", ""),
                "volume": (data.get("device") or {}).get("volume_percent")}
