import base64
import email
import email.header
import unittest

from assistente.integracoes import google_actions as ga


class Call:
    def __init__(self, svc, path, kwargs):
        self.svc, self.path, self.kwargs = svc, path, kwargs

    def execute(self):
        self.svc.calls.append((self.path, self.kwargs))
        r = self.svc.replies.get(self.path)
        return r(self.kwargs) if callable(r) else (r if r is not None else {})


class Node:
    def __init__(self, svc, path=""):
        self.svc, self.path = svc, path

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return Node(self.svc, self.path + "." + name if self.path else name)

    def __call__(self, **kw):
        if self.path.split(".")[-1] in ("events", "users", "messages", "drafts") and not kw:
            return Node(self.svc, self.path)
        return Call(self.svc, self.path, kw)


class FakeService:
    def __init__(self, **replies):
        self.calls, self.replies = [], replies

    def __getattr__(self, name):
        return Node(self, name)

    def last(self, path):
        return [kw for p, kw in self.calls if p == path][-1]


def decode(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw))


class AgendaTest(unittest.TestCase):
    def test_cria_evento_com_hora_e_duracao_padrao(self):
        s = FakeService(**{"events.insert": lambda kw: {"id": "ev1", "summary": kw["body"]["summary"], "start": kw["body"]["start"], "end": kw["body"]["end"]}})
        ev = ga.create_event(s, "Reunião", "2026-10-24 14:00")
        body = s.last("events.insert")["body"]
        self.assertEqual(body["start"], {"dateTime": "2026-10-24T14:00:00", "timeZone": "America/Sao_Paulo"})
        self.assertEqual(body["end"]["dateTime"], "2026-10-24T15:00:00")
        self.assertEqual(s.last("events.insert")["sendUpdates"], "none")
        self.assertEqual(ev["id"], "ev1")

    def test_dia_inteiro_convidados_e_lembrete(self):
        s = FakeService(**{"events.insert": {"id": "x"}})
        ga.create_event(s, "Viagem", "2026-11-01", end="2026-11-03", guests="a@x.com; b@y.org", remind_min=30)
        kw = s.last("events.insert")
        self.assertEqual(kw["body"]["start"], {"date": "2026-11-01"})
        self.assertEqual(kw["body"]["end"], {"date": "2026-11-04"})            # o fim do Google é exclusivo
        self.assertEqual([a["email"] for a in kw["body"]["attendees"]], ["a@x.com", "b@y.org"])
        self.assertEqual(kw["sendUpdates"], "all")
        self.assertEqual(kw["body"]["reminders"]["overrides"][0]["minutes"], 30)

    def test_validacoes(self):
        s = FakeService()
        for kw in (dict(title=" ", start="2026-10-24 10:00"), dict(title="x", start="amanhã"),
                   dict(title="x", start="2026-10-24 10:00", end="2026-10-24 09:00"),
                   dict(title="x", start="2026-10-24 10:00", guests="nao-e-email"),
                   dict(title="x", start="2026-10-24 10:00", guests=",".join(f"a{i}@x.com" for i in range(11)))):
            with self.assertRaises(ga.GoogleActionError, msg=str(kw)):
                ga.create_event(s, **kw)
        self.assertEqual(s.calls, [])

    def test_alterar_so_inicio_mantem_duracao(self):
        s = FakeService(**{"events.get": {"id": "ev1", "start": {"dateTime": "2026-10-24T14:00:00-03:00"},
                                          "end": {"dateTime": "2026-10-24T15:30:00-03:00"}},
                           "events.patch": {"id": "ev1"}})
        ga.update_event(s, "ev1", start="2026-10-25 09:00")
        body = s.last("events.patch")["body"]
        self.assertEqual(body["end"]["dateTime"], "2026-10-25T10:30:00")
        with self.assertRaises(ga.GoogleActionError):
            ga.update_event(s, "ev1")
        with self.assertRaises(ga.GoogleActionError):
            ga.update_event(s, "../x", title="a")

    def test_apagar_e_listar(self):
        s = FakeService(**{"events.list": {"items": [{"id": "e1", "summary": "A", "start": {"date": "2026-10-24"}, "end": {"date": "2026-10-25"}}]}})
        self.assertEqual(ga.list_events(s, "2026-10-24", 3, "dentista")[0]["titulo"], "A")
        self.assertEqual(s.last("events.list")["q"], "dentista")
        ga.delete_event(s, "e1")
        self.assertEqual(s.last("events.delete")["eventId"], "e1")


