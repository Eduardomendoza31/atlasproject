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
from core.subagents import get_subagent
from core.tools import Tool, all_tool_schemas, get_tool

MAX_TOOL_ROUNDTRIPS = 10

DELEGATE_TOOL_NAME = "delegate_to_agent"

# (tool_call_id, tool, arguments) -> aprobado?
ConfirmCallback = Callable[[str, Tool, dict], Awaitable[bool]]


async def run_agent_turn(
    role: str,
    messages: list[dict],
    confirm: ConfirmCallback,
    allowed_tools: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Corre un turno completo, incluyendo cualquier ida-y-vuelta con
    herramientas. `messages` se muta en el lugar (se le agregan los
    mensajes "assistant"/"tool" reales) para que el llamador se quede
    con exactamente lo que el modelo vio.

    `allowed_tools` restringe que herramientas ve el modelo en este
    turno - lo usan los agentes especializados (ver core/subagents.py)
    para ver solo las de su dominio. None (el turno principal) ve todas.

    Emite:
      {"type": "text", "text": str}
      {"type": "tool_call", "id", "name", "arguments"}
      {"type": "tool_confirm_needed", "id", "name", "tier", "description"}
      {"type": "tool_result", "id", "name", "result", "denied"}
      {"type": "subagent_call", "id", "agent", "agent_name", "task"}
      {"type": "subagent_result", "id", "agent", "agent_name", "result"}
      {"type": "turn_done", "final_text": str}

    Si el modelo delega en un agente especializado (delegate_to_agent),
    ese sub-turno se corre recursivamente llamando a esta misma funcion
    con las herramientas del especialista - sus propios tool_call/
    tool_confirm_needed/tool_result se re-emiten tal cual hacia arriba
    (el llamador los ve igual que si Atlas los hubiera hecho el mismo),
    envueltos entre un subagent_call/subagent_result para que la interfaz
    pueda mostrar la delegacion con claridad."""
    tools_schema = all_tool_schemas(allowed_tools)
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
            if tc["name"] == DELEGATE_TOOL_NAME:
                async for delegation_event in _run_delegation(role, tc, confirm):
                    yield delegation_event
                    if delegation_event["type"] == "subagent_result":
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": delegation_event["result"],
                        })
                continue

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


async def _run_delegation(
    role: str, tool_call: dict, confirm: ConfirmCallback
) -> AsyncIterator[dict]:
    """Corre la sub-tarea delegada como un turno normal (recursivo) del
    agente especializado, con su propio subconjunto de herramientas.
    Re-emite los eventos de ese sub-turno tal cual (sus propios
    tool_call/tool_confirm_needed/tool_result), envueltos entre un
    subagent_call inicial y un subagent_result final."""
    agent_key = tool_call["arguments"].get("agent", "")
    task = tool_call["arguments"].get("task", "")
    subagent = get_subagent(agent_key)

    if subagent is None:
        yield {
            "type": "subagent_result",
            "id": tool_call["id"],
            "agent": agent_key,
            "agent_name": agent_key,
            "result": f"Error: no existe el agente especializado '{agent_key}'.",
        }
        return

    yield {
        "type": "subagent_call",
        "id": tool_call["id"],
        "agent": subagent.key,
        "agent_name": subagent.name,
        "task": task,
    }

    sub_messages = [
        {"role": "system", "content": subagent.system_prompt},
        {"role": "user", "content": task},
    ]
    sub_final_text = ""
    async for sub_event in run_agent_turn(role, sub_messages, confirm, allowed_tools=subagent.tool_names):
        if sub_event["type"] == "turn_done":
            sub_final_text = sub_event["final_text"]
        else:
            yield sub_event

    yield {
        "type": "subagent_result",
        "id": tool_call["id"],
        "agent": subagent.key,
        "agent_name": subagent.name,
        "result": sub_final_text,
    }
