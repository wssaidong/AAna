#!/usr/bin/env python3
"""
A股盘后战报 端到端生成脚本

用法:
    python3 scripts/run_afterhours.py                    # 跑今天 (cron 推荐)
    python3 scripts/run_afterhours.py 2026-06-08         # 跑指定日期
    python3 scripts/run_afterhours.py 2026-06-08 --dry   # 不推送飞书，只输出
"""
import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
FEISHU_USER = "ou_5d0124d26ed21365f74764fcb9fa01b7"
REPORT_DIR = "/Users/cai/code/AAna/reports"

# v2026-08-23 Phase 3-2: log silenced() fallback
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from _logger import silenced as _silenced
except Exception:
    def _silenced(label, exc):  # noqa: E731
        pass

# v2026-08-23 Phase 4A: 数据源 facade 接入 scripts.data_sources
#   之前 4 个函数 (tencent_quote/get_indices/ths_hot/get_industry_ranking)
#   在本文件重复实现，已删除，改用 scripts.data_sources 真权威版本。
#   scripts.data_sources.tencent_quote 与原版行为相同（用 get_prefix 判断前缀），
#   ths_hot_reason 返回 dict 而原 ths_hot 返回 list — 提供 wrapper 保持向下兼容。
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
try:
    from scripts import data_sources as ds
except Exception:
    # 兼容 analysis_tools.data_sources 旧路径 (Phase 4A shim)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from analysis_tools import data_sources as ds  # noqa: F401


def tencent_quote(codes):
    """腾讯行情:从 scripts.data_sources facade 复刻 key 行为

    原返回 dict: {'sh000001': {name, code6, current, prev_close, change_pct}, ...}
    ds.tencent_quote 返回相同结构。
    """
    if isinstance(codes, str):
        codes = [c.strip() for c in codes.split(",")]
    return ds.tencent_quote(codes)


def get_indices():
    """上证/深证/创业板/中小100/沪深300/科创50 — 用 ds.tencent_quote"""
    codes = ["sh000001", "sz399001", "sz399006", "sz399005", "sz399300", "sh000688"]
    return tencent_quote(codes)


def ths_hot(date_str):
    """同花顺强势股;ds.ths_hot_reason 返回 dict {rows, ...},本函数取 rows 转 list 保持兼容

    原 ths_hot 返回 list[{code, name, reason, date, market}]
    ds.ths_hot_reason 返回 dict{rows, source, note}
    """
    raw = ds.ths_hot_reason(date_str)
    rows = raw.get("rows", []) if isinstance(raw, dict) else []
    return [
        {
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "date": row.get("date", ""),
            "market": row.get("market"),
        }
        for row in rows
    ]


def enrich_with_quote(hot_list):
    if not hot_list:
        return hot_list
    codes = []
    for h in hot_list:
        c = h.get("code", "")
        if not c:
            continue
        prefix = "sh" if c.startswith("6") or c.startswith("9") else "sz"
        codes.append(f"{prefix}{c}")
    q = tencent_quote(codes)
    for h in hot_list:
        c = h.get("code", "")
        if not c:
            continue
        prefix = "sh" if c.startswith("6") or c.startswith("9") else "sz"
        if f"{prefix}{c}" in q:
            h["change_pct"] = q[f"{prefix}{c}"]["change_pct"]
            h["current"] = q[f"{prefix}{c}"]["current"]
            h["prev_close"] = q[f"{prefix}{c}"]["prev_close"]
    return hot_list


def theme_counter(hot_list):
    c = Counter()
    for item in hot_list:
        for r in str(item.get("reason") or "").split("+"):
            if r.strip():
                c[r.strip()] += 1
    return c


def get_industry_ranking(top_n=10):
    """东财行业涨跌 — 用 ds.eastmoney_datacenter fallback 链 (push2 → push2delay)

    原版返回 dict: {top: rows[:n], bottom: rows[-n:], total, returned, source}
    ds.industry_comparison 签名是 (top_n=20) → 直接复用，调整 keys。
    """
    raw = ds.industry_comparison(top_n=top_n * 2)  # 取双倍才能给 bottom
    if not isinstance(raw, dict):
        return {"top": [], "bottom": [], "total": 0, "error": "ds 返回非 dict"}
    rows = raw.get("rows", []) or []
    # ds 返回的 keys: code, name, change_pct — 与原版一致
    rows.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return {
        "top": rows[:top_n],
        "bottom": rows[-top_n:] if len(rows) >= top_n else [],
        "total": len(rows),
        "returned": len(rows),
        "source": raw.get("source", "scripts.data_sources.industry_comparison"),
    }


