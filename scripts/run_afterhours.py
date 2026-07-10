#!/usr/bin/env python3
"""
A股盘后战报 端到端生成脚本

用法:
    python3 scripts/run_afterhours.py                    # 跑今天 (cron 推荐)
    python3 scripts/run_afterhours.py 2026-06-08         # 跑指定日期
    python3 scripts/run_afterhours.py 2026-06-08 --dry   # 不推送飞书，只输出
"""
import argparse
import re
import sys
from collections import Counter
from datetime import datetime

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
FEISHU_USER = "ou_5d0124d26ed21365f74764fcb9fa01b7"
REPORT_DIR = "/Users/cai/code/AAna/reports"


def tencent_quote(codes):
    """腾讯行情；key 用带前缀的 'sh000001' 不是 '000001'"""
    code_str = ",".join(codes) if isinstance(codes, list) else codes
    url = f"https://qt.gtimg.cn/q={code_str}"
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://finance.qq.com"}, timeout=10)
    r.encoding = "gbk"
    result = {}
    for line in r.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'v_(\w+)="(.+)"', line)
        if not m:
            continue
        key_code = m.group(1)
        parts = m.group(2).split("~")
        if len(parts) > 32:
            try:
                result[key_code] = {
                    "name": parts[1], "code6": parts[2],
                    "current": float(parts[3]) if parts[3] else None,
                    "prev_close": float(parts[4]) if parts[4] else None,
                    "change_pct": float(parts[32]) if parts[32] else 0,
                }
            except Exception:
                pass
    return result


def get_indices():
    codes = ["sh000001", "sz399001", "sz399006", "sz399005", "sz399300", "sh000688"]
    return tencent_quote(codes)


def ths_hot(date_str):
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
    data = r.json()
    rows = data.get("data") or []
    return [{"code": row.get("code", ""), "name": row.get("name", ""),
             "reason": row.get("reason", ""), "date": row.get("date", ""),
             "market": row.get("market")} for row in rows]


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


def _yesterday(date_str):
    from datetime import timedelta
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


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
    for line in content.split("\n"):
        if "重点关注 Top 10" in line or "🏆 重点关注" in line:
            in_section = True
            continue
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
            if code and pct is not None:
                rows.append((code, name or code, pct))
        elif in_section and line.startswith("## "):
            break
    return rows[:10]


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
    hot_yest = ths_hot(_yesterday(date_str))
    ct = theme_counter(hot)
    cy = theme_counter(hot_yest)
    themes = [t for t, _ in ct.most_common() if t != "ST板块"][:10]

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
    # ⚠️ v1.17 pitfall: 必须先按 20cm 优先 + 涨幅降序预排序，再按题材去重；
    # 否则 priority 先命中主板 10cm 会挤掉创业板/科创板 20cm 涨停。
    outside.sort(key=lambda h: (-(1 if h.get("market") in (33, 48) else 0), -h.get("change_pct", 0)))
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
            continue
        # 先按 20cm 优先排序后的股票流逐个选；同一题材只取一只，保证题材多样性。
        if matched in used_theme:
            continue
        market = h.get("market")
        h["_is_20cm"] = market in (33, 48)
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
    gap_md, has_gap = realtime_gap_alert(indices, candidate_paths)

    # 飞书版（短）
    feishu_md = format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                              positives, negatives, avg, avg_pos, avg_neg,
                              sh_pct, cyb_pct, kc50_pct, selected, len(hot),
                              gap_md)

    # 完整报告
    full_md = format_full_report(date_str, indices, themes, ct, cy, hit_rows,
                                 positives, negatives, avg, avg_pos, avg_neg,
                                 sh_pct, cyb_pct, kc50_pct, selected, len(hot))
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
        return "", False
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
    if not has_alert or not rows:
        return "", False
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
    return md, True


