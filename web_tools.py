"""Pesquisar na internet e ler páginas.

pesquisar: usa a pesquisa do Google embutida no Gemini ("grounding"): ele pesquisa, lê e responde com as fontes.
Se isso falhar (cota, modelo sem suporte), cai para o DuckDuckGo (sem chave, sem conta) e devolve os resultados.

ler_pagina: baixa uma página pública e devolve o texto limpo. Só http/https, nunca endereços da sua rede
(localhost, 192.168.x.x, 10.x.x.x, metadados de nuvem): páginas da internet não podem ser usadas para espiar o seu PC.
O conteúdo que volta é DADO, nunca instrução.
"""
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import gemini

MAX_BYTES = 2_000_000
MAX_CHARS = 12000
TIMEOUT = 15
UA = "Mozilla/5.0 (compatible; AssistentePessoal/1.0)"
DEFAULT_SEARCH_MODEL = "gemini-3.5-flash-lite"

_urlopen = urllib.request.urlopen     # os testes trocam por uma versão falsa
_resolve = socket.getaddrinfo


class WebError(Exception):
    pass


# ---------------------------------------------------------------- segurança de URL

def check_url(url: str) -> str:
    url = str(url or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError("Só endereços http:// ou https:// de sites públicos.")
    if parts.username or parts.password:
        raise WebError("Endereço com usuário e senha não é permitido.")
    host = parts.hostname
    try:
        infos = _resolve(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        raise WebError(f"Não consegui encontrar o site {host}.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise WebError("Esse endereço aponta para a rede local; por segurança só abro sites públicos.")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)                                   # cada redirecionamento passa pela mesma checagem
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, headers=None, data=None):
    check_url(url)
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
                                                          **(headers or {})})
    opener = urllib.request.build_opener(_SafeRedirect) if _urlopen is urllib.request.urlopen else None
    try:
        return opener.open(req, timeout=TIMEOUT) if opener else _urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        raise WebError(f"O site respondeu com erro {e.code}.") from None
    except WebError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise WebError(f"Não consegui abrir a página: {getattr(e, 'reason', e)}") from None


# ---------------------------------------------------------------- HTML -> texto

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe", "form", "nav", "footer", "aside"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "ul", "ol",
             "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
            if tag.startswith("h") and len(tag) == 2:
                self.out.append("## ")
            if tag == "li":
                self.out.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def html_to_text(raw: str):
    p = _Text()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        pass
    text = "".join(p.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return " ".join(p.title.split()), text


def _decode(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.I)
    enc = (m.group(1).decode() if m and isinstance(m.group(1), bytes) else m.group(1) if m else "utf-8")
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_page(url: str, max_chars: int = MAX_CHARS) -> dict:
    with _open(url) as resp:
        ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
        body = resp.read(MAX_BYTES + 1)
        final = getattr(resp, "url", None) or getattr(resp, "geturl", lambda: url)()
    truncated_bytes = len(body) > MAX_BYTES
    body = body[:MAX_BYTES]
    if "pdf" in ctype.lower() or body[:5] == b"%PDF-":
        text, title = _pdf_text(body), ""
    elif ctype and not re.search(r"text/|html|xml|json", ctype, re.I):
        raise WebError(f"Esse endereço não é uma página de texto ({ctype.split(';')[0]}).")
    else:
        raw = _decode(body, ctype)
        if "json" in ctype.lower() or "text/plain" in ctype.lower():
            title, text = "", raw
        else:
            title, text = html_to_text(raw)
    if not text.strip():
        raise WebError("A página não tem texto legível (pode depender de JavaScript ou exigir login).")
    cut = len(text) > max_chars or truncated_bytes
    return {"titulo": title, "url": final, "texto": text[:max_chars], "cortado": cut}


def _pdf_text(body: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:15])
    except Exception:
        raise WebError("Não consegui ler esse PDF.") from None


# ---------------------------------------------------------------- pesquisa

def _grounded(cfg: dict, query: str) -> dict:
    ia = (cfg or {}).get("ia") or {}
    models = [m for m in dict.fromkeys([ia.get("modelo_pesquisa") or DEFAULT_SEARCH_MODEL, ia.get("modelo")]) if m]
    prompt = ("Pesquise na internet e responda em português do Brasil, de forma objetiva, com os fatos, números e datas "
              "mais atuais e dizendo de qual fonte veio cada informação importante.\n\nPergunta: " + query)
    obj = gemini.generate([{"role": "user", "parts": [{"text": prompt}]}], models, temperature=0.2, grounding=True)
    text = gemini.text_of(obj).strip()
    if not text:
        raise WebError("A pesquisa não devolveu resposta.")
    meta = ((obj.get("candidates") or [{}])[0]).get("groundingMetadata") or {}
    sources, seen = [], set()
    for ch in meta.get("groundingChunks") or []:
        w = ch.get("web") or {}
        if w.get("uri") and w["uri"] not in seen:
            seen.add(w["uri"])
            sources.append({"titulo": w.get("title") or w["uri"], "url": w["uri"]})
    return {"resposta": text[:8000], "fontes": sources[:8], "como": "pesquisa do Google (Gemini)", "modelo": obj.get("_model", "")}


_DDG_LINK = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIP = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', re.S)


def _clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s)).split())


def parse_ddg(page: str, limit: int = 8) -> list:
    links = _DDG_LINK.findall(page)
    snips = _DDG_SNIP.findall(page)
    out = []
    for i, (href, title) in enumerate(links):
        if href.startswith("//"):
            href = "https:" + href
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        if "uddg" in q:
            href = q["uddg"][0]
        if not href.startswith(("http://", "https://")) or "duckduckgo.com/y.js" in href:
            continue                                        # anúncios e links internos
        out.append({"titulo": _clean(title), "url": href, "trecho": _clean(snips[i]) if i < len(snips) else ""})
        if len(out) >= limit:
            break
    return out


def _duckduckgo(query: str) -> dict:
    data = urllib.parse.urlencode({"q": query, "kl": "br-pt"}).encode()
    with _open("https://html.duckduckgo.com/html/", {"Content-Type": "application/x-www-form-urlencoded"}, data) as resp:
        page = resp.read(MAX_BYTES).decode("utf-8", errors="replace")
    results = parse_ddg(page)
    if not results:
        raise WebError("Não encontrei resultados (o DuckDuckGo pode ter bloqueado a consulta automática).")
    return {"resultados": results, "como": "DuckDuckGo",
            "nota": "São só títulos e trechos. Para o conteúdo completo use ler_pagina na URL que interessar."}


def search(cfg: dict, query: str) -> dict:
    query = " ".join(str(query or "").split())
    if not query:
        raise WebError("Diga o que pesquisar.")
    if len(query) > 300:
        raise WebError("Consulta longa demais (máximo 300 caracteres).")
    try:
        return _grounded(cfg, query)
    except (gemini.GeminiError, WebError) as first:
        try:
            out = _duckduckgo(query)
        except WebError as second:
            raise WebError(f"A pesquisa falhou: {first}; alternativa: {second}") from None
        out["aviso"] = f"A pesquisa do Google não respondeu ({str(first)[:120]}); usei o DuckDuckGo."
        return out
