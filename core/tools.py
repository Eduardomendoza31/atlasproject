"""Registro de herramientas que el modelo puede invocar (function calling).

Cada herramienta tiene un nivel de riesgo que determina si se ejecuta
sola (segura) o si primero hay que pedirle confirmacion al usuario
(sensible/critica) - ver core/agent.py, que es quien de verdad decide
cuando pedir esa confirmacion.

Las funciones ejecutoras nunca lanzan excepciones: atrapan sus propios
errores y devuelven un string describiendolos, porque ese string es lo
que se le manda de vuelta al modelo como resultado de la herramienta, y
el modelo necesita verlo como dato (no como un turno roto) para poder
reaccionar.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from ddgs import DDGS
from ddgs.exceptions import DDGSException

RiskTier = str  # "safe" | "sensitive" | "critical"

READ_FILE_MAX_BYTES = 200_000
LIST_DIR_MAX_ENTRIES = 500
WRITE_FILE_MAX_BYTES = 500_000
RUN_COMMAND_TIMEOUT_SECONDS = 30
RUN_COMMAND_MODEL_OUTPUT_CAP = 20_000
RUN_COMMAND_UI_OUTPUT_CAP = 4_000
WEB_SEARCH_MAX_RESULTS = 5


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    tier: RiskTier
    executor: Callable[[dict], Awaitable[str]]
    confirm_text: Callable[[dict], str]


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def all_tool_schemas(allowed: list[str] | None = None) -> list[dict]:
    """El formato `tools=` que espera litellm (compatible OpenAI).

    `allowed`, si se da, restringe el esquema a esos nombres - lo usan
    los agentes especializados (ver core/subagents.py) para ver solo las
    herramientas de su dominio en vez de las de todo Atlas."""
    tools = TOOLS.values() if allowed is None else (TOOLS[n] for n in allowed if n in TOOLS)
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def resolve_path(raw: str) -> Path:
    """Rutas relativas se resuelven contra la carpeta personal del
    usuario (no la carpeta del proyecto) - es la base mas util para un
    asistente que opera sobre "el PC" en general, no solo sobre si
    mismo. No hay restriccion de "carpeta permitida": la proteccion es
    la confirmacion sensible/critica, que muestra la ruta exacta antes
    de tocar nada."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.home() / path
    return path


async def _exec_read_file(arguments: dict) -> str:
    raw_path = arguments["path"]
    path = resolve_path(raw_path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return f"Error: el archivo '{raw_path}' no existe."
    except IsADirectoryError:
        return f"Error: '{raw_path}' es un directorio, no un archivo."
    except OSError as exc:
        return f"Error: no pude leer '{raw_path}': {exc}"

    truncated = len(data) > READ_FILE_MAX_BYTES
    data = data[:READ_FILE_MAX_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return f"Error: '{raw_path}' parece ser un archivo binario, no se puede leer como texto."

    prefix = f"[archivo truncado a {READ_FILE_MAX_BYTES} bytes]\n" if truncated else ""
    return prefix + text


async def _exec_list_directory(arguments: dict) -> str:
    raw_path = arguments.get("path") or "."
    path = resolve_path(raw_path)
    if not path.exists():
        return f"Error: la carpeta '{raw_path}' no existe."
    if not path.is_dir():
        return f"Error: '{raw_path}' no es una carpeta."
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return f"Error: no pude listar '{raw_path}': {exc}"

    if not entries:
        return "(carpeta vacía)"
    lines = [f"{'[dir] ' if e.is_dir() else ''}{e.name}" for e in entries[:LIST_DIR_MAX_ENTRIES]]
    if len(entries) > LIST_DIR_MAX_ENTRIES:
        lines.append(f"... y {len(entries) - LIST_DIR_MAX_ENTRIES} más (truncado)")
    return "\n".join(lines)


async def _exec_write_file(arguments: dict) -> str:
    raw_path = arguments["path"]
    path = resolve_path(raw_path)
    content = arguments.get("content", "")
    encoded = content.encode("utf-8")
    if len(encoded) > WRITE_FILE_MAX_BYTES:
        return f"Error: el contenido excede el limite de {WRITE_FILE_MAX_BYTES} bytes, no se escribio nada."
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Error: no pude escribir '{raw_path}': {exc}"
    return f"Archivo '{raw_path}' escrito correctamente ({len(encoded)} bytes)."


async def _exec_run_command(arguments: dict) -> str:
    command = arguments["command"]
    # Sin esto, PowerShell manda su salida en la codepage de la consola
    # (no UTF-8) cuando esta redirigida a una tuberia - los acentos y
    # enies salen como caracteres invalidos.
    full_command = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + command
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", full_command,
            cwd=str(Path.home()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return f"Error: no pude iniciar PowerShell: {exc}"

    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(), timeout=RUN_COMMAND_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: el comando tardo mas de {RUN_COMMAND_TIMEOUT_SECONDS}s y fue cancelado."
    except asyncio.CancelledError:
        proc.kill()
        raise

    output = stdout.decode(errors="replace")
    truncated = len(output) > RUN_COMMAND_MODEL_OUTPUT_CAP
    output = output[:RUN_COMMAND_MODEL_OUTPUT_CAP]
    if truncated:
        output += "\n[salida truncada]"
    output += f"\n[exit code: {proc.returncode}]"
    return output


async def _exec_web_search(arguments: dict) -> str:
    query = arguments["query"]
    try:
        # DDGS().text() es sincrono (usa un cliente HTTP normal por
        # debajo) - se corre en un hilo aparte para no bloquear el loop
        # de eventos mientras espera la respuesta de la red.
        results = await asyncio.to_thread(
            lambda: DDGS().text(query, max_results=WEB_SEARCH_MAX_RESULTS)
        )
    except DDGSException as exc:
        return f"Error: la busqueda fallo: {exc}"
    except Exception as exc:
        return f"Error: la busqueda fallo: {exc}"

    if not results:
        return "No se encontraron resultados."

    lines = []
    for i, r in enumerate(results, start=1):
        title = r.get("title", "(sin titulo)")
        href = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"{i}. {title}\n{href}\n{body}")
    return "\n\n".join(lines)


register(Tool(
    name="read_file",
    description="Lee el contenido de un archivo de texto del computador del usuario.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del archivo. Puede ser absoluta o relativa a la carpeta personal del usuario.",
            },
        },
        "required": ["path"],
    },
    tier="safe",
    executor=_exec_read_file,
    confirm_text=lambda a: f"Leer archivo: {a.get('path')}",
))

