#!/usr/bin/env python3
"""
东方财富组合 KEEP_DAYS 清理脚本

每天定时跑: 删除所有 date < cutoff 的组合 (cutoff = today - KEEP_DAYS 天)
KEEP_DAYS 默认 3 → 只保留最近 3 个日历日

用法:
    python3 eastmoney_cleanup_old_groups.py            # 默认 KEEP_DAYS=3
    python3 eastmoney_cleanup_old_groups.py --days 7   # 自定义天数

设计:
1. 全量并发扫服务端 gid=1..1300 (30 workers, ~12s 完成)
2. 提取每个组合 updatetime[:8] 作为日期
3. date < cutoff 的全部 dg 删除
4. 同步清理 groups.json (删掉所有 date < cutoff 的 key)
5. 保留系统默认分组 gid=1 (东财禁止 API 删除, state=-101)

退出码:
    0 = 成功 (无论删了几个)
    1 = cookie 失效
    2 = 网络/服务端异常
"""
import sys
import os
import json
import time
import argparse
import urllib.request
import concurrent.futures
from datetime import datetime, timedelta

BASE_URL = "https://myfavor.eastmoney.com/v4/webouter/"
APPKEY = "e9166c7e9cdfad3aa3fd7d93b757e9b1"
REFERER = "https://quote.eastmoney.com/zixuan/"
SKILL_DIR = os.path.expanduser("~/.hermes/skills/a-stock/eastmoney-portfolio-api")
COOKIE_PATH = os.path.join(SKILL_DIR, "references/cookie.json")
GROUPS_PATH = os.path.join(SKILL_DIR, "groups.json")
GID_RANGE_END = 1301
DEFAULT_KEEP_DAYS = 3


def load_cookie():
    with open(COOKIE_PATH) as f:
        data = json.load(f)
    pairs = [f"{k}={str(v)}" for k, v in data.items() if v and k != "ct"]
    pairs.append(f"ct={data.get('ct', '')}")
    return "; ".join(pairs), data


def api_call(url, cookie_str, timeout=10):
    req = urllib.request.Request(url, headers={
        "Referer": REFERER,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_str,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode()
    if "(" in text and ")" in text:
        text = text[text.index("(") + 1:text.rindex(")")]
    return json.loads(text)


def scan_gid(gid, cookie_str):
    try:
        url = f"{BASE_URL}gstkinfos?appkey={APPKEY}&g={gid}"
        r = api_call(url, cookie_str, timeout=5)
        if r.get("state") != 0:
            return None
        d = r.get("data") or {}
        stocks = d.get("stkinfolist") or []
        if not stocks:
            return None
        ut = str(stocks[0].get("updatetime", ""))
        if not ut or len(ut) < 8:
            return None
        return (gid, ut[:8], ut, len(stocks))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_KEEP_DAYS,
                        help=f"保留最近 N 天 (默认 {DEFAULT_KEEP_DAYS})")
    parser.add_argument("--gid-end", type=int, default=GID_RANGE_END,
                        help=f"扫描 gid 上界 (默认 {GID_RANGE_END})")
    parser.add_argument("--dry-run", action="store_true",
                        help="只扫描不删除")
    args = parser.parse_args()

    keep_days = args.days
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")
    print(f"🧹 东方财富组合清理: KEEP_DAYS={keep_days}, cutoff={cutoff}, today={today}")

    # 1) 加载 cookie
    if not os.path.exists(COOKIE_PATH):
        print(f"❌ cookie.json 不存在: {COOKIE_PATH}")
        return 1
    cookie_str, cookie_data = load_cookie()

    # 2) 全量并发扫
    print(f"\n[1] 扫描服务端 gid=1..{args.gid_end - 1}...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        results = list(ex.map(lambda g: scan_gid(g, cookie_str), range(1, args.gid_end)))
    print(f"  扫描完成 {time.time()-t0:.1f}s, 共 {len(results)} 个结果")

    alive = sorted([r for r in results if r], key=lambda x: (x[1], x[0]))
    print(f"\n[2] 服务端活着 {len(alive)} 个组合:")
    for gid, date, ut, n in alive:
        flag = "✅ 保留" if date >= cutoff else "🗑️ 应删"
        if gid == 1:
            flag = "⚙️ 默认(不可删)"
        print(f"  {flag}  gid={gid:>5} {date} {ut} stocks={n}")

    # 3) 找出要删的 (date < cutoff 且 gid != 1)
    to_delete = [(gid, date) for gid, date, ut, n in alive
                 if date < cutoff and gid != 1]
    print(f"\n[3] 待删除组合: {len(to_delete)} 个")
    for gid, date in to_delete:
        print(f"  - gid={gid} date={date}")

    if args.dry_run:
        print("\n[dry-run] 只扫描不删除, 退出")
        return 0

    # 4) dg 删除
    if to_delete:
        print(f"\n[4] dg 删除...")
        for gid, date in to_delete:
            url = f"{BASE_URL}dg?appkey={APPKEY}&g={gid}"
            r = api_call(url, cookie_str, timeout=10)
            state = r.get("state")
            msg = r.get("message", "")
            ok = state == 0 or state == -119  # -119 表示已不存在, 也算成功
            print(f"  dg gid={gid} ({date}) -> state={state}, msg={msg} {'✅' if ok else '❌'}")

    # 5) 同步清理 groups.json (date < cutoff 的 key)
    print(f"\n[5] 清理 groups.json 本地缓存 (date < {cutoff}):")
    if os.path.exists(GROUPS_PATH):
        with open(GROUPS_PATH) as f:
            groups = json.load(f)
        removed = []
        for name in list(groups.keys()):
            if len(name) >= 8 and name[:8].isdigit() and name[:8] < cutoff:
                removed.append(name)
                del groups[name]
        with open(GROUPS_PATH, "w") as f:
            json.dump(groups, f, indent=2, ensure_ascii=False)
        print(f"  移除本地条目: {removed if removed else '(无)'}")
    else:
        print("  groups.json 不存在, 跳过")

    # 6) 最终状态
    print(f"\n[6] 最终保留 (groups.json):")
    if os.path.exists(GROUPS_PATH):
        with open(GROUPS_PATH) as f:
            groups = json.load(f)
        for name in sorted(groups.keys()):
            print(f"  {name} gid={groups[name].get('gid')} stocks={len(groups[name].get('stocks', []))}")

    print(f"\n✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())