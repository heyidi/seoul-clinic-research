# 调研记录格式(data/records/*.json)

一份记录 = 一次调研的全部产出,按诊所落盘为 `data/records/<slug>-<日期>.json`,
经 `scripts/ingest.py` 强校验入库:**任一条目非法则整单回滚**。文件保留在仓库里,便于审计与重放。

## 顶层结构

```jsonc
{
  "clinic":     { ... },   // 必填,按 slug upsert
  "treatments": [ ... ],   // 可选:扩充比价规格字典
  "prices":     [ ... ],
  "ratings":    [ ... ],
  "reviews":    [ ... ],
  "xhs_posts":  [ ... ],
  "doctors":    [ ... ],
  "branches":   [ ... ],
  "offerings":  [ ... ],   // 诊所设备/药品清单(能力层,不含价格)
  "knowledge":  [ ... ],   // 跨诊所通识条目(全局)
  "archives":   [ ... ]    // 原始快照登记(文件放 data/archive/<slug>/)
}
```

## 各块字段与硬校验

### clinic(必填)
`slug`(必填,URL 安全的唯一标识)、`name_ko/name_en/name_zh`、`address_ko/address_zh`、
`lat/lng`、`official_site/naver_place_url/instagram/facebook`、
`verification_status`(verified/unverified/suspected_fake)、`verification_notes`(三方互证考据)、
`notes`(调研结论长文,支持【小标题】/①②③/「引文」结构化排版;写【氛围判定:…】小节可自动生成
面诊风格标签)、`editor_note`(一句话结论,≤160 字,长文放 notes)、`revisit_badge`、`opened_year`。

### treatments(扩充比价字典)
`category`(光电类/注射类/线雕类/其他)+ `treatment_zh` + `variant_zh` 必填;
`treatment_ko/variant_ko/variant_en/notes` 可选。同名幂等(INSERT OR IGNORE)。

### prices
- **必填**:`source_url`;`price_krw` 正整数韩元(**实卖价**;划线原价写进 `spec_notes`)
- `treatment_zh`+`variant_zh` 指向字典规格 → 进比价轴;省略则 treatment_id=NULL,仅详情页展示
  (套餐、规格不明、按部位重复计价的行,应当省略——不进轴是口径,不是缺陷)
- `raw_name_zh/raw_name_ko`(官网原名中韩对照)、`is_event_price`(活动价=1,正价=0)、
  `spec_notes`(VAT 口径/部位/发数/限制条件)、`collected_at`(实际采集日,缺省今天)
- `components`: [{treatment_zh, variant_zh}, ...] 套餐构成映射(可选,进套餐层比价)

### ratings
`source`(如 naver_map/naver_blog/google/modoodoc)+ `source_url` 必填;
`score` 可空(NAVER 对医院不显示星级属正常)、`review_count`、`collected_at`。
同店同源多日快照累积成时间序列,趋势页据此画增长曲线。

### reviews
`post_url` 必填;`text_original`(原文)+ `text_zh`(中译)中韩对照,**差评必须保留**;
`sentiment` ∈ positive/negative/neutral;正文尾部可写【编者标注】,前端自动移到 meta 行。

### xhs_posts
`url` 必填;`nature` **受控词表**:官方号/KOC系列/店家互动帖/素人/归因存疑/未判定
(词表外整单回滚;判定证据写 `summary_zh`);`sentiment` ∈ 推荐/差评/中性,与 nature 正交
(官方号发的差评口吻钩子帖 = 官方号 + 中性)。

### doctors
`name_ko` + `source_url` 必填;`is_specialist` ∈ specialist/general/unknown
(只有官网明载「X과 전문의」带科目才标 specialist);`credentials_zh` 写履历与疑点。

### branches
`name_ko` + `source_url` 必填;`visitor_reviews/blog_reviews` 逐店统计,`is_primary` 标主店。

### offerings / knowledge / archives
- offerings:`category` + `source_url` 必填,(clinic, category, name_ko) 幂等 upsert
- knowledge:`category` + `name_zh` + `summary_zh` 必填,标"通识"的可无单一来源
- archives:`file_path` 必填(相对 data/archive/ 的路径),`description/source_url/fetched_at`;
  图片类归档会在详情页"价目原图"画廊展示

## 最小可运行示例

见 `examples/records/demo-clinic-2026-01-01.json`(虚构诊所,可直接 ingest 验证环境):

```bash
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/ingest.py examples/records/demo-clinic-2026-01-01.json
```
