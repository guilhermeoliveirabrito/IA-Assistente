"""Autenticação com Google (Gmail + Agenda). Roda o login no navegador só na primeira vez."""
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.modify: ler, marcar e mandar para a lixeira (NÃO permite apagar para sempre)
# calendar.events: ler, criar, mudar e apagar EVENTOS da agenda (não mexe nas configurações das agendas)
# Quem conectou numa versão antiga só tem leitura da agenda: o app avisa e basta reconectar (token.json é refeito).
CAL_WRITE = "https://www.googleapis.com/auth/calendar.events"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    CAL_WRITE,
]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def granted_scopes() -> set:
    """Permissões que o token salvo realmente tem (vazio se não há token)."""
    try:
        return set(json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scopes") or [])
    except (OSError, ValueError):
        return set()


def can_write_calendar() -> bool:
    return CAL_WRITE in granted_scopes() or "https://www.googleapis.com/auth/calendar" in granted_scopes()


def get_credentials(force: bool = False) -> Credentials:
    creds = None
    if TOKEN_FILE.exists() and not force:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))   # com as permissões que o token JÁ tem (senão a renovação falha)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise SystemExit(
                    "Arquivo credentials.json não encontrado. Siga o passo 2 do README."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def gmail_service():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def calendar_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)
