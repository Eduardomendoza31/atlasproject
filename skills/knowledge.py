"""Skill: base de conocimiento documental (Fase 6 del plan de migracion).

La diferencia con read_file (core/tools.py): read_file lee un archivo AHORA,
para este turno, y ese texto se pierde cuando termina la conversacion.
Indexar un documento lo guarda partido en fragmentos dentro de la memoria de
Atlas (ver memory/documents.py), asi que a partir de ahi Atlas lo consulta
solo - sin que el usuario tenga que volver a nombrar el archivo - y puede
citar de que documento y de que pagina salio cada dato.

Los fragmentos relevantes ademas se inyectan automaticamente en cada turno
via memory/cortex.py::relevant_context. search_knowledge existe igual para
cuando el modelo necesita buscar algo puntual que no vino en ese bloque
automatico (otra formulacion de la pregunta, mas fragmentos, etc.).
"""

from pathlib import Path

from core.tools import Tool, register as register_tool, resolve_path
from memory.documents import forget_document, index_document, list_documents
from memory.search import hybrid_search_documents
from memory.semantic import embed_pending_chunks

SKILL = {
    "name": "Base de conocimiento",
    "description": "Indexa documentos del computador (PDF, Word, Excel, PowerPoint, CSV, HTML, imágenes) para que Atlas pueda consultarlos después y responder citando la fuente.",
}

# Cuantos fragmentos devuelve una busqueda explicita. Mas que los 2 que se
# inyectan solos en cada turno: si el modelo se tomo el trabajo de llamar a
# la herramienta, es porque el bloque automatico no le alcanzo.
SEARCH_LIMIT = 5


async def _exec_index_document(arguments: dict) -> str:
    raw_path = arguments["path"]
    path = resolve_path(raw_path)

    if not path.exists():
        return f"Error: el archivo '{raw_path}' no existe."
    if path.is_dir():
        return f"Error: '{raw_path}' es una carpeta, no un archivo. Indexa los archivos uno por uno."

    try:
        document = await index_document(path)
    except Exception as exc:
        return f"Error: no pude indexar '{raw_path}': {exc}"

    # Los vectores se calculan aca y no en la primera busqueda para que el
    # costo (una llamada de embeddings por tanda) se pague mientras el
    # usuario sabe que Atlas esta trabajando en el documento, y no despues,
    # colgando una pregunta cualquiera.
    try:
        await embed_pending_chunks()
    except Exception as exc:
        return (
            f"Indexé '{document.title}' en {document.chunk_count} fragmentos, pero no pude "
            f"calcular los vectores de búsqueda semántica ({exc}). Se puede consultar igual "
            f"por palabras clave, y los vectores se reintentan solos en la próxima búsqueda."
        )

    return (
        f"Documento '{document.title}' indexado en {document.chunk_count} fragmentos. "
        f"Ya puedo consultarlo y citar sus páginas."
    )


async def _exec_search_knowledge(arguments: dict) -> str:
    query = arguments["query"]
    try:
        chunks = await hybrid_search_documents(query, limit=SEARCH_LIMIT)
    except Exception as exc:
        return f"Error: falló la búsqueda en los documentos: {exc}"

    if not chunks:
        if not list_documents():
            return "No hay ningún documento indexado todavía (usa index_document para agregar uno)."
        return f"No encontré nada sobre '{query}' en los documentos indexados."

    return "\n\n".join(f"[{c.source}]\n{c.content}" for c in chunks)


async def _exec_list_indexed_documents(_arguments: dict) -> str:
    documents = list_documents()
    if not documents:
        return "No hay documentos indexados todavía."
    return "\n".join(
        f"- {d.title} ({d.chunk_count} fragmentos, indexado el {d.indexed_at[:10]}) — {d.path}"
        for d in documents
    )


async def _exec_forget_document(arguments: dict) -> str:
    raw_path = arguments["path"]
    path = resolve_path(raw_path)
    absolute = str(Path(path).resolve())

    if forget_document(absolute):
        return f"Olvidé el documento '{Path(absolute).name}' (el archivo original sigue en su lugar)."
    return f"'{raw_path}' no estaba indexado, no hay nada que olvidar."


def register() -> None:
    register_tool(Tool(
        name="index_document",
        description=(
            "Agrega un documento del computador del usuario a la base de "
            "conocimiento de Atlas (PDF, Word .docx, Excel .xlsx, CSV, "
            "PowerPoint .pptx, HTML, imágenes o texto plano). A diferencia "
            "de read_file, que solo lo lee para este momento, esto lo deja "
            "guardado: después Atlas puede consultarlo solo y citar de qué "
            "página salió cada dato. Úsalo cuando el usuario pida "
            "'guarda/indexa/aprende este documento' o quiera poder "
            "preguntar sobre él más adelante."
        ),
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
        executor=_exec_index_document,
        confirm_text=lambda a: f"Indexar documento: {a.get('path')}",
    ))

    register_tool(Tool(
        name="search_knowledge",
        description=(
            "Busca información dentro de los documentos que el usuario ya "
            "indexó en la base de conocimiento de Atlas. Devuelve los "
            "fragmentos más relevantes, cada uno con su fuente entre "
            "corchetes (archivo y página/hoja/diapositiva) para que la "
            "cites en tu respuesta. Úsalo cuando el usuario pregunte por "
            "algo que puede estar en sus documentos y el contexto que ya "
            "tienes no alcance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Qué buscar, en lenguaje natural.",
                },
            },
            "required": ["query"],
        },
        tier="safe",
        executor=_exec_search_knowledge,
        confirm_text=lambda a: f"Buscar en documentos: {a.get('query')}",
    ))

    register_tool(Tool(
        name="list_indexed_documents",
        description="Lista los documentos que están indexados en la base de conocimiento de Atlas.",
        parameters={"type": "object", "properties": {}, "required": []},
        tier="safe",
        executor=_exec_list_indexed_documents,
        confirm_text=lambda a: "Listar documentos indexados",
    ))

    register_tool(Tool(
        name="forget_document",
        description=(
            "Quita un documento de la base de conocimiento de Atlas. No "
            "borra el archivo del computador, solo lo que Atlas recordaba "
            "de él."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Ruta del documento indexado, tal como aparece en list_indexed_documents.",
                },
            },
            "required": ["path"],
        },
        tier="sensitive",
        executor=_exec_forget_document,
        confirm_text=lambda a: f"¿Olvido lo que aprendí de este documento?: {a.get('path')}",
    ))
