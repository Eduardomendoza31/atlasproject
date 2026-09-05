"""Skill: informacion del sistema (CPU, RAM, disco).

Primera skill real de Atlas - sirve tambien de ejemplo del patron: este
archivo registra su propia herramienta sin que core/tools.py sepa que
existe. Cualquier skill nueva sigue esta misma forma.
"""

import platform
from pathlib import Path

import psutil

from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Información del sistema",
    "description": "Consulta CPU, memoria y disco del computador en tiempo real.",
}


async def _exec_get_system_info(_arguments: dict) -> str:
    cpu_percent = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.home().anchor)

    def gb(n: int) -> float:
        return round(n / (1024 ** 3), 1)

    return (
        f"CPU: {cpu_percent}% de uso\n"
        f"RAM: {mem.percent}% de uso ({gb(mem.used)} GB de {gb(mem.total)} GB)\n"
        f"Disco ({Path.home().anchor}): {disk.percent}% de uso ({gb(disk.used)} GB de {gb(disk.total)} GB)\n"
        f"Sistema: {platform.system()} {platform.release()}"
    )


def register() -> None:
    register_tool(Tool(
        name="get_system_info",
        description=(
            "Consulta el uso actual de CPU, memoria RAM y disco del "
            "computador del usuario, y la version del sistema operativo."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        tier="safe",
        executor=_exec_get_system_info,
        confirm_text=lambda a: "Consultar información del sistema",
    ))
