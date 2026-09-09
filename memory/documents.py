"""Base de conocimiento documental: indexar un documento del PC (PDF, Word,
Excel, CSV, PowerPoint, HTML, imagen o texto plano) para que Atlas pueda
consultarlo despues por su cuenta, citando de que archivo y de que parte
del archivo salio cada dato (Fase 6 del plan de migracion - ver
ATLAS_MIGRATION_PLAN.md).

Hasta ahora Atlas podia LEER un documento (Fase 3, core/documents/) pero
solo si el usuario le pedia explicitamente ese archivo en ese momento: el
texto entraba al turno y se perdia al terminar. Aca ese texto se parte en
fragmentos y se guarda en memory/atlas.db (tablas `documents`, `chunks` y
`chunks_vec`), que es lo que convierte "leer un archivo" en "tener una base
de conocimiento".

El corte en fragmentos respeta primero los marcadores de posicion que ya
generan los extractores de la Fase 3 (`--- Pagina 3 ---`, `--- Hoja: Ventas
---`, `--- Diapositiva 2 ---`): un fragmento nunca cruza de una pagina a
otra, para que la cita de la fuente sea exacta y no aproximada. Recien
dentro de cada pagina/hoja se corta por tamaño.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.documents import can_extract, extract_text
from memory.db import DEFAULT_TENANT_ID, DEFAULT_USER_ID, connect
from memory.store import _tokenize

# Tamaño objetivo de cada fragmento, en caracteres. Es un compromiso entre
# dos cosas que se contradicen: un fragmento chico da una cita precisa y un
# vector mas "puro" (habla de un solo tema), pero uno demasiado chico pierde
# el contexto que hace falta para que la respuesta se entienda sola. ~1200
# caracteres son ~2-3 parrafos, y quedan muy por debajo del limite de tokens
# por texto del modelo de embeddings.
CHUNK_CHARS = 1200

# Cuanto del final de un fragmento se repite al principio del siguiente, para
# que una frase partida justo en el corte siga siendo encontrable entera en
# alguno de los dos. Como ese solape se agrega ANTES de empezar a llenar el
# fragmento nuevo, un fragmento puede llegar a CHUNK_CHARS + OVERLAP_CHARS en
# el peor caso - sigue muy por debajo del limite del modelo de embeddings, no
# vale la pena complicar el corte para ahorrar esos 150 caracteres.
OVERLAP_CHARS = 150

# Los marcadores que insertan los extractores de core/documents/extractors.py.
LOCATION_PATTERN = re.compile(r"^---\s+(Página\s+\d+|Hoja:\s*.+|Diapositiva\s+\d+)\s+---$")

# Extensiones que no pasan por core/documents (no hay nada que "extraer", ya
# son texto plano) pero que igual tiene sentido poder indexar.
PLAIN_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".xml", ".log", ".py"}


@dataclass
class Document:
    id: int
    path: str
    title: str
    size_bytes: int
    mtime: str
    indexed_at: str
    chunk_count: int = 0


@dataclass
class Chunk:
    id: int
    document_id: int
    ordinal: int
    location: str | None
    content: str
    embedding_model: str | None
    document_title: str
    document_path: str

    @property
    def source(self) -> str:
        """Como se cita este fragmento: 'informe.pdf, Página 3'."""
        return f"{self.document_title}, {self.location}" if self.location else self.document_title


def _row_to_document(row) -> Document:
    keys = row.keys()
    return Document(
        id=row["id"],
        path=row["path"],
        title=row["title"],
        size_bytes=row["size_bytes"],
        mtime=row["mtime"],
        indexed_at=row["indexed_at"],
        chunk_count=row["chunk_count"] if "chunk_count" in keys else 0,
    )


def _row_to_chunk(row) -> Chunk:
    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        location=row["location"],
        content=row["content"],
        embedding_model=row["embedding_model"],
        document_title=row["title"],
        document_path=row["path"],
    )


# --- Corte en fragmentos ----------------------------------------------------

def _sections(text: str) -> list[tuple[str | None, str]]:
    """Parte el texto extraido por los marcadores de posicion. Todo lo que
    aparece antes del primer marcador (o todo el texto, si ese formato no
    genera marcadores) queda como una seccion sin ubicacion."""
    sections: list[tuple[str | None, list[str]]] = []
    current_location: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        match = LOCATION_PATTERN.match(line.strip())
        if match is None:
            current_lines.append(line)
            continue
        if current_lines:
            sections.append((current_location, current_lines))
        current_location = re.sub(r"\s+", " ", match.group(1)).strip()
        current_lines = []

    if current_lines:
        sections.append((current_location, current_lines))

    result = []
    for location, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            result.append((location, body))
    return result


def _units(body: str) -> list[str]:
    """Unidades que conviene no partir por la mitad: parrafos; si un parrafo
    solo ya pasa el tamaño de fragmento, sus lineas (una hoja de Excel es una
    linea por fila, por ejemplo); y si una linea sola tambien lo pasa (tipico
    de un PDF que extrae una pagina entera sin saltos), corte duro."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= CHUNK_CHARS:
            units.append(paragraph)
            continue
        for line in paragraph.splitlines():
            line = line.strip()
            if not line:
                continue
            while len(line) > CHUNK_CHARS:
                units.append(line[:CHUNK_CHARS])
                line = line[CHUNK_CHARS:]
            if line:
                units.append(line)
    return units


