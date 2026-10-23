"""Ferramentas que o Gemini pode chamar (declaração, categoria de permissão e execução)."""
import json
from pathlib import Path

import files
import memory
import pc_control as pc
import spotify_control as spmod
import tracking
import workspace as wsmod

MAX_RESULT_CHARS = 6000
EXPECTED_ERRORS = (tracking.TrackingError, pc.PCError, spmod.SpotifyError, wsmod.WorkspaceError, files.FileAccessError, ValueError,
                   TypeError, OSError)


# ---- contexto -------------------------------------------------------------

def build_workspace(cfg: dict) -> wsmod.Workspace:
    p = cfg.get("projetos") or {}
    return wsmod.Workspace(p.get("pasta", "~/assistente-projetos"), p.get("repos_permitidos"),
                           int(p.get("tempo_limite_comando_segundos", wsmod.DEFAULT_TIMEOUT)))


def build_spotify(cfg: dict) -> spmod.Spotify:
    port = int((cfg.get("spotify") or {}).get("porta_login", 8888))
    apps = (cfg.get("pc") or {}).get("aplicativos") or {}
    return spmod.Spotify(port=port, launch_app=lambda: pc.open_app("spotify", apps))


class ToolContext:
    """Tudo que as ferramentas precisam: configuração, modo, projeto atual e ganchos da interface."""

    def __init__(self, cfg: dict, mode: str = "chat", project: str = None, workspace=None, spotify=None, hooks=None):
        self.cfg = cfg
        self.mode = mode                      # "chat" ou "task"
        self.project = project
        self.workspace = workspace or build_workspace(cfg)
        self.spotify = spotify or build_spotify(cfg)
        self.hooks = hooks or {}              # on_plan, on_step, on_finish, on_help, hide_window, show_window
        self.window_hidden = False
        self.control = {"finished": None, "help": None}   # sinais para o motor do agente

    @property
    def apps(self):
        return (self.cfg.get("pc") or {}).get("aplicativos") or {}

    @property
    def folders(self):
        return (self.cfg.get("arquivos") or {}).get("pastas_permitidas") or []

    def hide_window(self):
        """Esconde a janela do app antes de usar teclado/mouse, para não digitar nela mesma."""
        if (self.cfg.get("pc") or {}).get("esconder_janela", True) is False:
            return
        if not self.window_hidden and self.hooks.get("hide_window"):
            self.hooks["hide_window"]()
            self.window_hidden = True

    def release(self):
        if self.window_hidden and self.hooks.get("show_window"):
            self.hooks["show_window"]()
        self.window_hidden = False

    def project_name(self, args: dict) -> str:
        # Em tarefas, o projeto é sempre o da própria tarefa (o modelo não escolhe outro).
        name = self.project if self.mode == "task" else (args.get("projeto") or self.project)
        if not name:
            raise wsmod.WorkspaceError("Informe o nome do projeto.")
        return name


# ---- esquemas -------------------------------------------------------------

def S(desc, enum=None):
    d = {"type": "STRING", "description": desc}
    if enum:
        d["enum"] = list(enum)
    return d


def I(desc):
    return {"type": "INTEGER", "description": desc}


def N(desc):
    return {"type": "NUMBER", "description": desc}


def LST(desc):
    return {"type": "ARRAY", "description": desc, "items": {"type": "STRING"}}


PROJETO = S("Nome do projeto (opcional; usa o projeto atual).")


class Tool:
    def __init__(self, name, description, properties, required, category, run, summary, task_only=False):
        self.name, self.description = name, description
        self.properties, self.required = properties, required
        self.category, self.run, self.summary, self.task_only = category, run, summary, task_only

    def declaration(self):
        decl = {"name": self.name, "description": self.description}
        if self.properties:
            decl["parameters"] = {"type": "OBJECT", "properties": self.properties}
            if self.required:
                decl["parameters"]["required"] = list(self.required)
        return decl


