import re

from fastapi import APIRouter, HTTPException

from .db import connect
from .scoring import score_clinic

router = APIRouter(prefix="/api")

# 小红书"营销性质"集合(用于营销壁垒红线):官方号/KOC系列/店家互动帖
XHS_MARKETING_NATURES = ("官方号", "KOC系列", "店家互动帖")

LATEST_RATINGS_SQL = """
SELECT clinic_id, source, score, review_count, source_url, collected_at FROM (
  SELECT r.*, ROW_NUMBER() OVER (
    PARTITION BY clinic_id, source ORDER BY collected_at DESC, id DESC) AS rn
  FROM ratings r
) WHERE rn = 1
"""


def latest_ratings_map(conn):
    out = {}
    for r in conn.execute(LATEST_RATINGS_SQL):
        out.setdefault(r["clinic_id"], {})[r["source"]] = {
            "score": r["score"], "review_count": r["review_count"],
            "source_url": r["source_url"], "collected_at": r["collected_at"],
        }
    return out


# NAVER place id:branches.naver_place_url 与 ratings.source_url 都含
# (m.place.naver.com/hospital/<id>/... 或 map.naver.com/p/entry/place/<id>)
_PLACE_ID_RE = re.compile(r"(?:hospital|place)/(\d+)")


def _place_id(url):
    m = _PLACE_ID_RE.search(url or "")
    return m.group(1) if m else None


# 地址首词即广域自治体;"광주광역시/광주"两种写法并存,统一到短名(前端据此分组显示)
_REGION_ALIAS = {"광주광역시": "광주", "부산광역시": "부산", "대구광역시": "대구",
                 "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산",
                 "서울특별시": "서울", "세종특별자치시": "세종",
                 "제주특별자치도": "제주", "강원특별자치도": "강원",
                 "전북특별자치도": "전북"}


def _region(address_ko):
    head = (address_ko or "").split(" ")[0]
    return _REGION_ALIAS.get(head, head) or None


def align_branches(branch_rows, latest):
    """分店行与 ratings 最新快照对齐(API 组装层,branches 原始数据不动)。

    主店(is_primary=1)直接取本诊所 naver_map/naver_blog 最新快照——与总览主行
    同源同值,消灭"同一家店两个数字";非主店按 place_id 匹配分店快照源
    (如 naver_map_myeongdong,匹配只认 URL 里的 place id,不猜源名后缀)。
    匹配不到的保留 branches 静态值。每个数字带 visitor_as_of/blog_as_of
    (所示数字的采集日期),静态旧值因此"旧"得可见。

    同一 place_id 可能被多个源名覆盖(历史手工源名 naver_map_myeongdong 与脚本
    生成的 naver_map_b<pid>)——按 collected_at 择新,同日按源名定序,杜绝"赢家由
    SQL 行序决定"的数字漂移。
    """
    latest = latest or {}
    snaps = {}
    for src, r in sorted(latest.items()):
        kind = "visitor" if src.startswith("naver_map") else (
            "blog" if src.startswith("naver_blog") else None)
        pid = _place_id(r["source_url"]) if kind else None
        if not pid:
            continue
        cur = snaps.setdefault(pid, {}).get(kind)
        if cur is None or (r["collected_at"] or "") > (cur["collected_at"] or ""):
            snaps[pid][kind] = r
    out = []
    for b in branch_rows:
        d = dict(b)
        d["region"] = _region(d.get("address_ko"))
        d["visitor_as_of"] = d["blog_as_of"] = d["collected_at"]
        if d["is_primary"]:
            vis, blog = latest.get("naver_map"), latest.get("naver_blog")
        else:
            pid = _place_id(d.get("naver_place_url"))
            hit = snaps.get(pid, {}) if pid else {}
            vis, blog = hit.get("visitor"), hit.get("blog")
        # 快照行 review_count 可为空(ingest 允许;NAVER 医院无星级口径下合法)——
        # 空快照不覆盖有效静态值,否则"数据明明有,页面说未获取",违背"未获取"口径
        if vis and vis["review_count"] is not None:
            d["visitor_reviews"], d["visitor_as_of"] = vis["review_count"], vis["collected_at"]
        if blog and blog["review_count"] is not None:
            d["blog_reviews"], d["blog_as_of"] = blog["review_count"], blog["collected_at"]
        out.append(d)
    # 对齐后再排序(主店最前,其余按对齐后的访客评降序,未获取沉底)
    out.sort(key=lambda x: (-x["is_primary"],
                            -(x["visitor_reviews"] if x["visitor_reviews"] is not None else -1)))
    return out


