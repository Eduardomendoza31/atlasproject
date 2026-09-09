from core.providers import complete
from memory.search import hybrid_search, hybrid_search_documents
from memory.store import list_notes_by_tag, save_note

RULE_TAG = "regla"

# Cuantos fragmentos de documentos se inyectan solos en cada turno. Son pocos
# a proposito: cada fragmento son ~1200 caracteres que entran en el prompt de
# TODOS los turnos, y el modelo siempre puede pedir mas con la herramienta
# search_knowledge (skills/knowledge.py) si le hace falta.
DOC_CONTEXT_LIMIT = 2

SAVE_DECISION_PROMPT = """Estas leyendo un turno de una conversacion entre un
usuario y Atlas, su asistente personal.

Tu UNICA fuente de hechos es lo que el USUARIO escribio. Atlas puede
equivocarse, suponer o directamente inventar datos que el usuario nunca dio -
por eso, si algo aparece solo en la respuesta de Atlas y el usuario no lo
confirmo explicitamente en su propio mensaje, NO cuenta como un dato real y
no se guarda. Una pregunta del usuario tampoco cuenta como dato nuevo, sin
importar lo que Atlas haya respondido.

Usuario: {user_text}
Atlas: {assistant_text}

Decide si el usuario dio, en su propio mensaje, algun dato nuevo que valga la
pena recordar a largo plazo (datos personales, proyectos, decisiones, hechos
puntuales de una sola vez).

IMPORTANTE: si lo que el usuario esta haciendo es enseniar una REGLA de
comportamiento futuro para Atlas (algo que debe aplicar siempre de ahi en
adelante, como "los PDF van a la carpeta X" o "los resumenes hazlos cortos") -
eso NO se guarda aca. Ese flujo es separado (usa confirmacion explicita del
usuario antes de guardarse) y guardarlo tambien aca crearia una nota
duplicada. Si el turno es sobre eso y nada mas, responde NADA.

Si NO hay un dato nuevo confirmado por el usuario, responde exactamente:
NADA

Si SI lo hay, responde exactamente en este formato (una sola nota):
TITULO: <titulo corto, sin comillas>
CONTENIDO: <la nota en 1-3 frases, basada solo en lo que dijo el usuario>"""


async def relevant_context(user_text: str) -> str:
    """Arma el bloque de memoria a inyectar en el turno: las reglas que
    el usuario pidio recordar SIEMPRE van (no dependen de si el mensaje
    actual se parece semanticamente a ellas - una regla como "los PDF
    van a Documentacion" debe aplicar aunque el usuario no diga "PDF"),
    mas las notas relacionadas con lo que acaba de decir segun busqueda
    hibrida (significado + palabras clave combinados, ver
    memory/search.py) - no una sola de las dos como antes -, mas los
    fragmentos de los documentos indexados que hablen de lo mismo (Fase 6:
    la base de conocimiento, ver memory/documents.py).

    Los tres bloques van por separado y etiquetados porque no valen lo
    mismo: una regla es una orden, una nota es algo que Atlas creyo
    entender de una conversacion, y un fragmento es texto textual de un
    documento del usuario - lo unico de los tres que se puede citar como
    fuente."""
    rules = list_notes_by_tag(RULE_TAG)
    notes = await hybrid_search(user_text)
    chunks = await hybrid_search_documents(user_text, limit=DOC_CONTEXT_LIMIT)

    # Las reglas ya van en su propia seccion - no duplicarlas si tambien
    # salieron en la busqueda hibrida.
    rule_ids = {r.id for r in rules}
    notes = [n for n in notes if n.id not in rule_ids]

    blocks = []
    if rules:
        rule_lines = [f"- {r.title}: {r.content}" for r in rules]
        blocks.append(
            "Reglas que el usuario pidió que sigas siempre (aplican aunque "
            "no parezcan relacionadas con el mensaje actual):\n" + "\n".join(rule_lines)
        )
    if notes:
        note_lines = [f"- {n.title}: {n.content}" for n in notes]
        blocks.append("Memoria relevante de conversaciones pasadas:\n" + "\n".join(note_lines))
    if chunks:
        chunk_lines = [f"[{c.source}]\n{c.content}" for c in chunks]
        blocks.append(
            "Fragmentos textuales de documentos que el usuario indexó, por si "
            "sirven para responder. Si usas alguno, cita la fuente que va entre "
            'corchetes (por ejemplo: "según informe.pdf, página 3..."). Si no '
            "tienen que ver con lo que se está hablando, ignóralos y no los "
            "menciones:\n\n" + "\n\n".join(chunk_lines)
        )

    return "\n\n".join(blocks)


async def maybe_save(user_text: str, assistant_text: str) -> str | None:
    """Le pregunta al cortex si el turno merece una nota nueva y, si es
    asi, la guarda. Devuelve el titulo guardado o None."""
    prompt = SAVE_DECISION_PROMPT.format(
        user_text=user_text, assistant_text=assistant_text
    )
    try:
        reply = await complete(
            "memory_cortex",
            [{"role": "user", "content": prompt}],
            max_attempts=6,
        )
    except Exception as exc:
        print(f"[Cortex] Fallo al decidir que guardar: {exc}", flush=True)
        return None

    reply = reply.strip()
    if not reply or reply.upper().startswith("NADA"):
        return None

    title = ""
    content = ""
    for raw_line in reply.splitlines():
        # el modelo a veces agrega markdown (**TITULO:**) o guiones -
        # se limpia para no depender de que el formato salga perfecto.
        line = raw_line.strip().lstrip("-*• ").replace("**", "")
        upper = line.upper()
        if upper.startswith("TITULO:"):
            title = line.split(":", 1)[1].strip()
        elif upper.startswith("CONTENIDO:"):
            content = line.split(":", 1)[1].strip()

    if not title or not content:
        print(f"[Cortex] No pude interpretar la respuesta:\n{reply}", flush=True)
        return None

    save_note(title, content, tags=["conversacion"])
    return title
