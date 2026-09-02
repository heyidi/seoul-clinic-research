"""迁移:分店快照源名统一为 naver_map_b<place_id> / naver_blog_b<place_id>。

背景:早期人工录入的分店快照用了随手起的源名(naver_map_myeongdong 之类),
而 snapshot_naver.py 扩到分店后生成的是确定性源名 naver_map_b<place_id>。
同一个 place_id 出现两个源名时,align_branches 会各取一条"该源最新",
统一源名后同 place_id 只剩一条时间序列(API 侧另有按日期择新的兜底)。

幂等:已是 _b<digits> 形式的跳过;source_url 里取不到 place_id 的保留原样并告警。
用法:.venv/bin/python scripts/migrate_20260820_branch_sources.py [--dry]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect  # noqa: E402

PLACE_RE = re.compile(r"(?:hospital|place)/(\d+)")
LEGACY_RE = re.compile(r"^(naver_map|naver_blog)_(?!b\d+$)")


def main(dry=False):
    conn = connect()
    rows = conn.execute(
        "SELECT id, source, source_url FROM ratings "
        "WHERE source LIKE 'naver_map_%' OR source LIKE 'naver_blog_%'").fetchall()
    renamed = skipped = 0
    for r in rows:
        if not LEGACY_RE.match(r["source"]):
            skipped += 1
            continue
        m = PLACE_RE.search(r["source_url"] or "")
        if not m:
            print(f"  ⚠ ratings#{r['id']} source={r['source']} 取不到 place_id,保留原样")
            skipped += 1
            continue
        kind = "naver_map" if r["source"].startswith("naver_map") else "naver_blog"
        new = f"{kind}_b{m.group(1)}"
        print(f"  {r['source']:<24} → {new}")
        if not dry:
            conn.execute("UPDATE ratings SET source=? WHERE id=?", (new, r["id"]))
        renamed += 1
    if not dry:
        conn.commit()
    print(f"\n完成:改名 {renamed} · 跳过 {skipped}")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv[1:])
