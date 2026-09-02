import hashlib
import json
from pathlib import Path

from core.providers import embed
from memory.store import Note, list_notes

CACHE_PATH = Path(__file__).resolve().parent / "vault" / ".embeddings_cache.json"
MIN_SCORE = 0.6


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    cache = _load_cache()
    note_keys = [_hash(_note_text(note)) for note in notes]
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
