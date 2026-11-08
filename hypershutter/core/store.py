"""SQLite state in Application Support: ffprobe cache and per-project state.

Cache keys use (file name, size, mtime) and never the absolute path, because the
two "T7" drives swap mount names and organized projects move files between folders.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import unicodedata
from pathlib import Path

from hypershutter.core import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS probe_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT NOT NULL, data TEXT NOT NULL, updated REAL
);
CREATE TABLE IF NOT EXISTS hidden_projects (id TEXT PRIMARY KEY);
"""


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(config.app_support_dir() / "hypershutter.sqlite", timeout=30)
    db.executescript(_SCHEMA)
    return db


def file_key(name: str, size: int, mtime: float) -> str:
    return f"{unicodedata.normalize('NFC', name)}|{size}|{int(mtime)}"


def get_probe(db: sqlite3.Connection, key: str) -> dict | None:
    row = db.execute("SELECT data FROM probe_cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def put_probe(db: sqlite3.Connection, key: str, data: dict) -> None:
    db.execute("INSERT OR REPLACE INTO probe_cache VALUES (?,?,?)", (key, json.dumps(data), time.time()))


def project_id(root: Path) -> str:
    """Identity = normalized folder name, so a re-mounted drive maps to the same project."""
    name = unicodedata.normalize("NFC", root.name).strip()
    return hashlib.sha1(name.encode()).hexdigest()[:16]


def save_project(root: Path, data: dict) -> None:
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?)",
                   (project_id(root), root.name, str(root), json.dumps(data, ensure_ascii=False), time.time()))
        db.execute("DELETE FROM hidden_projects WHERE id=?", (project_id(root),))


def hide_project(root: Path) -> None:
    """Off the list; everything about the project stays and comes back when its folder is opened."""
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO hidden_projects VALUES (?)", (project_id(root),))


def show_project(root: Path) -> None:
    with connect() as db:
        db.execute("DELETE FROM hidden_projects WHERE id=?", (project_id(root),))


def delete_project(root: Path) -> None:
    with connect() as db:
        db.execute("DELETE FROM projects WHERE id=?", (project_id(root),))
        db.execute("DELETE FROM hidden_projects WHERE id=?", (project_id(root),))


def all_project_data() -> list[dict]:
    with connect() as db:
        return [{"id": i, "data": json.loads(d)} for i, d in db.execute("SELECT id, data FROM projects").fetchall()]


def locate(root: str) -> str | None:
    """The event folder now, when its drive mounted under another name ("T7" <-> "T7 1"): the same
    path on another volume. Only that exact path is tested on each volume; nothing is listed."""
    p = Path(root)
    if p.is_dir():
        return str(p)
    parts = p.parts
    if len(parts) > 3 and parts[1] == "Volumes":
        rest = Path(*parts[3:])
        for v in sorted(Path("/Volumes").iterdir()):
            if (v / rest).is_dir():
                return str(v / rest)
    return None


def recent_projects(limit: int = 12, include_hidden: bool = False) -> list[dict]:
    where = "" if include_hidden else "WHERE id NOT IN (SELECT id FROM hidden_projects)"
    with connect() as db:
        rows = db.execute(f"SELECT name, root, updated FROM projects {where} ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
    return [{"name": n, "root": r, "updated": u} for n, r, u in rows]


def load_project(root: Path) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT data FROM projects WHERE id=?", (project_id(root),)).fetchone()
    return json.loads(row[0]) if row else None
