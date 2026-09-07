"""Busqueda semantica de notas: en vez de coincidencia exacta de palabras,
usa el significado (embeddings) para encontrar las notas mas relacionadas
con una consulta. Los vectores viven en memory/atlas.db (tabla notes_vec,
via sqlite-vec) desde la Fase 5 del plan de migracion - antes vivian en un
JSON aparte (memory/vault/.embeddings_cache.json) con coseno calculado a
mano en Python; sqlite-vec hace la busqueda por vecinos mas cercanos y la
distancia coseno directamente en SQL."""

import sqlite_vec

from core.config import model_for_role
from core.providers import embed
from memory.db import connect
from memory.store import Note, list_notes, mark_embedded

# Umbral de similitud coseno para considerar una nota relevante. Es un
# valor empirico, NO una constante universal - distintos modelos de
# embeddings dan escalas de similitud distintas para el mismo par
# consulta/nota (con gemini-embedding-001 una nota claramente relevante
# daba ~0.7-0.8; con Qwen3-Embedding-0.6B via Ollama, la misma clase de
# coincidencia clara dio ~0.58 en pruebas reales - ver
# ATLAS_MIGRATION_PLAN.md Fase 4). Si se cambia el modelo de embeddings
# (config/settings.json, rol "embeddings"), conviene volver a medir un par
# consulta/nota conocido antes de asumir que este valor sigue sirviendo.
MIN_SCORE = 0.5


def _note_text(note: Note) -> str:
    return f"{note.title}\n{note.content}"


async def _ensure_embedded(notes: list[Note], model: str) -> None:
    """Calcula y guarda el vector de cualquier nota que no tenga uno
    calculado con el modelo de embeddings actual - solo se manda a
    embeber lo nuevo, igual que antes (cuando esto vivia en un cache JSON)."""
    pending = [n for n in notes if n.embedding_model != model]
    if not pending:
        return

    vectors = await embed("embeddings", [_note_text(n) for n in pending])
    with connect() as conn:
        for note, vector in zip(pending, vectors):
            conn.execute(
                "INSERT OR REPLACE INTO notes_vec (note_id, embedding) VALUES (?, ?)",
                (note.id, sqlite_vec.serialize_float32(vector)),
            )
    for note in pending:
        mark_embedded(note.id, model)


async def semantic_search(query: str, limit: int = 3) -> list[Note]:
    """Busca notas por significado, no por palabra exacta, usando
    embeddings."""
    notes = list_notes()
    if not notes:
        return []

    model = model_for_role("embeddings")
    await _ensure_embedded(notes, model)

    query_vector = (await embed("embeddings", [query]))[0]

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT note_id, distance FROM notes_vec
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (sqlite_vec.serialize_float32(query_vector), len(notes)),
        ).fetchall()

    notes_by_id = {n.id: n for n in notes}
    scored = []
    for row in rows:
        score = 1 - row["distance"]  # distance_metric=cosine -> distance = 1 - similitud
        if score >= MIN_SCORE:
            note = notes_by_id.get(row["note_id"])
            if note is not None:
                scored.append((score, note))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [note for _, note in scored[:limit]]
