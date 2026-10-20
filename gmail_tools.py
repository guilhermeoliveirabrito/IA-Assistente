"""Funções do Gmail: listar não lidos, ler conteúdo, mandar para a lixeira."""
import base64
import re

MAX_BODY_CHARS = 1200


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _extract_text(payload) -> str:
    """Pega o texto simples do email (ou HTML sem tags, se for o único)."""
    plain, html = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain) if plain else re.sub(r"<[^>]+>", " ", "\n".join(html))
    return re.sub(r"\s+", " ", text).strip()[:MAX_BODY_CHARS]


def list_new_emails(service, processed_ids: set, max_results: int = 25, query: str = "in:inbox is:unread newer_than:2d"):
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    emails = []
    for ref in resp.get("messages", []):
        if ref["id"] in processed_ids:
            continue
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        emails.append(
            {
                "id": msg["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(sem assunto)"),
                "date": headers.get("date", ""),
                "body": _extract_text(msg["payload"]) or msg.get("snippet", ""),
            }
        )
    return emails


def trash_email(service, message_id: str):
    """Manda para a lixeira (recuperável por 30 dias). Nunca apaga definitivamente."""
    service.users().messages().trash(userId="me", id=message_id).execute()
