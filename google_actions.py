"""Agir na agenda e no e-mail (além de ler): criar/mudar/apagar eventos, buscar e ler e-mails, preparar rascunhos,
marcar como lido, arquivar e (só se você liberar em Ajustes) enviar.

Os serviços do Google entram como parâmetro (`service`), então tudo aqui é testável sem internet.
Por segurança, enviar e-mail de verdade fica DESLIGADO por padrão: o assistente prepara o rascunho no seu Gmail
e você aperta enviar. Ligue em Ajustes › Gmail e Agenda se quiser que ele envie sozinho.
"""
import base64
import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import gmail_tools

TZ = "America/Sao_Paulo"
MAX_LIST = 25
MAX_RECIPIENTS = 10
EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


class GoogleActionError(ValueError):
    pass


# ---------------------------------------------------------------- agenda

def _parse(text: str):
    text = " ".join(str(text or "").split())
    for fmt, has_time in (("%Y-%m-%d %H:%M", True), ("%Y-%m-%dT%H:%M", True), ("%Y-%m-%d", False)):
        try:
            return datetime.strptime(text, fmt), has_time
        except ValueError:
            continue
    raise GoogleActionError("Data inválida. Use AAAA-MM-DD HH:MM (ou só AAAA-MM-DD para o dia inteiro).")


def _when(start_text, end_text=None, minutes=None):
    start, has_time = _parse(start_text)
    if not has_time:
        end = _parse(end_text)[0].date() if end_text else start.date()
        return ({"date": start.date().isoformat()}, {"date": (end + timedelta(days=1)).isoformat()})
    if end_text:
        end, _ = _parse(end_text)
    else:
        end = start + timedelta(minutes=int(minutes or 60))
    if end <= start:
        raise GoogleActionError("O fim precisa ser depois do início.")
    return ({"dateTime": start.isoformat(), "timeZone": TZ}, {"dateTime": end.isoformat(), "timeZone": TZ})


def _event_view(e: dict) -> dict:
    return {"id": e.get("id"), "titulo": e.get("summary", "(sem título)"),
            "inicio": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
            "fim": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
            "local": e.get("location", ""), "link": e.get("htmlLink", ""),
            "convidados": [a.get("email") for a in e.get("attendees", [])][:10]}


def _emails(value, field="e-mail"):
    items = [x.strip() for x in re.split(r"[;,]", value)] if isinstance(value, str) else [str(x).strip() for x in value or []]
    items = [x for x in items if x]
    if len(items) > MAX_RECIPIENTS:
        raise GoogleActionError(f"No máximo {MAX_RECIPIENTS} destinatários.")
    for x in items:
        if not EMAIL_RE.match(x):
            raise GoogleActionError(f"“{x}” não é um endereço de {field} válido.")
    return items


def list_events(service, start_text=None, days=7, query=None):
    start = _parse(start_text)[0] if start_text else datetime.now()
    days = max(1, min(int(days or 7), 90))
    params = {"calendarId": "primary", "timeMin": start.astimezone().isoformat(),
              "timeMax": (start + timedelta(days=days)).astimezone().isoformat(), "singleEvents": True,
              "orderBy": "startTime", "maxResults": 50}
    if query:
        params["q"] = str(query)[:100]
    return [_event_view(e) for e in service.events().list(**params).execute().get("items", [])]


def create_event(service, title, start, end=None, minutes=None, place="", description="", guests=None, remind_min=None):
    title = " ".join(str(title or "").split())
    if not title:
        raise GoogleActionError("Dê um título ao evento.")
    s, e = _when(start, end, minutes)
    body = {"summary": title[:200], "start": s, "end": e}
    if place:
        body["location"] = str(place)[:300]
    if description:
        body["description"] = str(description)[:4000]
    if guests:
        body["attendees"] = [{"email": x} for x in _emails(guests)]
    if remind_min not in (None, ""):
        body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": max(0, min(int(remind_min), 40320))}]}
    send = "all" if guests else "none"
    return _event_view(service.events().insert(calendarId="primary", body=body, sendUpdates=send).execute())


def update_event(service, event_id, title=None, start=None, end=None, minutes=None, place=None, description=None):
    event_id = _check_id(event_id)
    cur = service.events().get(calendarId="primary", eventId=event_id).execute()
    patch = {}
    if title:
        patch["summary"] = " ".join(str(title).split())[:200]
    if place is not None:
        patch["location"] = str(place)[:300]
    if description is not None:
        patch["description"] = str(description)[:4000]
    if start:
        if not end and not minutes:                                  # só mudou o início: mantém a duração
            old_s = (cur.get("start") or {}).get("dateTime")
            old_e = (cur.get("end") or {}).get("dateTime")
            if old_s and old_e:
                minutes = round((datetime.fromisoformat(old_e) - datetime.fromisoformat(old_s)).total_seconds() / 60)
        patch["start"], patch["end"] = _when(start, end, minutes)
    if not patch:
        raise GoogleActionError("Diga o que mudar (título, horário, local ou descrição).")
    return _event_view(service.events().patch(calendarId="primary", eventId=event_id, body=patch).execute())


