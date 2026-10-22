"""Ativação por voz: o assistente fica ouvindo uma frase de chamada ("ei assistente") e, ao ouvi-la, grava o
seu comando na hora, transcreve e manda para o assistente, como a Siri ou o "Ok Google".

Como funciona (tudo fica no seu computador até o comando):
  1. O microfone é lido em pedaços de 0,1 s. Um reconhecedor OFFLINE (Vosk, modelo pequeno em português) procura
     SÓ a frase de chamada; o que você fala fora dela é descartado na hora, nada é gravado nem enviado.
  2. Ouvida a frase, toca um bipe e o app grava o comando (incluindo os últimos segundos, para o caso de você ter
     falado tudo de uma vez: "ei assistente, abre o Spotify") até você ficar em silêncio.
  3. SÓ esse trecho é transcrito (pelo Gemini, que acerta mais, ou localmente, de graça e sem internet) e vai
     para o chat. A resposta curta é lida em voz alta.

As bibliotecas (vosk, sounddevice) e o modelo de voz são opcionais: sem eles o app funciona normalmente.
"""
import array
import collections
import importlib.util
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
import wave
import zipfile
from pathlib import Path

RATE = 16000
CHUNK = 1600                      # 0,1 s
CHUNK_S = CHUNK / RATE
MODEL_NAME = "vosk-model-small-pt-0.3"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = Path("data") / "models"
MODEL_MAX_BYTES = 200 * 1024 * 1024

RING_SECONDS = 3.0                # o que foi dito um pouco ANTES de a frase ser detectada também entra no comando
SILENCE_END = 1.2                 # silêncio que encerra o comando
WAIT_FOR_SPEECH = 6.0             # sem ouvir nada depois da frase: desiste
MAX_COMMAND = 20.0
MIN_THRESHOLD = 350               # energia mínima (int16) para contar como fala
COOLDOWN = 1.0

FILLERS = {"e", "ai", "oi", "ola", "ok", "hey", "ei", "eai", "opa"}


class VoiceError(Exception):
    pass


# ---------------------------------------------------------------- texto

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def strip_wake_phrase(text: str, phrase: str) -> str:
    """Tira a frase de chamada do começo da transcrição ("Ei assistente, abre o Spotify" -> "abre o Spotify")."""
    words = str(text or "").split()
    target = normalize(phrase).split()
    if not words or not target:
        return " ".join(words).strip()
    norm = [normalize(w) for w in words]
    n = len(target)
    for i in range(0, min(4, len(words))):
        window = [x for x in norm[i:i + n]]
        if window == target and all(norm[j] in FILLERS or norm[j] == "" for j in range(i)):
            rest = words[i + n:]
            return " ".join(rest).lstrip(" ,.:;!-—").strip()
    return " ".join(words).strip()


def plain_for_speech(text: str) -> str:
    """Markdown -> texto falável."""
    t = re.sub(r"```[\s\S]*?```", " (trecho de código) ", str(text or ""))
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " link ", t)
    t = re.sub(r"^\s*\|?[\s:|-]{3,}\|?\s*$", "", t, flags=re.M)
    t = t.replace("|", ", ")
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"(\*\*|__|\*|~~)", "", t)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    return re.sub(r"\n{2,}", ". ", re.sub(r"[ \t]+", " ", t)).strip()


# ---------------------------------------------------------------- áudio

def rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def to_wav(chunks) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(chunks))
    return buf.getvalue()


# ---------------------------------------------------------------- o ouvinte (lógica pura, testável)

