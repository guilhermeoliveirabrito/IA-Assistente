import array
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from assistente.pc import wake


def chunk(amp):
    return array.array("h", [amp] * wake.CHUNK).tobytes()


SIL, WAKE, SPEECH = chunk(0), chunk(2000), chunk(3000)


class FakeSource:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self):
        return self.chunks.pop(0) if self.chunks else None


class FakeWake:
    """Considera que ouviu a frase quando chega um pedaço com amplitude WAKE."""

    def accept(self, pcm):
        self._heard = pcm == WAKE
        return False

    def text(self):
        return ""

    def partial(self):
        return "ei assistente" if getattr(self, "_heard", False) else ""


def run(chunks, transcripts, phrase="ei assistente"):
    got, states, beeps, sent = [], [], [], []
    src = FakeSource(chunks)
    texts = list(transcripts)

    def transcribe(wav):
        got.append(wav)
        return texts.pop(0) if texts else ""

    lis = wake.Listener(phrase, src, FakeWake, transcribe, sent.append,
                        lambda s, d="": states.append(s), beeps.append, noise_floor=0)
    lis.run()
    return sent, states, beeps, got


class HelpersTest(unittest.TestCase):
    def test_strip(self):
        f = wake.strip_wake_phrase
        self.assertEqual(f("Ei assistente, abre o Spotify", "ei assistente"), "abre o Spotify")
        self.assertEqual(f("ok ei assistente abre", "ei assistente"), "abre")
        self.assertEqual(f("Ei, Assistente!", "ei assistente"), "")
        self.assertEqual(f("abre o Spotify", "ei assistente"), "abre o Spotify")
        self.assertEqual(f("por favor ei assistente abre", "ei assistente"), "por favor ei assistente abre")
        self.assertEqual(f("", "ei assistente"), "")

    def test_normalize(self):
        self.assertEqual(wake.normalize("  Ei,  ASSISTENTE! Olá "), "ei assistente ola")

    def test_plain_for_speech(self):
        t = wake.plain_for_speech("# Título\n**Oi** [site](http://x.com) `cmd`\n- item\n```py\nx=1\n```")
        self.assertNotIn("**", t)
        self.assertNotIn("http", t)
        self.assertNotIn("```", t)
        self.assertIn("Oi site cmd", t)
        self.assertIn("item", t)

    def test_rms_e_wav(self):
        self.assertEqual(wake.rms(b""), 0.0)
        self.assertAlmostEqual(wake.rms(chunk(1000)), 1000, delta=1)
        wav = wake.to_wav([SIL, SIL])
        self.assertTrue(wav.startswith(b"RIFF"))


