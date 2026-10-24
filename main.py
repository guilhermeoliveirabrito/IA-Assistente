"""Linha de comando do Assistente (python main.py --help mostra os comandos)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from assistente.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
