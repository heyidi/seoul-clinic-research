import datetime

import httpx
from fastapi import APIRouter, HTTPException

from .db import connect

router = APIRouter(prefix="/api")

FX_URL = "https://api.frankfurter.dev/v1/latest?base=KRW&symbols=CNY,SGD"
CACHE_SECONDS = 6 * 3600


def fetch_rates() -> dict:
    # 超时收紧到3秒:跨境访问 frankfurter 深夜易抽风,宁可回退缓存汇率也不拖住 /api/fx
    resp = httpx.get(FX_URL, timeout=3)
    resp.raise_for_status()
    return resp.json()["rates"]


@router.get("/fx")
def get_fx():
    conn = connect()
    try:
        rows = conn.execute("SELECT quote, rate, fetched_at FROM fx_rates").fetchall()
        now = datetime.datetime.utcnow()
        cached = {r["quote"]: r["rate"] for r in rows}
        fetched_at = min((r["fetched_at"] for r in rows), default=None)
        fresh = False
        if fetched_at:
            age = (now - datetime.datetime.fromisoformat(fetched_at)).total_seconds()
            fresh = age < CACHE_SECONDS
        if not fresh:
            try:
                rates = fetch_rates()
            except Exception:
                if not cached:
                    raise HTTPException(status_code=503, detail="汇率暂不可用") from None
                return {"base": "KRW", "rates": cached, "fetched_at": fetched_at, "stale": True}
            ts = now.isoformat(timespec="seconds")
            for quote, rate in rates.items():
                conn.execute(
                    """INSERT INTO fx_rates (quote, rate, fetched_at) VALUES (?,?,?)
                       ON CONFLICT(quote) DO UPDATE SET rate=excluded.rate, fetched_at=excluded.fetched_at""",
                    (quote, rate, ts),
                )
            conn.commit()
            return {"base": "KRW", "rates": rates, "fetched_at": ts, "stale": False}
        return {"base": "KRW", "rates": cached, "fetched_at": fetched_at, "stale": False}
    finally:
        conn.close()
