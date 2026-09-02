/* 共享层:汇率、页头、来源角标 */
const FX = { rates: {}, fetched_at: null, stale: false };

/* 静态托管模式:构建脚本(scripts/export_static.py)向页面注入 window.SB_STATIC,
   此时无 FastAPI,API 路径映射到导出的静态 JSON;比价数据一次性加载后客户端过滤;
   汇率优先直连 frankfurter.dev,失败退回构建时烘焙值 */
const SB_STATIC = typeof window !== "undefined" && !!window.SB_STATIC;
let _compareAll = null;

async function _getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

async function fetchJSON(url) {
  if (!SB_STATIC) return _getJSON(url);
  const [path, query] = url.replace(/^\//, "").split("?");
  if (path === "api/clinics") return _getJSON("api/clinics/index.json");
  if (path.startsWith("api/clinics/")) return _getJSON(`${path}.json`);
  if (path === "api/compare") {
    if (!_compareAll) _compareAll = await _getJSON("api/compare_all.json");
    const ids = ((new URLSearchParams(query || "")).get("treatment_ids") || "")
      .split(",").filter(Boolean).map(Number);
    return _compareAll.filter((b) => ids.includes(b.treatment.id));
  }
  if (path === "api/fx") {
    try {
      const d = await _getJSON("https://api.frankfurter.dev/v1/latest?base=KRW&symbols=CNY,SGD");
      return { rates: d.rates, fetched_at: d.date, stale: false };
    } catch {
      return _getJSON("api/fx.json");
    }
  }
  return _getJSON(`${path}.json`); // api/treatments · api/trends · api/knowledge
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// 行内排版:先 esc,再 **强调**→粗体,再把连续谚文(韩文)包成灰色小字(中韩分色,跟随层级),
// 再把「引文」整体做浅底高亮(调研文里的评论原文证据,读时一眼可辨)
function fmtInline(text) {
  let s = esc(text).replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/[가-힣]+(?:[ ·/~]+[가-힣]+)*/g, (m) => `<span class="ko-inline">${m}</span>`);
  s = s.replace(/「[^」]*」/g, (m) => `<span class="q">${m}</span>`);
  return s;
}

// 调研长文渲染:识别 【小标题】/· 项目符号/⚠ 警示行/①②③ 枚举/空行分段,生成有结构的可读排版
function renderProse(text) {
  if (!text) return "";
  const out = [];
  let ul = null;
  const flush = () => { if (ul !== null) { out.push(`<ul class="prose-ul">${ul}</ul>`); ul = null; } };
  // 按句切分:「」《》()内的句号不算句界(评论引文/括注里常有完整句)
  const splitSentences = (s) => {
    const res = [];
    let cur = "", depth = 0;
    for (const ch of s) {
      cur += ch;
      if ("「《『【((".includes(ch)) depth++;
      else if ("」》』】))".includes(ch)) depth = Math.max(0, depth - 1);
      else if (depth === 0 && "。!?".includes(ch)) { if (cur.trim()) res.push(cur.trim()); cur = ""; }
    }
    if (cur.trim()) res.push(cur.trim());
    return res;
  };
  // 句首"主题:"加粗成扫读锚点(如 医师资质:/营业:/注意:)
  const topicize = (s) => {
    const m = s.match(/^([^,,。;;::「」()()《》]{2,12})([::])/);
    return m ? `<strong>${fmtInline(m[1] + m[2])}</strong>${fmtInline(s.slice(m[0].length))}` : fmtInline(s);
  };
  // 段落级渲染:①②③ 枚举拆条目;无枚举的长段按句拆行——调研日志的两种"文墙"各治一种
  const para = (line) => {
    const parts = line.split(/(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])/);
    if (parts.filter((p) => /^[①-⑮]/.test(p)).length >= 2) {
      const intro = /^[①-⑮]/.test(parts[0]) ? "" : parts.shift();
      if (intro.trim()) out.push(`<p class="prose-p">${fmtInline(intro.trim())}</p>`);
      out.push(`<ul class="prose-ul enum">${parts.map((p) => `<li>${topicize(p.trim())}</li>`).join("")}</ul>`);
      return;
    }
    const sents = splitSentences(line);
    if (line.length > 120 && sents.length >= 3) {
      out.push(`<ul class="prose-ul sent">${sents.map((s) => `<li>${topicize(s)}</li>`).join("")}</ul>`);
    } else {
      out.push(`<p class="prose-p">${topicize(line)}</p>`);
    }
  };
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    if (!line) { flush(); continue; }
    let m = line.match(/^【(.+?)】(.*)$/);
    if (m) {
      flush();
      out.push(`<p class="prose-h">${fmtInline(m[1])}</p>`);
      if (m[2].trim()) para(m[2].trim());
      continue;
    }
    m = line.match(/^[·•‧・∙]\s*(.+)$/) || line.match(/^[-–]\s+(.+)$/);
    if (m) { ul = (ul || "") + `<li>${fmtInline(m[1])}</li>`; continue; }
    if (/^⚠/.test(line)) { flush(); out.push(`<p class="prose-warn">${fmtInline(line)}</p>`); continue; }
    flush();
    para(line);
  }
  flush();
  return out.join("");
}