class EmailTest(unittest.TestCase):
    ORIG = {"id": "m1", "threadId": "t1", "payload": {"headers": [
        {"name": "From", "value": "Maria <maria@x.com>"}, {"name": "Subject", "value": "Orçamento"},
        {"name": "Message-ID", "value": "<abc@x>"}]}}

    def test_busca_e_leitura(self):
        s = FakeService(**{"users.messages.list": {"messages": [{"id": "m1"}]},
                           "users.messages.get": {"id": "m1", "snippet": "oi", "labelIds": ["UNREAD"],
                                                  "payload": {"headers": [{"name": "Subject", "value": "S"}], "mimeType": "text/plain",
                                                              "body": {"data": base64.urlsafe_b64encode("corpo longo".encode()).decode()}}}})
        r = ga.search_emails(s, "is:unread", 5)
        self.assertTrue(r[0]["nao_lido"])
        self.assertEqual(s.last("users.messages.list")["maxResults"], 5)
        self.assertEqual(ga.read_email(s, "m1")["texto"], "corpo longo")

    def test_rascunho_de_resposta_preenche_tudo(self):
        s = FakeService(**{"users.messages.get": self.ORIG, "users.drafts.create": {"id": "d1"}})
        r = ga.create_draft(s, body="Segue o orçamento.", reply_to="m1")
        msg = s.last("users.drafts.create")["body"]["message"]
        self.assertEqual(msg["threadId"], "t1")
        m = decode(msg["raw"])
        self.assertEqual(m["To"], "maria@x.com")
        self.assertEqual(str(email.header.make_header(email.header.decode_header(m["Subject"]))), "Re: Orçamento")
        self.assertEqual(m["In-Reply-To"], "<abc@x>")
        self.assertIn("orçamento", m.get_payload(decode=True).decode())
        self.assertEqual(r["rascunho"], "d1")
        self.assertFalse(any(p == "users.messages.send" for p, _ in s.calls))     # rascunho nunca envia

    def test_nao_deixa_injetar_cabecalho(self):
        s = FakeService()
        for to, subject in (("a@x.com\nBcc: v@x.com", "oi"), ("a@x.com", "oi\nBcc: v@x.com")):
            try:
                raw = ga.build_message(to, subject, "corpo")
            except (ga.GoogleActionError, ValueError):
                continue
            self.assertNotIn("Bcc", decode(raw))

    def test_enviar_e_marcar(self):
        s = FakeService(**{"users.messages.send": {"id": "sent1"}})
        self.assertEqual(ga.send_email(s, "a@x.com", "Oi", "Texto")["enviado"], "sent1")
        ga.modify_email(s, "m1", "lido")
        self.assertEqual(s.last("users.messages.modify")["body"], {"removeLabelIds": ["UNREAD"]})
        ga.modify_email(s, "m1", "lixeira")
        self.assertEqual(s.last("users.messages.trash")["id"], "m1")
        with self.assertRaises(ga.GoogleActionError):
            ga.modify_email(s, "m1", "apagar_para_sempre")

    def test_sem_destinatario_assunto_ou_corpo(self):
        for kw in (dict(to=None, subject="x", body="y"), dict(to="a@x.com", subject="", body="y"), dict(to="a@x.com", subject="x", body=" ")):
            with self.assertRaises(ga.GoogleActionError):
                ga.build_message(**kw)


if __name__ == "__main__":
    unittest.main()
