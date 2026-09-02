"""迁移:reviews 增 issue_type(差评问题领域,受控词表)。

背景:差评此前只有 sentiment='negative' 一个维度,打分里只作 flag 不压分。
2026-08-21 用户口径改为"按差评主要集中领域扣分"——但**按条数扣分会惩罚我们自己挖得深**
(全库 222 条评论里差评仅 10 条,哪家有差评基本取决于翻了多深),故改为
**按严重度领域是否出现扣分,同一领域出现多次只算一次**。

词表(严重度降序)见 scripts/ingest.py 的 ISSUE_VALUES;正面/中性评论 issue_type 留空。
幂等:列已存在则跳过。
用法:.venv/bin/python scripts/migrate_20260821_review_issue.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect  # noqa: E402


def main():
    conn = connect()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(reviews)")]
    if "issue_type" in cols:
        print("issue_type 已存在,跳过")
    else:
        conn.execute("ALTER TABLE reviews ADD COLUMN issue_type TEXT")
        conn.commit()
        print("reviews 增列 issue_type")
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    print("foreign_key_check:", "OK" if not bad else bad)
    n = conn.execute("SELECT COUNT(*) FROM reviews WHERE sentiment='negative' AND issue_type IS NULL").fetchone()[0]
    print(f"待分类的差评:{n} 条(经 data/records/*.json 重录补 issue_type)")


if __name__ == "__main__":
    main()
