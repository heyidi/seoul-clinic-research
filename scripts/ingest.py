"""结构化录入:python scripts/ingest.py <record.json>

record.json 结构(除 clinic 外均可选):
{
  "clinic":     {"slug": "...", "name_ko": "...", ...},           # slug 必填,按 slug upsert
  "treatments": [{"category","treatment_zh","variant_zh",...}],    # 扩充项目字典
  "prices":     [{"treatment_zh","variant_zh","price_krw","source_url",...}],
  "ratings":    [{"source","score","review_count","source_url",...}],
  "reviews":    [{"source","text_original","text_zh","sentiment","issue_type"(仅差评,受控词表),"post_url",...}],
  "xhs_posts":  [{"url","title","sentiment","nature","summary_zh",...}],
  "archives":   [{"file_path","description","source_url","fetched_at"}],
  "offerings":  [{"category","name_ko","name_zh","name_en","description_zh","source_url"}],   # 诊所设备/药品清单
  "knowledge":  [{"category","name_zh","name_ko","name_en","origin","summary_zh","source_url"}],  # 医美知识库(全局)
  "doctors":    [{"name_ko","name_zh","title","credentials_zh","is_specialist","source_url"}],
  "branches":   [{"name_ko","name_zh","address_ko","naver_place_url","visitor_reviews","blog_reviews","is_primary","source_url"}]
}
prices 里 treatment_zh/variant_zh 可省略(组合套餐等无法对齐字典时,treatment_id 记 NULL,仅在详情页展示,不进入比价)。
校验:prices/ratings/offerings/doctors 必须带 source_url;reviews 必须带 post_url;xhs_posts 必须带 url。
collected_at/fetched_at 缺省为今天。任一条目非法则整体回滚。
"""
import datetime
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import connect  # noqa: E402

CLINIC_FIELDS = [
    "name_ko", "name_en", "name_zh", "address_ko", "address_zh", "lat", "lng",
    "official_site", "naver_place_url", "instagram", "facebook",
    "verification_status", "verification_notes", "notes", "revisit_badge", "editor_note",
    "opened_year",
]


class IngestError(Exception):
    pass


NATURE_VALUES = ("官方号", "KOC系列", "店家互动帖", "素人", "归因存疑", "未判定")
# 差评问题领域(受控词表,严重度降序)。打分按"该领域是否出现"计,不按条数——
# 差评条数取决于我们翻了多深,按条数扣分等于惩罚自己挖得深(2026-08-21 口径)
ISSUE_VALUES = ("量价不符", "成分调包", "术后伤害·推诿", "手法敷衍",
                "等待/流程", "服务态度", "内外有别存疑", "效果不满", "其他")


def _today() -> str:
    return datetime.date.today().isoformat()


def _require(item: dict, field: str, table: str) -> None:
    if not item.get(field):
        raise IngestError(f"{table} 条目缺少 {field},拒绝入库: {json.dumps(item, ensure_ascii=False)[:200]}")


def _upsert_clinic(conn: sqlite3.Connection, clinic: dict) -> int:
    _require(clinic, "slug", "clinic")
    slug = clinic["slug"]
    fields = {k: clinic[k] for k in CLINIC_FIELDS if k in clinic}
    row = conn.execute("SELECT id FROM clinics WHERE slug=?", (slug,)).fetchone()
    if row:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE clinics SET {sets}, updated_at=datetime('now') WHERE id=?",
                (*fields.values(), row["id"]),
            )
        return row["id"]
    cols = ", ".join(["slug", *fields])
    marks = ", ".join("?" * (1 + len(fields)))
    cur = conn.execute(f"INSERT INTO clinics ({cols}) VALUES ({marks})", (slug, *fields.values()))
    return cur.lastrowid


def _treatment_id(conn: sqlite3.Connection, item: dict) -> int:
    row = conn.execute(
        "SELECT id FROM treatments WHERE treatment_zh=? AND variant_zh=?",
        (item.get("treatment_zh"), item.get("variant_zh")),
    ).fetchone()
    if not row:
        raise IngestError(f"未知 treatment: {item.get('treatment_zh')}/{item.get('variant_zh')},请先在 treatments 中登记")
    return row["id"]


