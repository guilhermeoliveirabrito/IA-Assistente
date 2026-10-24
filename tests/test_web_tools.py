import io
import socket
import unittest

from assistente.ia import gemini
from assistente.integracoes import web_tools as W


class Resp:
    def __init__(self, body, ctype="text/html; charset=utf-8", url="https://exemplo.com/a"):
        self.body, self.url = body if isinstance(body, bytes) else body.encode(), url
        self.headers = {"Content-Type": ctype}

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def public(host, port, proto=0):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = (W._urlopen, W._resolve, gemini.generate)
        W._resolve = public
        self.reqs = []

    def tearDown(self):
        W._urlopen, W._resolve, gemini.generate = self.saved


class UrlTest(Base):
    def test_bloqueia_rede_local_e_esquemas_perigosos(self):
        for url in ("file:///etc/passwd", "ftp://x.com", "http://user:pw@x.com", "javascript:alert(1)", "", "http:///x"):
            with self.assertRaises(W.WebError, msg=url):
                W.check_url(url)
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.0.10", "169.254.169.254", "::1", "0.0.0.0", "172.16.3.4"):
            W._resolve = lambda h, p, proto=0, ip=ip: [(2, 1, 6, "", (ip, p))]
            with self.assertRaises(W.WebError, msg=ip):
                W.check_url("http://exemplo.com/x")
        W._resolve = public
        self.assertEqual(W.check_url("https://exemplo.com/x"), "https://exemplo.com/x")

    def test_dns_que_falha(self):
        def boom(*a, **k):
            raise socket.gaierror("x")
        W._resolve = boom
        with self.assertRaises(W.WebError):
            W.check_url("https://naoexiste.example")

    def test_redirecionamento_para_rede_local_e_barrado(self):
        h = W._SafeRedirect()
        W._resolve = lambda host, p, proto=0: [(2, 1, 6, "", ("127.0.0.1" if host == "interno" else "93.184.216.34", p))]
        import urllib.request
        req = urllib.request.Request("https://exemplo.com/")
        with self.assertRaises(W.WebError):
            h.redirect_request(req, None, 302, "Found", {}, "http://interno/admin")


class PaginaTest(Base):
    HTML = ("<html><head><title> Meu  Artigo </title><style>.a{}</style></head><body><nav>menu</nav>"
            "<h1>Título</h1><p>Primeiro <b>parágrafo</b> com &amp; símbolo.</p><script>evil()</script>"
            "<ul><li>um</li><li>dois</li></ul><footer>rodapé</footer></body></html>")

    def test_extrai_texto_limpo(self):
        W._urlopen = lambda req, timeout=0: Resp(self.HTML)
        r = W.fetch_page("https://exemplo.com/a")
        self.assertEqual(r["titulo"], "Meu Artigo")
        self.assertIn("## Título", r["texto"])
        self.assertIn("Primeiro parágrafo com & símbolo.", r["texto"])
        self.assertIn("- um", r["texto"])
        for ruim in ("evil", "menu", "rodapé", ".a{}"):
            self.assertNotIn(ruim, r["texto"])
        self.assertFalse(r["cortado"])

    def test_corta_texto_grande(self):
        W._urlopen = lambda req, timeout=0: Resp("<p>" + "palavra " * 5000 + "</p>")
        r = W.fetch_page("https://exemplo.com/a", max_chars=1000)
        self.assertEqual(len(r["texto"]), 1000)
        self.assertTrue(r["cortado"])

    def test_charset_latin1(self):
        W._urlopen = lambda req, timeout=0: Resp("<p>coração</p>".encode("latin-1"), "text/html; charset=iso-8859-1")
        self.assertIn("coração", W.fetch_page("https://exemplo.com/a")["texto"])

    def test_tipos_nao_textuais_e_vazias(self):
        W._urlopen = lambda req, timeout=0: Resp(b"\x89PNG", "image/png")
        with self.assertRaises(W.WebError):
            W.fetch_page("https://exemplo.com/a.png")
        W._urlopen = lambda req, timeout=0: Resp("<html><body><script>x</script></body></html>")
        with self.assertRaises(W.WebError):
            W.fetch_page("https://exemplo.com/a")

    def test_json_volta_como_texto(self):
        W._urlopen = lambda req, timeout=0: Resp('{"a": 1}', "application/json")
        self.assertEqual(W.fetch_page("https://exemplo.com/api")["texto"], '{"a": 1}')

    def test_erro_http_vira_mensagem(self):
        import urllib.error

        def boom(req, timeout=0):
            raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))
        W._urlopen = boom
        with self.assertRaises(W.WebError) as c:
            W.fetch_page("https://exemplo.com/a")
        self.assertIn("404", str(c.exception))


