import re

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.scoring import score_clinic
from scripts.ingest import IngestError, ingest_record


@pytest.fixture()
def client(tmp_db):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def seeded(tmp_db):
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "demo-a", "name_zh": "演示A", "name_ko": "데모A", "verification_status": "verified"},
        "ratings": [
            {"source": "naver_map", "score": 4.2, "review_count": 100, "source_url": "https://map.naver.com/a", "collected_at": "2026-07-01"},
            {"source": "naver_map", "score": 4.5, "review_count": 120, "source_url": "https://map.naver.com/a", "collected_at": "2026-07-10"},
        ],
        "prices": [{"treatment_zh": "肉毒素", "variant_zh": "德国西马", "price_krw": 90000, "source_url": "https://a.com/p", "collected_at": "2026-07-01"}],
    })
    ingest_record(conn, {
        "clinic": {"slug": "demo-b", "name_zh": "演示B"},
        "prices": [{"treatment_zh": "肉毒素", "variant_zh": "德国西马", "price_krw": 110000, "source_url": "https://b.com/p", "collected_at": "2026-07-01"}],
    })
    conn.close()


def test_list_clinics_with_latest_rating(client, seeded):
    data = client.get("/api/clinics").json()
    assert len(data) == 2
    a = next(c for c in data if c["slug"] == "demo-a")
    assert a["latest_ratings"]["naver_map"]["score"] == 4.5
    assert a["latest_ratings"]["naver_map"]["review_count"] == 120


def test_latest_rating_tie_broken_by_insertion_order(client, seeded):
    conn = connect()
    for score in (3.0, 4.9):
        ingest_record(conn, {"clinic": {"slug": "demo-b"}, "ratings": [{
            "source": "naver_map", "score": score, "review_count": 10,
            "source_url": "https://map.naver.com/b", "collected_at": "2026-07-12"}]})
    conn.close()
    data = client.get("/api/clinics").json()
    b = next(c for c in data if c["slug"] == "demo-b")
    assert b["latest_ratings"]["naver_map"]["score"] == 4.9  # 同日并列取后插入(id 大)者


def test_treatments_grouped_order(client):
    data = client.get("/api/treatments").json()
    assert data[0]["category"] == "光电类"
    assert any(t["variant_zh"] == "德国西马" for t in data)


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "Seoul Beauty" in resp.text


def test_clinic_detail(client, seeded):
    data = client.get("/api/clinics/demo-a").json()
    assert data["name_zh"] == "演示A"
    assert len(data["rating_history"]) == 2
    assert data["prices"][0]["variant_zh"] == "德国西马"
    assert data["prices"][0]["price_krw"] == 90000


def test_clinic_detail_404(client, seeded):
    assert client.get("/api/clinics/nope").status_code == 404


def test_compare_lists_latest_offer_per_clinic_sorted(client, seeded):
    conn = connect()
    tid = conn.execute("SELECT id FROM treatments WHERE treatment_zh='肉毒素' AND variant_zh='德国西马'").fetchone()["id"]
    # demo-a 更新报价:同规格新采集应覆盖旧值
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "prices": [{
        "treatment_zh": "肉毒素", "variant_zh": "德国西马", "price_krw": 95000,
        "source_url": "https://a.com/p2", "collected_at": "2026-07-14"}]})
    conn.close()
    data = client.get(f"/api/compare?treatment_ids={tid}").json()
    assert len(data) == 1
    offers = data[0]["offers"]
    assert [o["clinic_slug"] for o in offers] == ["demo-a", "demo-b"]  # 95000 < 110000
    assert offers[0]["price_krw"] == 95000


def test_compare_empty_and_bad_ids(client, seeded):
    assert client.get("/api/compare?treatment_ids=").json() == []
    assert client.get("/api/compare?treatment_ids=99999").json() == []


