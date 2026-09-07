"""Migracion unica del vault viejo (memory/vault/*.md, notas en Markdown
con frontmatter estilo Obsidian) a la tabla `notes` de memory/atlas.db
(Fase 5 del plan de migracion - ver ATLAS_MIGRATION_PLAN.md).

Se corre una sola vez, a mano (mismo patron que core/face_gen.py y
core/documents/setup_ocr.py):

    python -m memory.migrate_vault_to_db

Es idempotente (no duplica si se corre dos veces: se salta si `notes` ya
tiene datos) y NO borra ni toca los archivos .md originales - quedan como
respaldo de lectura, tal como pide la estrategia de rollback del plan de
migracion, hasta confirmar que la nueva tabla funciona bien en uso real."""

import json
from pathlib import Path

from memory.db import DEFAULT_TENANT_ID, DEFAULT_USER_ID, connect

VAULT_DIR = Path(__file__).resolve().parent / "vault"


def _parse_md_note(path: Path) -> dict:
    """Misma logica de parseo que memory/store.py tenia antes de esta
    fase, usada solo aca (ya no hace falta en el codigo que corre en cada
    arranque, la migracion es un evento unico)."""
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

    return {"title": title, "content": body, "tags": tags, "created": created}


def main() -> None:
    with connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
        if existing > 0:
            print(f"[Migración] La tabla 'notes' ya tiene {existing} nota(s) - no se hace nada.")
            print("[Migración] Si de verdad querés re-migrar, vaciá la tabla 'notes' primero.")
            return

        md_files = sorted(VAULT_DIR.glob("*.md"))
        if not md_files:
            print("[Migración] No hay notas .md en el vault - nada que migrar.")
            return

        for path in md_files:
            parsed = _parse_md_note(path)
            created = parsed["created"] or "1970-01-01T00:00:00"
            conn.execute(
                """
                INSERT INTO notes (user_id, tenant_id, title, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    DEFAULT_USER_ID, DEFAULT_TENANT_ID,
                    parsed["title"], parsed["content"],
                    json.dumps(parsed["tags"]),
                    created, created,
                ),
            )
            print(f"[Migración] '{path.name}' -> nota migrada: {parsed['title']!r}")

    print(f"[Migración] Listo - {len(md_files)} nota(s) migradas a memory/atlas.db.")
    print("[Migración] Los archivos .md originales NO se borraron (quedan como respaldo).")


if __name__ == "__main__":
    main()
