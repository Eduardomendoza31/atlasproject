"""Skill: Proyectos inteligentes (Fase 1 de la evolucion ATLAS V3).

Expone las herramientas para crear/listar proyectos y sus tareas, y
para cambiar de proyecto activo por voz o texto ("cambia al proyecto
Trabajo"). El almacenamiento real vive en core/projects.py (SQLite).

switch_project es especial, igual que announce_plan/stop_listening (ver
core/tools.py, core/app.py): su executor no hace nada por si solo -
cambiar cual es la conversacion activa requiere tocar el `history` de
la conexion de websocket en curso, algo a lo que un executor de tool
comun no tiene acceso (solo recibe los argumentos). El cambio real lo
hace core/app.py, interceptando el tool_call por nombre, cuando el
turno actual termina limpio."""

from core.projects import (
    create_project as _create_project,
    create_task as _create_task,
    find_project_by_name,
    list_projects as _list_projects,
    list_tasks as _list_tasks,
    update_task_status,
)
from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Proyectos",
    "description": "Crea y administra proyectos con su propia conversación y tareas, para retomarlos donde quedaron.",
}


async def _exec_create_project(arguments: dict) -> str:
    try:
        name = arguments["name"]
    except Exception as exc:
        return f"Error: falta el nombre del proyecto ({exc})."
    if find_project_by_name(name):
        return f"Ya existe un proyecto llamado '{name}'."
    description = arguments.get("description", "")
    project = _create_project(name, description)
    return f"Proyecto '{project.name}' creado."


async def _exec_list_projects(_arguments: dict) -> str:
    projects = _list_projects()
    if not projects:
        return "No hay proyectos creados todavía."
    return "\n".join(f"- {p.name}" + (f": {p.description}" if p.description else "") for p in projects)


async def _exec_switch_project(arguments: dict) -> str:
    # El cambio real de contexto lo hace core/app.py al terminar el
    # turno (ver docstring de arriba) - esto solo confirma la intencion.
    return f"Cambiando al proyecto '{arguments.get('name', '')}'."


async def _exec_create_task(arguments: dict) -> str:
    try:
        project_name = arguments["project"]
        description = arguments["description"]
    except Exception as exc:
        return f"Error: falta un dato para crear la tarea ({exc})."
    project = find_project_by_name(project_name)
    if not project:
        return f"No encontré ningún proyecto llamado '{project_name}'."
    task = _create_task(project.id, description)
    return f"Tarea agregada a '{project.name}': {task.description}"


async def _exec_list_tasks(arguments: dict) -> str:
    try:
        project_name = arguments["project"]
    except Exception as exc:
        return f"Error: falta indicar el proyecto ({exc})."
    project = find_project_by_name(project_name)
    if not project:
        return f"No encontré ningún proyecto llamado '{project_name}'."
    tasks = _list_tasks(project.id)
    if not tasks:
        return f"El proyecto '{project.name}' no tiene tareas todavía."
    return "\n".join(f"- [{t.status}] {t.description}" for t in tasks)


async def _exec_complete_task(arguments: dict) -> str:
    try:
        project_name = arguments["project"]
        task_description = arguments["task_description"]
    except Exception as exc:
        return f"Error: falta un dato para completar la tarea ({exc})."
    project = find_project_by_name(project_name)
    if not project:
        return f"No encontré ningún proyecto llamado '{project_name}'."
    matches = [t for t in _list_tasks(project.id) if task_description.lower() in t.description.lower()]
    if not matches:
        return f"No encontré ninguna tarea que coincida con '{task_description}' en '{project.name}'."
    update_task_status(matches[0].id, "done")
    return f"Tarea marcada como completada: {matches[0].description}"


def register() -> None:
    register_tool(Tool(
        name="create_project",
        description=(
            "Crea un proyecto nuevo, que agrupa su propia conversación y "
            "tareas para poder retomarlo más tarde con 'continúa mi "
            "proyecto X'. Úsala cuando el usuario pida empezar o crear un "
            "proyecto."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre del proyecto."},
                "description": {"type": "string", "description": "Descripción breve opcional."},
            },
            "required": ["name"],
        },
        tier="safe",
        executor=_exec_create_project,
        confirm_text=lambda a: f"Crear el proyecto '{a.get('name')}'",
    ))

    register_tool(Tool(
        name="list_projects",
        description="Lista los proyectos existentes.",
        parameters={"type": "object", "properties": {}, "required": []},
        tier="safe",
        executor=_exec_list_projects,
        confirm_text=lambda a: "Listar proyectos",
    ))

    register_tool(Tool(
        name="switch_project",
        description=(
            "Cambia el proyecto activo de la conversación (por ejemplo "
            "cuando el usuario dice 'continúa mi proyecto X' o 'cambia al "
            "proyecto Y'). A partir de ahí la conversación sigue con la "
            "memoria/tareas de ese proyecto. El proyecto debe existir "
            "(usa create_project primero si no)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre exacto del proyecto."},
            },
            "required": ["name"],
        },
        tier="safe",
        executor=_exec_switch_project,
        confirm_text=lambda a: f"Cambiar al proyecto '{a.get('name')}'",
    ))

    register_tool(Tool(
        name="create_task",
        description="Agrega una tarea pendiente a un proyecto.",
        parameters={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Nombre del proyecto."},
                "description": {"type": "string", "description": "Qué hay que hacer."},
            },
            "required": ["project", "description"],
        },
        tier="safe",
        executor=_exec_create_task,
        confirm_text=lambda a: f"Agregar tarea a '{a.get('project')}': {a.get('description')}",
    ))

    register_tool(Tool(
        name="list_tasks",
        description="Lista las tareas de un proyecto y su estado.",
        parameters={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Nombre del proyecto."},
            },
            "required": ["project"],
        },
        tier="safe",
        executor=_exec_list_tasks,
        confirm_text=lambda a: f"Listar tareas de '{a.get('project')}'",
    ))

    register_tool(Tool(
        name="complete_task",
        description="Marca una tarea de un proyecto como completada.",
        parameters={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Nombre del proyecto."},
                "task_description": {"type": "string", "description": "Texto que identifique la tarea a completar."},
            },
            "required": ["project", "task_description"],
        },
        tier="safe",
        executor=_exec_complete_task,
        confirm_text=lambda a: f"Marcar tarea completada en '{a.get('project')}'",
    ))