# ---- implementações -----------------------------------------------------------

def _ok(**kw):
    return {"ok": True, **kw}


def t_lembrar(ctx, a):
    return _ok(nota=memory.remember(a["texto"]))


def t_ver_memoria(ctx, a):
    return {"memoria": memory.read_all() or "(vazia)"}


def t_esquecer(ctx, a):
    return _ok(removida=memory.forget(int(a["numero"])))


def t_listar_arquivos(ctx, a):
    return {"arquivos": [str(p) for p in files.list_files(ctx.folders)]}


def t_ler_arquivo(ctx, a):
    target = files.resolve_allowed(a["caminho"], ctx.folders)
    return {"nome": target.name, "conteudo": files.read_text(target)}


def t_resumo_emails(ctx, a):
    import google_auth  # importado só aqui: depende das bibliotecas do Google
    import triage
    triage.run_triage(google_auth.gmail_service(), ctx.cfg)
    return {"resumo": triage.digest(ctx.cfg, float(a.get("horas") or 24))}


def t_analisar_agenda(ctx, a):
    import agenda
    import google_auth
    return {"analise": agenda.analyze(google_auth.calendar_service(), ctx.cfg)}


def t_controle_midia(ctx, a):
    return pc.media(a["acao"], a.get("vezes") or 1)


def t_spotify_tocar(ctx, a):
    return ctx.spotify.play(a["busca"], a.get("tipo") or "faixa")


def t_spotify_controle(ctx, a):
    sp, acao = ctx.spotify, a["acao"]
    if acao == "pausar":
        return sp.pause()
    if acao == "continuar":
        return sp.resume()
    if acao == "proxima":
        return sp.next()
    if acao == "anterior":
        return sp.previous()
    if acao == "volume":
        if a.get("volume") is None:
            raise ValueError("Informe o volume de 0 a 100.")
        return sp.set_volume(int(a["volume"]))
    raise ValueError("Ação desconhecida.")


def t_spotify_status(ctx, a):
    return ctx.spotify.now_playing()


def _item_view(i):
    ev = (i.get("events") or [None])[0]
    return {"codigo": i["code"], "nome": i["name"], "situacao": i["status_label"], "encontrado": i.get("found"),
            "ultimo_evento": (f"{ev['time']}: {ev['text']}" + (f" ({ev['place']})" if ev.get("place") else "")) if ev else None,
            "transportadora": i.get("carrier") or None, "erro": i.get("error") or None, "aviso": i.get("note") or None,
            "link": i.get("url")}


def t_rastreio_adicionar(ctx, a):
    tr = tracking.default()
    item = tr.add(a["codigo"], a.get("nome", ""), check=False)
    item = tr.check(item["id"], first=True)
    return _ok(encomenda=_item_view(item), chave_configurada=tr.configured)


def t_rastreio_listar(ctx, a):
    tr = tracking.default()
    return {"encomendas": [_item_view(i) for i in tr.items()], "chave_configurada": tr.configured}


def t_rastreio_verificar(ctx, a):
    tr = tracking.default()
    codes = [a["codigo"]] if a.get("codigo") else None
    items = [tr.find_code(c) for c in codes] if codes else tr.active()
    return {"encomendas": [_item_view(tr.check(i["id"])) for i in items]}


def t_rastreio_remover(ctx, a):
    tr = tracking.default()
    tr.remove(tr.find_code(a["codigo"])["id"])
    return _ok()


def t_abrir_aplicativo(ctx, a):
    return pc.open_app(a["nome"], ctx.apps)


def t_abrir_site(ctx, a):
    return pc.open_url(a["url"])


def t_projeto_listar(ctx, a):
    name = ctx.project_name(a)
    return {"projeto": name, "arquivos": ctx.workspace.list_dir(name, a.get("pasta") or ".")}


def t_projeto_ler(ctx, a):
    return {"conteudo": ctx.workspace.read_file(ctx.project_name(a), a["caminho"])}


