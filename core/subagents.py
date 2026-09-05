"""Definiciones de los agentes especializados a los que Atlas (el
agente principal, "orquestador") puede delegar una sub-tarea puntual.

Patron "supervisor" (agentes-como-herramienta): un unico agente con el
que el usuario siempre habla (Atlas), que delega sub-tareas acotadas a
especialistas expuestos como una herramienta mas. Se eligio este patron
en vez de "handoff" (donde el usuario pasa a hablar directo con el
especialista, tipico de sistemas de soporte multi-persona) porque aca
el usuario SIEMPRE le habla a Atlas - nunca directo a un sub-agente -
que es exactamente el caso de uso que la practica actual recomienda
para el patron supervisor sobre el de handoff.

Guardas de seguridad a proposito, no accidentales:
- Ningun sub-agente tiene la propia herramienta delegate_to_agent en su
  lista de herramientas permitidas -> no pueden delegar a su vez. Es un
  guard-rail estructural (el modelo ni siquiera ve la herramienta),
  no solo una instruccion de prompt que se pueda ignorar. Limita toda
  delegacion a un solo salto (la practica recomienda no mas de 2-3, y
  advierte que un sistema multiagente sin guarda de recursion es un
  incidente esperando pasar).
- Cada sub-agente ve solo el subconjunto de herramientas de su
  especialidad (core/tools.py::all_tool_schemas(allowed=...)), no las
  ~20 herramientas de Atlas de golpe - mejora la precision de sus
  decisiones y acota el radio de accion de una delegacion.
- Las llamadas a herramientas sensibles/criticas del sub-agente pasan
  por EL MISMO callback de confirmacion que el turno principal (ver
  core/agent.py) - delegar no es una forma de saltarse permisos, el
  usuario sigue viendo y aprobando cada accion delicada igual que si
  Atlas la hiciera directamente.
"""

from dataclasses import dataclass


@dataclass
class SubAgentDef:
    key: str
    name: str
    description: str
    system_prompt: str
    tool_names: list[str]


_SUBAGENTS: dict[str, SubAgentDef] = {}


def _register(agent: SubAgentDef) -> None:
    _SUBAGENTS[agent.key] = agent


def get_subagent(key: str) -> SubAgentDef | None:
    return _SUBAGENTS.get(key)


def list_subagents() -> list[SubAgentDef]:
    return list(_SUBAGENTS.values())


_register(SubAgentDef(
    key="programador",
    name="Programador",
    description="Escribe, lee, corrige y ejecuta código; corre comandos y verifica resultados reales.",
    system_prompt=(
        "Eres el agente Programador de Atlas, especializado en tareas de "
        "código: leer/escribir archivos de código, ejecutar comandos, "
        "correr y depurar programas. Se te delegó una tarea puntual y "
        "acotada - resuélvela con tus herramientas, verifica el resultado "
        "de verdad (ejecuta o relee lo que cambiaste, no asumas que "
        "funcionó), y termina con una respuesta breve y concreta de lo "
        "que hiciste y el resultado real. No hagas más de lo que se te "
        "pidió."
    ),
    tool_names=["read_file", "write_file", "run_command", "list_directory", "get_system_info"],
))

_register(SubAgentDef(
    key="investigador",
    name="Investigador",
    description="Busca información en internet y la sintetiza; puede revisar la pantalla si hace falta contexto visual.",
    system_prompt=(
        "Eres el agente Investigador de Atlas, especializado en buscar "
        "información real y actual en internet y sintetizarla con "
        "precisión. Se te delegó una pregunta o tema puntual - investígalo "
        "con tus herramientas (nunca inventes datos que no encontraste), y "
        "termina con una respuesta breve, concreta y basada solo en lo que "
        "de verdad encontraste."
    ),
    tool_names=["web_search", "see_screen"],
))

_register(SubAgentDef(
    key="documentos",
    name="Documentos",
    description="Crea documentos reales de Word, Excel, PowerPoint o PDF.",
    system_prompt=(
        "Eres el agente de Documentos de Atlas, especializado en generar "
        "documentos de oficina reales (Word, Excel, PowerPoint, PDF) bien "
        "estructurados. Se te delegó qué documento crear y con qué "
        "contenido - créalo con tus herramientas y termina con una "
        "respuesta breve confirmando qué se creó y dónde."
    ),
    tool_names=[
        "create_word_document", "create_excel_document",
        "create_pdf_document", "create_powerpoint_document",
        "read_file", "write_file",
    ],
))

_register(SubAgentDef(
    key="organizador",
    name="Organizador",
    description="Organiza, mueve, renombra y limpia archivos y carpetas.",
    system_prompt=(
        "Eres el agente Organizador de Atlas, especializado en organizar "
        "archivos y carpetas del computador del usuario: listar, mover, "
        "renombrar, limpiar. Se te delegó una tarea puntual de "
        "organización - resuélvela con tus herramientas, confirma el "
        "resultado real (vuelve a listar para comprobar), y termina con "
        "una respuesta breve de cómo quedó."
    ),
    tool_names=["read_file", "write_file", "list_directory", "run_command"],
))
