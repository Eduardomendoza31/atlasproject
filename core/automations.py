"""Automatizaciones: tareas programadas o repetidas sin que el usuario
tenga que pedirlas cada vez (parte del area 10 del documento de vision -
"cada viernes...", "cuando se descargue un PDF...", "cada mañana...").

Se guardan en un archivo JSON simple (mismo espiritu "vault" de memory/,
sin base de datos), y un loop de fondo (scheduler_loop) las revisa cada
minuto y corre las que ya tocan.

Una automatizacion corre como un turno normal del agente (el mismo
run_agent_turn que usa el chat en vivo), pero SIN nadie mirando: por
eso cualquier herramienta que no sea "safe" se deniega automaticamente
en vez de pedirle confirmacion a nadie. Esto es una limitacion real y a
proposito, no un descuido - una automatizacion nunca debe poder
escribir archivos o correr comandos sin que un humano lo haya aprobado
en el momento; si la tarea la necesita, se avisa en el resultado en vez
de saltarsela en silencio.
"""

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.agent import run_agent_turn
from core.tools import Tool

STORE_PATH = Path(__file__).resolve().parent.parent / "memory" / "automations.json"
CHECK_INTERVAL_SECONDS = 60


@dataclass
class Automation:
    id: str
    description: str
    schedule: dict
    enabled: bool = True
    created_at: str = ""
    last_run: Optional[str] = None
    last_result: Optional[str] = None


_automations: dict[str, Automation] = {}


def _load() -> None:
    global _automations
    if not STORE_PATH.exists():
        _automations = {}
        return
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        _automations = {a["id"]: Automation(**a) for a in raw}
    except Exception as exc:
        print(f"[Automatizaciones] No se pudo leer '{STORE_PATH.name}': {exc}", flush=True)
        _automations = {}


def _save() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps([asdict(a) for a in _automations.values()], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_automations() -> list[Automation]:
    return list(_automations.values())


def create_automation(description: str, schedule: dict) -> Automation:
    automation = Automation(
        id=uuid.uuid4().hex[:8],
        description=description,
        schedule=schedule,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    _automations[automation.id] = automation
    _save()
    return automation


def delete_automation(automation_id: str) -> bool:
    if automation_id not in _automations:
        return False
    del _automations[automation_id]
    _save()
    return True


def set_enabled(automation_id: str, enabled: bool) -> bool:
    automation = _automations.get(automation_id)
    if automation is None:
        return False
    automation.enabled = enabled
    _save()
    return True


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except Exception:
        return 8, 0


def _is_due(automation: Automation, now: datetime) -> bool:
    schedule = automation.schedule
    kind = schedule.get("type")
    last_run = datetime.fromisoformat(automation.last_run) if automation.last_run else None

    if kind == "interval_minutes":
        minutes = schedule.get("minutes", 60)
        if last_run is None:
            return True
        return (now - last_run).total_seconds() >= minutes * 60

    if kind == "daily":
        hh, mm = _parse_hhmm(schedule.get("time", "08:00"))
        if now.hour != hh or now.minute != mm:
            return False
        return last_run is None or last_run.date() != now.date()

    if kind == "weekly":
        hh, mm = _parse_hhmm(schedule.get("time", "08:00"))
        weekday = str(schedule.get("weekday", "monday")).lower()
        if now.strftime("%A").lower() != weekday:
            return False
        if now.hour != hh or now.minute != mm:
            return False
        return last_run is None or last_run.isocalendar()[:2] != now.isocalendar()[:2]

    return False


async def _run_automation(automation: Automation) -> None:
    print(f"[Automatizaciones] Ejecutando '{automation.description}'", flush=True)

    # Import diferido: core.app importa este modulo para arrancar el
    # scheduler, asi que importar build_system_prompt arriba del todo
    # crearia un ciclo de imports.
    from core.app import build_system_prompt

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": automation.description},
    ]
    denied_tools: list[str] = []

    async def auto_deny(_tool_call_id: str, tool: Tool, _arguments: dict) -> bool:
        denied_tools.append(tool.name)
        return False

    reply_text = ""
    try:
        async for event in run_agent_turn("conversational", messages, auto_deny):
            if event["type"] == "turn_done":
                reply_text = event["final_text"]
    except Exception as exc:
        reply_text = f"Error al ejecutar la automatización: {exc}"

    if denied_tools:
        reply_text += (
            f"\n[Se omitieron herramientas que necesitan confirmación humana: "
            f"{', '.join(denied_tools)}]"
        )

    automation.last_run = datetime.now().isoformat(timespec="seconds")
    automation.last_result = reply_text
    _save()
    print(f"[Automatizaciones] '{automation.description}' -> {reply_text[:200]!r}", flush=True)


async def scheduler_loop() -> None:
    _load()
    while True:
        now = datetime.now()
        for automation in list(_automations.values()):
            if automation.enabled and _is_due(automation, now):
                await _run_automation(automation)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
