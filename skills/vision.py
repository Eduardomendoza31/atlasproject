"""Skill: vision de pantalla (area 3 del documento de vision - "leer e
interpretar la pantalla: apps, ventanas, botones, errores").

Captura la pantalla real del usuario y se la manda, junto con una
pregunta, al mismo modelo conversacional (Gemini es multimodal - no
hace falta un modelo ni un rol aparte) usando core.providers.complete,
la misma funcion de llamada corta que ya usa memory/cortex.py. El
resultado (una descripcion en texto) es lo que vuelve como resultado de
la herramienta, igual que cualquier otra.
"""

import base64
import io

from PIL import ImageGrab

from core.providers import complete
from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Visión de pantalla",
    "description": "Captura la pantalla actual y la interpreta (apps, ventanas, botones, errores).",
}

MAX_DIMENSION = 1280
JPEG_QUALITY = 70


async def _exec_see_screen(arguments: dict) -> str:
    question = arguments.get("question") or "Describe en detalle que se ve en esta captura de pantalla."
    try:
        image = ImageGrab.grab()
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        return f"Error: no pude capturar la pantalla: {exc}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }
    ]
    try:
        return await complete("conversational", messages)
    except Exception as exc:
        return f"Error: no pude interpretar la captura de pantalla: {exc}"


def register() -> None:
    register_tool(Tool(
        name="see_screen",
        description=(
            "Toma una captura de la pantalla actual del usuario y la "
            "interpreta: que apps/ventanas hay abiertas, que texto o "
            "botones se ven, o si hay algun error visible. Usala cuando el "
            "usuario pregunte algo sobre lo que tiene en pantalla, o cuando "
            "necesites ver el estado real de una app para ayudar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Que buscar o responder sobre la pantalla (opcional; por defecto describe todo).",
                },
            },
            "required": [],
        },
        tier="sensitive",
        executor=_exec_see_screen,
        confirm_text=lambda a: "Ver la pantalla actual" + (f": {a['question']}" if a.get("question") else ""),
    ))
