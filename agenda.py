"""Análise da agenda: lê os próximos dias e sugere organização (não altera nada)."""
import json
from datetime import datetime, timedelta, timezone

import ai
import memory


def upcoming_events(service, dias: int):
    agora = datetime.now(timezone.utc)
    resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=agora.isoformat(),
            timeMax=(agora + timedelta(days=dias)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    return [
        {
            "titulo": e.get("summary", "(sem título)"),
            "inicio": e["start"].get("dateTime", e["start"].get("date")),
            "fim": e["end"].get("dateTime", e["end"].get("date")),
            "local": e.get("location", ""),
        }
        for e in resp.get("items", [])
    ]


def analyze(service, cfg):
    a = cfg["agenda"]
    eventos = upcoming_events(service, a["dias_a_frente"])
    if not eventos:
        return "Agenda vazia nos próximos dias."
    prompt = f"""Analise esta agenda (fuso America/Sao_Paulo) e responda em português, de forma objetiva:
1) Conflitos ou horários sobrepostos;
2) Dias sobrecarregados (muitos compromissos seguidos, sem pausa);
3) Janelas livres boas para trabalho focado (mín. {a['bloco_foco_minutos']} min) dentro do expediente {a['expediente']};
4) Sugestões concretas de reorganização (qual compromisso mover e para quando).
Preferências do usuário: {a['preferencias']}
{memory.prompt_block()}
Eventos: {json.dumps(eventos, ensure_ascii=False)}"""
    return ai.ask_text(prompt, cfg["ia"]["modelo"])