function getCurrency() { return localStorage.getItem("sb_currency") || "KRW"; }
function setCurrency(c) { localStorage.setItem("sb_currency", c); location.reload(); }
function manualRates() { try { return JSON.parse(localStorage.getItem("sb_manual_rates") || "{}"); } catch { return {}; } }

function activeRate(cur) {
  const manual = manualRates();
  if (manual[cur]) return { rate: manual[cur], manual: true };
  if (FX.rates[cur]) return { rate: FX.rates[cur], manual: false };
  return null;
}

function convert(krw) {
  if (krw == null) return null;
  const cur = getCurrency();
  if (cur === "KRW") return krw;
  const r = activeRate(cur);
  return r ? krw * r.rate : null;
}

function fmtPrice(krw) {
  if (krw == null) return "—";
  const cur = getCurrency();
  if (cur === "KRW") return "₩" + Number(krw).toLocaleString("en-US");
  const v = convert(krw);
  if (v == null) return "₩" + Number(krw).toLocaleString("en-US");
  const sym = cur === "CNY" ? "¥" : "S$";
  return sym + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function srcBadge(url, date) {
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) return "";
  const t = date ? `采集于 ${esc(date)}` : "";
  return `<a class="src" href="${esc(url)}" target="_blank" rel="noopener" title="${t}">来源</a>`;
}

// 分店评论数格子:数字+"截至日期"。数字来自 API 组装层对齐:主店=本诊所 ratings 最新
// 快照(与主行同源同值),place_id 匹配到快照的分店=快照值,其余回退 branches 静态值
// ——日期让静态旧值"旧"得可见
function branchNum(count, asOf) {
  if (count == null) return '<span class="muted">未获取</span>';
  const d = asOf ? `<span class="asof">截至 ${esc(asOf)}</span>` : "";
  return `${Number(count).toLocaleString("en-US")}${d}`;
}

