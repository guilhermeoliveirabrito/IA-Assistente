"""Rotina automática de e-mails e agenda, rodando em segundo plano enquanto o app está aberto.

Só funciona depois do login no Google (`python main.py setup`). Sem o login, fica quieta.
Cada execução vai para o histórico, e os relatórios ficam em data/.
"""
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from assistente.nucleo import activity

DATA = Path("data")


def google_ready() -> bool:
    return Path("token.json").exists()


def calendar_write() -> bool:
    """O token salvo permite criar e mudar eventos? (lê o arquivo; não precisa das bibliotecas do Google)"""
    import json

    try:
        scopes = set(json.loads(Path("token.json").read_text(encoding="utf-8")).get("scopes") or [])
    except (OSError, ValueError):
        return False
    return bool(scopes & {"https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar"})


def _save(name: str, text: str):
    DATA.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (DATA / f"{name}_{stamp}.txt").write_text(text, encoding="utf-8")


def job_triage(cfg):
    """Retorna (ok, texto curto do que aconteceu)."""
    from assistente.integracoes import google_auth
    from assistente.integracoes import triage

    try:
        r = triage.run_triage(google_auth.gmail_service(), cfg) or {}
        activity.log("info", "Triagem de e-mails feita. O que precisa da sua aprovação fica em `python main.py aprovar`.")
        n = r.get("novos", 0)
        if not n:
            return True, "Nenhum e-mail novo."
        cats = ", ".join(f"{v} {k}" for k, v in (r.get("categorias") or {}).items())
        return True, f"{n} e-mail(s) novo(s) classificado(s)" + (f": {cats}." if cats else ".")
    except Exception as e:  # a rotina nunca derruba o app
        activity.log("erro", f"Triagem de e-mails falhou: {e}")
        return False, f"Falhou: {e}"


def job_digest(cfg):
    from assistente.integracoes import triage

    try:
        text = triage.digest(cfg)
        _save("resumo", text)
        activity.log("resultado", "Resumo diário dos e-mails pronto (pasta data/).")
        return True, "Resumo do dia pronto."
    except Exception as e:
        activity.log("erro", f"Resumo diário falhou: {e}")
        return False, f"Falhou: {e}"


def job_agenda(cfg):
    from assistente.integracoes import agenda
    from assistente.integracoes import google_auth

    try:
        text = agenda.analyze(google_auth.calendar_service(), cfg)
        _save("agenda", text)
        activity.log("resultado", "Análise da agenda pronta (pasta data/).")
        return True, "Análise da agenda pronta."
    except Exception as e:
        activity.log("erro", f"Análise da agenda falhou: {e}")
        return False, f"Falhou: {e}"


def next_daily(hhmm: str, now: float) -> float:
    """Próximo horário local "HH:MM" depois de `now` (epoch)."""
    h, m = (int(x) for x in str(hhmm).split(":"))
    cur = datetime.fromtimestamp(now)
    t = cur.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= cur:
        t = t + timedelta(days=1)
    return t.timestamp()


FIRST_DELAY = 20          # segundos: dá tempo do app abrir antes da primeira triagem
TICK = 5


class Automation:
    """Roda as rotinas e guarda quando cada uma rodou e quando roda de novo (para a interface mostrar a contagem)."""

    JOBS = {
        "triagem": ("Triagem de e-mails (Gmail)", job_triage),
        "agenda": ("Análise da agenda", job_agenda),
        "resumo": ("Resumo diário dos e-mails", job_digest),
    }

    def __init__(self, cfg, on_change=None, clock=time.time):
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)
        self.clock = clock
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._info = {k: {"last_ts": None, "last_ok": None, "last_text": "", "running": False, "runs": 0} for k in self.JOBS}
        self._next_triage = None
        self._job_locks = {k: threading.Lock() for k in self.JOBS}

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def interval(self) -> int:
        return max(1, int((self.cfg.get("automatico") or {}).get("triagem_a_cada_minutos", 15))) * 60

    def start(self):
        if self.running:
            return True
        if not google_ready():
            return False
        self._stop.clear()
        s = self.cfg.get("automatico") or {}
        self._at = {"resumo": s.get("resumo_diario_as", "08:00"), "agenda": s.get("analise_agenda_as", "07:30")}
        now = self.clock()
        self._next_daily = {k: next_daily(v, now) for k, v in self._at.items()}
        self._next_triage = now + FIRST_DELAY
        self._thread = threading.Thread(target=self._loop, name="automacao", daemon=True)
        self._thread.start()
        self.on_change()
        return True

    def _loop(self):
        while not self._stop.wait(TICK):
            if self._next_triage is not None and self.clock() >= self._next_triage:
                self.run_job("triagem")
            now = self.clock()
            for key, due in list(self._next_daily.items()):
                if now >= due:
                    self._next_daily[key] = next_daily(self._at[key], now)   # antes de rodar: nunca repete
                    self.run_job(key)

    def run_job(self, key):
        """Roda uma rotina agora (também usado pelo botão "Verificar agora"). Retorna False se já estava rodando."""
        if key not in self.JOBS:
            raise KeyError(key)
        lock = self._job_locks[key]
        if not lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                self._info[key]["running"] = True
            self.on_change()
            try:
                ok, text = self.JOBS[key][1](self.cfg)
            except Exception as e:
                ok, text = False, f"Falhou: {e}"
            with self._lock:
                info = self._info[key]
                info.update(last_ts=self.clock(), last_ok=ok, last_text=text, running=False, runs=info["runs"] + 1)
                if key == "triagem":
                    self._next_triage = self.clock() + self.interval
            self.on_change()
            return True
        finally:
            lock.release()

    def run_job_async(self, key):
        if key not in self.JOBS:
            raise KeyError(key)
        if not self.running:
            raise RuntimeError("A rotina automática está desligada (conecte o Google em Ajustes).")
        threading.Thread(target=self.run_job, args=(key,), name=f"auto-{key}", daemon=True).start()

    def status(self) -> dict:
        jobs = []
        with self._lock:
            for key, (label, _fn) in self.JOBS.items():
                info = dict(self._info[key])
                if key == "triagem":
                    nxt, every = self._next_triage, f"a cada {self.interval // 60} min"
                else:
                    nxt = (getattr(self, "_next_daily", {}) or {}).get(key)
                    every = "todo dia"
                jobs.append({"id": key, "can_run": True, "label": label, "every": every, "next_ts": nxt if self.running else None, **info})
        return {"running": self.running, "connected": google_ready(), "now": self.clock(), "jobs": jobs}

    def stop(self):
        self._stop.set()
