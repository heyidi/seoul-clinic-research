import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SEOUL_BEAUTY_DB", str(db_file))
    from scripts.init_db import init_db

    init_db()
    return db_file
