import pytest

from app.db import connect
from scripts.ingest import IngestError, ingest_record

CLINIC = {"slug": "demo", "name_ko": "데모의원", "name_zh": "演示诊所", "verification_status": "verified"}


def test_upsert_clinic_and_insert_price(tmp_db):
    conn = connect()
    rec = {
        "clinic": CLINIC,
        "prices": [{
            "treatment_zh": "肉毒素", "variant_zh": "德国西马",
            "raw_name_ko": "제오민 50유닛", "raw_name_zh": "西马肉毒 50单位",
            "price_krw": 90000, "source_url": "https://example.com/price",
        }],
    }
    summary = ingest_record(conn, rec)
    assert summary["prices"] == 1
    row = conn.execute("SELECT p.price_krw, t.variant_zh FROM prices p JOIN treatments t ON t.id=p.treatment_id").fetchone()
    assert row["price_krw"] == 90000 and row["variant_zh"] == "德国西马"
    # upsert: 同 slug 再录只更新,不重复建档
    ingest_record(conn, {"clinic": {**CLINIC, "name_en": "Demo Clinic"}})
    rows = conn.execute("SELECT * FROM clinics").fetchall()
    assert len(rows) == 1 and rows[0]["name_en"] == "Demo Clinic" and rows[0]["name_zh"] == "演示诊所"


def test_price_without_source_rejected(tmp_db):
    conn = connect()
    rec = {"clinic": CLINIC, "prices": [{"treatment_zh": "肉毒素", "variant_zh": "德国西马", "price_krw": 90000}]}
    with pytest.raises(IngestError, match="source_url"):
        ingest_record(conn, rec)
    assert conn.execute("SELECT COUNT(*) c FROM clinics").fetchone()["c"] == 0  # 整体回滚


def test_unknown_treatment_rejected(tmp_db):
    conn = connect()
    rec = {"clinic": CLINIC, "prices": [{"treatment_zh": "不存在", "variant_zh": "X", "price_krw": 1, "source_url": "https://e.com"}]}
    with pytest.raises(IngestError, match="treatment"):
        ingest_record(conn, rec)


def test_price_krw_must_be_positive_int(tmp_db):
    conn = connect()
    for bad in ("abc", "90,000", -5000, 0, 12.5, None):
        rec = {"clinic": CLINIC, "prices": [{"treatment_zh": "肉毒素", "variant_zh": "德国西马",
                                             "price_krw": bad, "source_url": "https://e.com"}]}
        with pytest.raises(IngestError, match="price_krw"):
            ingest_record(conn, rec)
    assert conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"] == 0


def test_new_treatment_then_price(tmp_db):
    conn = connect()
    rec = {
        "clinic": CLINIC,
        "treatments": [{"category": "光电类", "treatment_zh": "LDM水滴提升", "variant_zh": "全脸 单次"}],
        "prices": [{"treatment_zh": "LDM水滴提升", "variant_zh": "全脸 单次", "price_krw": 150000, "source_url": "https://e.com"}],
    }
    assert ingest_record(conn, rec)["prices"] == 1


def test_review_and_xhs_url_required(tmp_db):
    conn = connect()
    with pytest.raises(IngestError, match="post_url"):
        ingest_record(conn, {"clinic": CLINIC, "reviews": [{"source": "naver", "text_zh": "好"}]})
    with pytest.raises(IngestError, match="url"):
        ingest_record(conn, {"clinic": CLINIC, "xhs_posts": [{"title": "帖"}]})


def test_collected_at_defaults_to_today(tmp_db):
    import datetime

    conn = connect()
    ingest_record(conn, {"clinic": CLINIC, "ratings": [{"source": "naver_map", "score": 4.8, "review_count": 321, "source_url": "https://map.naver.com/x"}]})
    row = conn.execute("SELECT collected_at FROM ratings").fetchone()
    assert row["collected_at"] == datetime.date.today().isoformat()


