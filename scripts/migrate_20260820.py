#!/usr/bin/env python3
"""2026-08-20:knowledge_items 增加 parent_id(型号子条目支持)。

背景:用户指出丽珠兰"不同型号不同盒",知识库需把产品家族的子型号逐条展开
(Rejuran Healer/HB Plus/I/S 各有定位与中文圈盒色俗称)。加自引用 parent_id,
父条目=产品家族,子条目=具体型号;前端按父子嵌套渲染。幂等可重跑。
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "seoul_beauty.db"


def main() -> None:
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(knowledge_items)")]
    if "parent_id" in cols:
        print("parent_id 已存在,跳过")
    else:
        conn.execute("ALTER TABLE knowledge_items ADD COLUMN parent_id INTEGER REFERENCES knowledge_items(id)")
        conn.commit()
        print("已添加 knowledge_items.parent_id")
    conn.execute("PRAGMA foreign_key_check")
    print("foreign_key_check 通过")


if __name__ == "__main__":
    sys.exit(main())