class ListenerTest(unittest.TestCase):
    def test_frase_e_comando(self):
        chunks = [SIL] * 3 + [WAKE] + [SIL] * 2 + [SPEECH] * 8 + [SIL] * 15
        sent, states, beeps, got = run(chunks, ["ei assistente abre o Spotify"])
        self.assertEqual(sent, ["abre o Spotify"])
        self.assertIn("recording", states)
        self.assertIn("processing", states)
        self.assertEqual(beeps[0], "wake")
        self.assertEqual(len(got), 1)

    def test_sem_frase_nada_acontece(self):
        sent, _s, beeps, got = run([SPEECH] * 20 + [SIL] * 20, ["x"])
        self.assertEqual((sent, beeps, got), ([], [], []))

    def test_so_a_frase_espera_o_comando(self):
        chunks = [WAKE] + [SIL] * 12 + [SPEECH] * 6 + [SIL] * 15
        sent, _s, beeps, got = run(chunks, ["toca uma música"])
        self.assertEqual(sent, ["toca uma música"])
        self.assertEqual(len(got), 1)

    def test_silencio_total_desiste(self):
        chunks = [WAKE] + [SIL] * 200
        sent, states, beeps, got = run(chunks, [])
        self.assertEqual(sent, [])
        self.assertEqual(got, [])
        self.assertIn("none", beeps)
        self.assertIn("idle", states)

    def test_transcricao_so_com_a_frase_tenta_de_novo(self):
        chunks = [WAKE] + [SPEECH] * 4 + [SIL] * 15 + [SPEECH] * 6 + [SIL] * 15
        sent, _s, beeps, got = run(chunks, ["ei assistente", "abre o bloco de notas"])
        self.assertEqual(sent, ["abre o bloco de notas"])
        self.assertIn("again", beeps)

    def test_erro_na_transcricao_nao_derruba(self):
        def boom(wav):
            raise RuntimeError("sem internet")

        states, sent = [], []
        lis = wake.Listener("ei assistente", FakeSource([WAKE] + [SPEECH] * 4 + [SIL] * 15 + [WAKE] + [SIL] * 3),
                            FakeWake, boom, sent.append, lambda s, d="": states.append(s), noise_floor=0)
        lis.run()
        self.assertIn("error", states)
        self.assertEqual(sent, [])

    def test_erro_no_comando_nao_derruba(self):
        def bad(text):
            raise RuntimeError("x")

        states = []
        lis = wake.Listener("ei assistente", FakeSource([WAKE] + [SPEECH] * 4 + [SIL] * 15),
                            FakeWake, lambda w: "ei assistente oi", bad, lambda s, d="": states.append(s), noise_floor=0)
        lis.run()
        self.assertIn("error", states)

    def test_pausa_ignora_a_frase(self):
        sent = []
        lis = wake.Listener("ei assistente", FakeSource([WAKE] + [SPEECH] * 3 + [SIL] * 15), FakeWake,
                            lambda w: "oi", sent.append, noise_floor=0)
        lis.pause()
        lis.run()
        self.assertEqual(sent, [])
        self.assertTrue(lis.paused)
        lis.resume()
        self.assertFalse(lis.paused)

    def test_intervalo_apos_acionar(self):
        chunks = [WAKE] + [SPEECH] * 4 + [SIL] * 15 + [WAKE] + [SIL] * 3
        sent, _s, beeps, got = run(chunks, ["ei assistente oi"])
        self.assertEqual(sent, ["oi"])


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def make_zip(self, name, members):
        with zipfile.ZipFile(name, "w") as z:
            for k, v in members.items():
                z.writestr(k, v)

    def test_zip_slip_recusado(self):
        self.make_zip("a.zip", {"../fora.txt": "x"})
        Path("d").mkdir()
        with self.assertRaises(wake.VoiceError):
            wake.extract_zip(Path("a.zip"), Path("d"))
        self.assertFalse(Path("fora.txt").exists())

    def test_extrai_normal(self):
        self.make_zip("a.zip", {"m/am/final.mdl": "x"})
        Path("d").mkdir()
        wake.extract_zip(Path("a.zip"), Path("d"))
        self.assertTrue(Path("d/m/am/final.mdl").exists())

    def test_download_com_arquivo_local(self):
        self.make_zip("src.zip", {f"{wake.MODEL_NAME}/am/final.mdl": "x"})
        self.assertIsNone(wake.model_path())
        seen = []
        wake.download_model(seen.append, Path("src.zip").resolve().as_uri())
        self.assertIsNotNone(wake.model_path())
        self.assertEqual(seen[-1], 100)
        self.assertFalse(list(wake.MODEL_DIR.glob("*.part")))

    def test_download_aceita_zip_com_outra_pasta_raiz(self):
        self.make_zip("src.zip", {"qualquer-nome/am/final.mdl": "x", "qualquer-nome/conf/mfcc.conf": "y"})
        wake.download_model(None, Path("src.zip").resolve().as_uri())
        self.assertIsNotNone(wake.model_path())
        self.assertFalse(list(wake.MODEL_DIR.glob("*.extraindo")))

    def test_download_aceita_zip_sem_pasta_raiz(self):
        self.make_zip("src.zip", {"am/final.mdl": "x"})
        wake.download_model(None, Path("src.zip").resolve().as_uri())
        self.assertIsNotNone(wake.model_path())

    def test_download_aceita_layout_novo_com_final_mdl_na_raiz(self):
        self.make_zip("src.zip", {f"{wake.MODEL_NAME}/final.mdl": "x", f"{wake.MODEL_NAME}/graph/HCLr.fst": "y"})
        wake.download_model(None, Path("src.zip").resolve().as_uri())
        self.assertIsNotNone(wake.model_path())

    def test_download_formato_errado_lista_o_conteudo(self):
        self.make_zip("src.zip", {"pasta/arquivo.txt": "x"})
        with self.assertRaises(wake.VoiceError) as cm:
            wake.download_model(None, Path("src.zip").resolve().as_uri())
        self.assertIn("arquivo.txt", str(cm.exception))

    def test_download_nao_zip_da_erro_claro(self):
        Path("src.zip").write_text("<html>bloqueado</html>")
        with self.assertRaises(wake.VoiceError) as cm:
            wake.download_model(None, Path("src.zip").resolve().as_uri())
        self.assertIn("zip", str(cm.exception))

    def test_download_formato_errado(self):
        self.make_zip("src.zip", {"outra/coisa.txt": "x"})
        with self.assertRaises(wake.VoiceError):
            wake.download_model(None, Path("src.zip").resolve().as_uri())


class ServiceTest(unittest.TestCase):
    def test_sem_ativar(self):
        events = []
        s = wake.VoiceService({"voz": {"ativada": False}}, lambda t: None, events.append)
        self.assertFalse(s.start())
        self.assertEqual(s.status()["state"], "off")

    def test_sem_dependencias_ou_modelo_informa(self):
        events = []
        s = wake.VoiceService({"voz": {"ativada": True}}, lambda t: None, events.append)
        self.assertFalse(s.start())
        self.assertEqual(s.state, "error")
        self.assertTrue(s.detail)
        self.assertEqual(s.status()["phrase"], "ei assistente")
        self.assertTrue(any(e["type"] == "voice" for e in events))

    def test_transcricao_cai_para_local(self):
        def remote(wav):
            raise RuntimeError("cota")

        s = wake.VoiceService({"voz": {"transcricao": "gemini"}}, lambda t: None, transcribe_remote=remote)
        orig = wake.local_transcribe
        wake.local_transcribe = lambda model, wav: "texto local"
        try:
            self.assertEqual(s._transcribe(b"x"), "texto local")
        finally:
            wake.local_transcribe = orig

    def test_fala_pausa_a_escuta(self):
        s = wake.VoiceService({"voz": {"falar_resposta": True}}, lambda t: None)
        lis = wake.Listener("oi", FakeSource([]), FakeWake, lambda w: "", lambda t: None)
        s._listener = lis
        seen = []
        orig = wake.speak
        wake.speak = lambda t: seen.append(lis.paused)
        try:
            s.speak_reply("olá")
        finally:
            wake.speak = orig
        self.assertEqual(seen, [True])
        self.assertFalse(lis.paused)


if __name__ == "__main__":
    unittest.main()