def test_compare_same_day_recollection_single_offer(client, seeded):
    conn = connect()
    tid = conn.execute("SELECT id FROM treatments WHERE treatment_zh='肉毒素' AND variant_zh='德国西马'").fetchone()["id"]
    for price in (105000, 99000):
        ingest_record(conn, {"clinic": {"slug": "demo-b"}, "prices": [{
            "treatment_zh": "肉毒素", "variant_zh": "德国西马", "price_krw": price,
            "source_url": "https://b.com/p2", "collected_at": "2026-07-14"}]})
    conn.close()
    offers = client.get(f"/api/compare?treatment_ids={tid}").json()[0]["offers"]
    b_offers = [o for o in offers if o["clinic_slug"] == "demo-b"]
    assert len(b_offers) == 1            # 同日重复采集只出一条
    assert b_offers[0]["price_krw"] == 99000  # 后插入(id 大)者胜


def test_static_pages_have_shared_assets(client):
    for path in ("/", "/assets/app.js", "/assets/style.css"):
        assert client.get(path).status_code == 200
    assert "initPage" in client.get("/assets/app.js").text


def test_compare_page_served(client):
    resp = client.get("/compare.html")
    assert resp.status_code == 200 and "一键比价" in resp.text


def test_clinic_page_served(client):
    resp = client.get("/clinic.html")
    assert resp.status_code == 200 and "assets/app.js" in resp.text


def test_trends_page_and_endpoint(client, seeded):
    assert client.get("/trends.html").status_code == 200
    conn = connect()
    ingest_record(conn, {"clinic": {"slug": "trend-demo"}, "ratings": [
        {"source": "naver_map", "review_count": 100, "source_url": "https://m.place.naver.com/hospital/1/home", "collected_at": "2026-07-01"},
        {"source": "naver_map", "review_count": 160, "source_url": "https://m.place.naver.com/hospital/1/home", "collected_at": "2026-08-01"},
        {"source": "naver_blog", "review_count": 500, "source_url": "https://m.place.naver.com/hospital/1/home", "collected_at": "2026-08-01"}]})
    conn.close()
    a = next(c for c in client.get("/api/trends").json() if c["slug"] == "trend-demo")
    assert [p["c"] for p in a["visitor"]] == [100, 160]  # 按日期升序的时间序列
    assert a["blog"][-1]["c"] == 500


def test_map_page_and_leaflet_vendored(client):
    assert "leaflet/leaflet.js" in client.get("/map.html").text
    js = client.get("/assets/leaflet/leaflet.js")
    assert js.status_code == 200 and len(js.content) > 100000


def test_knowledge_endpoint_and_detail_extras(client, seeded):
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "demo-a"},
        "offerings": [{"category": "提升设备", "name_ko": "울쎄라", "name_zh": "超声刀", "source_url": "https://a.com/m"}],
        "doctors": [{"name_ko": "김의사", "name_zh": "金医生", "is_specialist": "general", "source_url": "https://a.com/s"}],
        "knowledge": [{"category": "肉毒素品牌", "name_zh": "西马", "summary_zh": "德国纯毒素", "source_url": "https://a.com/b"}],
    })
    conn.close()
    d = client.get("/api/clinics/demo-a").json()
    assert d["offerings"][0]["name_zh"] == "超声刀"
    assert d["doctors"][0]["is_specialist"] == "general"
    kb = client.get("/api/knowledge").json()
    assert any(k["name_zh"] == "西马" for k in kb)
    assert client.get("/knowledge.html").status_code == 200


def test_clinics_aggregates_for_compare_badges(client, seeded):
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "demo-a", "revisit_badge": 1},
        "doctors": [{"name_ko": "김전문", "is_specialist": "specialist", "source_url": "https://a.com/s"}],
        "reviews": [{"source": "naver", "text_zh": "差", "sentiment": "negative", "post_url": "https://a.com/r"}],
    })
    conn.close()
    a = next(c for c in client.get("/api/clinics").json() if c["slug"] == "demo-a")
    assert a["specialist_level"] == "specialist"
    assert a["negative_review_count"] == 1
    assert a["revisit_badge"] == 1


