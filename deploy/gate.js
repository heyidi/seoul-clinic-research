(() => {
  if (!window.SB_STATIC) return;
  const HASH = "__GATE_HASH__";
  const KEY = "sb_gate_v1";
  try { if (localStorage.getItem(KEY) === HASH) return; } catch { return; }
  document.documentElement.style.visibility = "hidden";

  const sha256 = async (s) => {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
    return [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, "0")).join("");
  };

  const show = () => {
    const div = document.createElement("div");
    div.id = "gate";
    div.innerHTML = `
      <style>
        #gate { position: fixed; inset: 0; z-index: 99999; background: #fff; visibility: visible;
                display: flex; align-items: center; justify-content: center;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
        #gate .gate-box { text-align: center; padding: 2rem; max-width: 320px; }
        #gate h1 { font-size: 1.2rem; font-weight: 650; color: #1f2328; margin: 0 0 .4rem; }
        #gate p { color: #57606a; font-size: .9rem; margin: .3rem 0 1rem; }
        #gate input { font-size: 1rem; padding: .5rem .8rem; border: 1px solid #e6e8eb;
                      border-radius: 8px; width: 100%; box-sizing: border-box; text-align: center; }
        #gate button { margin-top: .7rem; font-size: .95rem; padding: .5rem 1.4rem; cursor: pointer;
                       border: none; border-radius: 8px; background: #2563eb; color: #fff; width: 100%; }
        #gate .gate-err { color: #d1242f; font-size: .85rem; }
      </style>
      <div class="gate-box">
        <h1>Seoul Beauty 医美对比</h1>
        <p>朋友间分享的个人调研站,请输入访问口令。</p>
        <form><input type="password" placeholder="访问口令" autocomplete="off"><button type="submit">进入</button></form>
        <p class="gate-err" hidden>口令不对,再试试。</p>
      </div>`;
    document.body.appendChild(div);
    document.documentElement.style.visibility = "";
    const input = div.querySelector("input");
    const err = div.querySelector(".gate-err");
    input.focus();
    div.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      if (!crypto.subtle) { err.textContent = "浏览器不支持校验(需 https 访问)"; err.hidden = false; return; }
      if ((await sha256(input.value.trim())) === HASH) {
        try { localStorage.setItem(KEY, HASH); } catch { /* 隐私模式:本次会话内直接放行 */ }
        div.remove();
      } else {
        err.hidden = false;
        input.select();
      }
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", show);
  else show();
})();
