"""Proyectos inteligentes (Fase 1 de la evolucion ATLAS V3 pedida por
Eduardo): agrupan una conversacion persistente y tareas bajo un mismo
contexto, para que "Atlas, continúa mi proyecto" funcione de verdad
entre reinicios de la app.

Antes de esto, `history` (ver core/app.py) vivia solo en memoria por
conexion de websocket - se perdia al cerrar Atlas, y no existia ningun
concepto de agrupar cosas por proyecto. Esto es puramente aditivo: sin
un proyecto activo, el comportamiento de Atlas es exactamente el mismo
que antes de esta fase (ver core/app.py, el estado "proyecto activo"
arranca en None).

Se eligio SQLite (modulo sqlite3, viene con Python - cero dependencia
nueva) en vez de seguir usando JSON plano como memory/automations.json,
porque estos datos son genuinamente relacionales (un proyecto tiene
muchos mensajes y tareas) y un archivo JSON de mensajes creceria sin
limite y habria que reescribirlo entero en cada mensaje nuevo. El vault
de memory/store.py y automations.json NO se tocan - siguen funcionando
igual que siempre, esto es un sistema aparte."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "memory" / "atlas.db"


@dataclass
class Project:
    id: str
    name: str
    description: str
    created_at: str


@dataclass
class Task:
    id: str
    project_id: str
    description: str
    status: str
    created_at: str


@contextmanager
def _connect():
    # sqlite3.Connection usada con "with" solo hace commit/rollback,
    # NO cierra la conexion sola (gotcha real del modulo) - sin este
    # wrapper, cada llamada dejaria una conexion abierta para siempre.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
            """
        )


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(id=row["id"], name=row["name"], description=row["description"], created_at=row["created_at"])


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], project_id=row["project_id"], description=row["description"],
        status=row["status"], created_at=row["created_at"],
    )


def create_project(name: str, description: str = "") -> Project:
    project = Project(
        id=uuid.uuid4().hex[:8],
        name=name,
        description=description,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (project.id, project.name, project.description, project.created_at),
        )
    return project


def list_projects() -> list[Project]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [_row_to_project(r) for r in rows]


def get_project(project_id: str) -> Project | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project(row) if row else None


def find_project_by_name(name: str) -> Project | None:
    """Busqueda case-insensitive por nombre exacto - para que el
    usuario pueda decir 'cambia al proyecto Trabajo' sin preocuparse
    por mayusculas."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE LOWER(name) = LOWER(?) LIMIT 1", (name,)
        ).fetchone()
    return _row_to_project(row) if row else None


def append_message(project_id: str, role: str, content) -> None:
    # content puede ser un string plano o una lista multimodal (texto +
    # imagen, ver core/app.py) - se guarda serializado en JSON para
    # soportar ambos casos sin dos columnas distintas.
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (project_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (project_id, role, json.dumps(content, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )


def load_project_history(project_id: str) -> list[dict]:
    """Devuelve los mensajes guardados en el formato que litellm espera
    ({"role", "content"}), listos para usar como `history` en
    core/app.py."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        ).fetchall()
    return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]


def create_task(project_id: str, description: str) -> Task:
    task = Task(
        id=uuid.uuid4().hex[:8],
        project_id=project_id,
        description=description,
        status="pending",
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tasks (id, project_id, description, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (task.id, task.project_id, task.description, task.status, task.created_at),
        )
    return task


def list_tasks(project_id: str) -> list[Task]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at ASC", (project_id,)
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def update_task_status(task_id: str, status: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    return cur.rowcount > 0


init_db()