def get_daily_dragon_tiger(date_str):
    """东财龙虎榜 — ds.daily_dragon_tiger(trade_date)

    原版返回 dict: {rows, source} 或 {rows, note}
    ds.daily_dragon_tiger 返回更结构化的 dict,本函数适配:
    """
    raw = ds.daily_dragon_tiger(trade_date=date_str)
    if isinstance(raw, dict) and "rows" in raw:
        return raw
    return {"rows": [], "note": "scripts.data_sources.daily_dragon_tiger 未返回 rows"}


def _yesterday(date_str):
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def previous_nonempty_hot_day(date_str, max_lookback=10):
    """回溯最近一个同花顺有数据的日期，避免空自然日环比被放大。"""
    cursor = datetime.strptime(date_str, "%Y-%m-%d")
    for offset in range(1, max_lookback + 1):
        day = (cursor - timedelta(days=offset)).strftime("%Y-%m-%d")
        rows = ths_hot(day)
        if rows:
            return day, rows
    return None, []


def parse_top10_with_baseline(date_str):
    path = f"{REPORT_DIR}/{date_str}-选股报告.md"
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ 选股报告不存在: {path}")
        return []
    rows = []
    in_section = False
    seen = set()
    for line in content.split("\n"):
        if "重点关注 Top 10" in line or "🏆 重点关注" in line:
            in_section = True
            continue
        # Top10 是 ### 小节；遇到下一个同级/更高级标题必须立即停止。
        if in_section and re.match(r"^#{1,3}\s+", line):
            break
        if in_section and line.startswith("|"):
            if "排名" in line or "代码" in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            code, name, pct = None, None, None
            for i, p in enumerate(parts):
                if re.match(r"^\d{6}$", p):
                    code = p
                    if i > 0:
                        name = parts[i - 1].replace("📊", "").strip()
                if code and i > 0 and ("+" in p or "-" in p) and "%" in p:
                    m = re.search(r'([+-]?\d+\.\d+)%', p)
                    if m:
                        pct = float(m.group(1))
                        break
            if code and pct is not None and code not in seen:
                rows.append((code, name or code, pct))
                seen.add(code)
            if len(rows) >= 10:
                break
    return rows


def classify_market_feature(market_avg, sh_pct, cyb_pct, kc50_pct, gap_rows,
                            other_5_avg=None):
    """按方向区分尾盘急涨/急跌，并覆盖极端情绪及科创单点分化。"""
    deltas = [row[3] for row in gap_rows]
    max_delta = max(deltas, default=0.0)
    min_delta = min(deltas, default=0.0)
    if market_avg < -3.0 and min_delta <= -3.5:
        return "💥 极端情绪日（模式⑤）+ 假突破后尾盘跳水（v1.22第四层）"
    if market_avg < -3.0:
        return "💥 极端情绪日（模式⑤）"
    if max_delta >= 3.5:
        return "📈 假平稳真急涨型（v1.22第五层）"
    if min_delta <= -3.5:
        return "📉 假突破后尾盘跳水型（v1.22第四层）"
    if sh_pct < -1.5 and kc50_pct < -5:
        return "📉 平稳转急跌型（模式⑦）"
    if other_5_avg is not None and kc50_pct < -3.0 and abs(other_5_avg) < 0.5:
        return "📊 主板稳态 + 科创50单点跳水型"
    if sh_pct > 1.5:
        return "📈 强势行情"
    if sh_pct < -1.0:
        return "📉 震荡偏弱"
    return "➡️ 震荡"


def eval_index(pct):
    if pct > 3: return "🔥 强势"
    elif pct > 1: return "📈 偏强"
    elif pct > -1: return "➡️ 平稳"
    elif pct > -3: return "📉 偏弱"
    else: return "❄️ 弱势"