@router.get("/clinics")
def list_clinics():
    conn = connect()
    try:
        ratings = latest_ratings_map(conn)
        spec = {}
        for r in conn.execute("SELECT clinic_id, is_specialist FROM doctors"):
            cur = spec.get(r["clinic_id"])
            rank = {"specialist": 3, "general": 2, "unknown": 1}
            if cur is None or rank.get(r["is_specialist"], 0) > rank.get(cur, 0):
                spec[r["clinic_id"]] = r["is_specialist"]
        neg = {r["clinic_id"]: r["n"] for r in conn.execute(
            "SELECT clinic_id, COUNT(*) n FROM reviews WHERE sentiment='negative' GROUP BY clinic_id")}
        # 差评按"问题领域是否出现"计分(不按条数),故这里取每店的领域集合
        neg_issues = {}
        for r in conn.execute("SELECT DISTINCT clinic_id, issue_type FROM reviews "
                              "WHERE sentiment='negative' AND issue_type IS NOT NULL"):
            neg_issues.setdefault(r["clinic_id"], set()).add(r["issue_type"])
        br = {r["clinic_id"]: r["n"] for r in conn.execute(
            "SELECT clinic_id, COUNT(*) n FROM branches GROUP BY clinic_id")}
        # 分店明细直接随列表返回:总览页默认展开逐店评论数,免去逐家点开再拉详情;
        # 数字经 align_branches 对齐 ratings 最新快照(排序也在其内完成)
        brs = {}
        for r in conn.execute("SELECT * FROM branches"):
            brs.setdefault(r["clinic_id"], []).append(r)
        brs = {k: align_branches(v, ratings.get(k)) for k, v in brs.items()}
        pc = {r["clinic_id"]: r["n"] for r in conn.execute(
            "SELECT clinic_id, COUNT(*) n FROM prices GROUP BY clinic_id")}
        oc = {r["clinic_id"]: r["n"] for r in conn.execute(
            "SELECT clinic_id, COUNT(*) n FROM clinic_offerings GROUP BY clinic_id")}
        # 真实售价:排除"非实际售价"占位(如 MARQ 的法定비급여区间),这些不算有价
        real_pc = {r["clinic_id"]: r["n"] for r in conn.execute(
            "SELECT clinic_id, COUNT(*) n FROM prices "
            "WHERE spec_notes IS NULL OR spec_notes NOT LIKE '%非实际售价%' GROUP BY clinic_id")}
        xhs_total, xhs_mkt, xhs_auth = {}, {}, {}
        for r in conn.execute("SELECT clinic_id, nature, COUNT(*) n FROM xhs_posts GROUP BY clinic_id, nature"):
            cid, nat, n = r["clinic_id"], r["nature"], r["n"]
            xhs_total[cid] = xhs_total.get(cid, 0) + n
            if nat in XHS_MARKETING_NATURES:
                xhs_mkt[cid] = xhs_mkt.get(cid, 0) + n
            elif nat == "素人":
                xhs_auth[cid] = xhs_auth.get(cid, 0) + n

        out = []
        for c in conn.execute("SELECT * FROM clinics ORDER BY name_zh"):
            cid = c["id"]
            rt = ratings.get(cid, {})
            naver = (rt.get("naver_map") or {}).get("review_count")
            scored = score_clinic({
                "verification_status": c["verification_status"],
                "specialist_level": spec.get(cid),
                "price_count": pc.get(cid, 0),
                "real_price_count": real_pc.get(cid, 0),
                "offering_count": oc.get(cid, 0),
                "negative_review_count": neg.get(cid, 0),
                "negative_issues": neg_issues.get(cid, ()),
                "naver_reviews": naver,
                "xhs_marketing": xhs_mkt.get(cid, 0),
                "xhs_authentic": xhs_auth.get(cid, 0),
                "xhs_total": xhs_total.get(cid, 0),
            })
            out.append({**dict(c), "latest_ratings": rt,
                        "specialist_level": spec.get(cid),
                        "negative_review_count": neg.get(cid, 0),
                        "branch_count": br.get(cid, 0),
                        "branches": brs.get(cid, []),
                        "price_count": pc.get(cid, 0),
                        "real_price_count": real_pc.get(cid, 0),
                        "xhs_total": xhs_total.get(cid, 0),
                        "xhs_marketing": xhs_mkt.get(cid, 0),
                        "rec_score": scored["score"], "rec_band": scored["band"],
                        "rec_reasons": scored["reasons"]})
        return out
    finally:
        conn.close()


