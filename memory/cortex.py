from core.providers import complete
from memory.semantic import semantic_search
from memory.store import list_notes_by_tag, save_note, search_notes

RULE_TAG = "regla"

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
pena recordar a largo plazo (datos personales, preferencias, proyectos,
decisiones, hechos).

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
    mas las notas relacionadas con lo que acaba de decir (por
    significado, no por palabra exacta). Si la busqueda semantica falla
    (p. ej. la API de embeddings no responde), cae a busqueda por
    palabras en vez de dejar al modelo sin nada."""
    rules = list_notes_by_tag(RULE_TAG)
    try:
        notes = await semantic_search(user_text)
    except Exception as exc:
        print(f"[Cortex] Fallo la busqueda semantica, uso palabras: {exc}", flush=True)
        notes = search_notes(user_text)

    # Las reglas ya van en su propia seccion - no duplicarlas si tambien
    # salieron en la busqueda semantica.
    rule_paths = {r.path for r in rules}
    notes = [n for n in notes if n.path not in rule_paths]

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