def generate_full_report(date_str):
    print(f"[1/5] 拉大盘指数…")
    indices = get_indices()
    if len(indices) != 6:
        print(f"⚠️  只拉到 {len(indices)}/6 个指数")

    print(f"[2/5] 拉强势股…")
    hot = ths_hot(date_str)
    print(f"      强势股 {len(hot)} 只")
    hot = enrich_with_quote(hot)

    print(f"[3/5] 拉候选池…")
    top10 = parse_top10_with_baseline(date_str)
    print(f"      Top10 {len(top10)} 只")

    print(f"[4/5] 计算题材热度对比…")
    comparison_date, hot_yest = previous_nonempty_hot_day(date_str)
    if comparison_date:
        print(f"      环比基准: {comparison_date}（最近非空日期；不宣称交易日）")
    else:
        print("      ⚠️ 最近10日无非空题材数据，环比按0处理")
    ct = theme_counter(hot)
    cy = theme_counter(hot_yest)
    themes = [t for t, _ in ct.most_common() if t != "ST板块"][:10]

    print("      拉东财行业板块涨跌…")
    industry = get_industry_ranking(10)
    if industry.get("total"):
        source_label = "push2delay fallback" if "push2delay" in industry.get("source", "") else "push2"
        print(f"      东财行业 {industry.get('returned', 0)}/{industry['total']} 个（{source_label}）")
    else:
        print(f"      ⚠️ 东财行业降级失败: {industry.get('error', '无数据')}")

    print("      拉今日龙虎榜…")
    dragon = get_daily_dragon_tiger(date_str)
    if dragon.get("rows"):
        print(f"      龙虎榜 {len(dragon['rows'])} 条")
    else:
        print(f"      ⚠️ 龙虎榜降级: {dragon.get('note', '无数据')}")

    print(f"[5/5] 计算候选池命中率…")
    top10_codes = [c for c, _, _ in top10]
    qq = tencent_quote([f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in top10_codes])
    hit_rows = []
    for code, name, baseline in top10:
        key = f"{'sh' if code.startswith('6') else 'sz'}{code}"
        actual = qq.get(key, {}).get("change_pct", 0)
        delta = actual - baseline
        hit_rows.append((code, name, baseline, actual, delta))

    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / max(len(hit_rows), 1)
    avg_pos = sum(r[3] for r in positives) / max(len(positives), 1) if positives else 0
    avg_neg = sum(r[3] for r in negatives) / max(len(negatives), 1) if negatives else 0

    sh_pct = indices.get("sh000001", {}).get("change_pct", 0)
    cyb_pct = indices.get("sz399006", {}).get("change_pct", 0)
    kc50_pct = indices.get("sh000688", {}).get("change_pct", 0)

    print(f"      选新晋异动 Top5…")
    top10_set = set(top10_codes)
    # ⚠️ v1.5/v1.12 pitfall: 过滤 *ST/ST 投机标的
    outside = [h for h in hot
               if h["code"] not in top10_set
               and "*ST" not in h.get("name", "")
               and "ST" not in h.get("name", "")
               and h.get("change_pct", 0) >= 9.5]  # 至少涨停
    # 20cm 识别必须看代码段/实际涨幅，不能用同花顺 market 字段：
    # 实测 market=33 同时覆盖深市主板与创业板，按 market 会把所有深市 10cm 误判为 20cm。
    def _is_20cm_stock(h):
        code = str(h.get("code", ""))
        return code.startswith(("300", "301", "688", "689")) or h.get("change_pct", 0) >= 19.5

    # 先按 20cm 优先 + 涨幅降序预排序，再按题材去重。
    outside.sort(key=lambda h: (-int(_is_20cm_stock(h)), -h.get("change_pct", 0)))
    # ⚠️ v1.5 pitfall: priority 拓宽至 20 项 + 动态按当日热度调整
    priority = ["AI智算", "算力", "半导体设备", "固态电池", "稀土永磁", "低空经济",
                "液冷服务器", "PCB概念", "先进封装", "MLCC", "存储芯片", "机器人",
                "商业航天", "数字科技", "央企", "一季报增长", "创新药", "可控核聚变",
                "分红", "黄金"]
    # 用 themes[:5] (当日热度前5) 替换硬编码前5个,实现动态 priority
    dynamic_top = themes[:5] if themes else []
    final_priority = list(dict.fromkeys(dynamic_top + priority))  # 去重保序
    selected = []
    used_theme = set()
    for h in outside:
        if len(selected) >= 5:
            break
        reason = h.get("reason", "")
        matched = next((theme for theme in final_priority if theme in reason), None)
        if not matched:
            # 20cm/涨停股即使题材不在既有 priority，也应使用 reason 首标签入榜，
            # 避免 AI智能体、DeepSeek 等新题材被硬编码列表漏掉。
            matched = next((tag.strip() for tag in reason.split("+")
                            if tag.strip() and tag.strip() != "ST板块"), None)
        if not matched:
            continue
        # 先按 20cm 优先排序后的股票流逐个选；同一题材只取一只，保证题材多样性。
        if matched in used_theme:
            continue
        h["_is_20cm"] = _is_20cm_stock(h)
        selected.append((matched, h))
        used_theme.add(matched)
    selected = selected[:5]

    # 14:45 vs 15:00 时点差警示（v1.3 必跑 + v1.6/v1.13 路径修复）
    # 候选路径顺序（v1.6 + v1.13 持续生效）:
    #   1. /Users/cai/code/AAna/reports/{date}/盘中/{date}_1445_尾盘分析.md  ← 首选
    #   2. /Users/cai/code/AAna/reports/{date}-尾盘选股.md                ← 已确认失真
    candidate_paths = [
        f"{REPORT_DIR}/{date_str}/盘中/{date_str}_1445_尾盘分析.md",
        f"{REPORT_DIR}/{date_str}-尾盘选股.md",
    ]
    gap_md, has_gap, gap_rows, gap_source = realtime_gap_alert(indices, candidate_paths)

    # 飞书版（短）
    feishu_md = format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                              positives, negatives, avg, avg_pos, avg_neg,
                              sh_pct, cyb_pct, kc50_pct, selected, len(hot),
                              gap_md, gap_rows, comparison_date, industry, dragon)

    # 完整报告
    full_md = format_full_report(date_str, indices, themes, ct, cy, hit_rows,
                                 positives, negatives, avg, avg_pos, avg_neg,
                                 sh_pct, cyb_pct, kc50_pct, selected, len(hot),
                                 feishu_md=feishu_md)
    return feishu_md, full_md


