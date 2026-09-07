"""Descarga los archivos de idioma de Tesseract (español + inglés +
orientación) para que Atlas pueda hacer OCR (leer texto de imágenes y de
PDFs escaneados). Se corre una sola vez, a mano - mismo patrón que
core/face_gen.py (un script manual, no algo que corre en cada arranque),
porque son ~16 MB de datos que no cambian entre ejecuciones:

    python -m core.documents.setup_ocr

Requiere que el MOTOR de Tesseract ya esté instalado por separado (no es
un paquete de Python, es un binario de sistema) - en Windows:

    winget install --id UB-Mannheim.TesseractOCR

Los archivos de idioma no se toman del instalador de Windows (que solo trae
inglés) sino del repositorio oficial tessdata_fast, directo a una carpeta
propia de Atlas (core/documents/tessdata/) - así no dependemos de permisos
de escritura en Archivos de Programa, ni de en qué ruta haya quedado
instalado Tesseract en esta máquina en particular (ver core/documents/ocr.py)."""

import urllib.request
from pathlib import Path

TESSDATA_DIR = Path(__file__).resolve().parent / "tessdata"
BASE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main"
LANGS = ["eng", "spa", "osd"]


def main() -> None:
    TESSDATA_DIR.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        dest = TESSDATA_DIR / f"{lang}.traineddata"
        if dest.exists():
            print(f"[OCR setup] {lang}.traineddata ya existe, se salta.")
            continue
        url = f"{BASE_URL}/{lang}.traineddata"
        print(f"[OCR setup] Descargando {lang}.traineddata...")
        urllib.request.urlretrieve(url, dest)
    print(f"[OCR setup] Listo - datos de idioma en {TESSDATA_DIR}")


if __name__ == "__main__":
    main()
