"""抓取各诊所 NAVER 访客评论正文(静态窗口),输出待判读清单 + 原始归档。

与 snapshot_naver.py 分工:那个只抓**评论数**入 ratings 做时间序列;这个抓**正文**,
供人工/AI 判读情感与问题领域后经 record 入库(reviews 表)。**本脚本不写库**——
情感与 issue_type 必须逐条判读,不能机器猜。

机制备注:访客评的 originType 多为 `영수증`(收据认证)或 `예약`——印证"访客评需到店
凭证才发得出",故这些评论只覆盖走 NAVER 的韩国本土客群。

页面静态窗口约 10 条(更多需翻页 API,本脚本不做,如实只取窗口内最新若干条)。
原始 JSON 归档到 data/archive/<slug>/naver-reviews-<date>.json。

用法:
    .venv/bin/python scripts/scrape_naver_reviews.py                 # 全部诊所
    .venv/bin/python scripts/scrape_naver_reviews.py --slug dana-clinic
    .venv/bin/python scripts/scrape_naver_reviews.py --out /tmp/rv.json   # 判读清单落盘
"""
import datetime
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
PLACE_RE = re.compile(r"(?:place/|hospital/)(\d+)")
# 负面线索词(仅用于**排序/标记**待判读,不作为判定依据——判定仍逐条读原文)
NEG_HINTS = ("아쉽", "별로", "불친절", "다시는", "최악", "실망", "비추", "환불", "부작용",
             "화가", "짜증", "기다렸", "대기", "오래 기다", "아프", "따갑", "붓", "멍",
             "권유", "강매", "상술", "바가지", "불쾌", "무성의", "대충", "공장", "그닥",
             "효과가 없", "효과 없", "안 좋", "않았", "못했", "안내가 없", "설명이 없")


def parse_reviews(html_text):
    i = html_text.find("window.__APOLLO_STATE__")
    if i < 0:
        return []
    start = html_text.find("{", i)
    try:
        data, _ = json.JSONDecoder().raw_decode(html_text[start:])
    except ValueError:
        return []
    out = []
    for k, v in data.items():
        if not (isinstance(v, dict) and v.get("body") and k.startswith("VisitorReview:")):
            continue
        out.append({
            "review_id": v.get("reviewId"),
            "body": v.get("body"),
            "visited": v.get("visited"),
            "created": v.get("created"),
            "visit_count": v.get("visitCount"),
            "origin": v.get("originType"),
            "visit_at": v.get("representativeVisitDateTime"),
            "has_reply": bool((v.get("reply") or {}).get("body")),
        })
    return out


def main(argv):
    slug_only = None
    out_path = None
    for i, a in enumerate(argv):
        if a == "--slug" and i + 1 < len(argv):
            slug_only = argv[i + 1]
        if a == "--out" and i + 1 < len(argv):
            out_path = argv[i + 1]
    conn = connect()
    today = datetime.date.today().isoformat()
    q = "SELECT id, slug, name_zh, naver_place_url FROM clinics WHERE naver_place_url IS NOT NULL"
    if slug_only:
        q += f" AND slug='{slug_only}'"
    rows = conn.execute(q).fetchall()
    # 已入库正文(reviews 无自然键)。库里旧记录的原文常被整理过(换行改标点等),
    # 精确匹配认不出来,故用"去掉所有空白与标点后的前 40 字"做归一化指纹
    def fp(t):
        return re.sub(r"[\s.,!?~…·\-—\u3000。,、!?()()\[\]'\"]+", "", t or "")[:40]
    seen = {(r["clinic_id"], fp(r["text_original"]))
            for r in conn.execute("SELECT clinic_id, text_original FROM reviews")}
    allrev, hits, dup = [], 0, 0
    with httpx.Client() as client:
        for c in rows:
            m = PLACE_RE.search(c["naver_place_url"] or "")
            if not m:
                continue
            url = f"https://m.place.naver.com/hospital/{m.group(1)}/review/visitor"
            try:
                r = client.get(url, headers={"User-Agent": UA}, timeout=25, follow_redirects=True)
                r.raise_for_status()
                revs = parse_reviews(r.text)
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {c['slug']}: {type(e).__name__} {str(e)[:70]}")
                time.sleep(1.5)
                continue
            arc = ROOT / "data" / "archive" / c["slug"]
            arc.mkdir(parents=True, exist_ok=True)
            (arc / f"naver-reviews-{today}.json").write_text(
                json.dumps(revs, ensure_ascii=False, indent=1), encoding="utf-8")
            n_hint = 0
            for v in revs:
                v["clinic_slug"] = c["slug"]
                v["clinic_id"] = c["id"]
                v["post_url"] = url
                v["dup"] = (c["id"], fp(v["body"])) in seen
                v["neg_hint"] = sorted({h for h in NEG_HINTS if h in (v["body"] or "")})
                dup += v["dup"]
                if v["neg_hint"] and not v["dup"]:
                    n_hint += 1
                allrev.append(v)
            hits += n_hint
            print(f"  {c['slug']:<24} 抓到 {len(revs):>2} 条 · 负面线索 {n_hint} · 已入库重复 "
                  f"{sum(1 for v in revs if v['dup'])}")
            time.sleep(1.2)
    print(f"\n完成:{len(rows)} 家 · 共 {len(allrev)} 条 · 带负面线索(未入库){hits} · 与库内重复 {dup}")
    if out_path:
        Path(out_path).write_text(json.dumps(allrev, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"判读清单 → {out_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
