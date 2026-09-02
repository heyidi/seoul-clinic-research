import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.environ.get("SEOUL_BEAUTY_DB", ROOT / "db" / "seoul_beauty.db"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