def realtime_gap_alert(indices, tail_paths, threshold_pct=2.0):
    """对比 14:45 尾盘报告 vs 15:00 收盘数据。
    Returns (md, has_alert) — 差距 >= 2pp 时返回警示md。
    2026-06-11 实测科创50 14:45 +9.71% → 15:00 +0.62% 差 -9.09pp（巨幅反转！必须警示）。

    ⚠️ v1.13 关键修复:
    - tail_paths 改为路径列表（盘中优先 + 尾盘选股 fallback）
    - 只列已抓取到的指数（盘中报告指数列不固定）
    - regex 必须跨管道 .*?（v1.5 修复）
    """
    import os as _os
    if isinstance(tail_paths, str):
        tail_paths = [tail_paths]
    tail_content = None
    used_path = None
    for p in tail_paths:
        if p and _os.path.exists(p):
            try:
                with open(p) as f:
                    tail_content = f.read()
                used_path = p
                break
            except Exception:
                continue
    if not tail_content:
        return "", False, [], None
    name_map = {"sh000001": "上证指数", "sz399001": "深证成指",
                "sz399006": "创业板指", "sz399005": "中小100",
                "sz399300": "沪深300", "sh000688": "科创50"}
    rows, has_alert = [], False
    for k, name in name_map.items():
        # ⚠️ v1.5 修复: regex 必须跨管道 .*?（不是 [^|]*?）
        m = re.search(rf"\|\s*{name}\s*\|.*?([+-]?\d+\.\d+)\s*%", tail_content)
        if not m:
            # ⚠️ v1.13 修复: 跳过缺失指数（如盘中报告无沪深300/中小100）
            continue
        v1445 = float(m.group(1))
        v1500 = indices.get(k, {}).get("change_pct", 0)
        delta = v1500 - v1445
        if abs(delta) >= threshold_pct:
            has_alert = True
        rows.append((name, v1445, v1500, delta))
    if not rows:
        return "", False, [], used_path
    if not has_alert:
        return "", False, rows, used_path
    md = "\n⚠️ **数据口径警示**（14:45 尾盘 vs 15:00 收盘 时点差）\n\n"
    md += "| 指数 | 14:45 尾盘 | 15:00 收盘 | 时点差 | 方向 |\n"
    md += "|:----:|:---------:|:---------:|:------:|:----:|\n"
    for name, v1445, v1500, delta in rows:
        if (v1445 > 0) != (v1500 > 0) and abs(delta) >= 2:
            arrow = "🔄 反转"
        elif delta > 0:
            arrow = "📈 修正"
        else:
            arrow = "📉 修正"
        md += f"| {name} | {v1445:+.2f}% | {v1500:+.2f}% | {delta:+.2f} pp | {arrow} |\n"
    md += f"\n> 14:45 盘中建议与收盘差异 > {threshold_pct}pp，请以本盘后战报为准。\n"
    md += f"> 数据源：{used_path}（共 {len(rows)}/6 指数）\n"
    return md, True, rows, used_path


