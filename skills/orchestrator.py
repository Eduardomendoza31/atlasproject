"""Skill: delegación a agentes especializados (patrón "supervisor" -
ver core/subagents.py para el porqué de este patrón y las guardas de
seguridad).

Esta skill solo registra el ESQUEMA de la herramienta delegate_to_agent
para que el modelo sepa que existe y qué especialistas hay disponibles.
La ejecución real NO pasa por el executor de abajo - core/agent.py
intercepta el nombre "delegate_to_agent" antes del despacho genérico de
herramientas, porque delegar implica correr un sub-turno completo del
agente especializado (con sus propios tool_call/confirmaciones/
resultados), no una sola llamada de función como el resto. El executor
de acá es solo una red de seguridad por si alguna vez se llamara fuera
de ese camino esperado.
"""

from core.agent import DELEGATE_TOOL_NAME
from core.subagents import list_subagents
from core.tools import Tool, register as register_tool

SKILL = {
    "name": "Orquestación de agentes",
    "description": "Delega sub-tareas puntuales a agentes especializados (Programador, Investigador, Documentos, Organizador).",
}


async def _exec_delegate_to_agent(_arguments: dict) -> str:
    return "Error interno: la delegación debería haber sido manejada por el loop del agente, no por este executor."


def register() -> None:
    agents = list_subagents()
    agent_list = "\n".join(f"- {a.key}: {a.description}" for a in agents)
    register_tool(Tool(
        name=DELEGATE_TOOL_NAME,
        description=(
            "Delega una sub-tarea puntual y bien definida a un agente "
            "especializado, cuando eso da mejor resultado que resolverlo "
            "vos mismo con tus herramientas generales (por ejemplo, una "
            "tarea de programación completa, o crear un documento). "
            "Agentes disponibles:\n"
            f"{agent_list}\n"
            "El agente delegado no puede volver a delegar. Úsalo para una "
            "tarea completa y específica, no para pasos sueltos - para "
            "cosas simples, usa tus propias herramientas directamente. "
            "Cuando el agente termine, te devuelve su resultado para que "
            "se lo comuniques al usuario."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": [a.key for a in agents],
                    "description": "A qué agente especializado delegar.",
                },
                "task": {
                    "type": "string",
                    "description": "La tarea completa y específica a realizar, con todo el contexto que el agente necesita (no la ve el resto de la conversación).",
                },
            },
            "required": ["agent", "task"],
        },
        tier="safe",
        executor=_exec_delegate_to_agent,
        confirm_text=lambda a: f"Delegar a {a.get('agent')}",
    ))
