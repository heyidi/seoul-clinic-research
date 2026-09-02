#!/usr/bin/env python3
"""把 FastAPI 站点导出为纯静态站(GitHub Pages 等可托管,无后端)。

用法:
  .venv/bin/python scripts/export_static.py                     # 导出到 dist/,直接可看,含归档
  .venv/bin/python scripts/export_static.py --no-archive        # 跳过归档(快速预览)
  .venv/bin/python scripts/export_static.py --passcode 口令      # 可选:加一层客户端口令门

导出内容:
  api/clinics/index.json + api/clinics/<slug>.json  ← /api/clinics(/{slug})
  api/compare_all.json(全部规格,前端静态模式按勾选客户端过滤) ← /api/compare
  api/treatments.json / trends.json / knowledge.json / fx.json(烘焙值标 stale)
  web/ 全量拷贝:HTML 与 app.js 把绝对路径改写为相对路径(适配子路径托管)、
    注入 window.SB_STATIC;仅当传了 --passcode 才另注入口令门 gate.js(哈希构建时替换)
  data/archive → archive/(原始凭据;--no-archive 跳过)
  robots.txt 全站禁抓 + .nojekyll
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 绝对路径 → 相对路径改写(静态站可能托管在 user.github.io/<repo>/ 子路径下)
REWRITES = [
    ('href="/assets/', 'href="assets/'),
    ('src="/assets/', 'src="assets/'),
    ('"/clinic.html', '"clinic.html'),
    ('"/compare.html', '"compare.html'),
    ('"/trends.html', '"trends.html'),
    ('"/map.html', '"map.html'),
    ('"/knowledge.html', '"knowledge.html'),
    ('"/archive/', '"archive/'),
    ('href="/"', 'href="index.html"'),
]
INJECT = '</title>\n<script>window.SB_STATIC=1</script>'
# 口令门是**可选**的:不传 --passcode 就不注入,静态站直接进总览。
# (口令门只是客户端软门,哈希和数据都发到浏览器,真要挡人得在服务器侧做)
INJECT_GATE = '\n<script src="assets/gate.js"></script>'

# 归档快照里的第三方 API token(如建站平台嵌在网页里的 Mapbox token)在公开仓会触发
# GitHub secret scanning 告警(实例:daybeau/imweb 的 pk.eyJ…,2026-08-13)。
# 发布副本一律脱敏;data/archive 私有原件保持原样以供审计。
SECRET_PATTERNS = [
    re.compile(rb"\b(?:pk|sk)\.eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}"),  # Mapbox JWT 型
    re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),                                # Google API key
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),                                     # AWS access key
    re.compile(rb"\bghp_[0-9A-Za-z]{36}\b"),                                  # GitHub PAT
    re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),                         # Slack token
    re.compile(rb"\bsk_live_[0-9A-Za-z]{20,}\b"),                             # Stripe live key
    re.compile(rb"\bIGQV[A-Za-z0-9_.-]{50,}\b"),                              # Instagram access token(建站嵌入)
]

# 我方最大暴露面:xhs_posts 帖子 URL 里的 xsec_token 是用登录态抓取时平台签发的链接令牌,
# 公开站上批量出现可被平台关联到抓取账号(有封号前科)。发布副本一律剥离该参数
# (代价:站外访客点"原帖"可能需登录/App 内打开;库内原始 URL 不动,审计与重放不受影响)。
_XSEC = re.compile(r"[?&]xsec_token=[^&\"\\]*(?:&xsec_source=[^&\"\\]*)?")


def _strip_xsec(json_text: str) -> str:
    return _XSEC.sub("", json_text)
TEXT_SUFFIXES = {".html", ".js", ".json", ".txt", ".xml"}


def _copy_archive_sanitized(src_root: Path, dst_root: Path) -> int:
    redacted = 0
    for src in sorted(src_root.rglob("*")):
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in TEXT_SUFFIXES:
            data = src.read_bytes()
            for pat in SECRET_PATTERNS:
                data, n = pat.subn(b"REDACTED-THIRD-PARTY-TOKEN", data)
                redacted += n
            dst.write_bytes(data)
        else:
            shutil.copy2(src, dst)
    return redacted


def export(out_dir: Path, passcode: str | None = None, include_archive: bool = True) -> dict:
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "api" / "clinics").mkdir(parents=True)

    def dump(rel: str, obj) -> None:
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        text = _strip_xsec(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        p.write_text(text, encoding="utf-8")

    clinics = client.get("/api/clinics").json()
    dump("api/clinics/index.json", clinics)
    for c in clinics:
        dump(f"api/clinics/{c['slug']}.json", client.get(f"/api/clinics/{c['slug']}").json())

    treatments = client.get("/api/treatments").json()
    dump("api/treatments.json", treatments)
    ids = ",".join(str(t["id"]) for t in treatments)
    dump("api/compare_all.json", client.get(f"/api/compare?treatment_ids={ids}").json())
    dump("api/trends.json", client.get("/api/trends").json())
    dump("api/knowledge.json", client.get("/api/knowledge").json())
    fx = client.get("/api/fx").json()
    fx["stale"] = True  # 烘焙值仅作断网兜底,前端静态模式优先直连 frankfurter.dev
    dump("api/fx.json", fx)

    for src in sorted((ROOT / "web").rglob("*")):
        rel = src.relative_to(ROOT / "web")
        dst = out_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if src.suffix == ".html" or rel.as_posix() == "assets/app.js":
            text = src.read_text(encoding="utf-8")
            for a, b in REWRITES:
                text = text.replace(a, b)
            if src.suffix == ".html":
                text = text.replace("</title>", INJECT + (INJECT_GATE if passcode else ""), 1)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if passcode:
        gate = (ROOT / "deploy" / "gate.js").read_text(encoding="utf-8")
        gate = gate.replace("__GATE_HASH__", hashlib.sha256(passcode.encode()).hexdigest())
        (out_dir / "assets" / "gate.js").write_text(gate, encoding="utf-8")

    redacted = 0
    if include_archive and (ROOT / "data" / "archive").exists():
        redacted = _copy_archive_sanitized(ROOT / "data" / "archive", out_dir / "archive")
    if redacted:
        print(f"归档脱敏:已抹去 {redacted} 处第三方 token")

    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"clinics": len(clinics), "treatments": len(treatments)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--passcode", default=None,
                    help="可选:给静态站加一层客户端口令门;不给则直接进总览")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args(argv)
    out_dir = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    stats = export(out_dir, args.passcode, include_archive=not args.no_archive)
    total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    print(f"导出完成 → {out_dir} · {stats['clinics']} 家诊所 · {stats['treatments']} 个规格 · 共 {total / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
