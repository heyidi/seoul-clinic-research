#!/usr/bin/env python3
"""小红书只读抓取的**唯一入口**——强制限频/限次/只读白名单,防封号。

背景:此前直接连调 xiaohongshu MCP 导致账号被封 7 天。所有 XHS 调用(人工或子 agent)
一律走本脚本,不再直接 `mcporter call xiaohongshu.*`。

用法:
    scripts/xhs_call.py search_feeds keyword=明洞丹雅
    scripts/xhs_call.py get_feed_detail feed_id=<id> xsec_token=<token>
    scripts/xhs_call.py quota        # 只看今日额度,不发起调用

机制(全部可用环境变量覆盖,默认保守):
    XHS_MIN_INTERVAL_SEC  两次调用最小间隔秒数(默认 25),实际再叠加 0~JITTER 抖动
    XHS_JITTER_SEC        随机抖动上限(默认 12)
    XHS_DAILY_CAP         每日调用上限(默认 20);达上限拒绝并退出码 3——当天停手
    XHS_STATE_FILE        额度状态文件(默认 ~/.agent-reach/xhs-data/xhs_quota.json,仓库外)

只读白名单:仅 search_feeds / get_feed_detail / user_profile。任何写操作
(点赞/评论/收藏/关注/发帖)一律拒绝(退出码 4),从机制上杜绝越权。

退出码:0 正常;2 参数错误;3 今日额度用尽;4 方法不在只读白名单;5 mcporter 调用失败。
"""
import json
import os
import random
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

READ_ONLY_METHODS = {"search_feeds", "get_feed_detail", "user_profile"}

MIN_INTERVAL = float(os.environ.get("XHS_MIN_INTERVAL_SEC", "25"))
JITTER = float(os.environ.get("XHS_JITTER_SEC", "12"))
DAILY_CAP = int(os.environ.get("XHS_DAILY_CAP", "20"))
STATE_FILE = Path(os.environ.get(
    "XHS_STATE_FILE", str(Path.home() / ".agent-reach" / "xhs-data" / "xhs_quota.json")))


def _load_state() -> dict:
    try:
        s = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    today = date.today().isoformat()
    if s.get("date") != today:
        s = {"date": today, "count": 0, "last_ts": 0.0}
    s.setdefault("count", 0)
    s.setdefault("last_ts", 0.0)
    return s


def _save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False))


def _print_quota(s: dict) -> None:
    remaining = max(0, DAILY_CAP - s["count"])
    print(f"[xhs quota] 日期 {s['date']} · 今日已用 {s['count']}/{DAILY_CAP} · 剩余 {remaining} "
          f"· 最小间隔 {MIN_INTERVAL:.0f}s(+0~{JITTER:.0f}s 抖动)", file=sys.stderr)


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2

    method = argv[0]
    s = _load_state()

    if method == "quota":
        _print_quota(s)
        return 0

    if method not in READ_ONLY_METHODS:
        print(f"[xhs] 拒绝:方法 '{method}' 不在只读白名单 {sorted(READ_ONLY_METHODS)}。"
              f"绝不点赞/评论/收藏/关注/发帖。", file=sys.stderr)
        return 4

    if s["count"] >= DAILY_CAP:
        print(f"[xhs] 今日抓取额度已用尽({s['count']}/{DAILY_CAP})。请明天再抓——"
              f"分多天少量抓取是防封号的核心纪律,不要提高上限硬抓。", file=sys.stderr)
        _print_quota(s)
        return 3

    # 限频:距上次调用不足最小间隔则补足,再叠加随机抖动(拟人化,避免固定节奏)
    wait = MIN_INTERVAL - (time.time() - s["last_ts"])
    wait = max(0.0, wait) + random.uniform(0, JITTER)
    if wait > 0:
        print(f"[xhs] 限频等待 {wait:.1f}s…", file=sys.stderr)
        time.sleep(wait)

    cmd = ["mcporter", "call", f"xiaohongshu.{method}", *argv[1:]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("[xhs] 找不到 mcporter(在 ~/.local/bin,确认 PATH)。", file=sys.stderr)
        return 5

    # 无论成败都记一次调用(已经打到了平台),推进额度与时间戳
    s["count"] += 1
    s["last_ts"] = time.time()
    _save_state(s)

    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        print(f"[xhs] mcporter 返回码 {proc.returncode}:{proc.stderr.strip()[:300]}", file=sys.stderr)
        _print_quota(s)
        return 5

    _print_quota(s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