class Listener:
    """Máquina de estados: ouvindo a frase -> gravando o comando -> transcrevendo -> entregando.

    source.read() devolve o próximo pedaço de PCM16 (ou None quando acabou); make_wake() devolve um reconhecedor
    com accept(pcm)->bool, text() e partial(); transcribe(wav) devolve o texto; on_command(texto) é chamado com
    o comando já sem a frase de chamada.
    """

    def __init__(self, phrase, source, make_wake, transcribe, on_command, on_state=None, beep=None, noise_floor=None):
        self.phrase = normalize(phrase)
        self.source = source
        self.make_wake = make_wake
        self.transcribe = transcribe
        self.on_command = on_command
        self.on_state = on_state or (lambda state, detail="": None)
        self.beep = beep or (lambda kind: None)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._floor = noise_floor if noise_floor is not None else 120.0
        self.phrase_name = phrase

    # controle
    def stop(self):
        self._stop.set()

    def pause(self):
        self._paused.set()
        self.on_state("paused")

    def resume(self):
        self._paused.clear()
        self.on_state("listening")

    @property
    def paused(self):
        return self._paused.is_set()

    # limiar de fala: acompanha o ruído do ambiente
    def _threshold(self):
        return max(MIN_THRESHOLD, self._floor * 3.0)

    def _track_floor(self, level):
        if level < self._threshold():                      # só aprende com o que NÃO é fala
            self._floor = 0.98 * self._floor + 0.02 * level

    def run(self):
        wake = self.make_wake()
        ring = collections.deque(maxlen=int(RING_SECONDS / CHUNK_S))
        cooldown = 0
        self.on_state("listening")
        while not self._stop.is_set():
            chunk = self.source.read()
            if chunk is None:
                break
            if self._paused.is_set():
                ring.clear()
                wake = self._fresh(wake)
                continue
            level = rms(chunk)
            self._track_floor(level)
            ring.append(chunk)
            if cooldown > 0:
                cooldown -= 1
                continue
            final = wake.accept(chunk)
            heard = normalize(wake.text() if final else wake.partial())
            if self.phrase and self.phrase in heard:
                self._handle_wake(list(ring))
                ring.clear()
                wake = self._fresh(wake)
                cooldown = int(COOLDOWN / CHUNK_S)
                if not self._stop.is_set():
                    self.on_state("listening")
            elif final:
                wake = self._fresh(wake)

    def _fresh(self, wake):
        return self.make_wake()

    # ---- depois da frase
    def _record(self, first_chunks, wait_for_speech):
        """Grava até o silêncio. Retorna (pedaços, ouviu_fala_depois_da_frase)."""
        chunks = list(first_chunks)
        speech_chunks = 0
        silent = 0
        total = 0
        limit_wait = int(wait_for_speech / CHUNK_S)
        limit_total = int(MAX_COMMAND / CHUNK_S)
        end_silence = int(SILENCE_END / CHUNK_S)
        thr = self._threshold()
        while not self._stop.is_set() and total < limit_total:
            chunk = self.source.read()
            if chunk is None:
                break
            total += 1
            chunks.append(chunk)
            if rms(chunk) > thr:
                speech_chunks += 1
                silent = 0
            else:
                silent += 1
            if speech_chunks >= 2 and silent >= end_silence:
                break
            if speech_chunks < 2 and total >= limit_wait:
                break
        return chunks, speech_chunks >= 2

    def _handle_wake(self, ring_chunks):
        self.on_state("recording")
        self.beep("wake")
        chunks, heard = self._record(ring_chunks, WAIT_FOR_SPEECH)
        text = ""
        if heard:
            text = self._to_text(chunks)
        if not text and not self._stop.is_set():
            # disse só a frase, ou falou e parou: dá mais uma chance de falar o comando
            self.beep("again")
            self.on_state("recording", "ainda ouvindo")
            chunks, heard = self._record([], WAIT_FOR_SPEECH)
            text = self._to_text(chunks) if heard else ""
        if text:
            self.on_state("processing", text)
            try:
                self.on_command(text)
            except Exception as e:       # o ouvinte nunca cai por causa de um comando
                self.on_state("error", f"Não consegui enviar o comando: {e}")
        else:
            self.beep("none")
            self.on_state("idle", "Não ouvi um comando.")

    def _to_text(self, chunks) -> str:
        self.on_state("processing")
        try:
            raw = self.transcribe(to_wav(chunks))
        except Exception as e:
            self.on_state("error", f"Não consegui transcrever: {e}")
            return ""
        return strip_wake_phrase(raw, self.phrase_name).strip()


# ---------------------------------------------------------------- peças reais (microfone, Vosk, voz)

def deps_status() -> dict:
    return {"vosk": importlib.util.find_spec("vosk") is not None,
            "sounddevice": importlib.util.find_spec("sounddevice") is not None}


def model_path():
    p = MODEL_DIR / MODEL_NAME
    return p if (p / "am" / "final.mdl").exists() else None


