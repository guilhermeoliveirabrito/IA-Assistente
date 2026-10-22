"""Rotina automática de e-mails e agenda, rodando em segundo plano enquanto o app está aberto.

Só funciona depois do login no Google (`python main.py setup`). Sem o login, fica quieta.
Cada execução vai para o histórico, e os relatórios ficam em data/.
"""
import threading
import time
from datetime import datetime
from pathlib import Path

import activity

DATA = Path("data")


def google_ready() -> bool:
    return Path("token.json").exists()


def _save(name: str, text: str):
    DATA.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (DATA / f"{name}_{stamp}.txt").write_text(text, encoding="utf-8")


def job_triage(cfg):
    import google_auth
    import triage

    try:
        triage.run_triage(google_auth.gmail_service(), cfg)
        activity.log("info", "Triagem de e-mails feita. O que precisa da sua aprovação fica em `python main.py aprovar`.")
    except Exception as e:  # a rotina nunca derruba o app
        activity.log("erro", f"Triagem de e-mails falhou: {e}")


def job_digest(cfg):
    import triage

    try:
        text = triage.digest(cfg)
        _save("resumo", text)
        activity.log("resultado", "Resumo diário dos e-mails pronto (pasta data/).")
    except Exception as e:
        activity.log("erro", f"Resumo diário falhou: {e}")


def job_agenda(cfg):
    import agenda
    import google_auth

    try:
        text = agenda.analyze(google_auth.calendar_service(), cfg)
        _save("agenda", text)
        activity.log("resultado", "Análise da agenda pronta (pasta data/).")
    except Exception as e:
        activity.log("erro", f"Análise da agenda falhou: {e}")


class Automation:
    def __init__(self, cfg):
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.running:
            return True
        if not google_ready():
            return False
        self._stop.clear()
        import schedule

        s = self.cfg.get("automatico") or {}
        self.sched = schedule.Scheduler()
        self.sched.every(int(s.get("triagem_a_cada_minutos", 15))).minutes.do(job_triage, self.cfg)
        self.sched.every().day.at(s.get("resumo_diario_as", "08:00")).do(job_digest, self.cfg)
        self.sched.every().day.at(s.get("analise_agenda_as", "07:30")).do(job_agenda, self.cfg)
        self._thread = threading.Thread(target=self._loop, name="automacao", daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        if self._stop.wait(20):          # dá tempo do app abrir antes da primeira triagem
            return
        job_triage(self.cfg)
        while not self._stop.wait(30):
            self.sched.run_pending()

    def stop(self):
        self._stop.set()