def format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                   positives, negatives, avg, avg_pos, avg_neg,
                   sh_pct, cyb_pct, kc50_pct, selected, hot_count,
                   gap_md=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = f"📊 **盘后战报 {date_str} {now[11:]}**\n\n"

    md += "━━━ **行业今日全貌** ━━━\n\n"
    md += "🔥 **今日最强题材（热度排行 Top10）：**\n"
    for i, theme in enumerate(themes, 1):
        cnt = ct.get(theme, 0)
        yest = cy.get(theme, 0)
        diff = cnt - yest
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        md += f"{i}️⃣ {theme} — {cnt}次（较昨日 {arrow}{abs(diff)}）\n"

    md += f"\n⚠️ **市场特征：**（根据 {hot_count} 只强势股判断）\n"
    md += f"- 上证 {sh_pct:+.2f}% / 创业板 {cyb_pct:+.2f}% / 科创50 {kc50_pct:+.2f}%\n\n"

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

    if hit_rows:
        md += f"\n📊 **命中率：** {len(positives)}/{len(hit_rows)} = {len(positives)/len(hit_rows)*100:.1f}%\n"
        md += f"- 整体均值：{avg:+.2f}% | 正：{avg_pos:+.2f}% | 负：{avg_neg:+.2f}%\n"
        md += f"- vs 上证 {sh_pct:+.2f}% 超额：**{avg - sh_pct:+.2f}%**\n"
    else:
        md += "\n⚠️ **候选池评估：** 上游选股报告 Top10 为空，本次无候选池命中率评估\n"
        md += f"- 大盘参考：上证 {sh_pct:+.2f}%；候选池超额：**N/A**\n"

    md += "\n━━━ **新晋异动 Top5** ━━━\n\n"
    for i, (theme, h) in enumerate(selected, 1):
        pct = h.get("change_pct", 0)
        md += f"{i}️⃣ {h['code']} {h['name']} — {theme} **{pct:+.2f}%**\n"

    md += "\n━━━ **明日观察要点** ━━━\n"
    # ⚠️ v1.11/v1.13 模式检测: 候选池失败模式 + 大盘性质
    if avg < -3.0:
        # v1.11 第五种模式: 系统性崩盘 (10%命中+负Alpha)
        md += f"1️⃣ **大盘性质：** ⚠️ 极端情绪日！上证 {sh_pct:+.2f}%，深证 {indices.get('sz399001',{}).get('change_pct',0):+.2f}%，**关注明日反弹**（普跌次日反弹概率高）\n"
        md += f"2️⃣ **回避：** 昨日涨幅+4%以上的追高标的（今日集体杀跌主力）\n"
        md += f"3️⃣ **防御：** 高股息/黄金/稀土等防御板块作为底仓\n"
    elif sh_pct < -1.5 and kc50_pct < -5:
        # 平稳转急跌型 (类似 2026-06-26)
        md += f"1️⃣ **大盘性质：** ⚠️ 平稳转急跌型！盘中{sh_pct:+.2f}%以内震荡 → 尾盘1小时集体跳水（创业板/科创50 {cyb_pct:+.2f}%/{kc50_pct:+.2f}%）\n"
        md += f"2️⃣ **回避：** 追高强势股（今日全市场普跌）+ 题材投机（小盘股流动性风险）\n"
        md += f"3️⃣ **主线：** 关注{', '.join(themes[:3])} 龙头股是否扛住杀跌（扛住=主线成立）\n"
    else:
        md += f"1️⃣ **大盘：** 上证 {sh_pct:+.2f}%，{'强势' if sh_pct > 1.5 else ('震荡偏弱' if sh_pct < -1 else '震荡')}；关注明日开盘30分钟量能\n"
        md += f"2️⃣ **主线：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、成交不萎缩50%\n"
        md += f"3️⃣ **防御：** 央企/红利股作为底仓对冲\n"
    if gap_md:
        md += gap_md
    md += "\n⚠️ **仅供参考，不构成投资建议**\n"
    return md


def format_full_report(date_str, indices, themes, ct, cy, hit_rows,
                       positives, negatives, avg, avg_pos, avg_neg,
                       sh_pct, cyb_pct, kc50_pct, selected, hot_count):
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

    report_path = f"{REPORT_DIR}/{args.date}-盘后战报.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    print(f"✅ 报告已保存: {report_path}")

    if args.dry:
        print("\n=== 飞书 Markdown (DRY) ===")
        print(feishu_md)
    elif not args.no_feishu:
        send_feishu(feishu_md, dry=False)


if __name__ == "__main__":
    main()