def download_model(progress=None, url: str = MODEL_URL) -> Path:
    """Baixa o modelo de voz pequeno (≈ 30 MB) e extrai com segurança em data/models/."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_DIR / (MODEL_NAME + ".zip.part")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                done += len(block)
                if done > MODEL_MAX_BYTES:
                    raise VoiceError("O arquivo do modelo é maior do que o esperado; cancelei o download.")
                f.write(block)
                if progress and total:
                    progress(min(99, int(100 * done / total)))
        target = MODEL_DIR / MODEL_NAME
        extract_zip(tmp, MODEL_DIR)
        if not (target / "am" / "final.mdl").exists():
            raise VoiceError("O modelo baixado não tem o formato esperado.")
        if progress:
            progress(100)
        return target
    except OSError as e:
        raise VoiceError(f"Não consegui baixar o modelo de voz: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)


def extract_zip(zip_path: Path, dest: Path):
    """Extrai recusando caminhos que fogem da pasta de destino (zip slip)."""
    base = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            out = (dest / member.filename).resolve()
            if base != out and base not in out.parents:
                raise VoiceError("O arquivo do modelo tem um caminho suspeito; não extraí.")
        z.extractall(dest)


class _VoskWake:
    """Reconhecedor que só entende a frase de chamada (gramática fechada) — rápido e preciso."""

    def __init__(self, model, phrase):
        from vosk import KaldiRecognizer

        self.rec = KaldiRecognizer(model, RATE, json.dumps([normalize(phrase), "[unk]"]))

    def accept(self, pcm: bytes) -> bool:
        return bool(self.rec.AcceptWaveform(pcm))

    def text(self) -> str:
        return json.loads(self.rec.Result()).get("text", "")

    def partial(self) -> str:
        return json.loads(self.rec.PartialResult()).get("partial", "")


class _MicSource:
    def __init__(self, device=None):
        try:
            import sounddevice as sd
        except ImportError as e:
            raise VoiceError("Falta instalar o sounddevice: pip install -r requirements.txt") from e
        try:
            self.stream = sd.RawInputStream(samplerate=RATE, blocksize=CHUNK, dtype="int16", channels=1, device=device)
            self.stream.start()
        except Exception as e:
            raise VoiceError(f"Não consegui abrir o microfone: {e}") from e

    def read(self):
        try:
            data, _overflow = self.stream.read(CHUNK)
            return bytes(data)
        except Exception:
            return None

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def local_transcribe(model, wav: bytes) -> str:
    from vosk import KaldiRecognizer

    with wave.open(io.BytesIO(wav), "rb") as w:
        pcm = w.readframes(w.getnframes())
    rec = KaldiRecognizer(model, RATE)
    for i in range(0, len(pcm), 8000):
        rec.AcceptWaveform(pcm[i:i + 8000])
    return json.loads(rec.FinalResult()).get("text", "").strip()


def word_known(model, word: str) -> bool:
    try:
        return model.vosk_model_find_word(word) >= 0
    except Exception:
        return True


def beep(kind: str):
    """Sinal sonoro curto: ouvi a chamada / ainda ouvindo / não ouvi nada."""
    if sys.platform != "win32":
        return
    try:
        import winsound

        tones = {"wake": [(880, 110), (1175, 110)], "again": [(988, 80)], "none": [(330, 200)]}
        for freq, ms in tones.get(kind, []):
            winsound.Beep(freq, ms)
    except Exception:
        pass


def speak(text: str, rate: int = 1):
    """Lê o texto em voz alta com a voz do Windows (sem instalar nada). Bloqueia até terminar."""
    text = plain_for_speech(text)[:1500]
    if not text:
        return
    try:
        if sys.platform == "win32":
            script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                      f"$s.Rate = {int(rate)}; "
                      "try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, "
                      "[System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]::GetCultureInfo('pt-BR')) } catch {}; "
                      "$t = [Console]::In.ReadToEnd(); $s.Speak($t)")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           input=text.encode("utf-8"), timeout=120, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif sys.platform == "darwin":
            subprocess.run(["say", "-v", "Luciana", text], timeout=120, check=False)
        else:
            subprocess.run(["espeak-ng", "-v", "pt-br", text], timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------- serviço (liga tudo)

class VoiceService:
    """Mantém o ouvinte rodando em segundo plano e informa a interface sobre o estado."""

    def __init__(self, cfg, on_command, publish=None, transcribe_remote=None):
        self.cfg = cfg
        self.on_command = on_command
        self.publish = publish or (lambda event: None)
        self.transcribe_remote = transcribe_remote
        self.state = "off"
        self.detail = ""
        self._listener = None
        self._thread = None
        self._source = None
        self._model = None
        self._lock = threading.RLock()
        self._download = None

    # configuração viva
    @property
    def vz(self) -> dict:
        return self.cfg.get("voz") or {}

    @property
    def phrase(self) -> str:
        return " ".join(str(self.vz.get("frase_de_ativacao") or "ei assistente").split())

    @property
    def enabled(self) -> bool:
        return bool(self.vz.get("ativada"))

    def status(self) -> dict:
        deps = deps_status()
        return {"enabled": self.enabled, "state": self.state, "detail": self.detail, "phrase": self.phrase,
                "deps": deps, "deps_ok": all(deps.values()), "model_ready": model_path() is not None,
                "model_download": self._download, "speak_reply": bool(self.vz.get("falar_resposta", True)),
                "transcription": self.vz.get("transcricao", "gemini")}

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        self.publish({"type": "voice", "voice": self.status()})

    # ---- ciclo de vida
    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            if not self.enabled:
                self._set("off")
                return False
            deps = deps_status()
            if not all(deps.values()):
                self._set("error", "Faltam bibliotecas de voz (pip install -r requirements.txt).")
                return False
            if model_path() is None:
                self._set("error", "Falta baixar o modelo de voz (Ajustes › Ativação por voz).")
                return False
            try:
                self._model = self._load_model()
                self._source = _MicSource()
            except VoiceError as e:
                self._set("error", str(e))
                return False
            except Exception as e:
                self._set("error", f"Não consegui iniciar a voz: {e}")
                return False
            unknown = [w for w in normalize(self.phrase).split() if not word_known(self._model, w)]
            if unknown:
                self._source.close()
                self._set("error", "O modelo de voz não conhece: " + ", ".join(unknown) + ". Escolha outra frase de chamada.")
                return False
            phrase = self.phrase
            self._listener = Listener(phrase, self._source, lambda: _VoskWake(self._model, phrase), self._transcribe,
                                      self._deliver, self._on_state, beep)
            self._thread = threading.Thread(target=self._run, name="voz", daemon=True)
            self._thread.start()
            return True

    def _load_model(self):
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        return Model(str(model_path()))

    def _run(self):
        try:
            self._listener.run()
        except Exception as e:
            self._set("error", f"A escuta parou: {e}")
        finally:
            if self._source:
                self._source.close()
            if self.state != "error":
                self._set("off")

    def stop(self):
        with self._lock:
            if self._listener:
                self._listener.stop()
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._listener = None
        self._thread = None
        if self.state != "error":
            self._set("off")

    def restart(self):
        self.stop()
        return self.start()

    def toggle_pause(self, paused=None):
        if not self._listener:
            return
        if paused is None:
            paused = not self._listener.paused
        self._listener.pause() if paused else self._listener.resume()

    # ---- peças
    def _on_state(self, state, detail=""):
        self._set(state, detail)

    def _transcribe(self, wav: bytes) -> str:
        mode = self.vz.get("transcricao", "gemini")
        errors = []
        if mode == "gemini" and self.transcribe_remote:
            try:
                text = self.transcribe_remote(wav)
                if text:
                    return text
            except Exception as e:           # sem internet, cota... cai no reconhecimento local
                errors.append(e)
        try:
            return local_transcribe(self._model, wav)
        except Exception as e:
            raise VoiceError(str(errors[0] if errors else e)) from e

    def _deliver(self, text: str):
        self.on_command(text)

    def speak_reply(self, text: str):
        """Lê a resposta; enquanto fala, a escuta fica em pausa para ela não ouvir a si mesma."""
        if not text or not self.vz.get("falar_resposta", True):
            return
        was = bool(self._listener and self._listener.paused)
        self.toggle_pause(True)
        try:
            speak(text)
        finally:
            if not was:
                self.toggle_pause(False)

    # ---- download do modelo
    def download_model_async(self):
        with self._lock:
            if self._download is not None:
                return False
            self._download = {"percent": 0}

        def go():
            try:
                def progress(p):
                    self._download = {"percent": p}
                    self.publish({"type": "voice", "voice": self.status()})

                download_model(progress)
                self._download = None
                self.publish({"type": "toast", "kind": "ok", "text": "Modelo de voz instalado."})
                self.publish({"type": "voice", "voice": self.status()})
                if self.enabled:
                    self.start()
            except Exception as e:
                self._download = None
                self.publish({"type": "toast", "kind": "error", "text": f"Modelo de voz: {e}"})
                self.publish({"type": "voice", "voice": self.status()})

        threading.Thread(target=go, name="voz-modelo", daemon=True).start()
        return True
