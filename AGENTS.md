# AGENTS.md — 给 AI agent 的项目操作手册

这是一套"可核验医美诊所对比站"的完整工具链:SQLite 落盘数据库 + FastAPI 只读 API + 原生 JS 中文前端 + 静态导出发布。核心价值是**可核验的真实数据**——每条价格/评分/评论都带来源 URL 和采集日期,**无来源不入库**。

> Claude Code 用户:把本文件复制为 `CLAUDE.md` 即自动加载;支持 AGENTS.md 约定的框架无需任何操作。
> 领域术语(规格/套餐/体验价/未获取/软广/归因等)以根目录 `CONTEXT.md` 为准,写代码和录数据前先对齐。

## 调研任务执行入口

用户说「调研 XX 诊所」时,按此执行:
1. 先完整读 `skills/researching-korean-clinics/SKILL.md`(方法论与红线)和 `docs/data-format.md`(记录契约)
2. 身份三方互证解析韩文正名 → 采集资质/价格/口碑(每条带 source_url,拿不到标"未获取")
3. 产出 `data/records/<slug>-<今天日期>.json`,跑 `.venv/bin/python scripts/ingest.py <文件>` 直到通过
4. 汇报:已证实清单 / 风险点 / 未获取项及原因(不写担保性措辞)

