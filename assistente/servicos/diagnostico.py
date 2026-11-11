"""Diagnóstico: confere, em um clique, o que funciona e o que falta no seu computador.

Cada verificação devolve {id, nome, estado, detalhe, dica}. Estados: "ok", "aviso" (funciona com ressalva),
"erro" (não funciona) e "info" (opcional / só informativo). Nada aqui altera configurações; a única verificação que
gasta uma requisição de IA é a do teste de conexão, e só roda quando você pede.
"""
import importlib.util
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

OK, WARN, ERR, INFO = "ok", "aviso", "erro", "info"

# (módulo importável, nome no pip, para quê, obrigatório?)
PACOTES = [
    ("yaml", "pyyaml", "ler o config.yaml", True),
    ("PIL", "pillow", "capturar a tela e tratar imagens", True),
    ("schedule", "schedule", "lembretes e rotinas", True),
    ("pypdf", "pypdf", "ler PDFs", False),
    ("docx", "python-docx", "ler arquivos Word", False),
    ("googleapiclient", "google-api-python-client", "Gmail e Agenda", False),
    ("google_auth_oauthlib", "google-auth-oauthlib", "entrar na conta Google", False),
    ("webview", "pywebview", "abrir como janela própria", False),
    ("pyautogui", "pyautogui", "controlar mouse e teclado", False),
    ("vosk", "vosk", "ativação por voz", False),
    ("sounddevice", "sounddevice", "microfone", False),
    ("pystray", "pystray", "ícone na bandeja", False),
]


def _r(id_, nome, estado, detalhe="", dica=""):
    return {"id": id_, "nome": nome, "estado": estado, "detalhe": detalhe, "dica": dica}


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def check_python():
    v = sys.version_info
    texto = f"Python {v.major}.{v.minor}.{v.micro} em {platform.system()} {platform.release()}"
    if v < (3, 10):
        return _r("python", "Python", ERR, texto, "Instale o Python 3.10 ou mais novo (python.org).")
    return _r("python", "Python", OK, texto)


def check_pacotes():
    faltam = [(m, p, uso, req) for m, p, uso, req in PACOTES if not _has(m)]
    if sys.platform == "win32" and not _has("uiautomation"):
        faltam.append(("uiautomation", "uiautomation", "enxergar botões e janelas do Windows", False))
    if not faltam:
        return _r("pacotes", "Pacotes instalados", OK, "Todos presentes.")
    obrig = [f for f in faltam if f[3]]
    lista = "; ".join(f"{p} ({uso})" for _, p, uso, _ in faltam)
    dica = "Rode “Instalar Assistente.bat” de novo, ou: .venv\\Scripts\\python -m pip install -r requirements.txt"
    return _r("pacotes", "Pacotes instalados", ERR if obrig else WARN, "Faltam: " + lista, dica)


def check_gemini_key():
    try:
        from assistente.ia import gemini
        if os.environ.get("GEMINI_API_KEY") or gemini.api_key():
            return _r("gemini", "Chave do Gemini", OK, "Encontrada (valor não é mostrado).")
    except Exception:
        pass
    return _r("gemini", "Chave do Gemini", ERR, "Não encontrei GEMINI_API_KEY.",
              "Crie uma chave grátis em aistudio.google.com/apikey e coloque no arquivo .env: GEMINI_API_KEY=sua_chave (depois reabra o app).")


def check_provedores(cfg):
    try:
        from assistente.ia import providers
        extras = [p for p in providers.status(cfg) if p.get("id") != "gemini" and p.get("configurada")]
    except Exception:
        return _r("provedores", "Provedores reserva", INFO, "Não consegui consultar.")
    if extras:
        return _r("provedores", "Provedores reserva", OK, ", ".join(str(p.get("nome") or p.get("id")) for p in extras))
    return _r("provedores", "Provedores reserva", INFO, "Nenhum configurado.",
              "Opcional: em Ajustes › Provedores de IA, adicione outro (vários têm plano grátis) para continuar quando a cota do Gemini acabar.")