def format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                   positives, negatives, avg, avg_pos, avg_neg,
                   sh_pct, cyb_pct, kc50_pct, selected, hot_count,
                   gap_md="", gap_rows=None, comparison_date=None,
                   industry=None, dragon=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = (f"📊 **盘后战报｜生成时间 {now} CST｜"
          f"目标交易日 {date_str} 15:00 收盘**\n\n")

    md += "━━━ **行业今日全貌** ━━━\n\n"
    industry = industry or {}
    if industry.get("top"):
        top_text = " / ".join(
            f"{row['name']} {row['change_pct']:+.2f}%" for row in industry["top"][:5]
        )
        bottom_text = " / ".join(
            f"{row['name']} {row['change_pct']:+.2f}%" for row in industry["bottom"][-5:]
        )
        md += f"📈 **东财行业涨幅 Top5：** {top_text}\n"
        md += f"📉 **东财行业跌幅 Bottom5：** {bottom_text}\n"
        md += f"> 口径：已分页拉取 {industry.get('returned', 0)}/{industry.get('total', 0)} 个行业板块。\n"
        if "push2delay" in industry.get("source", ""):
            md += "> 数据源降级：东财 push2 主域断连，已切换官方 push2delay 域。\n\n"
    else:
        md += f"> ⚠️ 东财行业板块不可用：{industry.get('error', '无数据')}；以下用同花顺强势股题材聚合作为 fallback。\n\n"
    md += "🔥 **今日最强题材（热度排行 Top10）：**\n"
    comparison_label = comparison_date or "最近非空日"
    for i, theme in enumerate(themes, 1):
        cnt = ct.get(theme, 0)
        yest = cy.get(theme, 0)
        diff = cnt - yest
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        md += f"{i}️⃣ {theme} — {cnt}次（较{comparison_label} {arrow}{abs(diff)}）\n"

    core_pcts = [indices.get(k, {}).get("change_pct", 0)
                 for k in ("sh000001", "sz399001", "sz399006", "sh000688")]
    market_avg = sum(core_pcts) / len(core_pcts)
    other_5 = [indices.get(k, {}).get("change_pct", 0)
               for k in ("sh000001", "sz399001", "sz399006", "sz399005", "sz399300")]
    other_5_avg = sum(other_5) / len(other_5)
    market_feature = classify_market_feature(
        market_avg, sh_pct, cyb_pct, kc50_pct, gap_rows or [], other_5_avg
    )
    md += f"\n⚠️ **市场特征：** {market_feature}（根据 {hot_count} 只强势股判断）\n"
    md += f"- 四大核心指数平均 {market_avg:+.2f}%｜上证 {sh_pct:+.2f}% / 创业板 {cyb_pct:+.2f}% / 科创50 {kc50_pct:+.2f}%\n\n"

    md += "📈 **大盘收盘表现：**\n"
    name_map = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指",
                "sz399005": "中小100", "sz399300": "沪深300", "sh000688": "科创50"}
    for k in ["sh000001", "sz399001", "sz399006", "sz399005", "sz399300", "sh000688"]:
        v = indices.get(k, {})
        cur = v.get("current", 0) or 0
        md += f"- {name_map[k]} {cur:.2f} ({v.get('change_pct', 0):+.2f}%)\n"

    md += "\n━━━ **候选池命中率** ━━━\n\n"
    md += "> 注：报告 08:03 生成，'baseline' 实为昨日(昨-1)收盘涨跌幅\n\n"
    md += "| 代码 | 名称 | baseline | 今日实际 | Δ | 评估 |\n"
    md += "|:----:|:----:|:------:|:------:|:----:|:----:|\n"
    if not hit_rows:
        md += "| ⚠️ | 上游报告缺失 | N/A | N/A | N/A | 无候选池评估 |\n"
    for code, name, baseline, actual, delta in hit_rows:
        if delta >= 3:
            ev = "✅ 强势延续"
        elif delta >= 0:
            ev = "✅ 延续"
        elif delta >= -3:
            ev = "⚠️ 高位震荡"
        else:
            ev = "❌ 高位回吐"
        md += f"| {code} | {name} | {baseline:+.2f}% | {actual:+.2f}% | {delta:+.2f}% | {ev} |\n"

    if 0 < len(hit_rows) < 7:
        md += f"\n⚠️ **上游 Top10 严重不完整：仅 {len(hit_rows)}/10（完整度 {len(hit_rows)*10}%），样本量不足。**\n"
    elif 7 <= len(hit_rows) < 10:
        md += f"\n⚠️ **上游 Top10 不完整：仅 {len(hit_rows)}/10（完整度 {len(hit_rows)*10}%），统计置信度打折。**\n"
    if hit_rows:
        baseline_avg = sum(r[2] for r in hit_rows) / len(hit_rows)
        continuation_negative = sum(1 for r in hit_rows if r[4] < 0)
        md += f"\n📊 **命中率：** {len(positives)}/{len(hit_rows)} = {len(positives)/len(hit_rows)*100:.1f}%\n"
        md += f"- 整体均值：{avg:+.2f}% | 正：{avg_pos:+.2f}% | 负：{avg_neg:+.2f}%\n"
        md += f"- baseline均值：{baseline_avg:+.2f}% | {continuation_negative}/{len(hit_rows)} 负延续 | Δ均值：{avg - baseline_avg:+.2f}pp\n"
        md += f"- vs 上证 {sh_pct:+.2f}% 超额：**{avg - sh_pct:+.2f}pp**\n"
        md += f"- vs 四大核心指数均值 {market_avg:+.2f}% 超额：**{avg - market_avg:+.2f}pp**\n"
    else:
        md += "\n⚠️ **候选池评估：** 上游选股报告 Top10 为空，本次无候选池命中率评估\n"
        md += f"- 大盘参考：上证 {sh_pct:+.2f}%；候选池超额：**N/A**\n"

    md += "\n━━━ **新晋异动 Top5** ━━━\n\n"
    dragon = dragon or {}
    if not dragon.get("rows"):
        md += f"> ⚠️ {dragon.get('note', '龙虎榜无数据')}。以下为候选池外涨停异动代表（20cm优先、题材去重）。\n\n"
    for i, (theme, h) in enumerate(selected, 1):
        pct = h.get("change_pct", 0)
        md += f"{i}️⃣ {h['code']} {h['name']} — {theme} **{pct:+.2f}%**\n"

    md += "\n━━━ **明日观察要点** ━━━\n"
    deltas = [row[3] for row in (gap_rows or [])]
    max_delta = max(deltas, default=0.0)
    min_delta = min(deltas, default=0.0)

    if market_avg < -3.0 and min_delta <= -3.5:
        md += f"1️⃣ **大盘性质：** ⚠️ 极端情绪日（模式⑤）+ 假突破后尾盘跳水；四大指数平均 {market_avg:+.2f}%，最深时点差 {min_delta:+.2f}pp，先观察止跌而非抢反弹\n"
        md += "2️⃣ **回避：** 昨日涨幅3%-5%的追高标的；所谓防御股也须等待量价企稳\n"
        md += f"3️⃣ **主线：** 观察{', '.join(themes[:4])}龙头次日溢价；无溢价则维持低仓位\n"
    elif market_avg < -3.0:
        md += f"1️⃣ **大盘性质：** ⚠️ 极端情绪日！四大指数平均 {market_avg:+.2f}%，关注明日缩量止跌信号\n"
        md += "2️⃣ **回避：** 昨日涨幅3%-5%的追高标的（系统性杀跌时回吐最明显）\n"
        md += "3️⃣ **防御：** 保持低仓位，等指数与主线龙头同步企稳后再加仓\n"
    elif max_delta >= 3.5:
        md += f"1️⃣ **大盘性质：** 📈 假平稳真急涨型！最大正时点差 {max_delta:+.2f}pp，14:45 谨慎判断被收盘强势推翻；明日先验量能，避免高潮追涨\n"
        md += f"2️⃣ **主线持续性：** {', '.join(themes[:3])}龙头若高开不回落且成交不萎缩50%，反弹结构延续；集体低开则防一日游\n"
        continuation = (f"{sum(1 for r in hit_rows if r[4] < 0)}/{len(hit_rows)}延续性转弱"
                        if hit_rows else "候选池缺失")
        md += (f"3️⃣ **候选池修正：** {len(positives)}/{len(hit_rows)}命中但"
               f"仅较上证 {avg - sh_pct:+.2f}pp、较四大核心指数 {avg - market_avg:+.2f}pp；"
               f"{continuation}，不追昨日+4%强势股，优先今日新主线回踩确认标的\n")
    elif min_delta <= -3.5:
        md += f"1️⃣ **大盘性质：** ⚠️ 假突破后尾盘跳水型！最深时点差 {min_delta:+.2f}pp，盘中建议已被收盘推翻\n"
        md += "2️⃣ **回避：** 追高强势股与高Beta小盘股，先看次日开盘量能\n"
        md += f"3️⃣ **主线：** 关注{', '.join(themes[:3])}龙头能否扛住杀跌\n"
    elif sh_pct < -1.5 and kc50_pct < -5:
        md += f"1️⃣ **大盘性质：** ⚠️ 平稳转急跌型！创业板/科创50收盘 {cyb_pct:+.2f}%/{kc50_pct:+.2f}%\n"
        md += "2️⃣ **回避：** 追高强势股 + 小盘题材投机\n"
        md += f"3️⃣ **主线：** 关注{', '.join(themes[:3])}龙头股是否扛住杀跌\n"
    else:
        md += f"1️⃣ **大盘：** 上证 {sh_pct:+.2f}%，{'强势' if sh_pct > 1.5 else ('震荡偏弱' if sh_pct < -1 else '震荡')}；关注明日开盘30分钟量能\n"
        md += f"2️⃣ **主线：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、成交不萎缩50%\n"
        md += "3️⃣ **防御：** 央企/红利股作为底仓对冲\n"
    if gap_md:
        # 外发正文只保留数据源文件名，不泄露本机绝对路径。
        gap_md = re.sub(r"(?<=数据源：)(?:/[^\s（]+/)+", "", gap_md)
        md += gap_md
    md += "\n⚠️ **仅供参考，不构成投资建议**\n"
    return md


