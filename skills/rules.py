"""Skill: aprendizaje de reglas enseñadas por el usuario.

Distinta a proposito del guardado automatico de memory/cortex.py: el
cortex decide solo, sin preguntar, si un HECHO puntual vale la pena
recordar ("el usuario dijo que trabaja en X"). Esta skill es para
REGLAS de comportamiento futuro que el usuario ensena explicitamente
("los PDF que descargo van a la carpeta Documentacion") - y a
diferencia del cortex, nunca se guardan sin que el usuario lo apruebe
de forma explicita.

Ese "preguntar antes de guardar" no necesita interfaz nueva: la
herramienta es tier "sensitive", asi que ya pasa por la misma
confirmacion Permitir/Denegar que cualquier otra accion sensible - el
texto de esa confirmacion ES la pregunta "¿quieres que recuerde esta
regla?", y si el usuario denegara, la regla nunca se guarda.
"""

from memory.cortex import RULE_TAG
from memory.store import list_notes_by_tag, save_note
from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Reglas aprendidas",
    "description": "Guarda preferencias o reglas que el usuario enseña para que Atlas las siga siempre, con su aprobación explícita.",
}


async def _exec_remember_rule(arguments: dict) -> str:
    try:
        title = arguments["title"]
        rule = arguments["rule"]
        save_note(title, rule, tags=[RULE_TAG])
    except Exception as exc:
        return f"Error: no pude guardar la regla: {exc}"
    return f"Regla guardada: '{title}' — {rule}"


async def _exec_list_rules(_arguments: dict) -> str:
    rules = list_notes_by_tag(RULE_TAG)
    if not rules:
        return "No hay reglas guardadas todavía."
    return "\n".join(f"- {r.title}: {r.content}" for r in rules)


def register() -> None:
    register_tool(Tool(
        name="remember_rule",
        description=(
            "Propone guardar una REGLA o preferencia de comportamiento que "
            "el usuario acaba de enseñar para que Atlas la siga siempre en "
            "el futuro (por ejemplo 'los PDF que descargue van a la carpeta "
            "Documentación', o 'cuando te pida un resumen, hazlo de máximo "
            "3 líneas'). NO uses esto para un dato puntual de una sola vez "
            "(eso ya se guarda solo, sin preguntar) - solo para algo que "
            "debe aplicar de ahí en adelante. Al usuario se le pedirá "
            "confirmación explícita antes de guardarla."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título corto de la regla."},
                "rule": {"type": "string", "description": "La regla completa, como debe aplicarse."},
            },
            "required": ["title", "rule"],
        },
        tier="sensitive",
        executor=_exec_remember_rule,
        confirm_text=lambda a: f"¿Quieres que recuerde esta regla siempre?: {a.get('rule')}",
    ))

    register_tool(Tool(
        name="list_rules",
        description="Lista las reglas o preferencias que el usuario le ha pedido a Atlas que siga siempre.",
        parameters={"type": "object", "properties": {}, "required": []},
        tier="safe",
        executor=_exec_list_rules,
        confirm_text=lambda a: "Listar reglas guardadas",
    ))
