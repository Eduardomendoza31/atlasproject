import asyncio
import sys
import tempfile
from pathlib import Path

import edge_tts

TTS_VOICE = "es-MX-DaliaNeural"
ROOT = Path(__file__).resolve().parent.parent

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
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)