@router.get("/trends")
def trends():
    """各诊所 NAVER 访客评/博客评的历史快照时间序列(供增长趋势页)。"""
    conn = connect()
    try:
        names = {c["id"]: c for c in conn.execute("SELECT id, slug, name_zh, name_ko FROM clinics")}
        # (clinic, source) -> {date: count};同日多条取后插入者(id 大)
        acc = {}
        for r in conn.execute(
            "SELECT clinic_id, source, review_count, collected_at FROM ratings "
            "WHERE source IN ('naver_map','naver_blog') AND review_count IS NOT NULL "
            "ORDER BY collected_at ASC, id ASC"):
            acc.setdefault((r["clinic_id"], r["source"]), {})[r["collected_at"]] = r["review_count"]

        def series(cid, src):
            return [{"d": d, "c": c} for d, c in sorted(acc.get((cid, src), {}).items())]

        out = []
        for cid, c in names.items():
            visitor, blog = series(cid, "naver_map"), series(cid, "naver_blog")
            if not visitor and not blog:
                continue
            out.append({"slug": c["slug"], "name_zh": c["name_zh"], "name_ko": c["name_ko"],
                        "visitor": visitor, "blog": blog})
        out.sort(key=lambda x: -(x["visitor"][-1]["c"] if x["visitor"] else 0))
        return out
    finally:
        conn.close()


@router.get("/treatments")
def list_treatments():
    conn = connect()
    try:
        return [dict(t) for t in conn.execute(
            "SELECT * FROM treatments ORDER BY category, treatment_zh, id")]
    finally:
        conn.close()


@router.get("/knowledge")
def list_knowledge():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM knowledge_items ORDER BY category, id")]
    finally:
        conn.close()