def test_compare_two_strata_packages(client, seeded):
    conn = connect()
    tid = conn.execute("SELECT id FROM treatments WHERE treatment_zh='肉毒素' AND variant_zh='德国西马'").fetchone()["id"]
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "prices": [{
        "raw_name_ko": "제오민+리쥬란 패키지", "raw_name_zh": "西马+Rejuran套餐", "price_krw": 500000,
        "is_event_price": 1, "source_url": "https://a.com/pkg",
        "components": [
            {"treatment_zh": "肉毒素", "variant_zh": "德国西马"},
            {"treatment_zh": "Rejuran婴儿针", "variant_zh": "Healer 2cc"},
        ]}]})
    conn.close()
    data = client.get(f"/api/compare?treatment_ids={tid}").json()[0]
    # 单项层不含套餐
    assert all("패키지" not in (o["raw_name_ko"] or "") for o in data["offers"])
    # 套餐层含该套餐及构成清单
    pkgs = data["package_offers"]
    assert len(pkgs) == 1 and pkgs[0]["price_krw"] == 500000
    assert "Rejuran婴儿针" in " ".join(pkgs[0]["component_names"])


def test_compare_lists_clinics_with_offering_but_no_price(client, seeded):
    conn = connect()
    tid = conn.execute("SELECT id FROM treatments WHERE treatment_zh='热玛吉' AND variant_zh='FLX 600发'").fetchone()["id"]
    # demo-b 官网清单里有热玛吉,但没有任何热玛吉报价
    ingest_record(conn, {"clinic": {"slug": "demo-b"}, "offerings": [
        {"category": "提升设备", "name_ko": "써마지 FLX", "name_zh": "热玛吉FLX", "source_url": "https://b.com/menu"}]})
    # demo-a 有该规格报价,不应重复出现在"无价格"列表
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "prices": [
        {"treatment_zh": "热玛吉", "variant_zh": "FLX 600发", "price_krw": 1650000,
         "source_url": "https://a.com/p", "collected_at": "2026-07-16"}]})
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "offerings": [
        {"category": "提升设备", "name_ko": "써마지 FLX", "name_zh": "热玛吉FLX", "source_url": "https://a.com/menu"}]})
    conn.close()
    d = client.get(f"/api/compare?treatment_ids={tid}").json()[0]
    slugs = [c["clinic_slug"] for c in d["available_no_price"]]
    assert "demo-b" in slugs and "demo-a" not in slugs


def test_clinic_branches_listed(client, seeded):
    conn = connect()
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "branches": [
        {"name_ko": "데모 본점", "name_zh": "本店", "visitor_reviews": 100, "blog_reviews": 50,
         "is_primary": 1, "source_url": "https://m.place.naver.com/hospital/1/home"},
        {"name_ko": "데모 2호점", "name_zh": "2号店", "visitor_reviews": 999, "blog_reviews": 10,
         "source_url": "https://m.place.naver.com/hospital/2/home"}]})
    conn.close()
    d = client.get("/api/clinics/demo-a").json()
    assert len(d["branches"]) == 2
    assert d["branches"][0]["is_primary"] == 1  # 主店排最前
    lst = next(c for c in client.get("/api/clinics").json() if c["slug"] == "demo-a")
    assert lst["branch_count"] == 2
    # 列表接口随行带分店明细(总览页默认展开逐店评论数),主店同样排最前
    assert [b["name_zh"] for b in lst["branches"]] == ["本店", "2号店"]
    assert lst["branches"][1]["visitor_reviews"] == 999