def _overlap_tail(chunk: str) -> str:
    """El final del fragmento anterior con el que arranca el siguiente,
    recortado hasta el primer espacio para no empezar a mitad de palabra."""
    if len(chunk) <= OVERLAP_CHARS:
        return chunk
    tail = chunk[-OVERLAP_CHARS:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def split_into_chunks(text: str) -> list[tuple[str | None, str]]:
    """(ubicacion, contenido) por fragmento, en orden de lectura."""
    chunks: list[tuple[str | None, str]] = []
    for location, body in _sections(text):
        current = ""
        for unit in _units(body):
            if current and len(current) + 1 + len(unit) > CHUNK_CHARS:
                chunks.append((location, current))
                current = _overlap_tail(current)
            current = f"{current}\n{unit}" if current else unit
        if current.strip():
            chunks.append((location, current))
    return chunks


# --- Indexado ---------------------------------------------------------------

def _read_source_text(path: Path) -> str:
    if can_extract(path):
        return extract_text(path)
    if path.suffix.lower() in PLAIN_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(
        f"No se puede indexar '{path.name}': no es un documento que Atlas sepa leer "
        f"(soportados: PDF, Word, Excel, CSV, PowerPoint, HTML, imágenes y texto plano)."
    )


async def index_document(path: Path) -> Document:
    """Extrae, parte y guarda un documento. Si ya estaba indexado, lo
    reemplaza entero (mas simple y mas seguro que intentar detectar que
    fragmentos cambiaron: un documento reeditado puede correr todas sus
    paginas de lugar). No calcula los vectores - de eso se encarga
    memory/semantic.py, igual que con las notas."""
    # La extraccion es sincronica y puede tardar mucho (un PDF escaneado con
    # OCR son varios segundos por pagina): va a un hilo aparte para no
    # congelar el event loop, que es el que atiende el websocket de la UI.
    text = await asyncio.to_thread(_read_source_text, path)
    if not text.strip():
        raise ValueError(f"'{path.name}' no tiene texto que indexar (¿está vacío?).")

    chunks = split_into_chunks(text)
    if not chunks:
        raise ValueError(f"'{path.name}' no produjo ningún fragmento indexable.")

    stat = path.stat()
    now = datetime.now().isoformat(timespec="seconds")
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    absolute = str(path.resolve())

    forget_document(absolute)
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (user_id, tenant_id, path, title, size_bytes, mtime, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (DEFAULT_USER_ID, DEFAULT_TENANT_ID, absolute, path.name, stat.st_size, mtime, now),
        )
        document_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (document_id, ordinal, location, content) VALUES (?, ?, ?, ?)",
            [(document_id, i, location, content) for i, (location, content) in enumerate(chunks)],
        )

    return Document(
        id=document_id, path=absolute, title=path.name, size_bytes=stat.st_size,
        mtime=mtime, indexed_at=now, chunk_count=len(chunks),
    )


def forget_document(path: str) -> bool:
    """Borra un documento indexado, sus fragmentos y sus vectores. Devuelve
    False si no estaba indexado."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM documents WHERE path = ?", (str(path),)).fetchone()
        if row is None:
            return False
        document_id = row["id"]
        chunk_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        # chunks_vec es una tabla virtual (vec0): no la alcanza ninguna
        # cascada de SQLite, hay que vaciarla a mano fila por fila.
        conn.executemany("DELETE FROM chunks_vec WHERE chunk_id = ?", [(i,) for i in chunk_ids])
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return True


def list_documents() -> list[Document]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT d.*, COUNT(c.id) AS chunk_count
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id ORDER BY d.indexed_at DESC
            """
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def find_document(path: str) -> Document | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT d.*, COUNT(c.id) AS chunk_count
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.path = ? GROUP BY d.id
            """,
            (str(path),),
        ).fetchone()
    return _row_to_document(row) if row and row["id"] is not None else None


_CHUNK_SELECT = """
    SELECT c.id, c.document_id, c.ordinal, c.location, c.content, c.embedding_model,
           d.title, d.path
    FROM chunks c JOIN documents d ON d.id = c.document_id
"""


def list_chunks() -> list[Chunk]:
    with connect() as conn:
        rows = conn.execute(_CHUNK_SELECT + " ORDER BY c.document_id, c.ordinal").fetchall()
    return [_row_to_chunk(r) for r in rows]


def chunks_by_ids(chunk_ids: list[int]) -> dict[int, Chunk]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    with connect() as conn:
        rows = conn.execute(
            _CHUNK_SELECT + f" WHERE c.id IN ({placeholders})", chunk_ids
        ).fetchall()
    return {r["id"]: _row_to_chunk(r) for r in rows}


def mark_chunks_embedded(chunk_ids: list[int], model: str) -> None:
    with connect() as conn:
        conn.executemany(
            "UPDATE chunks SET embedding_model = ? WHERE id = ?",
            [(model, chunk_id) for chunk_id in chunk_ids],
        )


# Cuantas palabras de la consulta tiene que compartir un fragmento para que
# cuente como coincidencia por palabras clave. Con una nota alcanza con una
# (son textos cortos que el usuario mismo dicto), pero un documento largo
# tiene miles de palabras y una sola coincidencia suelta es ruido casi
# siempre - y ese ruido se inyectaria en CADA turno via relevant_context.
MIN_KEYWORD_MATCHES = 2


def search_chunks(query: str, limit: int = 3) -> list[Chunk]:
    """Busqueda por palabras clave sobre los fragmentos indexados (la mitad
    no-semantica de la busqueda hibrida)."""
    query_words = _tokenize(query)
    if not query_words:
        return []
    required = min(MIN_KEYWORD_MATCHES, len(query_words))

    scored = []
    for chunk in list_chunks():
        score = len(query_words & _tokenize(chunk.content))
        if score >= required:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]
