#!/usr/bin/env python3
"""
scripts/daily_root_cause.py — AAna 每日推荐根因分析 (Phase 12)

为什么今天的选股没胜出? 5 大根因归类:
  A. 板块错配 (sector ∈ weak_sectors)
  B. 题材错配 (候选池 vs 主线热度偏离)
  C. 技术面虚高 (score≥90 但技术指标反向)
  D. 大盘错配 (大盘普跌导致个股跟随)
  E. 冷启动盲区 (n<3 新板块未被黑名单覆盖)

输出:
  - Markdown 报告 → reports/YYYY-MM-DD-根因分析.md
  - JSON 摘要 → data/daily_root_cause.json (auto_tune_next_day.py 读取)

用法:
  python3 scripts/daily_root_cause.py                    # 默认分析最新一天
  python3 scripts/daily_root_cause.py 2026-09-08         # 指定日期
  python3 scripts/daily_root_cause.py --days 7           # 分析最近 7 天 (日报模式)

cron 推荐: 16:00 (盘后战报后, 推荐次日调参前)
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))

DATA_DIR = PROJECT / "data"
REPORTS_DIR = PROJECT / "reports"
REC_FEEDBACK = DATA_DIR / "rec_feedback.csv"
REC_TUNING = DATA_DIR / "rec_tuning.json"
OUT_JSON = DATA_DIR / "daily_root_cause.json"
OUT_MD_DIR = REPORTS_DIR

# ============ 数据加载 ============

def load_feedback() -> list[dict]:
    if not REC_FEEDBACK.exists():
        return []
    with open(REC_FEEDBACK, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_tuning() -> dict:
    if not REC_TUNING.exists():
        return {}
    with open(REC_TUNING, encoding="utf-8") as f:
        return json.load(f)


def fnum(x) -> float | None:
    try: return float(x)
    except (TypeError, ValueError): return None


# ============ 5 大根因检测器 ============

def _sector_info(r: dict, sector_resolver) -> dict:
    """从推荐记录里取 sector 信息, 优先用 rec_feedback 的字段, 空时反查

    返回: {"cn": "锂电池", "enum": "energy"} 或 {"cn": "", "enum": ""}

    关键修复: rec_feedback.csv 新数据可能直接存英文 enum (如 "energy"),
    也可能存中文 cn (如 "锂电池"), 也可能空 (历史数据). 三种情况都要正确处理.
    """
    sec_raw = (r.get('sector') or '').strip()
    if sec_raw:
        # 判断是 enum 还是 cn: 如果含中文, 当 cn; 否则当 enum
        # 中文范围: \u4e00-\u9fff
        from aana_afternoon_screen import _cn_sector_to_enum
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in sec_raw)
        if has_chinese:
            # 中文 cn → 调映射拿 enum
            return {"cn": sec_raw, "enum": _cn_sector_to_enum(sec_raw)}
        else:
            # 英文 enum → 直接用, cn 从 _SECTOR_CN_TO_ENUM 反查 (或者用 resolver)
            return {"cn": "", "enum": sec_raw}
    if sector_resolver:
        return sector_resolver(r['code'])
    return {"cn": "", "enum": ""}


def detect_板块错配(day_recs: list[dict], tuning: dict, sector_resolver=None) -> dict:
    """A. 板块错配 — sector 在 weak_sectors 里还进了推荐

    重要: feedback.csv 里 sector 字段历史 100% 为空 (commit 4111349 修复前),
    必须用 sector_resolver (industry_for_code + _cn_sector_to_enum) 反查补救。
    判定用 enum (rec_tuning 的 key 是 enum), cn 作为辅助说明。
    """
    weak = set(tuning.get('weak_sectors', []))
    if not weak or not day_recs:
        return {"hit": False, "items": [], "summary": "无 weak_sectors 或无当日推荐"}

    items = []
    for r in day_recs:
        info = _sector_info(r, sector_resolver)
        enum = info.get('enum', '')
        cn = info.get('cn', '')
        ret_1d = fnum(r.get('ret_1d'))
        if enum in weak and ret_1d is not None and ret_1d < 0:
            items.append({
                "code": r['code'], "name": r['name'],
                "sector_cn": cn, "sector_enum": enum,
                "ret_1d": ret_1d,
                "severe": "high" if ret_1d < -3 else "mid",
            })
    return {
        "hit": len(items) > 0,
        "items": items,
        "summary": f"{len(items)}/{len(day_recs)} 命中 weak_sectors 但仍亏损" if items else "无弱板块命中",
    }


def detect_题材错配(day_recs: list[dict], tuning: dict, sector_resolver=None) -> dict:
    """B. 题材错配 — 候选池个股不在当日主线热度前 10 题材里
    (无实时题材热度数据时, 退化为"个股属于 n>=5 弱势板块")
    """
    sec_stats = tuning.get('sector_stats', {})
    weak_with_data = {k for k, v in sec_stats.items()
                      if v.get('count', 0) >= 5 and v.get('win_rate', 100) < 35}

    items = []
    if not day_recs:
        return {"hit": False, "items": [], "summary": "无当日推荐"}

    for r in day_recs:
        info = _sector_info(r, sector_resolver)
        enum = info.get('enum', '')
        cn = info.get('cn', '')
        ret_1d = fnum(r.get('ret_1d'))
        if enum in weak_with_data and ret_1d is not None and ret_1d < -1:
            items.append({
                "code": r['code'], "name": r['name'],
                "sector_cn": cn, "sector_enum": enum,
                "ret_1d": ret_1d,
                "note": "n>=5 板块仍亏损, 说明板块内部选股质量也差",
            })
    return {
        "hit": len(items) > 0,
        "items": items,
        "summary": f"{len(items)} 只来自 n>=5 弱势板块仍亏" if items else "无",
    }


def detect_冷启动盲区(day_recs: list[dict], tuning: dict, sector_resolver=None) -> dict:
    """E. 冷启动盲区 — 推荐里出现 sec_stats 未覆盖的板块 (n=0 或 n<3)

    关键修复: feedback.csv 历史 sector 字段为空, 必须用 resolver 反查。
    判定标准 (任一即视为冷启动):
      - 推荐票的 cn (中文行业名) 不在 sec_stats 里
      - 推荐票的 enum 不在 sec_stats 里
      - 已知板块但 n < 3
    """
    sec_stats = tuning.get('sector_stats', {})

    items = []
    for r in day_recs:
        info = _sector_info(r, sector_resolver)
        enum = info.get('enum', '')
        cn = info.get('cn', '')
        ret_1d = fnum(r.get('ret_1d'))

        # 没查到任何信息 -> 不是冷启动 (无法判断)
        if not enum and not cn:
            continue

        # 已知板块且样本 >= 3 -> 不是冷启动
        if enum and sec_stats.get(enum, {}).get('count', 0) >= 3:
            continue

        # 冷启动: cn 不在 sec_stats 里 (枚举或中文都查不到), 或 enum 在但 n<3
        is_cold = (cn and cn not in sec_stats) or (enum and sec_stats.get(enum, {}).get('count', 0) < 3)
        if is_cold:
            sec_stat = sec_stats.get(enum or cn, {})
            note = (f"板块 {cn} (enum={enum or '未映射'}) 未在 sec_stats 里, cold sector risk"
                    if enum and cn and cn not in sec_stats and enum not in sec_stats
                    else f"板块样本 {sec_stat.get('count', 0)} < 3")
            items.append({
                "code": r['code'], "name": r['name'],
                "sector_cn": cn, "sector_enum": enum,
                "n": sec_stat.get('count', 0),
                "ret_1d": ret_1d,
                "note": note,
            })
    if not items:
        return {"hit": False, "items": [], "summary": "无冷启动命中"}

    # 冷启动板块分组 (按 cn 或 enum 去重, 因为 enum 可能是空)
    groups = defaultdict(list)
    for it in items:
        key = it['sector_cn'] or it['sector_enum'] or '(unknown)'
        groups[key].append(it)
    # 出现 ≥3 次的进 watchlist; 其余仍标记为 cold_sector (单独列出)
    watchlist = [k for k, v in groups.items() if len(v) >= 3]
    cold_list = [k for k, v in groups.items() if len(v) < 3]
    return {
        "hit": True,
        "items": items,
        "watchlist": watchlist,
        "cold_sectors": cold_list,  # 新增: 一次性出现的冷启动板块 (低优先级但要提示)
        "summary": (f"{len(items)} 只命中冷启动板块 ({len(groups)} 个不同板块)"
                    + (f", watchlist: {watchlist}" if watchlist else "")
                    + (f", 单次冷板块: {cold_list[:5]}" if cold_list else "")),
    }


def detect_技术面虚高(day_recs: list[dict], tuning: dict) -> dict:
    """C. 技术面虚高 — score>=90 但 MACD 金叉 + ret<0 (90 天回测反向)"""
    items = []
    if not day_recs:
        return {"hit": False, "items": [], "summary": "无当日推荐"}

    for r in day_recs:
        sc = fnum(r.get('score'))
        ret_1d = fnum(r.get('ret_1d'))
        macd = (r.get('macd_gold') or '').lower() == 'true'
        if sc is not None and sc >= 90 and macd and ret_1d is not None and ret_1d < 0:
            items.append({
                "code": r['code'], "name": r['name'],
                "score": sc, "ret_1d": ret_1d,
                "note": "score>=90 + MACD 金叉 + 亏损 — 强负信号",
            })
    return {
        "hit": len(items) > 0,
        "items": items,
        "summary": f"{len(items)} 只高分红负收益 (MACD 金叉反向)" if items else "无",
    }


def detect_大盘错配(day_recs: list[dict], day_baseline: float | None) -> dict:
    """D. 大盘错配 — 大盘 4 大核心平均 < -1% 时, 个股大概率跟随跌"""
    if day_baseline is None:
        return {"hit": False, "items": [], "summary": "无大盘数据"}
    if day_baseline > -1.0:
        return {"hit": False, "items": [], "summary": f"大盘 {day_baseline:+.2f}% 正常, 非大盘错配"}

    # 大盘普跌: 候选池均值 < baseline 算"未跑赢大盘"
    if not day_recs:
        return {"hit": False, "items": [], "summary": "无当日推荐"}
    returns = [fnum(r.get('ret_1d')) for r in day_recs]
    returns = [r for r in returns if r is not None]
    if not returns:
        return {"hit": False, "items": [], "summary": "无收益数据"}
    pool_avg = sum(returns) / len(returns)
    if pool_avg < day_baseline:
        return {
            "hit": True,
            "items": [{"pool_avg": pool_avg, "baseline": day_baseline, "gap": pool_avg - day_baseline}],
            "summary": f"大盘 {day_baseline:+.2f}% 普跌, 候选池均值 {pool_avg:+.2f}% 跑输 {pool_avg - day_baseline:+.2f}pp",
        }
    return {"hit": False, "items": [], "summary": f"大盘跌但候选池 {pool_avg:+.2f}% 跑赢"}



def get_day_baseline(date: str, feedback_rows: list[dict]) -> float | None:
    """从当日复盘报告读 4 大指数平均"""
    report = REPORTS_DIR / f"{date}-复盘报告.md"
    if not report.exists():
        return None
    with open(report, encoding="utf-8") as f:
        content = f.read()
    # 找 "4 大核心平均" 字段
    import re
    m = re.search(r"4 大核心平均\s*([+-][\d.]+)\s*%", content)
    if m:
        return float(m.group(1))
    return None


def make_sector_resolver():
    """构造 industry_for_code + _cn_sector_to_enum 链, 反查 6 位代码 → sector 信息

    返回: (code) -> dict {"cn": "锂电池", "enum": "energy"} or {"cn": "", "enum": ""} if unknown
    """
    try:
        from data_sources import industry_for_code, normalize_code
        from aana_afternoon_screen import _cn_sector_to_enum
    except ImportError:
        return None

    cache = {}
    def resolve(code: str) -> dict:
        if code in cache:
            return cache[code]
        try:
            cn = industry_for_code(normalize_code(code)) or ''
            cn = cn.strip() if cn else ''
            if not cn or cn == 'unknown':
                cache[code] = {"cn": "", "enum": ""}
                return cache[code]
            enum = _cn_sector_to_enum(cn)
            cache[code] = {
                "cn": cn,
                "enum": enum if enum and enum != 'unknown' else "",
            }
            return cache[code]
        except Exception:
            cache[code] = {"cn": "", "enum": ""}
            return cache[code]
    return resolve


# ============ 主分析 ============

def analyze_day(date: str, feedback: list[dict], tuning: dict, sector_resolver=None) -> dict:
    """分析某一天的根因"""
    day_recs = [r for r in feedback if r.get('date', '').startswith(date)]

    baseline = get_day_baseline(date, feedback)

    causes = {
        "A_板块错配": detect_板块错配(day_recs, tuning, sector_resolver),
        "B_题材错配": detect_题材错配(day_recs, tuning, sector_resolver),
        "C_技术面虚高": detect_技术面虚高(day_recs, tuning),
        "D_大盘错配": detect_大盘错配(day_recs, baseline),
        "E_冷启动盲区": detect_冷启动盲区(day_recs, tuning, sector_resolver),
    }

    # 总命中统计
    hit_causes = [k for k, v in causes.items() if v.get('hit')]
    win = sum(1 for r in day_recs if fnum(r.get('ret_1d')) is not None and fnum(r.get('ret_1d')) > 0)
    fail = sum(1 for r in day_recs if fnum(r.get('ret_1d')) is not None and fnum(r.get('ret_1d')) <= 0)
    no_data = len(day_recs) - win - fail

    return {
        "date": date,
        "total_recs": len(day_recs),
        "win_count": win, "fail_count": fail, "no_data": no_data,
        "win_rate": win / (win + fail) * 100 if (win + fail) else 0,
        "baseline": baseline,
        "causes": causes,
        "hit_causes": hit_causes,
    }


def to_markdown(result: dict) -> str:
    d = result['date']
    md = [f"# 🔬 AAna 每日根因分析 — {d}", ""]
    md.append(f"> **生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    md.append(f"> **数据源:** data/rec_feedback.csv + data/rec_tuning.json  ")
    md.append(f"> **大盘基线 (4 大核心平均):** {result['baseline']:+.2f}%  " if result['baseline'] is not None
              else "> **大盘基线:** 复盘报告未生成")
    md.append("")

    md.append(f"## 📊 当日推荐概览\n")
    md.append(f"| 总推荐 | 命中 | 亏损 | 无 1D 数据 | 胜率 |")
    md.append("|:---:|:---:|:---:|:---:|:---:|")
    md.append(f"| {result['total_recs']} | {result['win_count']} | {result['fail_count']} | "
              f"{result['no_data']} | {result['win_rate']:.1f}% |")
    md.append("")

    # 根因分类输出
    md.append("## 🎯 5 大根因分类\n")
    icon_map = {"A_板块错配": "🏭", "B_题材错配": "🎭", "C_技术面虚高": "📊",
                "D_大盘错配": "📉", "E_冷启动盲区": "❄️"}
    for cause_key, cause in result['causes'].items():
        icon = icon_map[cause_key]
        hit_flag = "🔥 命中" if cause['hit'] else "✅ 未命中"
        md.append(f"### {icon} {cause_key}  {hit_flag}")
        md.append(f"> {cause['summary']}")
        if cause.get('items'):
            md.append("")
            md.append("| 代码 | 名称 | 板块 (cn) | enum | 1D | 备注 |")
            md.append("|:---:|:---:|:---:|:---:|:---:|:---|")
            for it in cause['items'][:10]:
                cn = it.get('sector_cn') or it.get('sector') or '-'
                enum = it.get('sector_enum') or '-'
                ret = it.get('ret_1d', 0)
                if ret is None: ret = 0
                md.append(f"| {it.get('code','')} | {it.get('name','')} | {cn} | {enum} | "
                          f"{ret:+.2f}% | {it.get('note','')} |")
        md.append("")

    # 命中根因汇总
    if result['hit_causes']:
        md.append("## 🚨 命中根因 (按优先级)")
        for c in result['hit_causes']:
            md.append(f"- **{c}**: {result['causes'][c]['summary']}")
        md.append("")
        md.append("## 💡 次日调参建议 (auto_tune_next_day.py 会读取以下字段)")
        md.append("- 见 `data/daily_root_cause.json` 的 `tuning_suggestion` 字段")
    else:
        md.append("## ✅ 无显著根因命中")
        md.append("当日推荐表现正常或样本过小, 不需要调参。")

    md.append("")
    md.append("---")
    md.append(f"*Generated by `scripts/daily_root_cause.py` | AAna v2026.3*")
    return "\n".join(md)


def suggest_tuning(result: dict, tuning: dict) -> dict:
    """根据根因结果生成次日调参建议"""
    suggestions = {
        "score_threshold_delta": 0,
        "hold_days_delta": 0,
        "weak_sectors_add": [],   # 加进黑名单
        "weak_sectors_remove": [],  # 移出黑名单
        "watchlist": [],          # 冷启动观察
        "position_delta": 0,
        "reasons": [],
    }

    sec_stats = tuning.get('sector_stats', {})
    cold_sectors = {k for k, v in sec_stats.items() if v.get('count', 0) < 3}

    # A. 板块错配命中 → score_threshold +5 (更严)
    cause_a = result['causes'].get('A_板块错配', {})
    if cause_a.get('hit'):
        # 命中 weak_sectors 的个股里如果有 n>=3 但 win_rate<35 的板块, 自动加严
        for it in cause_a.get('items', []):
            sec = it.get('sector_enum') or it.get('sector', '')
            if sec and sec not in suggestions['weak_sectors_add']:
                # 但仅当 sector_stats 已有这个 key 时才加 (避免乱加)
                if sec in sec_stats and sec_stats[sec].get('count', 0) >= 3:
                    suggestions['weak_sectors_add'].append(sec)
        if suggestions['weak_sectors_add']:
            suggestions['score_threshold_delta'] = max(suggestions['score_threshold_delta'], 5)
            suggestions['reasons'].append(
                f"A. 板块错配: {len(cause_a['items'])} 只命中 weak_sectors, 加严阈值 +5pp"
            )

    # B. 题材错配 → 评分阈值 +5, 仓位 -10
    cause_b = result['causes'].get('B_题材错配', {})
    if cause_b.get('hit'):
        suggestions['score_threshold_delta'] = max(suggestions['score_threshold_delta'], 5)
        suggestions['position_delta'] = min(suggestions['position_delta'], -10)
        suggestions['reasons'].append(
            f"B. 题材错配: {len(cause_b['items'])} 只来自 n>=5 弱势板块, 阈值+5 + 仓位-10"
        )

    # C. 技术面虚高 → MACD 扣分更狠 (建议在 aana_afternoon_screen 改 -3 → -5)
    cause_c = result['causes'].get('C_技术面虚高', {})
    if cause_c.get('hit'):
        suggestions['macd_gold_delta'] = -2  # 在已有 -3 基础上再减 2 = -5
        suggestions['reasons'].append(
            f"C. 技术面虚高: {len(cause_c['items'])} 只 score≥90 + MACD 金叉仍亏, MACD 扣分 -3→-5"
        )

    # D. 大盘错配 → 仓位 -10
    cause_d = result['causes'].get('D_大盘错配', {})
    if cause_d.get('hit'):
        suggestions['position_delta'] = min(suggestions['position_delta'], -10)
        suggestions['reasons'].append(
            f"D. 大盘错配: {cause_d['summary']}, 仓位 -10"
        )

    # E. 冷启动盲区 → watchlist + 阈值收紧
    cause_e = result['causes'].get('E_冷启动盲区', {})
    if cause_e.get('hit'):
        suggestions['watchlist'] = cause_e.get('watchlist', [])
        suggestions['cold_sectors'] = cause_e.get('cold_sectors', [])
        n_cold = len(cause_e.get('cold_sectors', []))
        n_items = len(cause_e.get('items', []))
        # 多只冷启动板块命中 -> 收紧阈值避免再选未验证板块
        if n_items >= 2:
            suggestions['score_threshold_delta'] = max(suggestions['score_threshold_delta'], 3)
            suggestions['position_delta'] = min(suggestions['position_delta'], -5)
            suggestions['reasons'].append(
                f"E. 冷启动盲区: {n_items} 只来自 {n_cold} 个未验证板块, 阈值+3pp + 仓位-5pp, "
                f"watchlist={suggestions['watchlist']}, cold={cause_e.get('cold_sectors', [])[:5]}"
            )
        else:
            suggestions['reasons'].append(
                f"E. 冷启动盲区: {n_items} 只命中冷启动板块, watchlist={suggestions['watchlist']}, "
                f"cold={cause_e.get('cold_sectors', [])[:5]}"
            )

    return suggestions


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("date", nargs="?", default=datetime.now().strftime("%Y-%m-%d"),
                   help="分析日期 (默认今天)")
    p.add_argument("--days", type=int, default=1, help="分析最近 N 天 (日报模式)")
    p.add_argument("--json", action="store_true", help="同时落 data/daily_root_cause.json")
    args = p.parse_args()

    feedback = load_feedback()
    tuning = load_tuning()
    if not feedback:
        print("[daily_root_cause] 无 rec_feedback 数据, 退出")
        return 1

    # 构造 sector 反查器 (用于历史 sector 字段为空的票)
    sector_resolver = make_sector_resolver()
    if sector_resolver:
        print("[daily_root_cause] sector_resolver 已加载 (industry_for_code + _cn_sector_to_enum)")
    else:
        print("[daily_root_cause] ⚠️ sector_resolver 加载失败, 历史空 sector 票无法归因")

    if args.days > 1:
        # 日报模式: 分析最近 N 天
        dates = sorted(set(r['date'][:10] for r in feedback), reverse=True)[:args.days]
    else:
        dates = [args.date]

    all_results = []
    for d in dates:
        result = analyze_day(d, feedback, tuning, sector_resolver)
        # 调参建议
        result['tuning_suggestion'] = suggest_tuning(result, tuning)
        all_results.append(result)

        # 写 markdown
        md = to_markdown(result)
        out_md = OUT_MD_DIR / f"{d}-根因分析.md"
        out_md.write_text(md, encoding="utf-8")
        print(f"[daily_root_cause] {d} → {out_md}")

    if args.json or len(dates) == 1:
        # 只落最近一天的 JSON
        latest = all_results[0]
        OUT_JSON.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[daily_root_cause] JSON → {OUT_JSON}")

    print(f"\n[daily_root_cause] 分析完成, 共 {len(all_results)} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