@pytest.fixture()
def branch_chain(tmp_db):
    """连锁诊所三种分店对齐场景:主店(快照已更新)/明洞店(有 place_id 可匹配的分店快照源)/九里店(无快照)。"""
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "chain-a", "name_zh": "连锁A"},
        "branches": [
            {"name_ko": "체인 신사점", "name_zh": "新沙店", "is_primary": 1,
             "naver_place_url": "https://m.place.naver.com/hospital/111/home",
             "visitor_reviews": 1229, "blog_reviews": 3658,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-07-17"},
            # naver_place_url 用 map.naver.com/p/entry/place/<id> 变体,对齐必须兼容两种 URL 形态
            {"name_ko": "체인 명동점", "name_zh": "明洞店",
             "naver_place_url": "https://map.naver.com/p/entry/place/222",
             "visitor_reviews": 114, "blog_reviews": 29,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-07-17"},
            {"name_ko": "체인 구리점", "name_zh": "九里店",
             "visitor_reviews": 55, "blog_reviews": 7,
             "source_url": "https://chain-a.com/branches", "collected_at": "2026-07-17"}],
        "ratings": [
            {"source": "naver_map", "review_count": 1257,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-08-20"},
            {"source": "naver_blog", "review_count": 3701,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-08-20"},
            # 分店快照源:源名(b2)与"明洞"无字面关系,只能靠 URL 里的 place_id=222 对齐;两次采集应取最新
            {"source": "naver_map_b2", "review_count": 114,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-07-17"},
            {"source": "naver_map_b2", "review_count": 130,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-08-20"},
            # 干扰快照:place_id=999 不属于任何分店,不得错配
            {"source": "naver_map_other", "review_count": 7777,
             "source_url": "https://m.place.naver.com/hospital/999/home", "collected_at": "2026-08-20"}],
    })
    conn.close()


def _branches_from_both_endpoints(client, slug):
    """列表与详情两个接口的 branches 都要对齐(总览分店表/详情分店一览同步受益)。"""
    lst = next(c for c in client.get("/api/clinics").json() if c["slug"] == slug)
    det = client.get(f"/api/clinics/{slug}").json()
    return lst, det


def test_branch_primary_row_matches_main_row_snapshot(client, branch_chain):
    for payload in _branches_from_both_endpoints(client, "chain-a"):
        primary = next(b for b in payload["branches"] if b["is_primary"])
        # 主店行与主行同源同值:取 ratings 最新快照,不再显示 branches 建档静态值(1229/3658)
        assert primary["visitor_reviews"] == payload["latest_ratings"]["naver_map"]["review_count"] == 1257
        assert primary["blog_reviews"] == payload["latest_ratings"]["naver_blog"]["review_count"] == 3701
        assert primary["visitor_as_of"] == primary["blog_as_of"] == "2026-08-20"


def test_branch_place_id_matched_takes_latest_snapshot(client, branch_chain):
    for payload in _branches_from_both_endpoints(client, "chain-a"):
        md = next(b for b in payload["branches"] if b["name_zh"] == "明洞店")
        assert md["visitor_reviews"] == 130      # place_id=222 对齐分店快照源,最新一次胜出
        assert md["visitor_as_of"] == "2026-08-20"
        assert md["blog_reviews"] == 29          # 该分店无博客快照 → 博客数回退静态值
        assert md["blog_as_of"] == "2026-07-17"


def test_branch_without_snapshot_keeps_static_value_with_date(client, branch_chain):
    for payload in _branches_from_both_endpoints(client, "chain-a"):
        guri = next(b for b in payload["branches"] if b["name_zh"] == "九里店")
        assert (guri["visitor_reviews"], guri["blog_reviews"]) == (55, 7)
        # 静态值必须带自己的采集日,"旧"要可见;干扰快照(place_id=999)不得错配进来
        assert guri["visitor_as_of"] == guri["blog_as_of"] == "2026-07-17"


def test_branch_same_place_id_two_source_names_takes_newest(client, tmp_db):
    """同一 place_id 被两个源名覆盖时按采集日择新——不许"赢家由 SQL 行序决定"。

    历史手工源名(naver_map_myeongdong)与脚本源名(naver_map_b<pid>)会并存一段时间;
    这里故意把旧日期那条**后插入**,行序上占优,断言仍是新日期的数字胜出。
    """
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "chain-d", "name_zh": "连锁D"},
        "branches": [
            {"name_ko": "체인D 본점", "name_zh": "本店", "is_primary": 1,
             "naver_place_url": "https://m.place.naver.com/hospital/111/home",
             "visitor_reviews": 1229, "blog_reviews": 3658,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-07-17"},
            {"name_ko": "체인D 명동점", "name_zh": "明洞店",
             "naver_place_url": "https://m.place.naver.com/hospital/222/home",
             "visitor_reviews": 100, "blog_reviews": 20,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-07-17"}],
        "ratings": [
            {"source": "naver_map_b222", "review_count": 130,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-08-20"},
            {"source": "naver_map_myeongdong", "review_count": 114,
             "source_url": "https://m.place.naver.com/hospital/222/home", "collected_at": "2026-07-17"}],
    })
    conn.close()
    for payload in _branches_from_both_endpoints(client, "chain-d"):
        md = next(b for b in payload["branches"] if b["name_zh"] == "明洞店")
        assert md["visitor_reviews"] == 130
        assert md["visitor_as_of"] == "2026-08-20"


def test_branch_region_normalized_from_address(client, tmp_db):
    """分店按地址首词给出 region(前端据此分"本档所在地区/其他地区"两组);광주광역시→광주。"""
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "chain-r", "name_zh": "连锁R"},
        "branches": [
            {"name_ko": "체인R 본점", "name_zh": "本店", "is_primary": 1,
             "address_ko": "서울 중구 남대문로 84", "visitor_reviews": 10,
             "source_url": "https://chain-r.com/branches", "collected_at": "2026-08-20"},
            {"name_ko": "체인R 광주점", "name_zh": "光州店",
             "address_ko": "광주광역시 서구 운천로 207", "visitor_reviews": 5,
             "source_url": "https://chain-r.com/branches", "collected_at": "2026-08-20"},
            {"name_ko": "체인R 미상점", "name_zh": "地址未获取店",
             "visitor_reviews": 1,
             "source_url": "https://chain-r.com/branches", "collected_at": "2026-08-20"}],
    })
    conn.close()
    for payload in _branches_from_both_endpoints(client, "chain-r"):
        got = {b["name_zh"]: b["region"] for b in payload["branches"]}
        assert got == {"本店": "서울", "光州店": "광주", "地址未获取店": None}


def test_branch_null_count_snapshot_does_not_clobber_static(client, tmp_db):
    """最新快照行 review_count 为空(ingest 合法)时,不得把分店有效静态值覆盖成 null。"""
    conn = connect()
    ingest_record(conn, {
        "clinic": {"slug": "chain-n", "name_zh": "连锁N"},
        "branches": [
            {"name_ko": "체인N 본점", "name_zh": "本店", "is_primary": 1,
             "naver_place_url": "https://m.place.naver.com/hospital/111/home",
             "visitor_reviews": 1229, "blog_reviews": 3658,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-07-17"}],
        "ratings": [
            # 最新快照只带 source+source_url,review_count 为空(NAVER 医院无星级口径下合法存在)
            {"source": "naver_map", "score": None,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-08-20"},
            {"source": "naver_blog", "score": None,
             "source_url": "https://m.place.naver.com/hospital/111/home", "collected_at": "2026-08-20"}],
    })
    conn.close()
    for payload in _branches_from_both_endpoints(client, "chain-n"):
        assert payload["latest_ratings"]["naver_map"]["review_count"] is None  # 空快照确为最新
        primary = next(b for b in payload["branches"] if b["is_primary"])
        # 静态值保留,as_of 仍为静态采集日——"未获取"只留给真没有的数据
        assert (primary["visitor_reviews"], primary["blog_reviews"]) == (1229, 3658)
        assert primary["visitor_as_of"] == primary["blog_as_of"] == "2026-07-17"


def test_available_no_price_uses_variant_match_hint(client, seeded):
    conn = connect()
    cur = conn.execute(
        "INSERT INTO treatments (category, treatment_zh, variant_zh, treatment_ko, variant_ko, match_hint)"
        " VALUES ('注射类','玻尿酸填充','唇部(丰唇)','필러','입술필러','입술|립|唇')")
    tid = cur.lastrowid
    conn.commit()
    # demo-b 有唇部专用 offering(命中 variant 关键词 립)→ 应出现
    ingest_record(conn, {"clinic": {"slug": "demo-b"}, "offerings": [
        {"category": "填充", "name_ko": "러시안 립필러", "name_zh": "俄式丰唇", "source_url": "https://b.com/menu"}]})
    # demo-a 只有泛用 필러 offering(命中 treatment 级但不命中 variant 关键词)→ 不应出现
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "offerings": [
        {"category": "填充", "name_ko": "필러", "name_zh": "玻尿酸填充", "source_url": "https://a.com/menu"}]})
    conn.close()
    d = client.get(f"/api/compare?treatment_ids={tid}").json()[0]
    slugs = [c["clinic_slug"] for c in d["available_no_price"]]
    assert "demo-b" in slugs and "demo-a" not in slugs


def test_xhs_nature_vocabulary_default_and_rollback(client, seeded):
    conn = connect()
    ingest_record(conn, {"clinic": {"slug": "demo-a"}, "xhs_posts": [
        {"url": "https://www.xiaohongshu.com/explore/p1", "title": "官方号帖",
         "sentiment": "中性", "nature": "官方号"},
        {"url": "https://www.xiaohongshu.com/explore/p2", "title": "未标性质帖",
         "sentiment": "推荐"},
    ]})
    # 词表外值 → IngestError 且整单回滚(p3 不落库)
    with pytest.raises(IngestError, match="nature"):
        ingest_record(conn, {"clinic": {"slug": "demo-a"}, "xhs_posts": [
            {"url": "https://www.xiaohongshu.com/explore/p3", "nature": "软广"}]})
    conn.close()
    posts = {p["url"]: p for p in client.get("/api/clinics/demo-a").json()["xhs_posts"]}
    assert posts["https://www.xiaohongshu.com/explore/p1"]["nature"] == "官方号"
    assert posts["https://www.xiaohongshu.com/explore/p2"]["nature"] == "未判定"
    assert "https://www.xiaohongshu.com/explore/p3" not in posts


def _base_signals(**kw):
    sig = {"verification_status": "verified", "specialist_level": "general", "price_count": 1,
           "real_price_count": 1, "negative_review_count": 0, "naver_reviews": 800,
           "xhs_marketing": 0, "xhs_authentic": 0, "xhs_total": 0}
    sig.update(kw)
    return sig


def test_score_strong_clinic_is_recommend():
    r = score_clinic(_base_signals(specialist_level="specialist", naver_reviews=2500))
    assert r["score"] >= 8.0 and r["band"] == "推荐"
    assert any("专科医师" in x["text"] for x in r["reasons"])


def test_score_legal_range_prices_not_counted_as_real():
    # 有价格条目但全是法定区间占位(real_price_count=0)→ 不给"有真实入库价"加分
    r = score_clinic(_base_signals(price_count=6, real_price_count=0))
    assert any("无实售价" in x["text"] for x in r["reasons"])
    assert not any("有真实入库价" in x["text"] for x in r["reasons"])


def test_score_missing_data_is_flagged_not_penalized():
    """采集状态(没读到)不减分,只标注;能读到但内容不合格的仍减分。

    2026-08-20 用户口径「获取不到价格不应该是减分项」。判据:没读到 → 0;
    读全了但不可比(仅法定区间价)/读到履历后判出疑点(资质存疑)→ 保留减分。
    """
    r = score_clinic(_base_signals(price_count=0, real_price_count=0, specialist_level=None))
    by = {x["text"]: x for x in r["reasons"]}
    assert by["价格未获取"]["delta"] == 0 and by["价格未获取"]["kind"] == "flag"
    assert by["医生资质未获取"]["delta"] == 0 and by["医生资质未获取"]["kind"] == "flag"
    # 有项目清单时文案不同,但同样是 0 分(成因"诊所不公示 vs 反爬抓不到"库里无法区分)
    r2 = score_clinic(_base_signals(price_count=0, real_price_count=0, offering_count=8))
    assert next(x for x in r2["reasons"] if "有项目清单" in x["text"])["delta"] == 0
    # 对照组:这两条是诊所的事实,必须仍然减分
    assert score_clinic(_base_signals(price_count=6, real_price_count=0))["reasons"]
    assert any(x["delta"] == -0.5 for x in score_clinic(
        _base_signals(price_count=6, real_price_count=0))["reasons"] if "无实售价" in x["text"])
    assert any(x["delta"] == -1 for x in score_clinic(
        _base_signals(specialist_level="unknown"))["reasons"] if "资质存疑" in x["text"])


def test_score_reason_text_carries_no_sign():
    """标签文案不得内嵌 ±N——界面只显示文案,权重走 delta 字段(用户口径)。"""
    r = score_clinic(_base_signals(specialist_level="specialist", naver_reviews=2500))
    for x in r["reasons"]:
        assert "+" not in x["text"] and "delta" in x
        assert not re.search(r"-\d", x["text"])


def test_score_recommend_gate_needs_clinic_side_evidence():
    """分够 8.0 但零实证信号 → 拦在中性;闸门条件全在诊所侧,不看"我们查了多少"。"""
    # 专科医(+2)+已核实(+1)=8.0,但无实价、无素人口碑、NAVER 仅 236
    thin = _base_signals(specialist_level="specialist", price_count=0, real_price_count=0,
                         naver_reviews=400, xhs_authentic=0)  # 300-499 为 0 分带,凑出净 8.0
    r = score_clinic(thin)
    assert r["score"] >= 8.0 and r["band"] == "中性" and r["gate_hits"] == []
    assert any("无实证信号" in x["text"] for x in r["reasons"])
    # 补上任一条诊所侧实证即可进推荐
    assert score_clinic({**thin, "real_price_count": 3, "price_count": 3})["band"] == "推荐"
    assert score_clinic({**thin, "xhs_authentic": 1})["band"] == "推荐"
    assert score_clinic({**thin, "naver_reviews": 500})["band"] == "推荐"


def test_score_thin_naver_is_flag_not_penalty():
    """样本薄不再扣分(2026-08-21 用户口径:可能只是新开或小众,1v1 接诊量本就有限)。"""
    r = score_clinic(_base_signals(naver_reviews=231))
    thin = next(x for x in r["reasons"] if "样本薄" in x["text"])
    assert thin["delta"] == 0 and thin["kind"] == "flag"


def test_score_negative_reviews_penalized_by_issue_domain_not_count():
    """差评按问题领域扣分,同领域多条只算一次——按条数扣会惩罚我们自己挖得深。"""
    one = score_clinic(_base_signals(negative_review_count=1, negative_issues={"量价不符"}))
    many = score_clinic(_base_signals(negative_review_count=5, negative_issues={"量价不符"}))
    assert one["score"] == many["score"]                      # 5 条同领域 == 1 条
    base = score_clinic(_base_signals())["score"]
    assert base - one["score"] == 1.5
    # 领域各自计,可叠加
    two = score_clinic(_base_signals(negative_review_count=2,
                                     negative_issues={"量价不符", "手法敷衍"}))
    assert base - two["score"] == 2.0
    # 等待/流程、内外有别存疑等如实标注但不压分
    soft = score_clinic(_base_signals(negative_review_count=3,
                                      negative_issues={"等待/流程", "内外有别存疑"}))
    assert soft["score"] == base
    assert all(x["kind"] == "flag" for x in soft["reasons"] if "差评指向" in x["text"])


def test_review_issue_type_vocabulary_enforced(client, tmp_db):
    """issue_type 走受控词表,词表外整单回滚;且只允许挂在差评上。"""
    conn = connect()
    bad = {"clinic": {"slug": "iss-a"}, "reviews": [
        {"source": "naver", "text_zh": "x", "sentiment": "negative",
         "issue_type": "随便编一个", "post_url": "https://x.com/r"}]}
    with pytest.raises(IngestError):
        ingest_record(conn, bad)
    misplaced = {"clinic": {"slug": "iss-a"}, "reviews": [
        {"source": "naver", "text_zh": "x", "sentiment": "positive",
         "issue_type": "量价不符", "post_url": "https://x.com/r"}]}
    with pytest.raises(IngestError):
        ingest_record(conn, misplaced)
    ingest_record(conn, {"clinic": {"slug": "iss-a"}, "reviews": [
        {"source": "naver", "text_zh": "付了4cc只打2cc", "sentiment": "negative",
         "issue_type": "量价不符", "post_url": "https://x.com/r"}]})
    conn.close()
    a = next(c for c in client.get("/api/clinics").json() if c["slug"] == "iss-a")
    assert any("差评指向:量价不符" in x["text"] and x["delta"] == -1.5 for x in a["rec_reasons"])
    assert client.get("/api/clinics/iss-a").json()["reviews"][0]["issue_type"] == "量价不符"


def test_score_xhs_marketing_red_line_caps_and_avoids():
    # 即便专门医+verified+有价+大体量,营销壁垒也把它压进"不推荐"且封顶≤3
    r = score_clinic(_base_signals(specialist_level="specialist", naver_reviews=3000,
                                   xhs_total=5, xhs_marketing=4, xhs_authentic=0))
    assert r["score"] <= 3.0 and r["band"] == "不推荐"
    assert any(x["kind"] == "danger" and "营销壁垒" in x["text"] for x in r["reasons"])


def test_score_red_line_needs_min_sample():
    # 样本不足门槛(<3 帖)即使占比高也不触发红线
    r = score_clinic(_base_signals(xhs_total=2, xhs_marketing=2))
    assert not any("营销壁垒" in x["text"] for x in r["reasons"])


def test_score_suspected_fake_is_avoid():
    r = score_clinic(_base_signals(verification_status="suspected_fake"))
    assert r["band"] == "不推荐"
    assert any(x["kind"] == "danger" and "仿冒" in x["text"] for x in r["reasons"])


def test_api_clinics_exposes_recommendation_fields(client, seeded):
    conn = connect()
    ingest_record(conn, {"clinic": {"slug": "demo-a", "verification_status": "verified"},
                         "doctors": [{"name_ko": "김전문", "is_specialist": "specialist", "source_url": "https://a.com/s"}]})
    conn.close()
    a = next(c for c in client.get("/api/clinics").json() if c["slug"] == "demo-a")
    assert isinstance(a["rec_score"], (int, float))
    assert a["rec_band"] in ("推荐", "中性", "不推荐")
    assert isinstance(a["rec_reasons"], list) and a["rec_reasons"]


def test_web_assets_send_no_cache_revalidation(client):
    # 前端三件套必须 no-cache(带 ETag 重验),否则浏览器缓存旧版,改版后用户看不到
    for path in ("/", "/index.html", "/assets/app.js", "/assets/style.css"):
        assert client.get(path).headers.get("cache-control") == "no-cache"