def t_projeto_escrever(ctx, a):
    return ctx.workspace.write_file(ctx.project_name(a), a["caminho"], a["conteudo"])


def t_projeto_editar(ctx, a):
    return ctx.workspace.edit_file(ctx.project_name(a), a["caminho"], a["buscar"], a["substituir"])


def t_executar_comando(ctx, a):
    return ctx.workspace.run(ctx.project_name(a), a["comando"])


def t_git_commit(ctx, a):
    return ctx.workspace.git_commit(ctx.project_name(a), a["mensagem"])


def t_git_enviar(ctx, a):
    return ctx.workspace.git_push(ctx.project_name(a), a.get("branch") or "")


def t_abrir_vscode(ctx, a):
    import shutil
    import subprocess

    path = ctx.workspace.project_dir(ctx.project_name(a), create=True)
    exe = shutil.which("code")
    if exe:
        subprocess.Popen([exe, str(path)])
        return _ok(aberto=str(path))
    pc.open_app("Visual Studio Code", ctx.apps)
    return _ok(aberto="Visual Studio Code (abra a pasta manualmente: " + str(path) + ")")


def t_ver_tela(ctx, a):
    ctx.hide_window()
    data, info = pc.screenshot()
    return {"_image": (data, "image/jpeg"), "ok": True, **info,
            "nota": "A captura da tela está anexada logo abaixo, com uma grade de números amarelos (0 a 1000). "
                    "Para clicar, leia nela o x e o y do alvo."}


def t_ver_regiao(ctx, a):
    ctx.hide_window()
    data, info = pc.screenshot(region=(a["x1"], a["y1"], a["x2"], a["y2"]))
    return {"_image": (data, "image/jpeg"), "ok": True, **info,
            "nota": "Zoom da região anexado. Os números amarelos continuam sendo as coordenadas da TELA INTEIRA (0 a 1000)."}


def _com_captura(result: dict, espera: float = 0.7) -> dict:
    """Depois de uma ação na tela, devolve junto uma captura nova: o modelo vê o resultado sem gastar outra chamada."""
    pc.wait(espera)
    try:
        data, _ = pc.screenshot()
    except pc.PCError:
        return result
    result["_image"] = (data, "image/jpeg")
    result["nota"] = "Captura da tela DEPOIS da ação anexada abaixo (o círculo vermelho é onde você clicou). Confira se deu certo."
    return result


def t_clicar(ctx, a):
    ctx.hide_window()
    return _com_captura(pc.click(a["x"], a["y"], a.get("botao") or "left", a.get("cliques") or 1))


def t_digitar(ctx, a):
    ctx.hide_window()
    return _com_captura(pc.type_text(a["texto"]))


def t_teclas(ctx, a):
    ctx.hide_window()
    return _com_captura(pc.hotkey(a["combinacao"]))


def t_rolar(ctx, a):
    ctx.hide_window()
    return _com_captura(pc.scroll(int(a["quantidade"])))


def t_esperar(ctx, a):
    return pc.wait(float(a["segundos"]))


def _hook(ctx, name, *args):
    fn = ctx.hooks.get(name)
    if not fn:
        raise ValueError("Esta ferramenta só funciona dentro de uma tarefa.")
    return fn(*args)


def t_definir_plano(ctx, a):
    passos = [str(p).strip() for p in (a.get("passos") or []) if str(p).strip()]
    if not 1 <= len(passos) <= 15:
        raise ValueError("Informe de 1 a 15 passos.")
    _hook(ctx, "on_plan", passos)
    return _ok(passos=len(passos))


def t_atualizar_passo(ctx, a):
    status = a["status"]
    if status not in ("pendente", "andamento", "feito", "bloqueado"):
        raise ValueError("status deve ser pendente, andamento, feito ou bloqueado.")
    _hook(ctx, "on_step", int(a["numero"]), status, a.get("nota") or "")
    return _ok()


