import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_db):
    from app.main import app

    return TestClient(app)


def test_fx_fetches_and_caches(client, monkeypatch):
    calls = []

    def fake_fetch():
        calls.append(1)
        return {"CNY": 0.00453, "SGD": 0.00086}

    import app.fx as fx
    monkeypatch.setattr(fx, "fetch_rates", fake_fetch)
    data = client.get("/api/fx").json()
    assert data["rates"]["CNY"] == 0.00453 and data["stale"] is False
    client.get("/api/fx")
    assert len(calls) == 1  # 6小时内走缓存


def test_fx_stale_fallback(client, monkeypatch):
    import app.fx as fx

    monkeypatch.setattr(fx, "fetch_rates", lambda: {"CNY": 0.005, "SGD": 0.0009})
    client.get("/api/fx")
    # 缓存过期 + 抓取失败 → 用旧值并标 stale
    from app.db import connect

    conn = connect()
    conn.execute("UPDATE fx_rates SET fetched_at='2020-01-01T00:00:00'")
    conn.commit()
    conn.close()

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(fx, "fetch_rates", boom)
    data = client.get("/api/fx").json()
    assert data["rates"]["CNY"] == 0.005 and data["stale"] is True


def test_fx_503_when_no_data(client, monkeypatch):
    import app.fx as fx

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(fx, "fetch_rates", boom)
    assert client.get("/api/fx").status_code == 503


def test_fx_cache_refresh_updates_existing_rows(client, monkeypatch):
    import app.fx as fx

    monkeypatch.setattr(fx, "fetch_rates", lambda: {"CNY": 0.004, "SGD": 0.0008})
    client.get("/api/fx")
    from app.db import connect

    conn = connect()
    conn.execute("UPDATE fx_rates SET fetched_at='2020-01-01T00:00:00'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(fx, "fetch_rates", lambda: {"CNY": 0.0046, "SGD": 0.00087})
    data = client.get("/api/fx").json()
    assert data["rates"]["CNY"] == 0.0046 and data["stale"] is False
    conn = connect()
    row = conn.execute("SELECT rate FROM fx_rates WHERE quote='CNY'").fetchone()
    conn.close()
    assert row["rate"] == 0.0046
