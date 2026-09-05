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

RiskTier = str  # "safe" | "sensitive" | "critical"

READ_FILE_MAX_BYTES = 200_000
LIST_DIR_MAX_ENTRIES = 500
WRITE_FILE_MAX_BYTES = 500_000
RUN_COMMAND_TIMEOUT_SECONDS = 30
RUN_COMMAND_MODEL_OUTPUT_CAP = 20_000
RUN_COMMAND_UI_OUTPUT_CAP = 4_000


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


def all_tool_schemas() -> list[dict]:
    """El formato `tools=` que espera litellm (compatible OpenAI)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]


def _resolve_path(raw: str) -> Path:
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
    path = _resolve_path(raw_path)
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
    path = _resolve_path(raw_path)
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
    path = _resolve_path(raw_path)
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
    confirm_text=lambda a: f"Escribir archivo: {a.get('path')} ({len(a.get('content', ''))} caracteres)",
))

register(Tool(
    name="run_command",
    description="Ejecuta un comando de PowerShell en el computador del usuario y devuelve su salida.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando de PowerShell a ejecutar."},
        },
        "required": ["command"],
    },
    tier="critical",
    executor=_exec_run_command,
    confirm_text=lambda a: f"Ejecutar comando: {a.get('command')}",
))
