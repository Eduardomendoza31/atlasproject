"""Script standalone: transcribe un archivo de audio y escribe el texto
a stdout. Corre como subproceso separado (ver core/voice.py) porque
faster-whisper choca cuando corre en el mismo proceso que la ventana de
Qt."""

import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from faster_whisper import WhisperModel  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    path = sys.argv[1]
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path, language="es")
    text = "".join(segment.text for segment in segments).strip()
    print(text)


if __name__ == "__main__":
    main()
