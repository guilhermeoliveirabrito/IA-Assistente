"""Camada de IA (Gemini). Se quiser trocar de modelo/provedor, só este arquivo muda."""
import json
import os
import time

from google import genai
from google.genai import types

_client = None


def _load_dotenv(path: str = ".env"):
    """Lê o arquivo .env (se existir) sem precisar de biblioteca extra."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("Defina a variável GEMINI_API_KEY (veja o passo 3 do README).")
        _client = genai.Client(api_key=key)
    return _client


def _generate(prompt: str, model: str, json_mode: bool):
    config = types.GenerateContentConfig(
        response_mime_type="application/json" if json_mode else "text/plain",
        temperature=0.2,
    )
    last_error = None
    for attempt in range(3):
        try:
            resp = _get_client().models.generate_content(
                model=model, contents=prompt, config=config
            )
            return resp.text
        except Exception as e:  # limite gratuito, rede, etc.
            last_error = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Falha ao chamar o Gemini: {last_error}")


def ask_json(prompt: str, model: str):
    return json.loads(_generate(prompt, model, json_mode=True))


def ask_text(prompt: str, model: str) -> str:
    return _generate(prompt, model, json_mode=False)
