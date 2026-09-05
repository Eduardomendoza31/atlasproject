"""Loop de turno con herramientas: llama al modelo, y si pide usar una
herramienta la ejecuta (o pide confirmacion antes, segun su nivel de
riesgo) y le devuelve el resultado, repitiendo hasta que el modelo
responda con texto normal.

No sabe nada de websockets ni de FastAPI - core/app.py es quien traduce
los eventos que este modulo produce a mensajes concretos para el
cliente, y quien implementa el callback de confirmacion."""

import json
from collections.abc import AsyncIterator
from typing import Awaitable, Callable

from core.providers import stream_agent_turn
from core.tools import Tool, all_tool_schemas, get_tool

MAX_TOOL_ROUNDTRIPS = 6

# (tool_call_id, tool, arguments) -> aprobado?
ConfirmCallback = Callable[[str, Tool, dict], Awaitable[bool]]


async def run_agent_turn(
    role: str, messages: list[dict], confirm: ConfirmCallback
) -> AsyncIterator[dict]:
    """Corre un turno completo, incluyendo cualquier ida-y-vuelta con
    herramientas. `messages` se muta en el lugar (se le agregan los
    mensajes "assistant"/"tool" reales) para que el llamador se quede
    con exactamente lo que el modelo vio.

    Emite:
      {"type": "text", "text": str}
      {"type": "tool_call", "id", "name", "arguments"}
      {"type": "tool_confirm_needed", "id", "name", "tier", "description"}
      {"type": "tool_result", "id", "name", "result", "denied"}
      {"type": "turn_done", "final_text": str}
    """
    tools_schema = all_tool_schemas()
    full_text_this_turn = ""

    for _ in range(MAX_TOOL_ROUNDTRIPS):
        pending_tool_calls: list[dict] = []
        assistant_text = ""

        async for event in stream_agent_turn(role, messages, tools_schema):
            if event["type"] == "text":
                assistant_text += event["text"]
                full_text_this_turn += event["text"]
                yield {"type": "text", "text": event["text"]}
            else:
                pending_tool_calls.append(event)
                yield event

        if not pending_tool_calls:
            messages.append({"role": "assistant", "content": assistant_text})
            yield {"type": "turn_done", "final_text": full_text_this_turn}
            return

        messages.append({
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in pending_tool_calls
            ],
        })

        for tc in pending_tool_calls:
            tool = get_tool(tc["name"])
            if tool is None:
                result = f"Error: herramienta desconocida '{tc['name']}'."
                denied = False
            elif tool.tier != "safe":
                yield {
                    "type": "tool_confirm_needed",
                    "id": tc["id"],
                    "name": tool.name,
                    "tier": tool.tier,
                    "description": tool.confirm_text(tc["arguments"]),
                }
                approved = await confirm(tc["id"], tool, tc["arguments"])
                if approved:
                    result = await tool.executor(tc["arguments"])
                    denied = False
                else:
                    result = "El usuario denego el permiso para ejecutar esta herramienta."
                    denied = True
            else:
                result = await tool.executor(tc["arguments"])
                denied = False

            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            yield {
                "type": "tool_result",
                "id": tc["id"],
                "name": tc["name"],
                "result": result,
                "denied": denied,
            }

    # Se agoto el limite de idas-y-vueltas: se le pide al modelo una
    # respuesta final sin mas herramientas, para no dejar el turno colgado.
    messages.append({
        "role": "system",
        "content": (
            "Se alcanzo el limite de pasos con herramientas. Responde "
            "ahora con lo que ya sabes, sin usar mas herramientas."
        ),
    })
    async for event in stream_agent_turn(role, messages, tools=[]):
        if event["type"] == "text":
            full_text_this_turn += event["text"]
            yield {"type": "text", "text": event["text"]}
    messages.append({"role": "assistant", "content": full_text_this_turn})
    yield {"type": "turn_done", "final_text": full_text_this_turn}
