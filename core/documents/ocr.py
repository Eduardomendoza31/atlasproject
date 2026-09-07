"""OCR (reconocimiento óptico de caracteres) vía Tesseract, para leer texto
de imágenes y de páginas de PDF sin capa de texto (escaneos).

El motor de Tesseract es un binario de sistema, no un paquete de Python -
`pytesseract` es solo el cliente que lo invoca. Los archivos de idioma
(spa/eng/osd) tampoco viven en el repo (son binarios de varios MB cada
uno) - se descargan una sola vez con `python -m core.documents.setup_ocr`
(ver ese módulo) a una carpeta propia de Atlas, para no depender de
permisos de escritura en Archivos de Programa ni de en qué ruta haya
quedado instalado Tesseract en esta máquina en particular."""

import os
import shutil
from pathlib import Path

import pytesseract
from PIL import Image

TESSDATA_DIR = Path(__file__).resolve().parent / "tessdata"
OCR_LANGS = "spa+eng"

_COMMON_INSTALL_PATHS = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


def _configure_tesseract() -> None:
    if not shutil.which("tesseract"):
        for candidate in _COMMON_INSTALL_PATHS:
            if candidate.exists():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                break

    # TESSDATA_PREFIX (variable de entorno) en vez de pasar `--tessdata-dir
    # "ruta"` como config: pytesseract arma la linea de comandos con
    # shlex(posix=False) en Windows, que NO saca las comillas que uno le
    # pone a mano - terminan siendo parte literal del nombre de carpeta que
    # Tesseract busca. La ruta de este proyecto tiene un espacio (la
    # carpeta del usuario), asi que sin comillas se corta mal y con
    # comillas quedan pegadas al valor - la variable de entorno evita el
    # problema por completo, no pasa por ese parseo.
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)


_configure_tesseract()


def is_ready() -> bool:
    """False si falta el motor de Tesseract o los datos de idioma - se usa
    para dar un error explicito en vez de un traceback confuso."""
    tesseract_available = bool(shutil.which("tesseract")) or any(
        p.exists() for p in _COMMON_INSTALL_PATHS
    )
    langs_available = TESSDATA_DIR.exists() and any(TESSDATA_DIR.glob("*.traineddata"))
    return tesseract_available and langs_available


def ocr_image(image: Image.Image) -> str:
    """Extrae el texto legible de una imagen ya cargada en memoria (PIL)."""
    if not is_ready():
        raise RuntimeError(
            "OCR no está configurado - instalá el motor de Tesseract "
            "('winget install --id UB-Mannheim.TesseractOCR' en Windows) y "
            "corré 'python -m core.documents.setup_ocr' una vez para "
            "descargar los datos de idioma."
        )
    return pytesseract.image_to_string(image, lang=OCR_LANGS).strip()
