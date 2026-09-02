import hashlib

from scripts.export_static import _strip_xsec, export


def test_strip_xsec_removes_token_params_keeps_url():
    s = '{"url":"https://www.xiaohongshu.com/explore/abc123?xsec_token=ABtok-_=&xsec_source=pc_search"}'
    assert _strip_xsec(s) == '{"url":"https://www.xiaohongshu.com/explore/abc123"}'
    # 无 token 的 URL 原样保留
    assert _strip_xsec('{"url":"https://a.com/p?q=1"}') == '{"url":"https://a.com/p?q=1"}'


def test_export_static_builds_site(tmp_db, tmp_path):
    out = tmp_path / "dist"
    export(out, include_archive=False)

    # API 快照齐全且合法 JSON(空库下也应产出结构)
    import json
    assert json.loads((out / "api" / "clinics" / "index.json").read_text(encoding="utf-8")) == []
    for name in ("treatments", "compare_all", "trends", "knowledge", "fx"):
        json.loads((out / "api" / f"{name}.json").read_text(encoding="utf-8"))

    # 页面注入静态标志,绝对路径全部改写为相对
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "window.SB_STATIC=1" in idx
    assert 'href="/assets/' not in idx and '"/clinic.html' not in idx
    appjs = (out / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'href="/"' not in appjs  # 页头导航已相对化

    # 默认不带口令门:直接进总览
    assert 'src="assets/gate.js"' not in idx
    assert not (out / "assets" / "gate.js").exists()

    assert (out / "robots.txt").exists() and (out / ".nojekyll").exists()


def test_export_static_passcode_opts_in_gate(tmp_db, tmp_path):
    out = tmp_path / "dist"
    export(out, "test-passcode", include_archive=False)

    idx = (out / "index.html").read_text(encoding="utf-8")
    assert 'src="assets/gate.js"' in idx
    # 口令哈希已注入,占位符不残留
    gate = (out / "assets" / "gate.js").read_text(encoding="utf-8")
    assert hashlib.sha256(b"test-passcode").hexdigest() in gate
    assert "__GATE_HASH__" not in gate