register(Tool(
    name="list_directory",
    description="Lista los archivos y carpetas dentro de una carpeta del computador del usuario.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta de la carpeta. Puede ser absoluta o relativa a la carpeta personal del usuario. Usa '.' para la carpeta personal.",
            },
        },
        "required": [],
    },
    tier="safe",
    executor=_exec_list_directory,
    confirm_text=lambda a: f"Listar carpeta: {a.get('path', '.')}",
))

register(Tool(
    name="write_file",
    description="Crea o sobrescribe un archivo de texto en el computador del usuario.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del archivo. Puede ser absoluta o relativa a la carpeta personal del usuario.",
            },
            "content": {"type": "string", "description": "Contenido completo a escribir."},
        },
        "required": ["path", "content"],
    },
    tier="sensitive",
    executor=_exec_write_file,
    confirm_text=lambda a: f"Crear/guardar el archivo: {a.get('path')}",
))

register(Tool(
    name="run_command",
    description=(
        "Ejecuta un comando de PowerShell en el computador del usuario y "
        "devuelve su salida. Como esto se le muestra al usuario para que "
        "confirme antes de correr y el usuario puede no saber de "
        "programacion, SIEMPRE incluye tambien 'explicacion': una frase "
        "corta y sin jerga tecnica de que hace el comando y para que, como "
        "se la dirias a alguien que nunca uso una terminal."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando de PowerShell a ejecutar."},
            "explicacion": {
                "type": "string",
                "description": (
                    "Que hace este comando y para que, en una frase simple y "
                    "sin jerga tecnica (nada de nombres de comandos, rutas "
                    "con barras, ni sintaxis) - la va a leer alguien que no "
                    "sabe programar."
                ),
            },
        },
        "required": ["command", "explicacion"],
    },
    tier="critical",
    executor=_exec_run_command,
    confirm_text=lambda a: (
        f"{a.get('explicacion') or 'Ejecutar una acción en tu computador'}"
        f"\n\n🔧 {a.get('command')}"
    ),
))

async def _exec_announce_plan(arguments: dict) -> str:
    # No hace nada por si sola - su unico valor es que sus argumentos
    # (los pasos) le llegan a la interfaz via el evento tool_call, para
    # mostrar el plan ANTES de actuar (transparencia real, no un log
    # armado despues de los hechos).
    steps = arguments.get("steps", [])
    return f"Plan recibido ({len(steps)} paso{'s' if len(steps) != 1 else ''})."


async def _exec_report_outcome(arguments: dict) -> str:
    # Idem: el valor esta en que el modelo declare explicitamente si
    # verifico el resultado, no en que esta funcion "haga" algo.
    return "Resultado registrado."


register(Tool(
    name="announce_plan",
    description=(
        "Anuncia el plan de pasos ANTES de empezar a ejecutar una tarea que "
        "requiere varias acciones sobre el computador (no uses esto para "
        "responder una pregunta simple). Llamala una vez, al principio, con "
        "los pasos concretos que vas a seguir."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista breve de los pasos que vas a ejecutar, en orden.",
            },
        },
        "required": ["steps"],
    },
    tier="safe",
    executor=_exec_announce_plan,
    confirm_text=lambda a: "Anunciar plan",
))

register(Tool(
    name="report_outcome",
    description=(
        "Cierra una tarea de varios pasos informando el resultado real. "
        "Llamala al final, despues de haber verificado el resultado con una "
        "herramienta de lectura (read_file, list_directory, o revisando la "
        "salida/exit code de run_command) - nunca antes de verificar, y "
        "nunca marques verified=true si no comprobaste el resultado de "
        "verdad."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Que se hizo, en una o dos frases."},
            "verified": {
                "type": "boolean",
                "description": "Si de verdad comprobaste el resultado con una herramienta de lectura.",
            },
            "success": {
                "type": "boolean",
                "description": "Si la tarea se completo correctamente segun esa verificacion.",
            },
        },
        "required": ["summary", "verified", "success"],
    },
    tier="safe",
    executor=_exec_report_outcome,
    confirm_text=lambda a: "Informar resultado",
))

register(Tool(
    name="web_search",
    description=(
        "Busca en internet informacion actual o que no sepas con certeza. "
        "Devuelve titulo, url y un fragmento de cada resultado."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Los terminos de busqueda."},
        },
        "required": ["query"],
    },
    tier="safe",
    executor=_exec_web_search,
    confirm_text=lambda a: f"Buscar en internet: {a.get('query')}",
))
