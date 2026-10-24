"""Permissões: decide se uma ação pode rodar sozinha, precisa de aprovação ou é bloqueada.

Cada ferramenta pertence a uma CATEGORIA, e cada categoria tem um risco.

No chat (você está na frente do computador):
  - risco baixo roda direto;
  - o resto pergunta, a não ser que você tenha liberado a categoria em `pc.confiar_sem_perguntar`
    (só categorias de risco médio podem ser liberadas) ou clicado em "permitir por alguns minutos".

MODO AUTÔNOMO (`pc.modo_autonomo`, o padrão do app): nada pede permissão. O assistente age e você vê tudo
depois no histórico. A única exceção é a categoria "regra": quando uma ação iria contra uma regra que
VOCÊ escreveu (arquivo regras.md), ele para e pergunta. As travas técnicas (pasta de projetos, lista de
programas permitidos, repositórios permitidos para push) continuam valendo: elas bloqueiam, não perguntam.

Nas tarefas autônomas (você pode estar longe), com o modo autônomo desligado:
  - roda só o que o PERFIL da tarefa já concedeu;
  - o resto vira um pedido de aprovação e a tarefa espera por você.
"""
import time

# id: (rótulo, risco)
CATEGORIES = {
    "tarefa": ("Planejar e registrar a tarefa", "low"),
    "memoria": ("Ler e anotar na memória", "low"),
    "ler_arquivos": ("Ler arquivos das pastas autorizadas", "low"),
    "email_agenda": ("Ler emails e agenda", "low"),
    "midia": ("Controlar música e volume", "low"),
    "rastreio": ("Acompanhar encomendas", "low"),
    "arquivos_escrever": ("Criar e editar arquivos na pasta de saída", "medium"),
    "agenda_escrever": ("Criar, alterar e apagar eventos da agenda", "medium"),
    "email_escrever": ("Criar rascunhos e organizar e-mails", "medium"),
    "email_enviar": ("Enviar e-mails", "high"),
    "web": ("Pesquisar na internet e ler páginas públicas", "low"),
    "lembretes": ("Criar e gerenciar lembretes e alarmes", "low"),
    "projeto_ler": ("Ler arquivos do projeto", "low"),
    "abrir": ("Abrir aplicativos e sites", "medium"),
    "projeto_escrever": ("Criar e editar arquivos do projeto", "medium"),
    "comandos": ("Rodar comandos (python, node, npm, git...)", "high"),
    "git_push": ("Enviar código ao GitHub", "high"),
    "tela": ("Ver a sua tela", "high"),
    "entrada": ("Controlar teclado e mouse", "high"),
    # só aparece no modo autônomo: o assistente pede quando uma ação iria contra uma regra sua
    "regra": ("Ação que vai contra uma regra sua", "high"),
}

_LEITURA = ["tarefa", "memoria", "ler_arquivos", "email_agenda", "midia", "rastreio", "lembretes", "web", "projeto_ler"]
PROFILES = {
    "leitura": _LEITURA,
    "projeto": _LEITURA + ["abrir", "agenda_escrever", "email_escrever", "arquivos_escrever", "projeto_escrever", "comandos", "git_push"],
    "total": _LEITURA + ["abrir", "agenda_escrever", "email_escrever", "email_enviar", "arquivos_escrever", "projeto_escrever", "comandos", "git_push", "tela", "entrada"],
}
PROFILE_LABELS = {
    "leitura": "Só leitura: lê arquivos, emails e agenda, mexe na memória e na música",
    "projeto": "Projeto: também cria arquivos, roda comandos, abre apps e envia ao GitHub",
    "total": "Controle total: também vê a tela e usa teclado e mouse",
}

# No chat, estas categorias SEMPRE pedem confirmação, mesmo se estiverem na lista de confiança
ALWAYS_ASK_IN_CHAT = {"tela", "entrada", "comandos", "git_push", "email_enviar"}


def risk_of(category: str) -> str:
    return CATEGORIES[category][1]


def label_of(category: str) -> str:
    return CATEGORIES[category][0]


def grants_for(profile) -> set:
    """Aceita o nome de um perfil ou uma lista de categorias."""
    if isinstance(profile, str):
        if profile not in PROFILES:
            raise ValueError(f"Perfil desconhecido: {profile}. Use: {', '.join(PROFILES)}.")
        return set(PROFILES[profile])
    cats = set(profile or [])
    unknown = cats - set(CATEGORIES)
    if unknown:
        raise ValueError(f"Categorias desconhecidas: {', '.join(sorted(unknown))}.")
    return cats | {"tarefa"}


class Policy:
    def __init__(self, cfg: dict = None, clock=time.time):
        pc = (cfg or {}).get("pc") or {}
        wanted = set(pc.get("confiar_sem_perguntar") or [])
        # só risco médio pode ser liberado de vez; o resto continua pedindo
        self.trusted = {c for c in wanted if c in CATEGORIES and risk_of(c) == "medium"}
        self.window_minutes = float(pc.get("janela_de_permissao_minutos", 5))
        self._clock = clock
        self._cfg = cfg if cfg is not None else {}

    @property
    def autonomous(self) -> bool:
        """Lê a configuração na hora, para a mudança em Ajustes valer sem reabrir o app."""
        return bool((self._cfg.get("pc") or {}).get("modo_autonomo", False))

    def decide(self, category: str, mode: str = "chat", granted=None, window_until: float = 0.0) -> str:
        """Retorna 'allow' (pode rodar) ou 'ask' (precisa de aprovação)."""
        if category not in CATEGORIES:
            return "ask"
        if category == "regra":
            return "ask"            # sempre pergunta: é o próprio assistente avisando que vai quebrar uma regra
        if category == "tarefa":
            return "allow"
        if self.autonomous:
            return "allow"
        if category == "arquivos_escrever" and (self._cfg.get("arquivos") or {}).get("gravar_sem_perguntar"):
            return "allow"          # a chave de Ajustes › Arquivos: gravar na pasta de saída sem pedir
        if mode == "task":
            return "allow" if category in (granted or ()) else "ask"
        if risk_of(category) == "low":
            return "allow"
        if self._clock() < window_until:
            return "allow"
        if category in self.trusted and category not in ALWAYS_ASK_IN_CHAT:
            return "allow"
        return "ask"

    def new_window(self) -> float:
        """Fim de uma janela 'permitir por alguns minutos' que começa agora."""
        return self._clock() + self.window_minutes * 60
