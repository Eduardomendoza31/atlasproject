import json
import re
from dataclasses import dataclass
from datetime import datetime

from memory.db import DEFAULT_TENANT_ID, DEFAULT_USER_ID, connect

LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
WORD_PATTERN = re.compile(r"[a-záéíóúñü0-9]+")
STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "un", "una", "y", "o", "a",
    "en", "que", "es", "por", "para", "con", "se", "su", "sus", "lo",
    "me", "mi", "tu", "te", "le", "les", "como", "qué", "cómo",
}


@dataclass
class Note:
    id: int
    user_id: str
    tenant_id: str
    title: str
    content: str
    tags: list[str]
    created_at: str
    updated_at: str
    # Con que modelo se calculo el ultimo vector guardado para esta nota
    # (None si todavia no se embebio nunca) - lo usa memory/semantic.py
    # para saber que notas hay que (re)embeber sin una consulta aparte.
    embedding_model: str | None = None

    @property
    def links(self) -> list[str]:
        return LINK_PATTERN.findall(self.content)


def _row_to_note(row) -> Note:
    return Note(
        id=row["id"],
        user_id=row["user_id"],
        tenant_id=row["tenant_id"],
        title=row["title"],
        content=row["content"],
        tags=json.loads(row["tags"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        embedding_model=row["embedding_model"],
    )


def save_note(title: str, content: str, tags: list[str] | None = None) -> Note:
    """Guarda una nota nueva y la devuelve ya con su id asignado."""
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO notes (user_id, tenant_id, title, content, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (DEFAULT_USER_ID, DEFAULT_TENANT_ID, title, content, json.dumps(tags or []), now, now),
        )
        note_id = cur.lastrowid
    return Note(
        id=note_id, user_id=DEFAULT_USER_ID, tenant_id=DEFAULT_TENANT_ID,
        title=title, content=content, tags=tags or [], created_at=now, updated_at=now,
    )


def mark_embedded(note_id: int, model: str) -> None:
    """Registra con que modelo se acaba de calcular el vector de una nota -
    lo llama memory/semantic.py despues de guardar el vector en notes_vec."""
    with connect() as conn:
        conn.execute("UPDATE notes SET embedding_model = ? WHERE id = ?", (model, note_id))


def list_notes() -> list[Note]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM notes ORDER BY created_at ASC").fetchall()
    return [_row_to_note(r) for r in rows]


def list_notes_by_tag(tag: str) -> list[Note]:
    # El filtro por tag se hace en Python, no en SQL (json_each seria mas
    # "correcto" pero el vault de un solo usuario tiene decenas de notas,
    # no miles - no vale la pena la complejidad de una consulta JSON para
    # esta escala).
    return [n for n in list_notes() if tag in n.tags]


STEM_MIN_LENGTH = 5


def _stem(word: str) -> str:
    """Recorte crudo de sufijos: 'trabajo', 'trabaja' y 'trabajando' caen
    en la misma clave. No es un stemmer de verdad, pero alcanza para que
    la busqueda por palabras no falle solo por la conjugacion del verbo."""
    return word[:STEM_MIN_LENGTH] if len(word) > STEM_MIN_LENGTH else word


def _tokenize(text: str) -> set[str]:
    words = (w for w in WORD_PATTERN.findall(text.lower()) if w not in STOPWORDS)
    return {_stem(w) for w in words}


def search_notes(query: str, limit: int = 3) -> list[Note]:
    """Busqueda simple por coincidencia de palabras. Sirve de respaldo
    cuando la busqueda semantica (memory/semantic.py) no esta disponible."""
    query_words = _tokenize(query)
    if not query_words:
        return []

    scored = []
    for note in list_notes():
        note_words = _tokenize(note.title) | _tokenize(note.content)
        score = len(query_words & note_words)
        if score > 0:
            scored.append((score, note))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [note for _, note in scored[:limit]]