def check_google():
    cred, token = Path("credentials.json").is_file(), Path("token.json").is_file()
    if cred and token:
        return _r("google", "Gmail e Agenda", OK, "Conta conectada.")
    if cred:
        return _r("google", "Gmail e Agenda", INFO, "credentials.json presente, mas ainda não entrou na conta.",
                  "Em Ajustes › Google, clique em Conectar.")
    return _r("google", "Gmail e Agenda", INFO, "Não configurado (opcional).", "Veja o passo 4 do README para ativar.")


def check_tela(grab=None):
    try:
        from assistente.pc import pc_control
        raw = (grab or pc_control.snapshot_jpeg)(320)
        return _r("tela", "Captura de tela", OK, f"Funcionou ({len(raw) // 1024 or 1} KB de teste).")
    except Exception as e:
        return _r("tela", "Captura de tela", ERR, str(e)[:200],
                  "Sem isso o assistente não enxerga a tela nem manda foto para o celular. Confirme que o pillow está instalado e que o app roda na sessão do Windows (não como serviço).")


def check_microfone(devices=None):
    if not _has("sounddevice"):
        return _r("microfone", "Microfone", INFO, "Pacote sounddevice ausente.", "Necessário só para a ativação por voz.")
    try:
        found = devices() if devices else __import__("sounddevice").query_devices()
        entradas = [d for d in found if d.get("max_input_channels", 0) > 0]
    except Exception as e:
        return _r("microfone", "Microfone", WARN, str(e)[:200], "Confira se o Windows permite o microfone para apps (Configurações › Privacidade).")
    if not entradas:
        return _r("microfone", "Microfone", WARN, "Nenhum microfone encontrado.", "Conecte um microfone ou ative-o nas configurações de som.")
    return _r("microfone", "Microfone", OK, f"{len(entradas)} entrada(s); a primeira é “{entradas[0].get('name', '?')}”.")


def check_voz():
    from assistente.pc import wake
    deps = wake.deps_status()
    if not all(deps.values()):
        return _r("voz", "Ativação por voz", INFO, "Pacotes de voz ausentes (vosk/sounddevice).", "Instale as dependências para usar “ei assistente”.")
    if wake.model_path() is None:
        return _r("voz", "Ativação por voz", WARN, "Falta o modelo em português.", "Em Ajustes › Ativação por voz, clique em Baixar modelo de voz.")
    return _r("voz", "Ativação por voz", OK, "Modelo instalado.")


def check_fala():
    if sys.platform != "win32":
        return _r("fala", "Voz do assistente (leitura)", INFO, "Leitura no navegador/app.", "")
    if shutil.which("powershell") or shutil.which("pwsh"):
        return _r("fala", "Voz do assistente (leitura)", OK, "PowerShell encontrado para falar.")
    return _r("fala", "Voz do assistente (leitura)", WARN, "PowerShell não encontrado.", "A leitura em voz alta pode não funcionar.")


def check_rede(cfg, addresses):
    modo = (cfg.get("app") or {}).get("acesso", "local")
    if modo != "rede":
        return _r("rede", "Acesso pelo celular", INFO, "Desligado (só este PC).", "Para usar pelo celular: Ajustes › Usar pelo celular.")
    ips = addresses()
    if not ips:
        return _r("rede", "Acesso pelo celular", WARN, "Ligado, mas não achei o endereço deste PC.", "Confira se está conectado ao Wi-Fi ou à rede.")
    tail = [ip for ip in ips if ip.startswith("100.")]
    detalhe = "Endereços: " + ", ".join(f"http://{ip}:{(cfg.get('app') or {}).get('porta', 8765)}" for ip in ips)
    if tail:
        return _r("rede", "Acesso pelo celular", OK, detalhe + " (Tailscale detectado: conexão privada)")
    return _r("rede", "Acesso pelo celular", WARN, detalhe,
              "Sem Tailscale a conexão é HTTP puro: use só em Wi-Fi de confiança (casa), nunca em rede pública. Quem tiver o código de acesso controla o PC.")


