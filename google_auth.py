"""Autenticação com Google (Gmail + Agenda). Roda o login no navegador só na primeira vez."""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.modify: ler, marcar e mandar para a lixeira (NÃO permite apagar para sempre)
# calendar.readonly: só leitura da agenda (seguro para a primeira versão)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
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
