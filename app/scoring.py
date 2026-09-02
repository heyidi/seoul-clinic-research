"""推荐预定指数(0-10)——**信号汇总,非空口担保**。

设计原则:项目核心是"可核验的档案"。本指数不是编辑主观推荐,而是把已采集的**可溯源信号**
按固定规则加总,每一分加减都对应一条能在诊所卡片上看到的事实标签(reasons)。读者一眼看到
分数与理由,能自行复核。担保性措辞不进入本模块。

用户特别关切:**小红书营销占比过高 = 壁垒红线**(官方号+KOC系列+店家互动帖为营销性质)。
命中红线时硬封顶并归入"不推荐"档,其他优点不能把它拉出该档。

**采集状态不减分**(2026-08-20 用户口径:"获取不到价格不应该是减分项")。判据是
**能读到内容但内容不合格 → 减分(诊所的事实);根本没读到 → 0 分但保留标签(我们的采集状态)**:
- 价格全未获取、医生资质未获取 = 没读到 → 0 分,只标注
- 仅法定区间价 = 读全了、是诊所主动选的合规最低限度公示,可读但不可比 → 保留 -0.5
- 资质存疑(专门医无科目/仅实习) = 读到履历后判出的疑点 → 保留 -1
- NAVER 样本薄 = 不再扣分(2026-08-21 用户口径:可能只是新开或小众,1v1 接诊量本就有限;
  且访客评需到店凭证、中文客不留痕,这个数量的是韩国本土客群)
**差评按问题领域扣分,不按条数**(2026-08-21 用户口径):差评条数取决于我们翻了多深,
按条数扣等于惩罚自己挖得深;而"付了 4cc 只打 2cc"这类是关于诊所的一条确凿事实,一条就够。
故按 reviews.issue_type 的**领域是否出现**计分,同领域多条只算一次,见 ISSUE_PENALTY。
去掉减分后 5.0+专科2+核实1 恰好=8.0,"推荐"档会被无实证的诊所蹭到,故把原本隐含的
选择性门槛显式化为 GATE:进"推荐"必须至少命中一条**诊所侧**实证信号(见 STRONG_SIGNALS)。
"""

BASE = 5.0
RED_LINE_MIN_POSTS = 3      # 营销红线样本门槛:XHS 帖数须 ≥ 此值才据占比判红线
RED_LINE_RATIO = 0.6        # 营销占比 ≥ 此值触发红线
RED_LINE_CAP = 3.0          # 红线命中后的分数封顶

BAND_GOOD = 8.0             # ≥ 推荐的分数线(还须过 GATE)
GATE_NAVER = 500            # 实证信号之一:NAVER 评论量达此值
# 进"推荐"档的准入信号(三选一)。刻意全部落在**诊所侧**——不用"我们查了多少"
# (证据条数/覆盖维度)当门槛,那是采集状态,会把反爬站再罚一次。
STRONG_SIGNALS = ("有真实入库价", "有素人真实口碑", f"NAVER 评论量≥{GATE_NAVER}")
# 差评领域权重(reviews.issue_type,词表见 scripts/ingest.py ISSUE_VALUES)。
# 0 分档=如实标注但不压分:等待/态度是常见波动且高度取决于个人在不在乎,
# "内外有别存疑""效果不满"分别是未坐实与主观预期。判定依据写在评论本身,可逐条复核。
ISSUE_PENALTY = {
    "量价不符": -1.5,        # 付款量与实际施打量不符——金钱层面可核的实证
    "成分调包": -1.5,        # 约定产品在收款后被更换
    "术后伤害·推诿": -1,     # 造成损伤且院方未处置
    "手法敷衍": -0.5,        # 施术草率(工厂型扫一遍/不看部位凭感觉下针)
}


# 展示与计分的稳定顺序(严重的在前);词表本身以 scripts/ingest.py ISSUE_VALUES 为准
ISSUE_VALUES_ORDER = ("量价不符", "成分调包", "术后伤害·推诿", "手法敷衍",
                      "等待/流程", "服务态度", "内外有别存疑", "效果不满", "其他")


