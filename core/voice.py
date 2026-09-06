import asyncio
import re
import sys
import tempfile
from pathlib import Path

import edge_tts

TTS_VOICE = "es-MX-DaliaNeural"
ROOT = Path(__file__).resolve().parent.parent

# El modelo responde en markdown (negritas con **, links [texto](url),
# vinetas con "- ", etc.) y a veces con emojis - genial para leer en
# pantalla, pero edge-tts lee esos simbolos en voz alta tal cual
# ("asterisco asterisco", el nombre del emoji, o directamente lo salta
# de forma rara). Antes de sintetizar se limpia todo eso; el texto que
# se muestra en el chat (data["text"] en los chunks) no se toca, esto
# solo afecta al audio.
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BULLET = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_MD_ITALIC = re.compile(r"(?<!\w)\*(?!\s)([^*\n]+?)\*(?!\w)")
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "️"
    "]+",
    flags=re.UNICODE,
)


def _clean_for_speech(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = _MD_ITALIC.sub(r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", ". ", text)
    return text.strip()

# Whisper corre en un subproceso de python.exe totalmente aparte:
# mezclado con el hilo de Qt de la ventana, ctranslate2/onnxruntime
# terminaba tumbando toda la app (choque de runtimes nativos). Un
# subprocess.exec limpio, en vez de un ProcessPoolExecutor, tambien deja
# ver el error real si algo vuelve a fallar (stdout/stderr/exit code).
async def transcribe(audio_bytes: bytes, suffix: str = ".wav") -> str:
    """Transcribe un clip de audio a texto."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "core.transcribe_cli",
            path,
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"transcribe_cli fallo (codigo {proc.returncode}): "
                f"{stderr.decode(errors='replace')[-500:]}"
            )
        return stdout.decode("utf-8").strip()
    finally:
        Path(path).unlink(missing_ok=True)


async def synthesize(text: str) -> bytes:
    """Convierte texto a audio (mp3) usando una voz en español."""
    communicate = edge_tts.Communicate(_clean_for_speech(text), TTS_VOICE)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)