DDG = '''
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.com%2Fnoticia&amp;rut=abc">Notícia <b>boa</b></a>
<a class="result__snippet" href="x">Um trecho &amp; mais.</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Anúncio</a><a class="result__snippet">anuncio</a></div>
<div class="result"><a class="result__a" href="https://outro.org/p">Outro</a><a class="result__snippet">Segundo trecho</a></div>
'''


class PesquisaTest(Base):
    def grounded(self, text="Resposta com dados.", chunks=None):
        def gen(contents, models, **kw):
            self.reqs.append((models, kw))
            return {"_model": models[0], "candidates": [{"content": {"parts": [{"text": text}]},
                    "groundingMetadata": {"groundingChunks": chunks if chunks is not None else
                                          [{"web": {"uri": "https://a.com", "title": "A"}}, {"web": {"uri": "https://a.com"}}]}}]}
        gemini.generate = gen

    def test_pesquisa_do_google_com_fontes(self):
        self.grounded()
        r = W.search({"ia": {"modelo": "gemini-x"}}, "dólar hoje")
        self.assertEqual(r["resposta"], "Resposta com dados.")
        self.assertEqual(r["fontes"], [{"titulo": "A", "url": "https://a.com"}])      # sem repetir
        models, kw = self.reqs[0]
        self.assertEqual(models, [W.DEFAULT_SEARCH_MODEL, "gemini-x"])
        self.assertTrue(kw["grounding"])

    def test_modelo_de_pesquisa_configuravel(self):
        self.grounded()
        W.search({"ia": {"modelo": "m", "modelo_pesquisa": "lite-z"}}, "x")
        self.assertEqual(self.reqs[0][0], ["lite-z", "m"])

    def test_cai_para_duckduckgo_quando_o_google_falha(self):
        def boom(*a, **k):
            raise gemini.GeminiError("cota", 429, "quota")
        gemini.generate = boom
        seen = []
        W._urlopen = lambda req, timeout=0: (seen.append((req.full_url, req.data)), Resp(DDG))[1]
        r = W.search({}, "notícia")
        self.assertEqual(r["como"], "DuckDuckGo")
        self.assertEqual([x["url"] for x in r["resultados"]], ["https://exemplo.com/noticia", "https://outro.org/p"])
        self.assertEqual(r["resultados"][0]["titulo"], "Notícia boa")
        self.assertEqual(r["resultados"][0]["trecho"], "Um trecho & mais.")
        self.assertIn("cota", r["aviso"])
        self.assertIn(b"q=not%C3%ADcia", seen[0][1])

    def test_tudo_falha_da_erro_claro(self):
        def boom(*a, **k):
            raise gemini.GeminiError("cota", 429, "quota")
        gemini.generate = boom
        W._urlopen = lambda req, timeout=0: Resp("<html>nada</html>")
        with self.assertRaises(W.WebError) as c:
            W.search({}, "x")
        self.assertIn("falhou", str(c.exception))

    def test_consulta_invalida(self):
        for q in ("", "  ", "x" * 301):
            with self.assertRaises(W.WebError):
                W.search({}, q)


if __name__ == "__main__":
    unittest.main()