def check_ntfy(cfg):
    topic = (cfg.get("notificacoes") or {}).get("ntfy_topico")
    if topic:
        return _r("ntfy", "Avisos no celular (ntfy)", OK, "Tópico configurado.", "")
    return _r("ntfy", "Avisos no celular (ntfy)", INFO, "Não configurado (opcional).", "Em Ajustes › Avisos no celular, gere um tópico e assine no app ntfy.")


def check_pastas():
    try:
        Path("data").mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir="data", prefix=".teste", delete=True) as f:
            f.write(b"ok")
    except OSError as e:
        return _r("pastas", "Pasta de dados", ERR, str(e)[:200], "O app precisa gravar na própria pasta. Mova-o para fora de pastas protegidas (ex.: Arquivos de Programas).")
    mem = Path("memory")
    detalhe = "data/ gravável" + ("; memory/ presente" if mem.is_dir() else "; memory/ será criada")
    return _r("pastas", "Pasta de dados", OK, detalhe)


def check_versao(root=None):
    from assistente.servicos import atualizador
    info = atualizador.installed(root)
    if info.get("sha"):
        return _r("versao", "Versão", OK, f"{info['sha'][:7]} (atualizada em {info.get('atualizado_em', '?')}).")
    return _r("versao", "Versão", INFO, "Instalada por ZIP (sem registro).", "Use Ajustes › Atualizações para ficar com a mais recente.")


def check_conexao_gemini(ping=None):
    """Teste real: uma requisição mínima ao Gemini. Só roda quando o usuário pede."""
    t0 = time.time()
    try:
        if ping is None:
            from assistente.ia import gemini
            def ping():
                gemini.generate([{"role": "user", "parts": [{"text": "Responda apenas: ok"}]}],
                                gemini.models_for("gemini-3.8-flash"), temperature=0.0)
        ping()
    except Exception as e:
        msg = str(e)[:240]
        return _r("conexao", "Teste de conexão com o Gemini", ERR, msg,
                  "Confira a chave, a internet e se a cota do dia não acabou (Ajustes › Limites da cota).")
    return _r("conexao", "Teste de conexão com o Gemini", OK, f"Respondeu em {time.time() - t0:.1f} s.")


def run(cfg: dict, deep: bool = False, addresses=None, grab=None, devices=None, ping=None) -> dict:
    """Roda todas as verificações. Cada uma é isolada: uma que quebre vira um item de erro, não derruba o resto."""
    from assistente import server

    steps = [
        ("python", check_python), ("versao", check_versao), ("pastas", check_pastas), ("pacotes", check_pacotes),
        ("gemini", check_gemini_key), ("provedores", lambda: check_provedores(cfg)), ("google", check_google),
        ("tela", lambda: check_tela(grab)), ("microfone", lambda: check_microfone(devices)), ("voz", check_voz),
        ("fala", check_fala), ("rede", lambda: check_rede(cfg, addresses or server.lan_addresses)),
        ("ntfy", lambda: check_ntfy(cfg)),
    ]
    if deep:
        steps.append(("conexao", lambda: check_conexao_gemini(ping)))
    items = []
    for id_, fn in steps:
        try:
            items.append(fn())
        except Exception as e:      # uma verificação com defeito não pode esconder as outras
            items.append(_r(id_, id_, ERR, f"A verificação falhou: {type(e).__name__}: {e}"[:200]))
    count = {k: sum(1 for i in items if i["estado"] == k) for k in (OK, WARN, ERR, INFO)}
    return {"itens": items, "resumo": count, "ok": count[ERR] == 0}
