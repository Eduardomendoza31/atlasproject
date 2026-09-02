import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent / "vault"
VAULT_DIR.mkdir(exist_ok=True)

LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
WORD_PATTERN = re.compile(r"[a-záéíóúñü0-9]+")
STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "un", "una", "y", "o", "a",
    "en", "que", "es", "por", "para", "con", "se", "su", "sus", "lo",
    "me", "mi", "tu", "te", "le", "les", "como", "qué", "cómo",
}


@dataclass
class Note:
    path: Path
    title: str
    created: str
    tags: list[str]
    content: str

    @property
    def links(self) -> list[str]:
        return LINK_PATTERN.findall(self.content)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9áéíóúñü\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:60] or "nota"


def save_note(title: str, content: str, tags: list[str] | None = None) -> Path:
    """Guarda una nota nueva en el vault y devuelve su ruta."""
    tags = tags or []
    now = datetime.now()
    filename = f"{now.strftime('%Y-%m-%d')}_{_slugify(title)}.md"
    path = VAULT_DIR / filename
    counter = 2
    while path.exists():
        path = VAULT_DIR / f"{now.strftime('%Y-%m-%d')}_{_slugify(title)}-{counter}.md"
        counter += 1

    frontmatter = (
        "---\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        f"tags: [{', '.join(tags)}]\n"
        "---\n\n"
    )
    path.write_text(f"{frontmatter}# {title}\n\n{content}\n", encoding="utf-8")
    return path


def _parse_note(path: Path) -> Note:
    raw = path.read_text(encoding="utf-8")
    created = ""
    tags: list[str] = []
    body = raw

    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            frontmatter = raw[3:end]
            body = raw[end + 3:].strip()
            for line in frontmatter.splitlines():
                if line.startswith("created:"):
                    created = line.split(":", 1)[1].strip()
                elif line.startswith("tags:"):
                    raw_tags = line.split(":", 1)[1].strip().strip("[]")
                    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    title = path.stem
    if body.startswith("#"):
        first_line, _, rest = body.partition("\n")
        title = first_line.lstrip("#").strip()
        body = rest.strip()

    return Note(path=path, title=title, created=created, tags=tags, content=body)


def list_notes() -> list[Note]:
    return [_parse_note(p) for p in sorted(VAULT_DIR.glob("*.md"))]


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
    """Busqueda simple por coincidencia de palabras. Suficiente para el
    tamano de vault de un solo usuario; se puede cambiar por busqueda
    vectorial mas adelante sin tocar el resto del sistema."""
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
