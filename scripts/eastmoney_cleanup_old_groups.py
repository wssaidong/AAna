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
# gid 单调递增分配。实测 2026-10 已用到 1706, 旧上界 1300 会漏扫当前全部自建组合。
# 取 2100 作上界留足余量(全量扫描约 10s, 超出范围返回 -119 无副作用)。
GID_RANGE_END = 2101
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
    deleted_gids = set()
    if to_delete:
        print(f"\n[4] dg 删除...")
        for gid, date in to_delete:
            url = f"{BASE_URL}dg?appkey={APPKEY}&g={gid}"
            r = api_call(url, cookie_str, timeout=10)
            state = r.get("state")
            msg = r.get("message", "")
            ok = state == 0 or state == -119  # -119 表示已不存在, 也算成功
            print(f"  dg gid={gid} ({date}) -> state={state}, msg={msg} {'✅' if ok else '❌'}")
            if ok:
                deleted_gids.add(gid)

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
        print(f"  移除本地条目: {removed if removed else '(无)'}")

        # 5b) 对账: 本地记录但服务端已不存在的 gid (state=-119) 一并清掉。
        # 仅按日期清理会留下"幽灵组合", 让本地缓存比服务端多算持仓。
        ghosts = []
        for name in list(groups.keys()):
            gid = str(groups[name].get("gid") or "")
            if not gid.isdigit():
                continue
            try:
                st = api_call(f"{BASE_URL}gstkinfos?appkey={APPKEY}&g={gid}",
                              cookie_str, timeout=5).get("state")
            except Exception:
                continue  # 网络异常时保守跳过, 不误删
            if st == -119:  # 分组信息不存在
                ghosts.append((name, gid))
                del groups[name]
        if ghosts:
            print(f"  对账移除幽灵条目 (服务端已删): "
                  f"{', '.join(f'{n}(gid={g})' for n, g in ghosts)}")

        # 5c) 名称纠正 + stocks 全量回写 + 服务端孤儿报告 (2026-10-28 沉淀)
        # 根因: 尾盘 PM 流程曾把缓存写在 key "YYYYMMDD" 而非 "YYYYMMDDPP",
        #       覆盖早盘组条目 → 早盘组 gid 在本地丢失; 同日早盘 sync 按 YYYYMMDD
        #       取组时命中被污染条目 → 把早盘 Top10 灌进 PP 组。
        # 服务端 gname 恒为 null, 无法反查 gid→组名, 因此:
        #   - 组名纠正只信本地条目自带的 "name" 字段 (写缓存时记录的真实组名)
        #   - 服务端有、本地无的组只报告, 不臆造名字 (App 端组名不可知)

        # 5c-1) 组名纠正: 条目自带 name 字段(写缓存时记录的真实组名)与 key 不符 → key 写错了
        renamed = []
        for name in list(groups.keys()):
            entry = groups[name]
            real = str(entry.get("name") or "").strip()
            if not real or real == name:
                continue
            if not (real[:8].isdigit() and (len(real) == 8 or
                    (len(real) == 10 and real[8:] in ("PP", "ZZ")))):
                continue  # 不认识的组名格式 → 不动
            if real in groups:
                print(f"  ⚠️ 组名冲突: key={name} 记录组名={real} (目标 key 已占用, 需人工确认)")
                continue
            groups[real] = groups.pop(name)
            renamed.append((name, real))
        if renamed:
            print("  组名纠正 (key → 服务端组名): "
                  + ", ".join(f"{a}→{b}" for a, b in renamed))

        # 5c-2) stocks 全量回写服务端真值 (本地可能只记了 Top1 或集合已过期)
        fixed = []
        for name in list(groups.keys()):
            gid = str(groups[name].get("gid") or "")
            if not gid.isdigit():
                continue
            try:
                r = api_call(f"{BASE_URL}gstkinfos?appkey={APPKEY}&g={gid}",
                             cookie_str, timeout=5)
            except Exception:
                continue  # 网络异常时保守跳过, 不误改
            if r.get("state") != 0:
                continue
            codes = []
            for s in (r.get("data") or {}).get("stkinfolist") or []:
                sec = str(s.get("security", ""))
                c = sec.split("$")[1] if "$" in sec else sec
                if c:
                    codes.append(c)
            if codes and sorted(codes) != sorted(groups[name].get("stocks") or []):
                groups[name]["stocks"] = codes
                fixed.append(f"{name}({len(codes)}只)")
        if fixed:
            print("  stocks 回写服务端真值: " + ", ".join(fixed))

        # 5c-3) 服务端有、本地无 → 只报告不臆造组名 (App 端组名不可知, 需人工确认)
        # 注意: alive 是删除前的快照, 必须排除本次已删的 gid, 否则会把自己刚删的组
        # 误报成"服务端孤儿"(2026-10-29 修复)。
        local_gids = {str(groups[n].get("gid")) for n in groups}
        orphans = [(g, d, n) for (g, d, _ut, n) in alive
                   if str(g) not in local_gids and g != 1 and g not in deleted_gids]
        if orphans:
            print("  ⚠️ 服务端有、本地未登记 (需人工确认组名后补登记, 勿臆造):")
            for g, d, n in orphans:
                print(f"     gid={g} date={d} stocks={n}")

        with open(GROUPS_PATH, "w") as f:
            json.dump(groups, f, indent=2, ensure_ascii=False)
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