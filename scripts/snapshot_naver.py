"""每日快照:抓取各诊所 NAVER Place 的访客评/博客评总数,写入 ratings 表,累积成时间序列。

供增长趋势页(trends.html / /api/trends)使用。**只静态抓 NAVER(iPhone UA),与小红书无关**。

抓两类目标:
  - 诊所主店 → 源名 naver_map / naver_blog(趋势页只认这两个源名)
  - 各分店   → 源名 naver_map_b<place_id> / naver_blog_b<place_id>
              (与主店同 place_id 的分店跳过,避免同一家店抓两遍;
               无 naver_place_url 的分店抓不到,保持"未获取")
幂等:同一诊所同一源名同一天已有快照则跳过,不重复插入。

用法:
    .venv/bin/python scripts/snapshot_naver.py           # 抓全部(主店+分店)
    .venv/bin/python scripts/snapshot_naver.py --dry     # 只打印解析结果,不写库
    .venv/bin/python scripts/snapshot_naver.py --main    # 只抓主店(旧行为)
"""
import datetime
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect  # noqa: E402

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
PLACE_RE = re.compile(r"(?:place/|hospital/)(\d+)")
VISITOR_RE = re.compile(r'"visitorReviewsTotal":(\d+)')
BLOG_RE = re.compile(r'"cafeBlogReviewsTotal":(\d+)')


def fetch_counts(place_id: str, client: httpx.Client):
    """返回 (visitor, blog);解析失败返回 (None, None)。"""
    url = f"https://m.place.naver.com/hospital/{place_id}/home"
    r = client.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    r.raise_for_status()
    v = VISITOR_RE.search(r.text)
    b = BLOG_RE.search(r.text)
    return (int(v.group(1)) if v else None, int(b.group(1)) if b else None), url


def targets(conn, main_only=False):
    """[(clinic_id, 标签, place_id, 访客源名, 博客源名)];主店在前,分店在后。"""
    out, mains, seen = [], {}, set()
    for c in conn.execute(
            "SELECT id, slug, naver_place_url FROM clinics WHERE naver_place_url IS NOT NULL"):
        m = PLACE_RE.search(c["naver_place_url"] or "")
        if not m:
            continue
        mains[c["id"]] = m.group(1)
        seen.add((c["id"], m.group(1)))
        out.append((c["id"], c["slug"], m.group(1), "naver_map", "naver_blog"))
    if main_only:
        return out
    for b in conn.execute(
            "SELECT clinic_id, name_zh, name_ko, naver_place_url FROM branches "
            "WHERE naver_place_url IS NOT NULL ORDER BY clinic_id, id"):
        m = PLACE_RE.search(b["naver_place_url"] or "")
        if not m:
            continue
        pid, cid = m.group(1), b["clinic_id"]
        if (cid, pid) in seen:  # 与主店同店 / 同一分店重复登记
            continue
        seen.add((cid, pid))
        label = (b["name_zh"] or b["name_ko"] or "")[:16]
        out.append((cid, f"  └{label}", pid, f"naver_map_b{pid}", f"naver_blog_b{pid}"))
    return out


def main(dry=False, main_only=False):
    conn = connect()
    today = datetime.date.today().isoformat()
    done = ok = skipped = failed = 0
    with httpx.Client() as client:
        for cid, label, place_id, src_v, src_b in targets(conn, main_only):
            exists = conn.execute(
                "SELECT 1 FROM ratings WHERE clinic_id=? AND source=? AND collected_at=?",
                (cid, src_v, today)).fetchone()
            if exists and not dry:
                skipped += 1
                continue
            try:
                (visitor, blog), url = fetch_counts(place_id, client)
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {label}: 抓取失败 {type(e).__name__}: {str(e)[:80]}")
                failed += 1
                time.sleep(1.5)
                continue
            print(f"  {label:<26} 访客={visitor}  博客={blog}")
            if not dry and (visitor is not None or blog is not None):
                if visitor is not None:
                    conn.execute(
                        "INSERT INTO ratings (clinic_id, source, score, review_count, source_url, collected_at)"
                        " VALUES (?,?,?,?,?,?)", (cid, src_v, None, visitor, url, today))
                if blog is not None:
                    conn.execute(
                        "INSERT INTO ratings (clinic_id, source, score, review_count, source_url, collected_at)"
                        " VALUES (?,?,?,?,?,?)", (cid, src_b, None, blog, url, today))
                ok += 1
            done += 1
            time.sleep(1.2)  # 对 NAVER 温柔些
    if not dry:
        conn.commit()
    print(f"\n完成:成功 {ok} · 跳过(今日已快照){skipped} · 失败 {failed} · 处理 {done}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    main(dry="--dry" in argv, main_only="--main" in argv)
