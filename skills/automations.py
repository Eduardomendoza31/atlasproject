"""Skill: crear y administrar automatizaciones (tareas programadas o
repetidas). El guardado y el loop que las ejecuta viven en
core/automations.py - esta skill solo expone las herramientas para que
el modelo las use desde una conversacion normal, siguiendo el mismo
patron que cualquier otra skill (ver skills/__init__.py).
"""

from core.automations import (
    create_automation as _create,
    delete_automation as _delete,
    list_automations as _list,
    set_enabled as _set_enabled,
)
from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Automatizaciones",
    "description": "Crea y administra tareas programadas o repetidas (diarias, semanales, o por intervalo).",
}


def _describe_schedule(schedule: dict) -> str:
    """Version en español simple de un horario, para mostrarle al usuario
    en la confirmacion en vez del diccionario tecnico ({'type': ...})."""
    kind = (schedule or {}).get("type")
    if kind == "daily":
        return f"todos los días a las {schedule.get('time', '08:00')}"
    if kind == "weekly":
        dias = {
            "monday": "los lunes", "tuesday": "los martes", "wednesday": "los miércoles",
            "thursday": "los jueves", "friday": "los viernes", "saturday": "los sábados",
            "sunday": "los domingos",
        }
        dia = dias.get(str(schedule.get("weekday", "")).lower(), "cada semana")
        return f"{dia} a las {schedule.get('time', '08:00')}"
    if kind == "interval_minutes":
        return f"cada {schedule.get('minutes', 60)} minutos"
    return "con un horario personalizado"


def _find_description(automation_id: str) -> str:
    """Busca la descripcion en español de una automatizacion por id, para
    no mostrar solo un id sin contexto en la confirmacion."""
    for a in _list():
        if a.id == automation_id:
            return f"'{a.description}'"
    return f"con id {automation_id}"


async def _exec_create_automation(arguments: dict) -> str:
    try:
        description = arguments["description"]
        schedule = arguments["schedule"]
        automation = _create(description, schedule)
    except Exception as exc:
        return f"Error: no pude crear la automatización: {exc}"
    return f"Automatización creada (id {automation.id}): '{description}' con horario {schedule}."


async def _exec_list_automations(_arguments: dict) -> str:
    automations = _list()
    if not automations:
        return "No hay automatizaciones creadas."
    lines = []
    for a in automations:
        estado = "activa" if a.enabled else "pausada"
        ultima = a.last_run or "nunca"
        lines.append(f"[{a.id}] {a.description} — horario: {a.schedule} — {estado} — última ejecución: {ultima}")
    return "\n".join(lines)


async def _exec_delete_automation(arguments: dict) -> str:
    try:
        automation_id = arguments["id"]
    except Exception as exc:
        return f"Error: falta el id de la automatización ({exc})."
    ok = _delete(automation_id)
    return f"Automatización {automation_id} eliminada." if ok else f"No encontré una automatización con id '{automation_id}'."


async def _exec_set_automation_enabled(arguments: dict) -> str:
    try:
        automation_id = arguments["id"]
        enabled = bool(arguments["enabled"])
    except Exception as exc:
        return f"Error: falta el campo {exc} para activar/pausar la automatización."
    ok = _set_enabled(automation_id, enabled)
    if not ok:
        return f"No encontré una automatización con id '{automation_id}'."
    return f"Automatización {automation_id} {'activada' if enabled else 'pausada'}."


def register() -> None:
    register_tool(Tool(
        name="create_automation",
        description=(
            "Crea una tarea programada que Atlas ejecutará solo, sin que el "
            "usuario tenga que pedirla cada vez. Úsala cuando el usuario pida "
            "algo recurrente (diario, semanal, o cada cierto tiempo). Nota "
            "importante: si la tarea requiere una acción sensible o crítica "
            "(escribir archivos, ejecutar comandos), esa parte se omitirá "
            "cuando se ejecute sola porque no hay nadie para confirmarla - "
            "avísale eso al usuario si aplica, no lo prometas sin más."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Qué debe hacer Atlas cuando se ejecute (una instrucción clara, como si el usuario la escribiera en el chat).",
                },
                "schedule": {
                    "type": "object",
                    "description": "Cuándo ejecutarla.",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["daily", "weekly", "interval_minutes"],
                            "description": "'daily' (todos los días a una hora), 'weekly' (un día de la semana a una hora), o 'interval_minutes' (cada N minutos).",
                        },
                        "time": {"type": "string", "description": "Hora en formato HH:MM de 24h, para 'daily'/'weekly'."},
                        "weekday": {"type": "string", "description": "Día de la semana en inglés (monday..sunday), para 'weekly'."},
                        "minutes": {"type": "integer", "description": "Cada cuántos minutos, para 'interval_minutes'."},
                    },
                    "required": ["type"],
                },
            },
            "required": ["description", "schedule"],
        },
        tier="sensitive",
        executor=_exec_create_automation,
        confirm_text=lambda a: (
            f"Crear una tarea que se repita sola: \"{a.get('description')}\", "
            f"{_describe_schedule(a.get('schedule'))}."
        ),
    ))

    register_tool(Tool(
        name="list_automations",
        description="Lista las automatizaciones creadas, su horario y su estado.",
        parameters={"type": "object", "properties": {}, "required": []},
        tier="safe",
        executor=_exec_list_automations,
        confirm_text=lambda a: "Listar automatizaciones",
    ))

    register_tool(Tool(
        name="delete_automation",
        description="Elimina una automatización existente por su id (usa list_automations para ver los ids).",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Id de la automatización."}},
            "required": ["id"],
        },
        tier="sensitive",
        executor=_exec_delete_automation,
        confirm_text=lambda a: f"Eliminar la automatización {_find_description(a.get('id'))}.",
    ))

    register_tool(Tool(
        name="set_automation_enabled",
        description="Activa o pausa una automatización existente sin eliminarla.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Id de la automatización."},
                "enabled": {"type": "boolean", "description": "true para activarla, false para pausarla."},
            },
            "required": ["id", "enabled"],
        },
        tier="sensitive",
        executor=_exec_set_automation_enabled,
        confirm_text=lambda a: (
            f"{'Activar' if a.get('enabled') else 'Pausar'} la automatización "
            f"{_find_description(a.get('id'))}."
        ),
    ))
