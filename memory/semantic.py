import hashlib
import json
from pathlib import Path

from core.config import model_for_role
from core.providers import embed
from memory.store import Note, list_notes

CACHE_PATH = Path(__file__).resolve().parent / "vault" / ".embeddings_cache.json"
# Umbral de similitud coseno para considerar una nota relevante. Es un
# valor empirico, NO una constante universal - distintos modelos de
# embeddings dan escalas de similitud distintas para el mismo par
# consulta/nota (con gemini-embedding-001 una nota claramente relevante
# daba ~0.7-0.8; con Qwen3-Embedding-0.6B via Ollama, la misma clase de
# coincidencia clara dio ~0.58 en pruebas reales). Si se cambia el modelo
# de embeddings (config/settings.json, rol "embeddings"), conviene volver
# a medir un par consulta/nota conocido antes de asumir que este valor
# sigue sirviendo.
MIN_SCORE = 0.5


def _hash(text: str, model: str) -> str:
    # El modelo entra en la clave a proposito: dos modelos de embeddings
    # distintos producen vectores de dimension/espacio distintos (Gemini:
    # 3072, Qwen3-Embedding-0.6B via Ollama: 1024) - si la clave fuera solo
    # el contenido, cambiar de proveedor (ver config/settings.json,
    # ATLAS_MIGRATION_PLAN.md Fase 4) mezclaria vectores incompatibles bajo
    # la misma clave y _cosine() los compararia como si fueran
    # comparables, dando una similitud sin sentido en silencio en vez de
    # un error. Con el modelo en la clave, cambiar de proveedor simplemente
    # hace que todo se re-embeba con el nuevo (las entradas viejas quedan
    # sin usar en el cache, no se leen nunca mas).
    return hashlib.sha256(f"{model}::{text}".encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, list[float]]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict[str, list[float]]) -> None:
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _note_text(note: Note) -> str:
    return f"{note.title}\n{note.content}"


async def semantic_search(query: str, limit: int = 3) -> list[Note]:
    """Busca notas por significado, no por palabra exacta, usando
    embeddings. Las notas ya vistas quedan cacheadas en disco - solo se
    manda a embeber lo nuevo mas la consulta actual."""
    notes = list_notes()
    if not notes:
        return []

    model = model_for_role("embeddings")
    cache = _load_cache()
    note_keys = [_hash(_note_text(note), model) for note in notes]
    missing_keys = [key for key in note_keys if key not in cache]
    missing_texts = [
        _note_text(note)
        for note, key in zip(notes, note_keys)
        if key in missing_keys
    ]

    vectors = await embed("embeddings", missing_texts + [query])
    for key, vector in zip(missing_keys, vectors[: len(missing_texts)]):
        cache[key] = vector
    query_vector = vectors[-1]

    if missing_texts:
        _save_cache(cache)

    scored = []
    for note, key in zip(notes, note_keys):
        score = _cosine(cache[key], query_vector)
        if score >= MIN_SCORE:
            scored.append((score, note))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [note for _, note in scored[:limit]]