def t_concluir_tarefa(ctx, a):
    _hook(ctx, "on_finish", a["resumo"])
    ctx.control["finished"] = a["resumo"]
    return _ok()


def t_pedir_permissao(ctx, a):
    # chegar aqui significa que o usuário aprovou (a negação é tratada pelo motor antes de executar)
    return _ok(nota="O usuário autorizou esta ação específica.")


def t_pedir_ajuda(ctx, a):
    _hook(ctx, "on_help", a["pergunta"])
    ctx.control["help"] = a["pergunta"]
    return _ok(nota="Pergunta registrada. A tarefa aguarda a resposta do usuário.")


def _cmd_category(a):
    return wsmod.command_category(a.get("comando", ""))


def _short(text, n=160):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


# nome, descrição, props, obrigatórios, categoria, função, resumo(args)
def _tools():
    T = Tool
    return [
        T("lembrar", "Guarda uma instrução ou preferência do usuário na memória permanente.",
          {"texto": S("O que deve ser lembrado, em uma frase.")}, ["texto"], "memoria", t_lembrar,
          lambda a: f"Anotar na memória: {_short(a.get('texto', ''))}"),
        T("ver_memoria", "Mostra tudo o que está guardado na memória do usuário.", {}, [], "memoria", t_ver_memoria,
          lambda a: "Ler a memória"),
        T("esquecer", "Apaga uma nota da memória pelo número.", {"numero": I("Número da nota (1 = primeira).")},
          ["numero"], "memoria", t_esquecer, lambda a: f"Apagar a nota {a.get('numero')} da memória"),
        T("listar_arquivos", "Lista os arquivos que o usuário autorizou o assistente a ler.", {}, [], "ler_arquivos",
          t_listar_arquivos, lambda a: "Listar arquivos autorizados"),
        T("ler_arquivo", "Lê um arquivo (txt, md, csv, json, pdf, docx) das pastas autorizadas.",
          {"caminho": S("Nome ou caminho do arquivo.")}, ["caminho"], "ler_arquivos", t_ler_arquivo,
          lambda a: f"Ler o arquivo {a.get('caminho')}"),
        T("resumo_emails", "Verifica os emails novos e resume o que é importante de verdade.",
          {"horas": N("Janela em horas (padrão 24).")}, [], "email_agenda", t_resumo_emails,
          lambda a: "Verificar e resumir os emails"),
        T("analisar_agenda", "Analisa a agenda dos próximos dias: conflitos, dias lotados e janelas livres.", {}, [],
          "email_agenda", t_analisar_agenda, lambda a: "Analisar a agenda"),
        T("controle_midia", "Teclas de mídia do computador: play/pause, próxima, anterior e volume geral.",
          {"acao": S("Ação.", ["play_pause", "proxima", "anterior", "volume_mais", "volume_menos", "mudo"]),
           "vezes": I("Repetições (só para volume, até 25; cada uma muda ~2%).")}, ["acao"], "midia",
          t_controle_midia, lambda a: f"Mídia: {a.get('acao')}"),
        T("spotify_tocar", "Busca e toca música, álbum, playlist ou artista no Spotify do usuário (abre o app se precisar).",
          {"busca": S("O que tocar, por exemplo 'Bohemian Rhapsody Queen'."),
           "tipo": S("Tipo de resultado.", ["faixa", "album", "playlist", "artista"])}, ["busca"], "midia",
          t_spotify_tocar, lambda a: f"Tocar no Spotify: {_short(a.get('busca', ''), 80)}"),
        T("spotify_controle", "Controla a reprodução do Spotify.",
          {"acao": S("Ação.", ["pausar", "continuar", "proxima", "anterior", "volume"]),
           "volume": I("Volume de 0 a 100 (só para a ação volume).")}, ["acao"], "midia", t_spotify_controle,
          lambda a: f"Spotify: {a.get('acao')}"),
        T("spotify_status", "Diz o que está tocando agora no Spotify.", {}, [], "midia", t_spotify_status,
          lambda a: "Ver o que está tocando"),
        T("rastreio_adicionar", "Passa a acompanhar uma encomenda pelo código de rastreio e já faz a primeira consulta. "
          "O assistente avisa o usuário sozinho quando houver novidades.",
          {"codigo": S("Código de rastreio (ex.: AA123456789BR)."), "nome": S("Nome curto da encomenda (opcional).")},
          ["codigo"], "rastreio", t_rastreio_adicionar, lambda a: f"Acompanhar a encomenda {a.get('codigo')}"),
        T("rastreio_listar", "Lista as encomendas acompanhadas e a última situação de cada uma.", {}, [], "rastreio",
          t_rastreio_listar, lambda a: "Listar encomendas"),
        T("rastreio_verificar", "Consulta agora a situação de uma encomenda (ou de todas as ativas, sem código).",
          {"codigo": S("Código de rastreio (opcional).")}, [], "rastreio", t_rastreio_verificar,
          lambda a: f"Consultar encomenda {a.get('codigo') or '(todas)'}"),
        T("rastreio_remover", "Para de acompanhar uma encomenda.", {"codigo": S("Código de rastreio.")}, ["codigo"],
          "rastreio", t_rastreio_remover, lambda a: f"Remover a encomenda {a.get('codigo')}"),
        T("abrir_aplicativo", "Abre um aplicativo instalado no computador pelo nome (ex.: Spotify, Visual Studio Code, Chrome).",
          {"nome": S("Nome do aplicativo.")}, ["nome"], "abrir", t_abrir_aplicativo,
          lambda a: f"Abrir o aplicativo {a.get('nome')}"),
        T("abrir_site", "Abre um endereço http/https no navegador padrão.", {"url": S("Endereço do site.")}, ["url"],
          "abrir", t_abrir_site, lambda a: f"Abrir o site {_short(a.get('url', ''), 120)}"),
        T("projeto_listar", "Lista os arquivos de um projeto na pasta de projetos.",
          {"projeto": PROJETO, "pasta": S("Subpasta (opcional).")}, [], "projeto_ler", t_projeto_listar,
          lambda a: "Listar arquivos do projeto"),
        T("projeto_ler", "Lê um arquivo de texto do projeto.", {"caminho": S("Caminho dentro do projeto."), "projeto": PROJETO},
          ["caminho"], "projeto_ler", t_projeto_ler, lambda a: f"Ler {a.get('caminho')} do projeto"),
        T("projeto_escrever", "Cria ou sobrescreve um arquivo do projeto com o conteúdo completo.",
          {"caminho": S("Caminho dentro do projeto, ex.: src/app.py."), "conteudo": S("Conteúdo completo do arquivo."),
           "projeto": PROJETO}, ["caminho", "conteudo"], "projeto_escrever", t_projeto_escrever,
          lambda a: f"Escrever o arquivo {a.get('caminho')} ({len(a.get('conteudo', ''))} caracteres)"),
        T("projeto_editar", "Troca um trecho exato e único de um arquivo do projeto por outro.",
          {"caminho": S("Arquivo."), "buscar": S("Trecho atual, idêntico e único."), "substituir": S("Novo trecho."),
           "projeto": PROJETO}, ["caminho", "buscar", "substituir"], "projeto_escrever", t_projeto_editar,
          lambda a: f"Editar o arquivo {a.get('caminho')}"),
        T("executar_comando",
          "Roda UM comando na pasta do projeto. Só: git, python, python3, py, pip, pip3, node, npm, npx, pnpm, yarn, pytest. "
          "Sem pipes, redirecionamentos nem encadeamento (| & ; < >). Para lógica longa, escreva um script e rode-o.",
          {"comando": S("Comando completo, ex.: npm test"), "projeto": PROJETO}, ["comando"], _cmd_category,
          t_executar_comando, lambda a: f"Executar comando: {_short(a.get('comando', ''))}"),
        T("git_commit", "Faz 'git add -A' e commit no projeto (inicia o repositório se precisar).",
          {"mensagem": S("Mensagem do commit."), "projeto": PROJETO}, ["mensagem"], "comandos", t_git_commit,
          lambda a: f"Commit no projeto: {_short(a.get('mensagem', ''), 100)}"),
        T("git_enviar", "Envia (git push) o projeto ao GitHub. Só funciona para repositórios autorizados pelo usuário.",
          {"branch": S("Branch (opcional; usa a atual)."), "projeto": PROJETO}, [], "git_push", t_git_enviar,
          lambda a: "Enviar o projeto ao GitHub"),
        T("abrir_no_vscode", "Abre a pasta do projeto no Visual Studio Code.", {"projeto": PROJETO}, [], "abrir",
          t_abrir_vscode, lambda a: "Abrir o projeto no VS Code"),
        T("ver_tela", "Tira uma foto da tela inteira, com uma grade de números amarelos de 0 a 1000, para você enxergar "
          "o que está aberto e ler as coordenadas. Chame antes do primeiro clique.", {}, [],
          "tela", t_ver_tela, lambda a: "Capturar a tela"),
        T("ver_regiao", "Amplia uma parte da tela (com grade mais fina) para achar um botão ou texto pequeno com precisão. "
          "Os números continuam sendo as coordenadas da tela inteira (0 a 1000).",
          {"x1": N("Esquerda (0-1000)."), "y1": N("Topo (0-1000)."), "x2": N("Direita (0-1000)."),
           "y2": N("Base (0-1000).")}, ["x1", "y1", "x2", "y2"], "tela", t_ver_regiao,
          lambda a: f"Ampliar a região ({a.get('x1')}, {a.get('y1')}) a ({a.get('x2')}, {a.get('y2')})"),
        T("clicar", "Clica na tela. x e y vão de 0 a 1000 (0,0 = canto superior esquerdo; 1000,1000 = canto inferior "
          "direito): leia nos números amarelos da grade da captura, mirando no CENTRO do alvo. Depois do clique você "
          "recebe uma captura nova mostrando onde clicou (círculo vermelho).",
          {"x": N("Coordenada x, de 0 a 1000."), "y": N("Coordenada y, de 0 a 1000."),
           "botao": S("Botão.", ["left", "right", "middle"]), "cliques": I("1 a 3 (2 = duplo clique).")}, ["x", "y"],
          "entrada", t_clicar, lambda a: f"Clicar na tela em ({a.get('x')}, {a.get('y')})"),
        T("digitar", "Digita um texto onde o cursor estiver (aceita acentos).", {"texto": S("Texto a digitar.")}, ["texto"],
          "entrada", t_digitar, lambda a: f"Digitar o texto: “{_short(a.get('texto', ''), 200)}”"),
        T("teclas", "Pressiona uma combinação de teclas, ex.: ctrl+s, enter, win+d.",
          {"combinacao": S("Teclas separadas por +.")}, ["combinacao"], "entrada", t_teclas,
          lambda a: f"Pressionar {a.get('combinacao')}"),
        T("rolar", "Rola a tela (positivo = para cima, negativo = para baixo).", {"quantidade": I("De -30 a 30.")},
          ["quantidade"], "entrada", t_rolar, lambda a: f"Rolar a tela ({a.get('quantidade')})"),
        T("esperar", "Espera alguns segundos (até 10), por exemplo para um programa abrir.",
          {"segundos": N("Segundos.")}, ["segundos"], "tarefa", t_esperar, lambda a: f"Esperar {a.get('segundos')}s"),
        T("definir_plano", "Registra o plano da tarefa: de 1 a 15 passos curtos, em ordem. Chame primeiro.",
          {"passos": LST("Passos do plano.")}, ["passos"], "tarefa", t_definir_plano, lambda a: "Definir o plano",
          task_only=True),
        T("atualizar_passo", "Atualiza o andamento de um passo do plano.",
          {"numero": I("Número do passo (1 = primeiro)."),
           "status": S("Novo status.", ["pendente", "andamento", "feito", "bloqueado"]), "nota": S("Observação curta.")},
          ["numero", "status"], "tarefa", t_atualizar_passo, lambda a: f"Passo {a.get('numero')}: {a.get('status')}",
          task_only=True),
        T("concluir_tarefa", "Encerra a tarefa com um resumo do que foi feito e onde ficaram os arquivos.",
          {"resumo": S("Resumo final.")}, ["resumo"], "tarefa", t_concluir_tarefa, lambda a: "Concluir a tarefa",
          task_only=True),
        T("pedir_permissao", "Use SOMENTE quando a ação que você vai fazer iria contra uma regra escrita pelo usuário "
          "(arquivo de regras). Chame ANTES de agir, descrevendo a ação e a regra. Para todo o resto, aja sem perguntar.",
          {"acao": S("O que você pretende fazer."), "regra": S("A regra do usuário que isso iria contra.")},
          ["acao", "regra"], "regra", t_pedir_permissao,
          lambda a: f"{a.get('acao', 'Ação')} — vai contra a regra: {a.get('regra', '?')}"),
        T("pedir_ajuda", "Para a tarefa e faz uma pergunta ao usuário quando você não consegue continuar sozinho.",
          {"pergunta": S("Pergunta clara e objetiva.")}, ["pergunta"], "tarefa", t_pedir_ajuda,
          lambda a: "Pedir ajuda ao usuário", task_only=True),
    ]