抓取渠道:NAVER 内置零依赖;小红书需先装 [Agent Reach](https://github.com/Panniantong/Agent-Reach)
提供的 xiaohongshu 后端且**只准经 `scripts/xhs_call.py`**;未配置则跳过该渠道并在 notes 注明。

## 常用命令

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt  # 初始化环境
.venv/bin/python scripts/init_db.py              # 建库+种子字典(幂等)
.venv/bin/python scripts/ingest.py data/records/<slug>-<date>.json  # 录入一份调研记录(强校验,整单回滚)
.venv/bin/uvicorn app.main:app --port 8899       # 本地起站 → http://localhost:8899
.venv/bin/pytest tests/ -q                       # 测试门禁(改完必须全绿)
.venv/bin/python scripts/snapshot_naver.py       # NAVER 评论数每日快照:主店(源名 naver_map/naver_blog)+ 各分店
                                                 # (源名 naver_map_b<place_id>);幂等按 (诊所,源名,当日);--dry 只打印;--main 只抓主店
.venv/bin/python scripts/export_static.py        # 导出纯静态站到 dist/(--passcode 自设口令)
SITE_REPO=you/your-site deploy/publish_site.sh   # 发布到 GitHub Pages 产物仓
```

## 数据流

```
调研(AI agent + 人工核对)→ data/records/<slug>-<date>.json(保留,便于审计/重放)
  → scripts/ingest.py(强校验+整体回滚)→ SQLite → 只读 API → 前端
原始网页/价目图快照 → data/archive/<slug>/ 并登记 archives 表
```

**比价对齐轴**:`treatments` 字典(category>treatment>variant 三级)是跨诊所比价的锚。
`prices.treatment_id` 可为 NULL(套餐/规格不明者不进比价轴,仅详情页展示)。
记录格式详见 `docs/data-format.md`;调研方法论见 `skills/researching-korean-clinics/SKILL.md`。

## 录入校验规则(ingest.py 强制)

- prices/ratings/offerings/doctors 必须带 `source_url`;reviews 必须带 `post_url`;xhs_posts 必须带 `url`
- `price_krw` 必须正整数韩元(拒绝 bool/浮点/字符串);价格永远取**实卖价**,划线原价进备注
- xhs_posts 的 `nature` 受控词表:官方号/KOC系列/店家互动帖/素人/归因存疑/未判定(词表外整单回滚)
- treatment 引用不存在则报错(可在同一 record 的 `treatments` 块先登记新规格)
- 任一条目非法则整个 record 回滚;`collected_at` 缺省为今天

## 调研纪律(硬约束,派子 agent 时必须在指令里重申)

- **反爬机制一律不绕过**:遇 JS cookie 质询站(CUPID/slowAES 等),如实标"未获取"或改走
  NAVER 等合法渠道,不得解密/复现质询算法取数
- **小红书只经 `scripts/xhs_call.py` 发起**(强制限频 25s+/每日 ≤20 次/只读白名单);
  绝不点赞/评论/收藏/关注/发帖;额度用尽当天停手,分多天少量抓
- **差评必须保留**;软广(官方号/KOC/店家互动帖)如实标注性质,不隐藏也不冒充素人口碑
- 身份核验先于一切:官网 ↔ NAVER Place ↔ 官方社媒三方互证,谨防同名/音近仿冒
- 拿不到就标"未获取",**绝不编造**;金额保留韩元,不做币种换算
- 每次口径取舍/身份甄别/存疑判断,追加到 `docs/research-journal.md` 并随 git 提交

## 前端纪律

- 无构建步骤,纯静态。所有数据插值必须过 `esc()`(app.js),slug 进 URL 用 `encodeURIComponent`
- 双运行模式:FastAPI(默认)与静态托管(`window.SB_STATIC`,构建时注入)——新增 API 端点
  必须同步 export_static.py 的导出清单与 app.js fetchJSON 映射
- 展示三原则:①调研长文走 renderProse 三层拆解(【】小节头/①②③枚举/按句拆行),不许整段文墙;
  ②文本列宽用 px 不用 ch(ch 对中文会缩成假窄列);③低信息密度内容默认折叠,结论常显、过程可展开——
  折叠面板必须**自带常驻收起入口**,不能只靠远处的触发按钮;开合状态存 localStorage 时读写必须 try/catch
  (页面脚本是一个 IIFE,未捕获异常=白屏)
- **分店是主档案的一个属性(连锁版图),不是同级行**:branches 只有店名/地址/两个评论数,没有价格/医生/指数,
  因此总览页不做"表中表"(嵌套表会把版图清单伪装成可比较对象)。分店数字在 API 组装层 `align_branches`
  对齐 ratings 最新快照:主店取本诊所 naver_map/naver_blog(与主行同源同值),分店按 URL 里的 place_id 匹配;
  **同一 place_id 被多个源名覆盖时按 collected_at 择新**(不比日期会让赢家由 SQL 行序决定,数字在新旧值间漂)。
  `region` 由地址首词归一,前端据此分"本档所在地区常显 / 其他地区折叠"两组
- **采集状态不减分**:判据是「能读到内容但内容不合格 → 减分(对象的事实);根本没读到 → 0 分但保留标签
  (我们的采集状态)」。否则会出现倒挂:官网坦白写『一般医师』得 0 分,反而高于我们没查到的 -0.5;
  守反爬红线拿不到价的店被罚,等于惩罚自己的纪律。去掉减分后要检查高分档会不会被无实证对象蹭到,
  必要时加**准入闸门**——闸门条件必须落在对象侧(有真实价/有素人口碑/体量),**不要用"我们查了多少"
  (证据条数、覆盖维度)当门槛**,那是采集状态换个马甲
- **负面证据按严重度领域计分,不按条数**:能收集到多少差评取决于你翻得多深,按条数扣分是"惩罚自己挖得深"的另一种形态。改为按受控词表标问题领域、按领域是否出现计分(同领域多次只算一次);"付了 4cc 只打 2cc"这类是关于对象的确凿事实(一条就够),"等了 40 分钟"这类如实标注但不压分
- **分数要能自行复核**:标签可以只显示文案,但权重必须有落点(折叠明细/说明页)。留分数、撤依据、
  无解释入口,是把可核验退化成"我们说几分"
- **分类轴不要用质量轴的配色**:面诊风格(1v1/流水线)这类标签只是不同选择,统一中性配色靠文字区分,
  绿/橙/红留给真正的事实判定(已核实/红旗);算分不因分类加减分时,视觉更不该暗示优劣
- Leaflet 本地 vendored(web/assets/leaflet/),禁止引 CDN;价格只存韩元,折算仅在展示层

## 静态发布与脱敏

- `export_static.py` 会自动:剥离 XHS 链接里的 `xsec_token`(保护抓取账号)、抹除归档快照中
  第三方 API token(七类模式)、注入访问口令门(客户端软门,防路人不防内行,发布前自设口令)
- 发布产物仓走单提交强推,不留历史;源仓(含原始数据与审计线)建议保持私有