@router.get("/compare")
def compare(treatment_ids: str = ""):
    ids = [int(x) for x in treatment_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return []
    conn = connect()
    try:
        result = []
        for tid in ids:
            t = conn.execute("SELECT * FROM treatments WHERE id=?", (tid,)).fetchone()
            if not t:
                continue
            offers = conn.execute(
                """SELECT price_krw, raw_name_ko, raw_name_zh, is_event_price, spec_notes,
                          source_url, collected_at, clinic_slug, clinic_name_zh, clinic_name_ko,
                          verification_status
                   FROM (
                     SELECT p.price_krw, p.raw_name_ko, p.raw_name_zh, p.is_event_price,
                            p.spec_notes, p.source_url, p.collected_at,
                            c.slug AS clinic_slug, c.name_zh AS clinic_name_zh,
                            c.name_ko AS clinic_name_ko, c.verification_status,
                            ROW_NUMBER() OVER (
                              PARTITION BY p.clinic_id
                              ORDER BY p.collected_at DESC, p.id DESC) AS rn
                     FROM prices p
                     JOIN clinics c ON c.id = p.clinic_id
                     WHERE p.treatment_id = ?
                       AND (SELECT COUNT(*) FROM price_components pc WHERE pc.price_id = p.id) < 2
                   ) WHERE rn = 1
                   ORDER BY price_krw ASC""",
                (tid,),
            ).fetchall()
            package_offers = conn.execute(
                """SELECT p.id AS price_id, p.price_krw, p.raw_name_ko, p.raw_name_zh,
                          p.is_event_price, p.spec_notes, p.source_url, p.collected_at,
                          c.slug AS clinic_slug, c.name_zh AS clinic_name_zh,
                          c.name_ko AS clinic_name_ko, c.verification_status
                   FROM prices p
                   JOIN clinics c ON c.id = p.clinic_id
                   JOIN price_components pc ON pc.price_id = p.id AND pc.treatment_id = ?
                   WHERE (SELECT COUNT(*) FROM price_components pc2 WHERE pc2.price_id = p.id) >= 2
                      OR p.treatment_id IS NULL
                   ORDER BY p.price_krw ASC""",
                (tid,),
            ).fetchall()
            pkg_list = []
            for po in package_offers:
                comps = [f"{r['treatment_zh']}·{r['variant_zh']}" for r in conn.execute(
                    """SELECT t.treatment_zh, t.variant_zh FROM price_components pc
                       JOIN treatments t ON t.id = pc.treatment_id
                       WHERE pc.price_id = ? ORDER BY t.id""", (po["price_id"],))]
                d = dict(po)
                d.pop("price_id", None)
                d["component_names"] = comps
                pkg_list.append(d)
            have_price = {o["clinic_slug"] for o in offers} | {p["clinic_slug"] for p in pkg_list}
            zh_core = t["treatment_zh"].split("(")[0]
            ko = t["treatment_ko"] or ""
            hint = t["match_hint"] if "match_hint" in t.keys() else None
            avail = []
            if hint:
                # 变体级推断:部位/产品专用规格按关键词匹配,避免 treatment 级过宽归因
                tokens = [x for x in hint.split("|") if x]
                cond = " OR ".join(
                    "(o.name_ko LIKE '%' || ? || '%' OR o.name_zh LIKE '%' || ? || '%')"
                    for _ in tokens)
                params = [v for tok in tokens for v in (tok, tok)]
                rows = conn.execute(
                    f"""SELECT DISTINCT c.slug AS clinic_slug, c.name_zh AS clinic_name_zh,
                               o.name_ko AS offering_ko, o.source_url
                        FROM clinic_offerings o JOIN clinics c ON c.id = o.clinic_id
                        WHERE {cond}""", params).fetchall()
            elif ko or zh_core:
                rows = conn.execute(
                    """SELECT DISTINCT c.slug AS clinic_slug, c.name_zh AS clinic_name_zh,
                              o.name_ko AS offering_ko, o.source_url
                       FROM clinic_offerings o JOIN clinics c ON c.id = o.clinic_id
                       WHERE (? != '' AND (o.name_ko LIKE '%' || ? || '%'))
                          OR (o.name_zh LIKE '%' || ? || '%')""",
                    (ko, ko, zh_core)).fetchall()
            else:
                rows = []
            if rows:
                seen = set()
                for r in rows:
                    if r["clinic_slug"] not in have_price and r["clinic_slug"] not in seen:
                        seen.add(r["clinic_slug"])
                        avail.append(dict(r))
            result.append({"treatment": dict(t), "offers": [dict(o) for o in offers],
                           "package_offers": pkg_list, "available_no_price": avail})
        return result
    finally:
        conn.close()


@router.get("/clinics/{slug}")
def clinic_detail(slug: str):
    conn = connect()
    try:
        c = conn.execute("SELECT * FROM clinics WHERE slug=?", (slug,)).fetchone()
        if not c:
            raise HTTPException(status_code=404, detail="clinic not found")
        cid = c["id"]
        latest = latest_ratings_map(conn).get(cid, {})
        return {
            **dict(c),
            "latest_ratings": latest,
            "rating_history": [dict(r) for r in conn.execute(
                "SELECT * FROM ratings WHERE clinic_id=? ORDER BY collected_at DESC", (cid,))],
            "prices": [dict(r) for r in conn.execute(
                """SELECT p.*, t.category, t.treatment_zh, t.variant_zh FROM prices p
                   LEFT JOIN treatments t ON t.id = p.treatment_id
                   WHERE p.clinic_id=? ORDER BY t.category, t.treatment_zh, p.collected_at DESC""", (cid,))],
            "reviews": [dict(r) for r in conn.execute(
                "SELECT * FROM reviews WHERE clinic_id=? ORDER BY collected_at DESC", (cid,))],
            "xhs_posts": [dict(r) for r in conn.execute(
                "SELECT * FROM xhs_posts WHERE clinic_id=? ORDER BY collected_at DESC", (cid,))],
            "archives": [dict(r) for r in conn.execute(
                "SELECT * FROM archives WHERE clinic_id=? ORDER BY fetched_at DESC", (cid,))],
            "offerings": [dict(r) for r in conn.execute(
                "SELECT * FROM clinic_offerings WHERE clinic_id=? ORDER BY category, id", (cid,))],
            "doctors": [dict(r) for r in conn.execute(
                "SELECT * FROM doctors WHERE clinic_id=? ORDER BY id", (cid,))],
            "branches": align_branches(
                conn.execute("SELECT * FROM branches WHERE clinic_id=?", (cid,)).fetchall(), latest),
        }
    finally:
        conn.close()
