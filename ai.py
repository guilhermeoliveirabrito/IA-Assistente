"""Camada de IA simples (texto, JSON e transcrição) sobre o cliente REST do Gemini."""
import base64
import json
import re

import gemini

GeminiError = gemini.GeminiError


def configure(cfg: dict):
    """Aplica as configurações do config.yaml (modelos reserva)."""
    gemini.set_fallbacks((cfg.get("ia") or {}).get("modelos_reserva", []))


def _user(parts):
    return [{"role": "user", "parts": parts}]


def ask_text(prompt: str, model: str) -> str:
    obj = gemini.generate(_user([{"text": prompt}]), gemini.models_for(model))
    return gemini.text_of(obj)


def _loads(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError as e:
        raise ValueError(f"A IA não devolveu um JSON válido: {text[:200]!r}") from e


def ask_json(prompt: str, model: str):
    obj = gemini.generate(_user([{"text": prompt}]), gemini.models_for(model), json_mode=True)
    return _loads(gemini.text_of(obj))


def transcribe(audio: bytes, mime: str, model: str) -> str:
    """Transcreve um áudio curto (fala em português) para texto."""
    parts = [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode("ascii")}},
        {"text": "Transcreva fielmente esta fala em português do Brasil. "
                 "Responda SOMENTE com o texto falado, sem comentários. "
                 "Se não houver fala, responda com uma string vazia."},
    ]
    obj = gemini.generate(_user(parts), gemini.models_for(model), temperature=0.0)
    return gemini.text_of(obj).strip()