# ---- registro -------------------------------------------------------------

def _clip(obj, limit=MAX_RESULT_CHARS):
    """Garante que o resultado cabe no limite, encurtando textos longos."""
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return obj
    out = {}
    for k, v in obj.items():
        out[k] = (v[: limit // 2] + " [...cortado...]") if isinstance(v, str) and len(v) > limit // 2 else v
    if len(json.dumps(out, ensure_ascii=False, default=str)) > limit:
        return {"erro": "Resultado grande demais para exibir.", "parcial": json.dumps(out, ensure_ascii=False, default=str)[:limit]}
    return out


class Registry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        autonomous = bool((ctx.cfg.get("pc") or {}).get("modo_autonomo", False))
        self.tools = {t.name: t for t in _tools()
                      if (ctx.mode == "task" or not t.task_only) and (autonomous or t.name != "pedir_permissao")}

    def declarations(self):
        return [t.declaration() for t in self.tools.values()]

    def has(self, name: str) -> bool:
        return name in self.tools

    def category(self, name: str, args: dict) -> str:
        cat = self.tools[name].category
        return cat(args) if callable(cat) else cat

    def summary(self, name: str, args: dict) -> str:
        try:
            return self.tools[name].summary(args or {})
        except Exception:
            return name

    def execute(self, name: str, args: dict):
        """Roda a ferramenta. NUNCA levanta exceção. Retorna (resultado, imagem|None)."""
        tool = self.tools.get(name)
        if tool is None:
            return {"erro": f"Ferramenta desconhecida: {name}."}, None
        args = args if isinstance(args, dict) else {}
        try:
            result = tool.run(self.ctx, args)
        except KeyError as e:
            return {"erro": f"Falta um parâmetro obrigatório ou o item não existe: {e.args[0] if e.args else e}"}, None
        except EXPECTED_ERRORS as e:
            return {"erro": str(e) or type(e).__name__}, None
        except SystemExit as e:  # ex.: faltou credentials.json
            return {"erro": str(e)}, None
        except Exception as e:
            return {"erro": f"Erro inesperado ({type(e).__name__}): {e}"}, None
        image = result.pop("_image", None) if isinstance(result, dict) else None
        return _clip(result if isinstance(result, dict) else {"resultado": result}), image