def format_full_report(date_str, indices, themes, ct, cy, hit_rows,
                       positives, negatives, avg, avg_pos, avg_neg,
                       sh_pct, cyb_pct, kc50_pct, selected, hot_count,
                       feishu_md=None):
    """完整落盘报告；复用已验证的飞书正文，避免两套市场定性漂移。"""
    if feishu_md is not None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (f"# AAna 盘后战报 — {date_str}\n\n"
                f"> **生成时间：** {now}\n"
                f"> **目标交易日：** {date_str} 15:00 收盘\n"
                f"> **数据源：** 腾讯收盘行情 + 东财行业板块 + 同花顺强势股；龙虎榜不可用时明确降级\n\n"
                f"{feishu_md}\n")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name_map = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指",
                "sz399005": "中小100", "sz399300": "沪深300", "sh000688": "科创50"}

    md = f"""# AAna 盘后战报 — {date_str}

> **生成时间：** {now}
> **数据源：** 腾讯 qt.gtimg.cn（收盘价）+ 同花顺 zx.10jqka.com.cn（题材归因）
> **样本量：** {hot_count} 只强势股 + {len(hit_rows)} 只候选池
> **触发方式：** AAna 复盘报告 autopilot (cron 17:00)

---

## 一、大盘收盘表现

| 指数 | 收盘价 | 涨跌幅 | 评价 |
|:----:|:------:|:------:|:----:|
"""
    for k in ["sh000001", "sz399001", "sz399006", "sz399005", "sz399300", "sh000688"]:
        v = indices.get(k, {})
        cur = v.get("current", 0) or 0
        pct = v.get("change_pct", 0)
        md += f"| {name_map[k]} | {cur:.2f} | {pct:+.2f}% | {eval_index(pct)} |\n"

    md += f"""
---

## 二、今日最强题材（热度排行 Top10）

| 排名 | 题材 | 出现次数 | 较昨日 |
|:----:|:----:|:--------:|:------:|
"""
    for i, theme in enumerate(themes, 1):
        cnt = ct.get(theme, 0)
        yest = cy.get(theme, 0)
        diff = cnt - yest
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        md += f"| {i} | {theme} | {cnt} | {arrow}{abs(diff)} |\n"

    md += f"""
---

## 三、候选池命中率（v2.5 选股报告 Top10）

> **数据口径警示**：报告生成于开盘前 08:03，"baseline" 列实为**昨日收盘涨跌幅**，非当日预期。
> 正确评估：Δ = 当日实际涨跌幅 − baseline（衡量"延续性"）

| 排名 | 代码 | 名称 | baseline (昨收) | 今日实际 | Δ | 评估 |
|:----:|:----:|:----:|:------:|:------:|:----:|:----:|
"""
    if not hit_rows:
        md += "| ⚠️ | N/A | 上游报告缺失 | N/A | N/A | N/A | 无候选池评估 |\n"
    for i, (code, name, baseline, actual, delta) in enumerate(hit_rows, 1):
        if delta >= 3:
            ev = "✅ 强势延续"
        elif delta >= 0:
            ev = "✅ 延续"
        elif delta >= -3:
            ev = "⚠️ 高位震荡"
        else:
            ev = "❌ 高位回吐"
        md += f"| {i} | {code} | {name} | {baseline:+.2f}% | {actual:+.2f}% | {delta:+.2f}% | {ev} |\n"

    if hit_rows:
        md += f"""
**统计：**
- 命中率：{len(positives)}/{len(hit_rows)} = {len(positives)/len(hit_rows)*100:.1f}%
- 整体均值：{avg:+.2f}%
- 正收益均值：{avg_pos:+.2f}%（{len(positives)} 只）
- 负收益均值：{avg_neg:+.2f}%（{len(negatives)} 只）
- **vs 上证 {sh_pct:+.2f}% 超额：{avg - sh_pct:+.2f}%**
- vs 创业板 {cyb_pct:+.2f}% 超额：{avg - cyb_pct:+.2f}%
"""
    else:
        md += f"""
**统计：**
- ⚠️ 上游选股报告 Top10 为空，本次无候选池命中率评估
- 大盘参考：上证 {sh_pct:+.2f}% / 创业板 {cyb_pct:+.2f}%
- 候选池超额：**N/A**
"""

    md += f"""
---

## 四、归因分析

"""
    if hit_rows:
        sorted_hits = sorted(hit_rows, key=lambda x: x[4], reverse=True)
        best = sorted_hits[0]
        worst = sorted_hits[-1]
        md += f"**最强延续：** {best[1]}({best[0]}) Δ={best[4]:+.2f}%\n\n"
        md += f"**最大回吐：** {worst[1]}({worst[0]}) Δ={worst[4]:+.2f}%\n\n"
        if avg > sh_pct + 1:
            md += f"✅ 候选池整体跑赢大盘 {avg - sh_pct:+.2f}%，策略有效\n"
        elif avg < sh_pct - 1:
            md += f"⚠️ 候选池跑输大盘 {abs(avg - sh_pct):.2f}%，需审视板块分布\n"
        else:
            md += f"➡️ 候选池与大盘持平（差额 {avg - sh_pct:+.2f}%），中性表现\n"

    md += f"""
---

## 五、新晋异动 Top5（候选池外）

| # | 代码 | 名称 | 题材标签 | 今日涨幅 |
|:-:|:----:|:----:|:--------|:------:|
"""
    for i, (theme, h) in enumerate(selected, 1):
        pct = h.get("change_pct", 0)
        md += f"| {i} | {h['code']} | {h['name']} | {theme}+... | **{pct:+.2f}%** |\n"

    md += f"""
---

## 六、明日观察要点

1. **大盘性质：** 上证 {sh_pct:+.2f}%，{'强势行情' if sh_pct > 1.5 else ('震荡偏强' if sh_pct > 0 else '震荡偏弱')}；关注明日开盘30分钟量能
2. **主线持续性：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、成交额不萎缩50%
3. **防御方向：** 央企/红利股作为底仓对冲

---

## 七、关键提示

- ⚠️ 本报告基于 17:00 收盘数据生成（数据源：腾讯 + 同花顺）
- 候选池"baseline"实为昨日涨跌幅，Δ 衡量延续性
- 飞书推送 bot: `cli_a934f5a889619bd6` → user `ou_5d0124d26ed21365f74764fcb9fa01b7`
- 关联脚本：`scripts/run_afterhours.py`

---

*📊 AAna 盘后战报 v1.2 | {now}*
"""
    return md


def send_feishu(md, dry=False):
    if dry:
        print("=== DRY RUN: 飞书Markdown ===")
        print(md)
        return
    import subprocess
    result = subprocess.run(
        ["lark-cli", "im", "+messages-send",
         "--user-id", FEISHU_USER, "--as", "bot", "--markdown", md],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print(f"✅ 飞书推送成功")
        print(result.stdout[:200])
    else:
        print(f"❌ 飞书推送失败: {result.stderr}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--dry", action="store_true", help="只输出不推送")
    parser.add_argument("--no-feishu", action="store_true", help="不推送飞书")
    args = parser.parse_args()

    print(f"=== A股盘后战报 {args.date} ===")
    feishu_md, full_md = generate_full_report(args.date)

    if args.dry:
        print("\n=== 飞书 Markdown (DRY) ===")
        print(feishu_md)
        return

    report_path = f"{REPORT_DIR}/{args.date}-盘后战报.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    print(f"✅ 报告已保存: {report_path}")

    if not args.no_feishu:
        send_feishu(feishu_md, dry=False)


if __name__ == "__main__":
    main()
