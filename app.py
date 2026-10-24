"""Abre o Assistente como um aplicativo (janela própria).

  python app.py               # janela do app (usa pywebview; sem ele abre no navegador)
  python app.py --no-window   # só o servidor (útil para deixar rodando e usar pelo celular)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)                      # config.yaml, data/ e memory/ são sempre os da pasta do projeto
sys.path.insert(0, str(ROOT))

from assistente.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