def score_clinic(sig: dict) -> dict:
    """sig 字段:verification_status, specialist_level(specialist/general/unknown/None),
    price_count(实价条数), real_price_count, offering_count, negative_review_count,
    negative_issues(差评问题领域集合), naver_reviews, xhs_marketing, xhs_authentic, xhs_total。
    返回 {score, band, reasons:[{text,delta,kind}]}。
    kind ∈ plus/minus/flag/danger,前端据此上色;delta 供"这分怎么来的"明细展开,
    **不拼进 text**——卡片标签只显示文案(2026-08-20 用户口径)。"""
    score = BASE
    reasons = []

    def add(delta, text, kind):
        nonlocal score
        score += delta
        reasons.append({"text": text, "delta": delta, "kind": kind})

    # 医生资质(is_specialist 只表"有具名科目专门医",不区分科目——故不写"皮肤科")
    lvl = sig.get("specialist_level")
    if lvl == "specialist":
        add(2, "专科医师(官网具名科目)", "plus")
    elif lvl == "general":
        reasons.append({"text": "一般医师", "delta": 0, "kind": "flag"})
    elif lvl == "unknown":
        add(-1, "资质存疑(专门医无科目/仅实习)", "minus")
    else:  # None:无医生资料入库——没读到,不减分(否则官网坦白写"一般医师"得0分,
           # 反而高于我们没查到的 -0.5,不透明比透明得分高)
        add(0, "医生资质未获取", "flag")

    # 身份核验
    vs = sig.get("verification_status")
    if vs == "verified":
        add(1, "身份已核实", "plus")
    elif vs == "suspected_fake":
        add(-4, "疑似仿冒", "danger")
    else:
        add(-1, "身份未核实", "minus")

    # 价格透明度(实售价;法定区间等"非实际售价"占位不算)
    real_pc = sig.get("real_price_count", sig.get("price_count", 0))
    total_pc = sig.get("price_count", 0)
    if real_pc > 0:
        add(1, "有真实入库价", "plus")
    elif total_pc > 0:
        # 读全了、是诊所主动选的合规最低限度公示(如"보톡스 6만~20만원"不标品牌/单位数),
        # 可读但不可比 → 这是诊所的事实,保留减分
        add(-0.5, "仅法定区间价·无实售价", "minus")
    elif sig.get("offering_count", 0) > 0:
        # 成因(诊所不公示 vs 反爬我们抓不到)库里无字段可靠区分,故文案只描述我方档案
        # 状态、不归因;两种文案同为 0 分
        add(0, "有项目清单·暂无价格", "flag")
    else:
        add(0, "价格未获取", "flag")

    # 口碑真实性(素人)
    if sig.get("xhs_authentic", 0) >= 1:
        add(0.5, "有素人真实口碑", "plus")

    # NAVER 患者体量(代理指标):量大加分,样本过薄扣分(证据不足)
    nv = sig.get("naver_reviews")
    if nv is not None:
        if nv >= 2000:
            add(1, f"NAVER 评论量大({nv:,})", "plus")
        elif nv >= 500:
            add(0.5, f"NAVER 评论量中({nv:,})", "plus")
        elif nv < 300:
            # 不扣分:新开/小众/1v1 接诊量有限都会落在这一档,且这个数只覆盖韩国本土客群
            add(0, f"NAVER 样本薄({nv})", "flag")

    # 差评:条数只作透明度标注(保留差评是加分项文化),压分看**问题领域**
    neg = sig.get("negative_review_count", 0)
    if neg >= 1:
        reasons.append({"text": f"⚠ {neg} 条差评在档", "delta": 0, "kind": "flag"})
    # 同领域出现多次只算一次;按 ISSUE_PENALTY 的严重度降序稳定输出
    issues = set(sig.get("negative_issues") or ())
    for name in ISSUE_VALUES_ORDER:
        if name not in issues:
            continue
        pen = ISSUE_PENALTY.get(name, 0)
        add(pen, f"⚠ 差评指向:{name}", "minus" if pen else "flag")

    # 小红书营销壁垒——硬红线
    total = sig.get("xhs_total", 0)
    mkt = sig.get("xhs_marketing", 0)
    red = False
    if total >= RED_LINE_MIN_POSTS and mkt / total >= RED_LINE_RATIO:
        red = True
        pct = round(100 * mkt / total)
        reasons.append({"text": f"小红书营销壁垒({mkt}/{total} 帖 {pct}% 为营销)",
                        "delta": 0, "kind": "danger"})

    score = max(0.0, min(10.0, score))
    if red:
        score = min(score, RED_LINE_CAP)

    # 推荐档准入闸门:分数够了还须至少一条诊所侧实证信号。没有它,采集状态不减分之后
    # 5.0+专科2+核实1=8.0 就能让一家零价格零口碑的诊所蹭进"推荐"。
    gate = [s for s, hit in (
        (STRONG_SIGNALS[0], real_pc > 0),
        (STRONG_SIGNALS[1], sig.get("xhs_authentic", 0) >= 1),
        (STRONG_SIGNALS[2], nv is not None and nv >= GATE_NAVER),
    ) if hit]

    # 不推荐 = 有"主动红旗"(营销壁垒 / 疑似仿冒等 danger 级信号),而非仅仅分低。
    # 分低但只是资料不足(如反爬站、样本薄)归"中性",不冤枉进"不推荐"。
    # (档位旧称 避雷/建议去,2026-08-13 依用户口径更名 不推荐/推荐,判定规则未变)
    has_danger = any(r["kind"] == "danger" for r in reasons)
    if has_danger:
        band = "不推荐"
    elif score >= BAND_GOOD and gate:
        band = "推荐"
    else:
        band = "中性"
        if score >= BAND_GOOD:
            reasons.append({"text": "分数够但无实证信号(价格/素人口碑/NAVER体量),暂不进推荐",
                            "delta": 0, "kind": "flag"})

    return {"score": round(score, 1), "band": band, "reasons": reasons,
            "base": BASE, "gate_hits": gate}
