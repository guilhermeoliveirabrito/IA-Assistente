"""Assistente pessoal automático: emails + agenda, rodando sozinho em segundo plano.

Uso:
  python main.py setup      # login no Google (só na primeira vez)
  python main.py triagem    # classifica emails novos agora
  python main.py resumo     # resumo do que chegou nas últimas 24h
  python main.py aprovar    # revisa o que a IA quer apagar/fazer
  python main.py agenda     # análise da agenda dos próximos dias
  python main.py rodar      # modo automático 24h (deixe aberto)
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
import yaml

import agenda
import google_auth
import triage

LOG = Path("data")
LOG.mkdir(exist_ok=True)


def load_cfg():
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))


def save_report(name: str, text: str):
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (LOG / f"{name}_{stamp}.txt").write_text(text, encoding="utf-8")


def job_triage(cfg):
    try:
        triage.run_triage(google_auth.gmail_service(), cfg)
    except Exception as e:
        print(f"[erro triagem] {e}")


def job_digest(cfg):
    try:
        text = triage.digest(cfg)
        save_report("resumo", text)
        print("\n=== RESUMO DO DIA ===\n" + text + "\n")
    except Exception as e:
        print(f"[erro resumo] {e}")


def job_agenda(cfg):
    try:
        text = agenda.analyze(google_auth.calendar_service(), cfg)
        save_report("agenda", text)
        print("\n=== ANÁLISE DA AGENDA ===\n" + text + "\n")
    except Exception as e:
        print(f"[erro agenda] {e}")


def run_forever(cfg):
    s = cfg["automatico"]
    schedule.every(s["triagem_a_cada_minutos"]).minutes.do(job_triage, cfg)
    schedule.every().day.at(s["resumo_diario_as"]).do(job_digest, cfg)
    schedule.every().day.at(s["analise_agenda_as"]).do(job_agenda, cfg)
    print("Assistente rodando. Ctrl+C para parar.")
    job_triage(cfg)
    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = load_cfg()
    if cmd == "setup":
        google_auth.get_credentials()
        print("Login feito. token.json criado.")
    elif cmd == "triagem":
        job_triage(cfg)
    elif cmd == "resumo":
        job_digest(cfg)
    elif cmd == "aprovar":
        triage.approve_pending(google_auth.gmail_service())
    elif cmd == "agenda":
        job_agenda(cfg)
    elif cmd == "rodar":
        run_forever(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