// 面诊风格标签:从 notes 的【氛围判定:…】小节提取。取判定首段原文当标签(不强行二分,
// "走量型但非冷脸流水线"这类保留条件不丢),完整判定放 title;无判定=无标签,不冤枉。
function atmosphereOf(notes) {
  const m = /【氛围判定[::]([^】]+)】/.exec(notes || "");
  if (!m) return null;
  const full = m[1].trim();
  const tag = full.split(/[,,((——]/)[0].trim();
  const cls = /1[vV:]1|亲诊/.test(tag) ? "atm-1v1" : /流水线|走量/.test(tag) ? "atm-line" : "atm-mid";
  return { tag, full, cls };
}

function verifyBadge(status) {
  if (status === "verified") return '<span class="badge ok">已核实</span>';
  if (status === "suspected_fake") return '<span class="badge danger">疑似仿冒</span>';
  return '<span class="badge">未核实</span>';
}

function fxLabel() {
  const cur = getCurrency();
  if (cur === "KRW") return "";
  const r = activeRate(cur);
  if (!r) return "(汇率不可用)";
  const src = r.manual ? "手动汇率" : `实时汇率${FX.stale ? "(缓存值)" : ""} ${FX.fetched_at || ""}`;
  return `1 KRW = ${r.rate} ${cur} · ${src}`;
}

async function initPage(active) {
  // 汇率绝不阻塞页面渲染:最多等 2 秒,慢了就先渲染(韩元不受影响),到货后补更新页头标签
  const fxReady = fetchJSON("/api/fx").then((d) => Object.assign(FX, d)).catch(() => { /* KRW 仍可用 */ });
  await Promise.race([fxReady, new Promise((r) => setTimeout(r, 2000))]);
  fxReady.then(() => {
    const el = document.getElementById("fxLabel");
    if (el) el.textContent = fxLabel();
  });
  const cur = getCurrency();
  const header = document.createElement("header");
  header.className = "site";
  header.innerHTML = `
    <span class="logo">Seoul Beauty 医美对比</span>
    <nav>
      <a href="/" ${active === "index" ? 'class="active"' : ""}>总览</a>
      <a href="/compare.html" ${active === "compare" ? 'class="active"' : ""}>一键比价</a>
      <a href="/trends.html" ${active === "trends" ? 'class="active"' : ""}>口碑趋势</a>
      <a href="/map.html" ${active === "map" ? 'class="active"' : ""}>地图</a>
      <a href="/knowledge.html" ${active === "knowledge" ? 'class="active"' : ""}>知识库</a>
    </nav>
    <span class="fx">
      <span id="fxLabel" class="muted">${fxLabel()}</span>
      <select id="curSel">
        <option value="KRW" ${cur === "KRW" ? "selected" : ""}>₩ 韩元</option>
        <option value="CNY" ${cur === "CNY" ? "selected" : ""}>¥ 人民币</option>
        <option value="SGD" ${cur === "SGD" ? "selected" : ""}>S$ 新币</option>
      </select>
      <button id="fxBtn" type="button">汇率设置</button>
    </span>
    <dialog id="fxDlg">
      <h3>手动汇率(留空=用实时值)</h3>
      <p>1 KRW = <input id="mCNY" placeholder="${FX.rates.CNY ?? ""}"> CNY</p>
      <p>1 KRW = <input id="mSGD" placeholder="${FX.rates.SGD ?? ""}"> SGD</p>
      <p class="muted">实时汇率更新于 ${FX.fetched_at || "未知"}(frankfurter.dev)</p>
      <button id="fxSave" type="button">保存</button>
      <button id="fxClear" type="button">恢复自动</button>
      <button id="fxClose" type="button">关闭</button>
    </dialog>`;
  document.body.prepend(header);
  const dlg = document.getElementById("fxDlg");
  const manual = manualRates();
  document.getElementById("mCNY").value = manual.CNY ?? "";
  document.getElementById("mSGD").value = manual.SGD ?? "";
  document.getElementById("curSel").onchange = (e) => setCurrency(e.target.value);
  document.getElementById("fxBtn").onclick = () => dlg.showModal();
  document.getElementById("fxClose").onclick = () => dlg.close();
  document.getElementById("fxClear").onclick = () => { localStorage.removeItem("sb_manual_rates"); location.reload(); };
  document.getElementById("fxSave").onclick = () => {
    const m = {};
    const cny = parseFloat(document.getElementById("mCNY").value);
    const sgd = parseFloat(document.getElementById("mSGD").value);
    if (cny > 0) m.CNY = cny;
    if (sgd > 0) m.SGD = sgd;
    localStorage.setItem("sb_manual_rates", JSON.stringify(m));
    location.reload();
  };
  const footer = document.createElement("footer");
  footer.textContent = "数据为个人调研快照,仅供参考,不构成医疗建议。价格与评分以各官方渠道实时信息为准。";
  document.body.append(footer);
}
