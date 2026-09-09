"""Conexion compartida a memory/atlas.db para todo lo relacionado con
memoria de notas (Fase 5 del plan de migracion - ver
ATLAS_MIGRATION_PLAN.md). Antes de esto, memory/store.py guardaba cada
nota como un archivo .md suelto en memory/vault/ y memory/semantic.py
cacheaba sus embeddings en un JSON aparte - dos formatos de archivo
distintos para lo que siempre fue el mismo concepto (una nota).

core/projects.py ya usa este mismo archivo (atlas.db) para proyectos/tareas,
con su propia conexion - a proposito NO se unifica el codigo de conexion
entre ambos modulos: SQLite soporta perfectamente que dos modulos abran su
propia conexion al mismo archivo, y proyectos/notas no tienen ninguna razon
real para compartir codigo mas alla del archivo fisico. Lo que si se
comparte, como pide la auditoria ("una sola base para todo"), es JUSTAMENTE
eso: un unico archivo .db, no cinco almacenes distintos.

La Fase 6 sumo a este mismo archivo la base de conocimiento documental
(`documents` + `chunks` + `chunks_vec`): un documento indexado se parte en
fragmentos y cada fragmento guarda de que parte del archivo salio (pagina,
hoja, diapositiva) para poder citar la fuente al responder. Va aca y no en
una base aparte por la misma razon que las notas: la auditoria pide una
sola base para todo.

Los fragmentos NO tienen FOREIGN KEY declarada contra `documents`: SQLite
no las verifica salvo que cada conexion active `PRAGMA foreign_keys=ON`
(por compatibilidad hacia atras viene apagado por defecto), asi que una FK
declarada aca daria una falsa sensacion de integridad. El borrado en
cascada se hace explicito en memory/documents.py, que ademas tiene que
borrar a mano los vectores de `chunks_vec` (una tabla virtual vec0 no
participa de ninguna cascada de SQLite aunque estuviera activada).

`user_id`/`tenant_id` estan en el esquema desde el dia uno con un valor
fijo ("local") aunque hoy nadie los use para filtrar nada - el objetivo es
que una migracion futura a multiusuario (Fase 12-13) sea llenar esas
columnas de verdad, no rediseñar la tabla."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

DB_PATH = Path(__file__).resolve().parent / "atlas.db"

# gemini-embedding-001 (el proveedor activo del rol "embeddings" hoy - ver
# config/settings.json y ATLAS_MIGRATION_PLAN.md Fase 4) produce vectores
# de esta dimension. Un vec0 de sqlite-vec necesita una dimension fija de
# antemano para toda la tabla - si el proveedor de embeddings cambia a un
# modelo con otra dimension (p. ej. Qwen3-Embedding-0.6B da 1024), esta
# tabla hay que recrearla (sqlite-vec rechaza con un error un vector de
# dimension distinta a la declarada, no lo trunca ni lo mezcla en
# silencio), no alcanza con cambiar la config.
EMBEDDING_DIM = 3072

DEFAULT_USER_ID = "local"
DEFAULT_TENANT_ID = "local"


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                tenant_id TEXT NOT NULL DEFAULT 'local',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                embedding_model TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, tenant_id);

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                tenant_id TEXT NOT NULL DEFAULT 'local',
                path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, tenant_id);

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                location TEXT,
                content TEXT NOT NULL,
                embedding_model TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
            """
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING "
            f"vec0(note_id INTEGER PRIMARY KEY, embedding float[{EMBEDDING_DIM}] distance_metric=cosine)"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING "
            f"vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{EMBEDDING_DIM}] distance_metric=cosine)"
        )


init_db()