def ingest_record(conn: sqlite3.Connection, record: dict) -> dict:
    summary = {"treatments": 0, "prices": 0, "ratings": 0, "reviews": 0, "xhs_posts": 0,
               "archives": 0, "offerings": 0, "knowledge": 0, "doctors": 0, "branches": 0}
    try:
        clinic_id = _upsert_clinic(conn, record.get("clinic") or {})

        for t in record.get("treatments", []):
            for f in ("category", "treatment_zh", "variant_zh"):
                _require(t, f, "treatments")
            defaults = {"treatment_ko": None, "variant_ko": None, "variant_en": None, "notes": None}
            conn.execute(
                """INSERT OR IGNORE INTO treatments
                   (category, treatment_zh, treatment_ko, variant_zh, variant_ko, variant_en, notes)
                   VALUES (:category, :treatment_zh, :treatment_ko, :variant_zh, :variant_ko, :variant_en, :notes)""",
                {**defaults, **t},
            )
            summary["treatments"] += 1

        for p in record.get("prices", []):
            _require(p, "source_url", "prices")
            price = p.get("price_krw")
            if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
                raise IngestError(f"prices 条目 price_krw 必须为正整数(韩元), got {price!r}: {json.dumps(p, ensure_ascii=False)[:200]}")
            tid = _treatment_id(conn, p) if p.get("treatment_zh") else None
            cur = conn.execute(
                """INSERT INTO prices (clinic_id, treatment_id, raw_name_ko, raw_name_zh, price_krw,
                                       is_event_price, spec_notes, source_url, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (clinic_id, tid, p.get("raw_name_ko"), p.get("raw_name_zh"),
                 price, int(p.get("is_event_price", 0)), p.get("spec_notes"),
                 p["source_url"], p.get("collected_at", _today())),
            )
            for comp in p.get("components", []):
                conn.execute(
                    "INSERT OR IGNORE INTO price_components (price_id, treatment_id) VALUES (?,?)",
                    (cur.lastrowid, _treatment_id(conn, comp)),
                )
            summary["prices"] += 1

        for r in record.get("ratings", []):
            _require(r, "source_url", "ratings")
            _require(r, "source", "ratings")
            conn.execute(
                "INSERT INTO ratings (clinic_id, source, score, review_count, source_url, collected_at) VALUES (?,?,?,?,?,?)",
                (clinic_id, r["source"], r.get("score"), r.get("review_count"), r["source_url"], r.get("collected_at", _today())),
            )
            summary["ratings"] += 1

        for r in record.get("reviews", []):
            _require(r, "post_url", "reviews")
            issue = r.get("issue_type")
            if issue is not None and issue not in ISSUE_VALUES:
                raise IngestError(f"reviews 条目 issue_type 必须 ∈ {ISSUE_VALUES}, got {issue!r}")
            if issue and r.get("sentiment") != "negative":
                raise IngestError("reviews 的 issue_type 只用于 sentiment='negative' 的条目")
            conn.execute(
                """INSERT INTO reviews (clinic_id, source, text_original, text_zh, sentiment, issue_type,
                                        post_url, posted_at, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (clinic_id, r.get("source", "naver"), r.get("text_original"), r.get("text_zh"),
                 r.get("sentiment"), issue, r["post_url"], r.get("posted_at"), r.get("collected_at", _today())),
            )
            summary["reviews"] += 1

        for x in record.get("xhs_posts", []):
            _require(x, "url", "xhs_posts")
            nature = x.get("nature") or "未判定"
            if nature not in NATURE_VALUES:
                raise IngestError(
                    f"xhs_posts 条目 nature 必须 ∈ {NATURE_VALUES}, got {nature!r}"
                    f"(性质判定证据写 summary_zh): {json.dumps(x, ensure_ascii=False)[:200]}")
            conn.execute(
                "INSERT INTO xhs_posts (clinic_id, url, title, sentiment, nature, summary_zh, posted_at, collected_at) VALUES (?,?,?,?,?,?,?,?)",
                (clinic_id, x["url"], x.get("title"), x.get("sentiment"), nature, x.get("summary_zh"),
                 x.get("posted_at"), x.get("collected_at", _today())),
            )
            summary["xhs_posts"] += 1

        for o in record.get("offerings", []):
            _require(o, "source_url", "offerings")
            _require(o, "category", "offerings")
            conn.execute(
                """INSERT INTO clinic_offerings (clinic_id, category, name_ko, name_zh, name_en,
                                                 description_zh, source_url, collected_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(clinic_id, category, name_ko) DO UPDATE SET
                     name_zh=excluded.name_zh, name_en=excluded.name_en,
                     description_zh=excluded.description_zh,
                     source_url=excluded.source_url, collected_at=excluded.collected_at""",
                (clinic_id, o["category"], o.get("name_ko"), o.get("name_zh"), o.get("name_en"),
                 o.get("description_zh"), o["source_url"], o.get("collected_at", _today())),
            )
            summary["offerings"] += 1

        for k in record.get("knowledge", []):
            _require(k, "category", "knowledge")
            _require(k, "name_zh", "knowledge")
            _require(k, "summary_zh", "knowledge")
            # 子型号条目:parent_zh 指向同类别下的父条目(父条目须先于子条目出现/已在库)
            parent_id = None
            if k.get("parent_zh"):
                prow = conn.execute(
                    "SELECT id FROM knowledge_items WHERE category=? AND name_zh=?",
                    (k["category"], k["parent_zh"])).fetchone()
                if not prow:
                    raise IngestError(f"knowledge 条目 parent_zh 未找到父条目: {k['parent_zh']}(须同类别且先行录入)")
                parent_id = prow["id"]
            conn.execute(
                """INSERT INTO knowledge_items (category, name_zh, name_ko, name_en, origin,
                                                summary_zh, source_url, collected_at, parent_id)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(category, name_zh) DO UPDATE SET
                     name_ko=excluded.name_ko, name_en=excluded.name_en, origin=excluded.origin,
                     summary_zh=excluded.summary_zh, source_url=excluded.source_url,
                     collected_at=excluded.collected_at, parent_id=excluded.parent_id""",
                (k["category"], k["name_zh"], k.get("name_ko"), k.get("name_en"), k.get("origin"),
                 k["summary_zh"], k.get("source_url"), k.get("collected_at", _today()), parent_id),
            )
            summary["knowledge"] += 1

        for d in record.get("doctors", []):
            _require(d, "source_url", "doctors")
            _require(d, "name_ko", "doctors")
            conn.execute(
                """INSERT INTO doctors (clinic_id, name_ko, name_zh, title, credentials_zh,
                                        is_specialist, source_url, collected_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(clinic_id, name_ko) DO UPDATE SET
                     name_zh=excluded.name_zh, title=excluded.title,
                     credentials_zh=excluded.credentials_zh, is_specialist=excluded.is_specialist,
                     source_url=excluded.source_url, collected_at=excluded.collected_at""",
                (clinic_id, d["name_ko"], d.get("name_zh"), d.get("title"), d.get("credentials_zh"),
                 d.get("is_specialist", "unknown"), d["source_url"], d.get("collected_at", _today())),
            )
            summary["doctors"] += 1

        for b in record.get("branches", []):
            _require(b, "source_url", "branches")
            _require(b, "name_ko", "branches")
            conn.execute(
                """INSERT INTO branches (clinic_id, name_ko, name_zh, address_ko, naver_place_url,
                                         visitor_reviews, blog_reviews, is_primary, source_url, collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(clinic_id, name_ko) DO UPDATE SET
                     name_zh=excluded.name_zh, visitor_reviews=excluded.visitor_reviews,
                     blog_reviews=excluded.blog_reviews, collected_at=excluded.collected_at,
                     source_url=excluded.source_url""",
                (clinic_id, b["name_ko"], b.get("name_zh"), b.get("address_ko"),
                 b.get("naver_place_url"), b.get("visitor_reviews"), b.get("blog_reviews"),
                 int(b.get("is_primary", 0)), b["source_url"], b.get("collected_at", _today())),
            )
            summary["branches"] += 1

        for a in record.get("archives", []):
            _require(a, "file_path", "archives")
            conn.execute(
                "INSERT INTO archives (clinic_id, file_path, description, source_url, fetched_at) VALUES (?,?,?,?,?)",
                (clinic_id, a["file_path"], a.get("description"), a.get("source_url"), a.get("fetched_at", _today())),
            )
            summary["archives"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return summary


if __name__ == "__main__":
    record = json.loads(Path(sys.argv[1]).read_text())
    result = ingest_record(connect(), record)
    print(json.dumps(result, ensure_ascii=False))
