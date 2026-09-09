"""Skill: generación de imágenes a partir de una descripción de texto.

Investigado antes de escribir codigo (ver ATLAS_MIGRATION_PLAN.md y la
memoria de la sesion): correr un modelo de difusion local en esta maquina
(i3-1125G4, sin GPU) es impractico de verdad, no una exageracion - hasta
SDXL/SD1.5 optimizados para CPU tardan varios minutos por imagen, y ni
siquiera las variantes "turbo" (1-4 pasos) tienen benchmarks confiables por
debajo de eso en hardware de esta clase. La alternativa elegida es
Pollinations.AI (pollinations.ai, licencia MIT, codigo y modelos abiertos,
autohospedable): un servicio gratuito, sin API key, que sirve el modelo
abierto Flux via una simple llamada HTTP GET. Probado en vivo antes de
integrarlo: imagenes reales de buena calidad en 3-28 segundos, muy por
debajo de los minutos que tomaria generar localmente en este hardware.

Sigue el mismo patron que la Fase 4 (embeddings locales) y la Fase 7 (modelo
de conversacion hibrido) del plan de migracion: elegir la opcion mas
efectiva que de verdad funciona en la maquina real, no la mas "local" a
cualquier costo de velocidad."""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from core.config import GENERATED_IMAGES_DIR
from core.tools import IMAGE_MARKER, Tool, register as register_tool, resolve_path

SKILL = {
    "name": "Generación de imágenes",
    "description": "Genera imágenes a partir de una descripción de texto usando Flux (modelo abierto, vía Pollinations.AI) y las muestra en el chat.",
}

API_BASE = "https://image.pollinations.ai/prompt"
MODEL = "flux"
DEFAULT_SIZE = 1024

# Generar una imagen real puede tardar bastante mas que una llamada de
# texto comun (se midieron hasta ~28s en pruebas reales) - un timeout corto
# cortaria generaciones legitimas, no solo las que de verdad fallaron.
REQUEST_TIMEOUT_SECONDS = 120

# El nivel gratuito/anonimo de Pollinations limita a un pedido cada 15
# segundos (ver su documentacion). Hasta 2 reintentos (3 intentos en
# total) alcanzan para el uso normal de un asistente personal - pedidos
# sueltos, no una rafaga - sin dejar al usuario esperando indefinidamente
# si el servicio esta genuinamente con problemas.
RATE_LIMIT_RETRY_SECONDS = 16
RATE_LIMIT_MAX_RETRIES = 2

SLUG_MAX_LENGTH = 40


def _slug(prompt: str) -> str:
    """Nombre de archivo legible a partir del prompt, para que el usuario
    reconozca la imagen en su carpeta sin tener que abrirla."""
    ascii_only = re.sub(r"[^a-zA-Z0-9]+", "_", prompt).strip("_").lower()
    return (ascii_only or "imagen")[:SLUG_MAX_LENGTH]


async def _download_image(prompt: str, width: int, height: int) -> bytes:
    url = f"{API_BASE}/{quote(prompt)}"
    params = {"model": MODEL, "width": width, "height": height, "nologo": "true"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            response = await client.get(url, params=params, follow_redirects=True)
            if response.status_code != 429 or attempt == RATE_LIMIT_MAX_RETRIES:
                break
            # asyncio.sleep, no time.sleep: esto corre en el mismo event
            # loop que atiende el websocket de toda la app - bloquearlo con
            # time.sleep congelaria Atlas entero (otras conversaciones,
            # confirmaciones pendientes) durante la espera.
            await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
        response.raise_for_status()
        return response.content


async def _exec_generate_image(arguments: dict) -> str:
    prompt = arguments["prompt"]
    width = int(arguments.get("width") or DEFAULT_SIZE)
    height = int(arguments.get("height") or DEFAULT_SIZE)
    raw_path = arguments.get("path")

    try:
        image_bytes = await _download_image(prompt, width, height)
    except httpx.HTTPStatusError as exc:
        return f"Error: el servicio de generación de imágenes respondió con un error ({exc.response.status_code})."
    except httpx.HTTPError as exc:
        # Las excepciones de timeout de httpx suelen tener str(exc) vacio -
        # sin el nombre de la clase, el error le llegaria al modelo (y de
        # ahi al usuario) como "fallo la conexion: " sin ninguna pista.
        detalle = str(exc) or type(exc).__name__
        return f"Error: no pude generar la imagen, falló la conexión ({detalle})."

    if raw_path:
        path = resolve_path(raw_path)
        if path.suffix.lower() not in (".jpg", ".jpeg"):
            path = path.with_suffix(".jpg")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = GENERATED_IMAGES_DIR / f"atlas_{timestamp}_{_slug(prompt)}.jpg"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)

    # La URL apunta al mismo puerto que ya usa el resto de Atlas
    # (core/app.py monta GENERATED_IMAGES_DIR en /generated-images) - si el
    # usuario pidio guardarla en otro lado (`raw_path`), la imagen igual se
    # guarda ahi, pero solo se puede MOSTRAR en el chat si ese destino cae
    # dentro de esa carpeta (fuera de ahi, FastAPI no la sirve).
    try:
        relative = path.resolve().relative_to(GENERATED_IMAGES_DIR.resolve())
        image_url = f"http://127.0.0.1:8731/generated-images/{quote(str(relative).replace(chr(92), '/'))}"
        marker = f"{IMAGE_MARKER}{image_url}"
    except ValueError:
        marker = ""

    return (
        f"Imagen generada a partir de: \"{prompt}\". Se guardó en '{path}'."
        f"{marker}"
    )


def register() -> None:
    register_tool(Tool(
        name="generate_image",
        description=(
            "Genera una imagen real a partir de una descripción de texto "
            "(usando el modelo Flux) y la muestra en el chat. Escribe el "
            "argumento 'prompt' en inglés y de forma descriptiva (estilo, "
            "colores, composición, iluminación) para la mejor calidad, "
            "aunque el usuario haya pedido la imagen en español - vos "
            "traducís y enriquecés la descripción, el usuario no tiene que "
            "hacerlo. Úsalo cuando el usuario pida crear, generar o "
            "dibujar una imagen, ilustración, foto o diseño."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Descripción de la imagen a generar, en inglés, detallada.",
                },
                "width": {"type": "integer", "description": "Ancho en píxeles (por defecto 1024)."},
                "height": {"type": "integer", "description": "Alto en píxeles (por defecto 1024)."},
                "path": {
                    "type": "string",
                    "description": "Ruta donde guardar el archivo. Opcional - si no se da, se guarda en la carpeta de imágenes de Atlas con un nombre automático.",
                },
            },
            "required": ["prompt"],
        },
        tier="sensitive",
        executor=_exec_generate_image,
        confirm_text=lambda a: f"Generar imagen: \"{a.get('prompt')}\"",
    ))
