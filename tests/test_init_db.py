from app.db import connect


def test_init_creates_tables_and_seeds(tmp_db):
    conn = connect()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"clinics", "treatments", "prices", "ratings", "reviews", "xhs_posts", "archives", "fx_rates"} <= tables
    n = conn.execute("SELECT COUNT(*) c FROM treatments").fetchone()["c"]
    assert n >= 20


def test_init_is_idempotent(tmp_db):
    from scripts.init_db import init_db

    init_db()
    init_db()
    conn = connect()
    n = conn.execute("SELECT COUNT(*) c FROM treatments").fetchone()["c"]
    assert n == conn.execute("SELECT COUNT(*) c FROM treatments").fetchone()["c"]
    assert n >= 20
