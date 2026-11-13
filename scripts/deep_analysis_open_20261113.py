#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析 2026-11-13 开盘复核 (autopilot ca411dd3 run 01a1d286, 手动触发 09:30) — 第三口径 live 确认
背景: 08:35 盘前 run (01a1d250) 已判定 Top10 表 0 只 + 冰点守卫双口径短路 (快照 30 + live ths 11-12 收盘口径 30) → 0 推荐不建 20261113ZZ。
本 run 增量: 昨日先例 (11-12 盘前 80 亢奋被 09:31 开盘证伪) 表明盘前结论必须过开盘实测 —
今日 09:33 开盘 live 复核: 冰点守卫第三口径 (开盘实时 ths) score 35 冰点 is_ice_point=True 维持短路,
Top10 独立解析 0 行 (报告 mtime 08:03:41 未变), 结论: 0 推荐维持, 不建 20261113ZZ (先例口径)。
指数开盘实况 (tencent 09:34:40): 上证 -0.06% / 深成 -0.40% / 创业板 -0.82% / 沪深300 -0.34% / 科创50 +1.10% (连续第3日逆势领涨) → 四均 -0.04% (09:33 曾瞬时至 +0.13% 后回落), 广度冰点 (涨停6/跌停1), 指数结构分化非情绪修复。
东财: 0 推荐日不同步, groups.json 只读预检 20261113* 无占用 (维持)。
"""
import sys, os, json, re, time
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, '/Users/cai/code/AAna/scripts')

TODAY = "2026-11-13"
RUN_ID = "01a1d286-f9bb-7e6f-8cd3-0764c5e081d3"
REPORT = os.path.expanduser(f"~/code/AAna/reports/{TODAY}-选股报告.md")
OUT_JSON = os.path.expanduser("~/code/AAna/data/deep_analysis_20261113_open.json")
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def parse_top10(text):
    """口径同 deep_analysis_20261113.raw_row_count: 截到 ##/### 标题防基金表误计。"""
    m = re.search(r'重点关注 Top 10(.*?)(?=\n#{2,3} |\Z)', text, re.S)
    return [l for l in (m.group(1) if m else "").split("\n")
            if l.strip().startswith("|") and re.search(r'\d{6}', l)
            and not l.strip().startswith("|:")]


def tencent_indices():
    import requests
    r = requests.get("https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000300,sh000688",
                     timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.encoding = "gbk"
    out = {}
    for m in re.finditer(r'v_(?:sh|sz)(\w+)="([^"]+)"', r.text):
        p = m.group(2).split("~")
        try:
            out[m.group(1)] = {"name": p[1], "close": float(p[3]),
                               "pct": float(p[32]), "time": p[30]}
        except (ValueError, IndexError):
            continue
    return out


def main():
    result = {"date": TODAY, "session": "open_verify", "run_id": RUN_ID,
              "generated": time.strftime("%H:%M:%S"),
              "source_run": "01a1d250-3fc2-724f-93d5-f0c300b428b1 (08:35 盘前)"}

    # 1) 当日报告独立复核
    text = open(REPORT).read()
    result["report"] = os.path.basename(REPORT)
    result["report_mtime"] = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(REPORT)))
    rows = parse_top10(text)
    result["top10_rows_independent"] = len(rows)
    result["report_unchanged_since_0835"] = result["report_mtime"] < "2026-11-13T08:35"

    # 2) 冰点守卫第三口径: 开盘 live
    from aana_afternoon_screen import check_ice_point_guard
    try:
        live = check_ice_point_guard()
        result["live_guard"] = {k: live.get(k) for k in (
            "is_ice_point", "sentiment_label", "sentiment_score",
            "position_ratio", "reason")}
    except Exception as e:
        result["live_guard"] = {"error": str(e)}

    # 3) 指数开盘实况 + 四均
    try:
        idx = tencent_indices()
        result["indices"] = idx
        core = ["000001", "399001", "399006", "000688"]
        result["four_core_avg_pct"] = round(
            sum(idx[c]["pct"] for c in core if c in idx) / len(core), 2)
    except Exception as e:
        result["indices_error"] = str(e)

    # 4) 东财 groups 只读预检
    try:
        groups = json.load(open(GROUPS_FILE))
        result["groups_20261113_occupied"] = sorted(
            k for k in groups if str(k).startswith("20261113"))
        result["groups_latest_keys"] = sorted(groups.keys())[-4:]
    except Exception as e:
        result["groups_error"] = str(e)

    # 5) 终判
    zero_pool = result["top10_rows_independent"] == 0
    guard = result.get("live_guard", {})
    result["verdict"] = {
        "recommendations": 0,
        "create_20261113ZZ": False,
        "reason": ("Top10 表 0 只 (独立解析复核) + 开盘 live 冰点守卫第三口径短路 "
                   "(score {} {}) → 0 推荐, 不建组 (先例: 守卫短路日不建组)".format(
                       guard.get("sentiment_score"), guard.get("sentiment_label")))
        if zero_pool and guard.get("is_ice_point")
        else "UNEXPECTED: 复核与盘前结论不一致, 需人工介入",
        "iron_rule_status": "无候选标的可满足铁律 (当日胜出+正盈利), 0 推荐即合规输出",
    }

    with open(OUT_JSON, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["verdict"], ensure_ascii=False, indent=2))
    print("saved:", OUT_JSON)


if __name__ == "__main__":
    main()
