"""Busqueda hibrida sobre la memoria de notas: combina la busqueda
semantica (memory/semantic.py, por significado) y la busqueda por palabras
clave (memory/store.py, por coincidencia exacta) en un unico ranking, en
vez de usar una sola de las dos segun si la otra fallo o no - que es como
funcionaba antes de la Fase 6 del plan de migracion (ver
ATLAS_MIGRATION_PLAN.md).

Se combinan por RANGO (Reciprocal Rank Fusion), no sumando puntajes: sumar
un coseno semantico (~0-1) con un conteo de palabras en comun (~0-N) no
tiene sentido sin normalizar cada escala por separado, y la Fase 4 ya
mostro en la practica que ni siquiera dos modelos de embeddings distintos
comparten la misma escala de puntaje (ver memory/semantic.py, MIN_SCORE).
RRF no le importa el valor del puntaje, solo en que POSICION quedo cada
nota en cada lista - sigue siendo valido sin importar que proveedor de
embeddings este activo, incluso si el dia de mañana cambia."""

from memory.semantic import semantic_search
from memory.store import Note, search_notes

# Constante estandar de Reciprocal Rank Fusion (asi se usa practicamente
# siempre en la literatura de recuperacion de informacion - no es un valor
# ajustado a mano para este proyecto en particular).
RRF_K = 60

# Cuantos candidatos pedirle a CADA busqueda antes de fusionar - mas que el
# `limit` final para que una nota que aparece bien rankeada en una lista
# pero no en la otra igual tenga chance de entrar en el resultado combinado.
CANDIDATE_POOL = 10


async def hybrid_search(query: str, limit: int = 3) -> list[Note]:
    try:
        semantic_results = await semantic_search(query, limit=CANDIDATE_POOL)
    except Exception as exc:
        print(f"[Búsqueda] Falló la búsqueda semántica, sigo solo con palabras clave: {exc}", flush=True)
        semantic_results = []

    keyword_results = search_notes(query, limit=CANDIDATE_POOL)

    scores: dict[int, float] = {}
    notes_by_id: dict[int, Note] = {}
    for ranked_list in (semantic_results, keyword_results):
        for rank, note in enumerate(ranked_list, start=1):
            scores[note.id] = scores.get(note.id, 0.0) + 1 / (RRF_K + rank)
            notes_by_id[note.id] = note

    ranked_ids = sorted(scores, key=lambda note_id: scores[note_id], reverse=True)
    return [notes_by_id[note_id] for note_id in ranked_ids[:limit]]
