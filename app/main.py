from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .fx import router as fx_router

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Seoul Beauty")
app.include_router(api_router)
app.include_router(fx_router)


@app.middleware("http")
async def revalidate_web_assets(request, call_next):
    """HTML/JS/CSS 一律 no-cache(存但每次带 ETag 校验,304 极快):
    否则浏览器按启发式缓存旧前端,改版后用户看不到变化(2026-08-20 实证)。
    /archive 的快照与图片不动——内容不可变,放心久缓存。"""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css")):
        if not p.startswith("/archive"):
            resp.headers["Cache-Control"] = "no-cache"
    return resp
(ROOT / "data" / "archive").mkdir(parents=True, exist_ok=True)  # 新克隆无此目录时自动创建
app.mount("/archive", StaticFiles(directory=ROOT / "data" / "archive"), name="archive")
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
