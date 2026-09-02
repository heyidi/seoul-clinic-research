import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect, db_path  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "app" / "schema.sql"
SEEDS = Path(__file__).resolve().parent / "seed_treatments.json"


def init_db() -> None:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA.read_text())
    defaults = {"treatment_ko": None, "variant_ko": None, "variant_en": None, "notes": None}
    for t in json.loads(SEEDS.read_text()):
        conn.execute(
            """INSERT OR IGNORE INTO treatments
               (category, treatment_zh, treatment_ko, variant_zh, variant_ko, variant_en, notes)
               VALUES (:category, :treatment_zh, :treatment_ko, :variant_zh, :variant_ko, :variant_en, :notes)""",
            {**defaults, **t},
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"initialized {db_path()}")
