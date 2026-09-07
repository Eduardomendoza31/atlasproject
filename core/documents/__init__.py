"""Extraccion de texto de documentos reales (Fase 3 del plan de migracion -
ver ATLAS_MIGRATION_PLAN.md). Hasta ahora `read_file` (core/tools.py) solo
podia leer texto plano UTF-8 y rechazaba cualquier binario - este paquete
le da a Atlas la mitad que faltaba de "creacion de documentos" (la lectura,
no solo la escritura que ya existia en skills/documents.py).

Deliberadamente sin OCR todavia: un PDF escaneado (sin capa de texto) no se
puede leer asi, y agregar eso depende de instalar Tesseract (un binario de
sistema aparte, no solo un paquete pip) - ver ATLAS_TECHNOLOGY_DECISIONS.md.
extract_text() avisa explicitamente ese caso en vez de devolver vacio en
silencio."""

from pathlib import Path

from core.documents.extractors import (
    extract_csv,
    extract_docx,
    extract_html,
    extract_image,
    extract_pdf,
    extract_pptx,
    extract_xlsx,
)

EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".csv": extract_csv,
    ".pptx": extract_pptx,
    ".html": extract_html,
    ".htm": extract_html,
    ".png": extract_image,
    ".jpg": extract_image,
    ".jpeg": extract_image,
    ".bmp": extract_image,
    ".tiff": extract_image,
}


def can_extract(path: Path) -> bool:
    """True si este paquete sabe extraer texto de este tipo de archivo -
    core/tools.py lo usa para decidir si un archivo "binario" en realidad
    es un documento que sabemos leer, antes de rendirse."""
    return path.suffix.lower() in EXTRACTORS


def extract_text(path: Path) -> str:
    """Extrae el texto de un documento segun su extension. Lanza la
    excepcion tal cual si algo falla (archivo corrupto, dependencia
    faltante, etc.) - el llamador (core/tools.py) decide como mostrarle el
    error al usuario, este modulo no formatea mensajes de error."""
    extractor = EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        raise ValueError(f"Tipo de archivo no soportado para extraccion: '{path.suffix}'")
    return extractor(path)