def test_offerings_doctors_knowledge_and_package_price(tmp_db):
    conn = connect()
    rec = {
        "clinic": CLINIC,
        "prices": [{"raw_name_ko": "패키지A", "raw_name_zh": "套餐A", "price_krw": 500000,
                    "is_event_price": 1, "source_url": "https://e.com/event"}],
        "offerings": [{"category": "提升设备", "name_ko": "울쎄라피 프라임", "name_zh": "超声刀Prime",
                       "source_url": "https://e.com/menu"}],
        "knowledge": [{"category": "肉毒素品牌", "name_zh": "西马", "name_ko": "제오민",
                       "origin": "德国Merz", "summary_zh": "纯毒素制剂", "source_url": "https://e.com/botox"}],
        "doctors": [{"name_ko": "홍길동", "name_zh": "洪吉童", "title": "代表院长",
                     "is_specialist": "specialist", "source_url": "https://e.com/staff"}],
    }
    s = ingest_record(conn, rec)
    assert s["prices"] == 1 and s["offerings"] == 1 and s["knowledge"] == 1 and s["doctors"] == 1
    assert conn.execute("SELECT treatment_id FROM prices").fetchone()["treatment_id"] is None
    # upsert 不重复
    ingest_record(conn, rec)
    assert conn.execute("SELECT COUNT(*) c FROM clinic_offerings").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM doctors").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM knowledge_items").fetchone()["c"] == 1


def test_offering_and_doctor_require_source(tmp_db):
    conn = connect()
    with pytest.raises(IngestError, match="source_url"):
        ingest_record(conn, {"clinic": CLINIC, "offerings": [{"category": "x", "name_ko": "y"}]})
    with pytest.raises(IngestError, match="source_url"):
        ingest_record(conn, {"clinic": CLINIC, "doctors": [{"name_ko": "홍길동"}]})


def test_price_components_semantic_mapping(tmp_db):
    conn = connect()
    rec = {
        "clinic": CLINIC,
        "prices": [{
            "raw_name_ko": "울쎄라 400샷+리쥬란 2cc", "raw_name_zh": "套餐",
            "price_krw": 1850000, "is_event_price": 1, "source_url": "https://e.com/pkg",
            "components": [
                {"treatment_zh": "超声提升(超声刀)", "variant_zh": "Ulthera 300线"},
                {"treatment_zh": "Rejuran婴儿针", "variant_zh": "Healer 2cc"},
            ],
        }],
    }
    ingest_record(conn, rec)
    n = conn.execute("SELECT COUNT(*) c FROM price_components").fetchone()["c"]
    assert n == 2
    # 未知规格的 component 整体回滚
    bad = {"clinic": {"slug": "demo2", "name_zh": "X"},
           "prices": [{"raw_name_ko": "p", "price_krw": 1000, "source_url": "https://e.com",
                       "components": [{"treatment_zh": "不存在", "variant_zh": "X"}]}]}
    with pytest.raises(IngestError):
        ingest_record(conn, bad)
    assert conn.execute("SELECT COUNT(*) c FROM clinics WHERE slug='demo2'").fetchone()["c"] == 0


def test_knowledge_parent_child_linkage(tmp_db):
    from app.db import connect
    from scripts.ingest import IngestError, ingest_record
    import pytest as _pytest
    conn = connect()
    ingest_record(conn, {"clinic": {"slug": "kb-demo"}, "knowledge": [
        {"category": "测试类", "name_zh": "家族", "summary_zh": "父条目"},
        {"category": "测试类", "name_zh": "型号A", "summary_zh": "子条目", "parent_zh": "家族"},
    ]})
    pid, cid_parent = conn.execute("SELECT parent_id, id FROM knowledge_items WHERE name_zh='家族'").fetchone()
    child_parent = conn.execute("SELECT parent_id FROM knowledge_items WHERE name_zh='型号A'").fetchone()[0]
    assert pid is None and child_parent == cid_parent
    # 父条目不存在 → 整单回滚
    with _pytest.raises(IngestError):
        ingest_record(conn, {"clinic": {"slug": "kb-demo"}, "knowledge": [
            {"category": "测试类", "name_zh": "孤儿", "summary_zh": "x", "parent_zh": "不存在的父"}]})
    conn.close()
