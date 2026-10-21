"""Avisos no celular via ntfy.sh (grátis, sem conta): chegam como notificação no iPhone.

Instale o app "ntfy" no iPhone e assine o MESMO tópico do config.yaml (`notificacoes.ntfy_topico`).
O tópico funciona como uma senha: quem souber o nome lê os avisos. Use um nome longo e aleatório
(o app gera um na primeira execução). Os avisos NÃO levam conteúdo sensível, só títulos curtos.
"""
import re
import secrets
import urllib.error
import urllib.request

SERVER = "https://ntfy.sh"
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_urlopen = urllib.request.urlopen


def new_topic() -> str:
    return "assistente-" + secrets.token_urlsafe(18).replace("=", "")[:24]


def valid_topic(topic: str) -> bool:
    return bool(topic and TOPIC_RE.match(topic))


def _ascii_header(text: str) -> str:
    return text.encode("ascii", "ignore").decode().strip() or "Assistente"


def send(topic: str, title: str, message: str, click_url: str = "", priority: int = 3, server: str = SERVER) -> bool:
    """Envia um aviso. Nunca levanta exceção: devolve False se não conseguiu."""
    if not valid_topic(topic):
        return False
    headers = {"Title": _ascii_header(title), "Priority": str(max(1, min(priority, 5))),
               "Content-Type": "text/plain; charset=utf-8"}
    if click_url.startswith(("http://", "https://")):
        headers["Click"] = click_url
    req = urllib.request.Request(f"{server}/{topic}", data=message[:500].encode("utf-8"), headers=headers, method="POST")
    try:
        with _urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


class Notifier:
    """Envia avisos conforme as preferências do config.yaml."""

    def __init__(self, cfg: dict, base_url: str = ""):
        n = (cfg or {}).get("notificacoes") or {}
        self.topic = n.get("ntfy_topico") or ""
        self.on = {"pedido": bool(n.get("avisar_pedidos", True)), "pronta": bool(n.get("avisar_conclusao", True)),
                   "pausa": bool(n.get("avisar_pausas", True)), "erro": bool(n.get("avisar_erros", True))}
        self.base_url = base_url

    @property
    def enabled(self) -> bool:
        return valid_topic(self.topic)

    def notify(self, kind: str, title: str, message: str, priority: int = 3) -> bool:
        if not self.enabled or not self.on.get(kind, True):
            return False
        return send(self.topic, title, message, self.base_url, priority)