def delete_event(service, event_id):
    event_id = _check_id(event_id)
    service.events().delete(calendarId="primary", eventId=event_id).execute()


def _check_id(value):
    value = str(value or "").strip()
    if not re.match(r"^[\w\-.]{1,200}$", value):
        raise GoogleActionError("Identificador inválido (veja em agenda_listar).")
    return value


# ---------------------------------------------------------------- e-mail

def _headers(msg):
    return {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}


def search_emails(service, query="in:inbox", limit=10):
    limit = max(1, min(int(limit or 10), MAX_LIST))
    refs = service.users().messages().list(userId="me", q=str(query or "in:inbox")[:200], maxResults=limit).execute().get("messages", [])
    out = []
    for r in refs:
        m = service.users().messages().get(userId="me", id=r["id"], format="metadata",
                                           metadataHeaders=["From", "Subject", "Date"]).execute()
        h = _headers(m)
        out.append({"id": m["id"], "de": h.get("from", ""), "assunto": h.get("subject", "(sem assunto)"),
                    "data": h.get("date", ""), "trecho": m.get("snippet", "")[:200],
                    "nao_lido": "UNREAD" in (m.get("labelIds") or [])})
    return out


def read_email(service, message_id, max_chars=6000):
    message_id = _check_id(message_id)
    m = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = _headers(m)
    body = gmail_tools._extract_text(m["payload"], max_chars) or m.get("snippet", "")
    return {"id": m["id"], "de": h.get("from", ""), "para": h.get("to", ""), "assunto": h.get("subject", ""),
            "data": h.get("date", ""), "texto": body, "thread": m.get("threadId")}


def build_message(to, subject, body, cc=None, reply_headers=None) -> str:
    to, cc = _emails(to), _emails(cc or [])
    if not to:
        raise GoogleActionError("Informe pelo menos um destinatário.")
    subject = " ".join(str(subject or "").split())
    if not subject:
        raise GoogleActionError("Informe o assunto.")
    if not str(body or "").strip():
        raise GoogleActionError("Escreva o corpo do e-mail.")
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject[:300]
    for k, v in (reply_headers or {}).items():
        msg[k] = v
    msg.set_content(str(body)[:20000])
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _reply_context(service, reply_to_id):
    orig = service.users().messages().get(userId="me", id=_check_id(reply_to_id), format="metadata",
                                          metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"]).execute()
    h = _headers(orig)
    to = h.get("reply-to") or h.get("from", "")
    m = re.search(r"<([^>]+)>", to)
    to = m.group(1) if m else to.strip()
    subject = h.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    headers = {}
    if h.get("message-id"):
        headers["In-Reply-To"] = h["message-id"]
        headers["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
    return to, subject, headers, orig.get("threadId")


def _compose(service, to, subject, body, cc, reply_to):
    thread, headers = None, None
    if reply_to:
        r_to, r_subject, headers, thread = _reply_context(service, reply_to)
        to = to or r_to
        subject = subject or r_subject
    raw = build_message(to, subject, body, cc, headers)
    msg = {"raw": raw}
    if thread:
        msg["threadId"] = thread
    return msg


def create_draft(service, to=None, subject=None, body=None, cc=None, reply_to=None):
    msg = _compose(service, to, subject, body, cc, reply_to)
    d = service.users().drafts().create(userId="me", body={"message": msg}).execute()
    return {"rascunho": d.get("id"), "para": _emails(to) if to else None, "assunto": subject}


def send_email(service, to=None, subject=None, body=None, cc=None, reply_to=None):
    msg = _compose(service, to, subject, body, cc, reply_to)
    sent = service.users().messages().send(userId="me", body=msg).execute()
    return {"enviado": sent.get("id")}


def modify_email(service, message_id, action):
    message_id = _check_id(message_id)
    users = service.users().messages()
    if action == "lido":
        users.modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
    elif action == "nao_lido":
        users.modify(userId="me", id=message_id, body={"addLabelIds": ["UNREAD"]}).execute()
    elif action == "arquivar":
        users.modify(userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}).execute()
    elif action == "estrela":
        users.modify(userId="me", id=message_id, body={"addLabelIds": ["STARRED"]}).execute()
    elif action == "lixeira":
        users.trash(userId="me", id=message_id).execute()          # recuperável por 30 dias
    else:
        raise GoogleActionError("Ação inválida: use lido, nao_lido, arquivar, estrela ou lixeira.")
    return {"id": message_id, "acao": action}
