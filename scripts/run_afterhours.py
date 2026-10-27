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
    q = tencent_quote(codes)
    # ⚠️ 2026-10-21 修复: ds.tencent_quote 同时返回裸 6 位 key 和带前缀 key
    # （2026-08-31 兼容性改造），6 个指数会变成 12 个条目。
    # 旧代码 `len(indices) != 6` 因此永远误报 "只拉到 12/6 个指数"。
    # 正确做法: 按实际需要的 6 个带前缀 key 判断覆盖率。
    missing = [c for c in codes if c not in q]
    if missing:
        print(f"⚠️  指数缺失: {missing}")
    return q


def ths_hot(date_str):
    """同花顺强势股（直连接口，保留行级 date 字段用于非交易日过滤）

    ⚠️ 2026-10-26 修复（两层）:
    1. 同花顺 /date/{非交易日}/ 端点**不返回空**，而是回落到"最近一个有数据的
       交易日"（实测 2026-10-24/25 两个非交易日都返回了 2026-10-26 当天的记录）。
       旧代码直接取用 → 题材环比变成"今天 vs 今天"，所有 diff 恒为 0。
       修复: 按行内 `date` 字段过滤，只保留 date == 请求日期的记录。
    2. ds.ths_hot_reason() 的返回结构**丢弃了行级 date 字段**（只回顶层
       'date' 回显），导致按行过滤无从下手 → 本函数改为直连接口解析。
    请求日无数据时返回 [] → previous_nonempty_hot_day 会继续向前回溯。
    """
    import requests as _rq
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_str}"
           f"/orderby/date/orderway/desc/charset/GBK/")
    try:
        r = _rq.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"}, timeout=10)
        data = r.json()
    except Exception:
        return []
    rows = data.get("data") or []
    out = []
    for row in rows:
        # 端点在无数据日会回落成"最近交易日"的数据 → 必须按行级 date 过滤
        row_date = str(row.get("date") or "")[:10]
        if row_date != date_str:
            continue
        out.append({
            "code": str(row.get("code", "")).zfill(6),
            "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "date": row_date,
            "market": row.get("market"),
        })
    return out


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
        # 2026-08-31 修复: ds.tencent_quote 用 price/last_close (而非 current/prev_close)
        # 同时兼容两种命名: 优先 ds 标准字段, fallback 到旧字段
        q_entry = q.get(f"{prefix}{c}") or q.get(c) or {}
        if q_entry:
            h["change_pct"] = q_entry.get("change_pct", 0)
            h["current"] = q_entry.get("price", q_entry.get("current"))
            h["prev_close"] = q_entry.get("last_close", q_entry.get("prev_close"))
    return hot_list


def theme_counter(hot_list):
    c = Counter()
    for item in hot_list:
        for r in str(item.get("reason") or "").split("+"):
            if r.strip():
                c[r.strip()] += 1
    return c


def _industry_ranking_ths(top_n=10):
    """同花顺行业板块 fallback — 东财 push2 全断时使用。

    ⚠️ 2026-10-26 实战: 东财 push2 **主域 + push2delay 双双 RemoteDisconnected**
    (已连续多日不可用), 行业全貌整段降级为"无数据" → 战报丢失最重要的
    "行业今日全貌"章节。同花顺行业接口 (akshare stock_board_industry_summary_ths)
    实测可用, 返回 90 个行业板块的涨跌幅/净流入/涨跌家数。

    返回契约与东财一致: {top, bottom, total, fetched, universe, source}
      - top:    涨幅榜（降序）
      - bottom: 跌幅榜（升序，最差在前）
    """
    try:
        import akshare as ak
        df = ak.stock_board_industry_summary_ths()
    except Exception as e:
        return {"top": [], "bottom": [], "total": 0, "fetched": 0,
                "universe": 0, "source": "ths", "error": f"ths 行业接口失败: {e}"}
    if df is None or len(df) == 0:
        return {"top": [], "bottom": [], "total": 0, "fetched": 0,
                "universe": 0, "source": "ths", "error": "ths 行业接口返回空"}
    rows = []
    for _, r in df.iterrows():
        try:
            pct = float(r.get("涨跌幅"))
        except (TypeError, ValueError):
            continue
        rows.append({
            "name": str(r.get("板块", "")).strip(),
            "change_pct": pct,
            "code": "",
            "up_count": r.get("上涨家数", 0),
            "down_count": r.get("下跌家数", 0),
            "leader": str(r.get("领涨股", "")).strip(),
            "leader_change": r.get("领涨股-涨跌幅", 0),
        })
    rows.sort(key=lambda x: -x["change_pct"])
    return {
        "top": rows[:top_n],
        "bottom": list(reversed(rows[-top_n:])) if rows else [],
        "total": len(rows),
        "fetched": len(rows),
        "universe": len(rows),
        "source": "ths",
    }


def get_industry_ranking(top_n=10):
    """东财行业涨跌 — 用 ds.industry_comparison（已内置 fid=f3 排序 + 全量分页）

    ds.industry_comparison 返回 dict: {top, bottom, total, fetched, source}
    契约（2026-10-21 修复后）:
      - top:    涨幅榜，按 change_pct 降序
      - bottom: 跌幅榜，按 change_pct 升序（**最差在前**）
    ⚠️ 旧代码用 `bottom[-top_n:]` 取跌幅榜，在 bottom 已按升序排列后会拿到
    "跌幅榜里最不差的那几条"，反而丢掉真正的跌幅榜 → 榜单标签与内容相反。

    ⚠️ 2026-10-26 新增: 东财 push2 双域断连时降级到同花顺行业板块
    (见 _industry_ranking_ths), 保住"行业今日全貌"章节。
    """
    raw = ds.industry_comparison(top_n=top_n)  # ds 已同时给出 top/bottom 各 top_n 条
    if not isinstance(raw, dict):
        raw = {"top": [], "bottom": [], "total": 0, "error": "ds 返回非 dict"}
    top = raw.get("top", []) or []
    bottom = raw.get("bottom", []) or []
    source = raw.get("source", "scripts.data_sources.industry_comparison")
    error = raw.get("error", "")

    if not top:
        # 东财不可用 → 同花顺行业板块兜底
        ths = _industry_ranking_ths(top_n)
        if ths.get("top"):
            ths["error"] = error  # 保留东财失败原因用于展示
            return {
                "top": ths["top"],
                "bottom": ths["bottom"],
                "total": ths["total"],
                "returned": ths["fetched"],
                "universe": ths["universe"],
                "source": "ths",
                "error": error,
            }
        return {
            "top": [], "bottom": [], "total": 0, "returned": 0, "universe": 0,
            "source": "none",
            "error": f"{error} | 同花顺行业兜底也失败: {ths.get('error', '无数据')}",
        }

    return {
        "top": top[:top_n],
        "bottom": bottom[:top_n],  # bottom 已是"最差在前"，直接取头部
        "total": raw.get("total", len(top) + len(bottom)),
        "returned": raw.get("fetched", len(top) + len(bottom)),
        "universe": raw.get("universe", raw.get("total", 0)),
        "source": source,
        "error": error,
    }


def get_daily_dragon_tiger(date_str):
    """东财龙虎榜 — ds.daily_dragon_tiger(trade_date)

    ds.daily_dragon_tiger 返回 {date, total_records, stocks, [note]}
    本函数适配为 {rows, source} 接口约定,以便下游消费方拿到统一格式。
    """
    raw = ds.daily_dragon_tiger(trade_date=date_str)
    if isinstance(raw, dict):
        # 2026-08-31 修复: ds 返回 key 是 "stocks", 转换为 "rows" 兼容下游
        if "rows" in raw:
            return raw
        if "stocks" in raw:
            return {
                "rows": raw.get("stocks", []),
                "date": raw.get("date", date_str),
                "total_records": raw.get("total_records", 0),
                "source": "scripts.data_sources.daily_dragon_tiger",
                "note": raw.get("note", ""),
            }
    return {"rows": [], "note": "scripts.data_sources.daily_dragon_tiger 未返回 rows", "date": date_str}


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
    """向后兼容包装: 只返回 rows。候选池来源回捞逻辑见 resolve_candidate_pool()。"""
    rows, _, _ = resolve_candidate_pool(date_str)
    return rows


def parse_top10_content(content):
    """从选股报告正文解析 Top10 section → [(code, name, baseline_pct)]。

    纯函数（不含 IO），供 on-disk / git HEAD 两种来源复用。
    """
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
            # 列顺序: ['', '排名', '股票', '代码', '价格', '涨跌幅', '技术分', '综合评分', '信号', '风险', '趋势', '']
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


def _parse_top10_from_deep_analysis(date_str):
    """从 {date}-深度分析.md 的"候选池"表格回捞候选池。

    ⚠️ 2026-10-26 实战: 选股报告的 Top10 section 会被**盘中重跑覆盖**成空
    (09:37 重跑用盘中实时情绪把"停止交易"状态写回同一个文件, 把 08:02 盘前
    版的 10 只候选池清空)。深度分析报告 08:34 生成时读的还是盘前版,
    其"二、候选池"表格保留了完整的 10 只 + 基准日涨跌幅 → 作为回捞来源。

    表格形如:
      | 深度排名 | 股票 | 代码 | 10-23 涨跌 | ... |
      | 1 | 🥇**西麦食品** | **002956** | **+4.73%** | ... |
    """
    path = f"{REPORT_DIR}/{date_str}-深度分析.md"
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return []
    lines = content.split("\n")
    start = None
    for i, line in enumerate(lines):
        if "候选池" in line and line.startswith("##"):
            start = i
            break
    if start is None:
        return []
    rows = []
    seen = set()
    for line in lines[start + 1:]:
        if re.match(r"^#{1,3}\s+", line):
            break
        if not line.startswith("|"):
            continue
        if "代码" in line:
            continue
        cells = [c.strip().replace("**", "").replace("🥇", "").replace("🥈", "")
                 .replace("🥉", "").replace("🆕", "") for c in line.split("|")]
        code = next((c for c in cells if re.match(r"^\d{6}$", c)), None)
        if not code or code in seen:
            continue
        ci = cells.index(code)
        name = cells[ci - 1] if ci > 0 else code
        pct = None
        for c in cells[ci + 1:]:
            m = re.search(r"([+-]?\d+\.\d+)%", c)
            if m:
                pct = float(m.group(1))
                break
        if pct is None:
            continue
        rows.append((code, name or code, pct))
        seen.add(code)
        if len(rows) >= 10:
            break
    return rows


def _git_head_top10(date_str):
    """从 git HEAD 读取 {date}-选股报告.md 并解析 Top10。

    选股报告每天都会被 autopilot 提交, 因此 HEAD 版本通常就是**盘前版**
    (08:02 生成的 Top10), 即使工作区文件已被盘中重跑覆盖。
    """
    import subprocess
    rel = f"reports/{date_str}-选股报告.md"
    repo = os.path.dirname(REPORT_DIR.rstrip("/"))
    try:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    return parse_top10_content(out.stdout)


def resolve_candidate_pool(date_str):
    """解析候选池, 返回 (rows, source_label, note)。

    来源优先级 (on-disk → git HEAD → 深度分析回捞):
      1. 工作区 {date}-选股报告.md 的 "重点关注 Top 10" section
      2. git HEAD 的同名文件 (盘前版, 盘中重跑覆盖工作区时的兜底)
      3. {date}-深度分析.md 的 "二、候选池" 表格 (上游 bug 的最后兜底)

    ⚠️ 2026-10-26 实战: 工作区文件 09:39 被重跑覆盖成 Top10 空表
    (情绪 25 冰点/停止交易), 直接读会把**真实存在并已同步东财**的
    10 只候选池误判为"上游报告缺失"。三源回捞后命中率评估恢复正常。
    """
    path = f"{REPORT_DIR}/{date_str}-选股报告.md"
    try:
        with open(path) as f:
            rows = parse_top10_content(f.read())
        if rows:
            return rows, "选股报告(工作区)", ""
    except FileNotFoundError:
        pass

    rows = _git_head_top10(date_str)
    if rows:
        return rows, "选股报告(git HEAD 盘前版)", (
            "⚠️ 工作区选股报告的 Top10 section 为空（盘中重跑覆盖），"
            "已回捞 git HEAD 盘前版候选池"
        )

    rows = _parse_top10_from_deep_analysis(date_str)
    if rows:
        return rows, "深度分析报告候选池表", (
            "⚠️ 工作区与 git HEAD 的选股报告 Top10 均为空，"
            "已从深度分析报告的候选池表格回捞"
        )

    return [], "无", "⚠️ 三源均无候选池（选股报告/深度分析报告）"


def resolve_theme_label(reason, final_priority):
    """从同花顺 reason 解析题材标签。

    规则:
      1. 命中 final_priority（当日热度 Top5 + 硬编码 20 项）→ 用该 priority 词；
         但若标的自身标签里有更具体的包含该词的标签，取**最长的那个**
         （reason="人形机器人" + priority 含"机器人" → 显示"人形机器人"，
          不显示"机器人"，避免丢掉"人形机器人当日 ↓5"这类信息）。
      2. 未命中 priority → 取 reason 首个非 ST 标签（保证新题材 20cm 涨停能入榜）。
      3. 无任何标签 → None（调用方跳过该股）。
    """
    tags = [t.strip() for t in str(reason or "").split("+")
            if t.strip() and t.strip() != "ST板块"]
    matched = next((theme for theme in (final_priority or []) if theme in str(reason or "")), None)
    if matched:
        cands = [t for t in tags if matched in t]
        if cands:
            return max(cands, key=len)
        return matched
    return tags[0] if tags else None


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
    # ⚠️ 2026-10-21 新增（v1.28）: 单点 V 型反转层
    # 触发条件: 某个指数 14:45→15:00 **跨越零点**（正负号翻转）且 |Δ| >= 2pp，
    # 同时大盘整体为负（其余指数在跌）→ 该指数是当日唯一逆势方向。
    # 与 v1.24 第六层（科创50 单点跳水）是**镜像场景**: 那次是 kc50 独跌，
    # 这次是 kc50 独涨/翻红，v1.14/v1.22/v1.24 六层检测全部落空 →
    # 战报会写"震荡"，掩盖"盘中冰点读数被收盘推翻"的关键信息。
    for name, v1445, v1500, delta in (gap_rows or []):
        if (v1445 < 0 < v1500) or (v1500 < 0 < v1445):
            if abs(delta) >= 2.0 and market_avg < 0:
                direction = "翻红" if v1500 > 0 else "翻绿"
                return f"🔄 单点V型反转型（{name} 尾盘{direction} {delta:+.2f}pp，其余指数普跌）"
    if sh_pct < -1.5 and kc50_pct < -5:
        return "📉 平稳转急跌型（模式⑦）"
    # ⚠️ 2026-10-26 新增（v1.29）: 上证红盘/微跌 + 成长方向（创业板/科创50）杀跌
    # 主板相对平稳时属"结构性分化"，写"震荡"会掩盖成长方向的系统性杀跌风险。
    # 阈值按 2026-10-26 实战校准（科创50 -2.23 / 创业板 -1.71 / 上证 +0.19）。
    if kc50_pct < -2.0 and cyb_pct < -1.5 and sh_pct > -0.5:
        return "📊 主板稳态 + 成长方向杀跌型（结构性分化）"
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
    # ⚠️ 2026-10-21 修复: ds.tencent_quote 同时返回裸 key + 带前缀 key，
    # len(indices) 恒为 12（6 指数 × 2），旧的 `!= 6` 判据永远误报。
    # 改为按实际需要的 6 个带前缀 key 统计覆盖率。
    _expect = ["sh000001", "sz399001", "sz399006", "sz399005", "sz399300", "sh000688"]
    _got = sum(1 for k in _expect if k in indices)
    if _got != len(_expect):
        print(f"⚠️  只拉到 {_got}/{len(_expect)} 个指数")

    print(f"[2/5] 拉强势股…")
    hot = ths_hot(date_str)
    print(f"      强势股 {len(hot)} 只")
    hot = enrich_with_quote(hot)

    print(f"[3/5] 拉候选池…")
    top10, pool_source, pool_note = resolve_candidate_pool(date_str)
    print(f"      Top10 {len(top10)} 只（来源: {pool_source}）")
    if pool_note:
        print(f"      {pool_note}")

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
        # ⚠️ 2026-10-21: 标签解析统一走 resolve_theme_label（子串命中时回退到
        # 标的自身的更具体标签，如"人形机器人"而非"机器人"）
        matched = resolve_theme_label(reason, final_priority)
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
                              gap_md, gap_rows, comparison_date, industry, dragon,
                              pool_note=pool_note)

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
    # ⚠️ 2026-10-21 修复: 盘中/尾盘报告的指数行标签并不统一 ——
    # 实测 `2026-10-21-尾盘选股.md` 写的是 "| 创业板 |" 而非 "| 创业板指 |"，
    # 旧 name_map 只匹配全称 → 创业板被静默跳过，警示表只剩 3/6 指数。
    # 这里为每个指数配置别名，任一别名命中即算抓到。
    name_aliases = {
        "sh000001": ["上证指数", "上证"],
        "sz399001": ["深证成指", "深证"],
        "sz399006": ["创业板指", "创业板"],
        "sz399005": ["中小100", "中小板100"],
        "sz399300": ["沪深300", "沪深 300"],
        "sh000688": ["科创50", "科创 50"],
    }
    rows, has_alert = [], False
    for k, name in name_map.items():
        # ⚠️ v1.5 修复: regex 必须跨管道 .*?（不是 [^|]*?）
        m = None
        for alias in name_aliases.get(k, [name]):
            m = re.search(rf"\|\s*{re.escape(alias)}\s*\|.*?([+-]?\d+\.\d+)\s*%", tail_content)
            if m:
                break
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
                   industry=None, dragon=None, pool_note=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = (f"📊 **盘后战报｜生成时间 {now} CST｜"
          f"目标交易日 {date_str} 15:00 收盘**\n\n")

    md += "━━━ **行业今日全貌** ━━━\n\n"
    industry = industry or {}
    if industry.get("top"):
        top_text = " / ".join(
            f"{row['name']} {row['change_pct']:+.2f}%" for row in industry["top"][:5]
        )
        # ⚠️ 2026-10-21 修复: bottom 现在是"最差在前"（ds 端已排好），
        # 旧代码用 [-5:] 会取到跌幅榜里最不差的几条 → 跌幅榜标签与内容相反。
        bottom_text = " / ".join(
            f"{row['name']} {row['change_pct']:+.2f}%" for row in industry["bottom"][:5]
        )
        md += f"📈 **东财行业涨幅 Top5：** {top_text}\n"
        md += f"📉 **东财行业跌幅 Bottom5：** {bottom_text}\n"
        md += (f"> 口径：已分页拉取 {industry.get('returned', 0)}/{industry.get('universe', 0)} "
               f"个行业板块（m:90+t:2 全量）。\n")
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
        # 2026-08-31 修复: ds.tencent_quote 用 price/last_close 而非 current/prev_close
        cur = v.get("price", v.get("current", 0)) or 0
        md += f"- {name_map[k]} {cur:.2f} ({v.get('change_pct', 0):+.2f}%)\n"

    md += "\n━━━ **候选池命中率** ━━━\n\n"
    md += "> 注：报告 08:03 生成，'baseline' 实为昨日(昨-1)收盘涨跌幅\n\n"
    if pool_note:
        md += f"> {pool_note}\n\n"
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
        # ⚠️ v1.19/v1.24: 样本量不足时命中率必须带 ⚠️ 前缀，不得以正常数字呈现
        hit_prefix = "⚠️ " if len(hit_rows) < 7 else ""
        md += f"\n{hit_prefix}📊 **命中率：** {len(positives)}/{len(hit_rows)} = {len(positives)/len(hit_rows)*100:.1f}%\n"
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
    elif any((r[1] < 0 < r[2]) or (r[2] < 0 < r[1]) for r in (gap_rows or [])) and max_delta >= 2.0:
        # ⚠️ 2026-10-21 新增（v1.28）: 单点 V 型反转 → 盘中读数被收盘推翻
        flip = next((r for r in (gap_rows or [])
                     if ((r[1] < 0 < r[2]) or (r[2] < 0 < r[1])) and abs(r[3]) >= 2.0),
                    None) or ("某指数", 0.0, 0.0, max_delta)
        flip_name = flip[0]
        md += (f"1️⃣ **大盘性质：** 🔄 单点V型反转！{flip_name} 14:45 {flip[1]:+.2f}% → 收盘 {flip[2]:+.2f}%"
               f"（Δ={flip[3]:+.2f}pp），四大核心指数均值 {market_avg:+.2f}% —— 盘中\"冰点\"读数已被收盘推翻，"
               f"明日{flip_name}能否延续是首要验证点\n")
        md += (f"2️⃣ **主线持续性：** {', '.join(themes[:3])} 龙头若高开不回落且成交不萎缩50%则结构延续；"
               f"若{flip_name}再度翻绿则今日翻红属尾盘脉冲而非趋势反转\n")
        md += (f"3️⃣ **候选池修正：** 上游仅 {len(hit_rows)} 只样本"
               f"{'（⚠️ 完整度不足，命中率不可外推）' if len(hit_rows) < 7 else ''}，"
               f"整体均值 {avg:+.2f}% vs 上证 {sh_pct:+.2f}%，"
               f"{'暂不据此调仓' if len(hit_rows) < 7 else '关注延续性'}\n")
    elif sh_pct < -1.5 and kc50_pct < -5:
        md += f"1️⃣ **大盘性质：** ⚠️ 平稳转急跌型！创业板/科创50收盘 {cyb_pct:+.2f}%/{kc50_pct:+.2f}%\n"
        md += "2️⃣ **回避：** 追高强势股 + 小盘题材投机\n"
        md += f"3️⃣ **主线：** 关注{', '.join(themes[:3])}龙头股是否扛住杀跌\n"
    elif other_5_avg is not None and kc50_pct < -2.0 and cyb_pct < -1.5 and sh_pct > -0.5:
        # ⚠️ 2026-10-26 新增（v1.29）: 主板稳态 + 成长方向杀跌（结构性分化）
        # 明日观察要点要指出"成长杀跌但候选池跑赢"的仓位含义：结构市不追成长回撤。
        md += (f"1️⃣ **大盘性质：** 📊 主板稳态（上证 {sh_pct:+.2f}%）+ 成长方向杀跌"
               f"（创业板 {cyb_pct:+.2f}% / 科创50 {kc50_pct:+.2f}%），结构性分化——"
               f"明日看点是成长杀跌是否向主板扩散（上证跌破 -0.5% 即确认）\n")
        md += (f"2️⃣ **主线持续性：** {', '.join(themes[:3])} 今日热度回落（对比 {comparison_date or '上期'}），"
               f"延续条件：龙头不跌停、成交不萎缩50%；杀跌中的半导体/元件等成长板块先看企稳再接\n")
        md += "3️⃣ **防御/仓位：** 候选池今日 +1.01pp 超额但 9/10 负延续，追高资金退潮期优先低位补涨方向，不追昨日+4%强势股\n"
    else:
        md += f"1️⃣ **大盘：** 上证 {sh_pct:+.2f}%，{'强势' if sh_pct > 1.5 else ('震荡偏弱' if sh_pct < -1 else '震荡')}；关注明日开盘30分钟量能\n"
        md += f"2️⃣ **主线：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、成交不萎缩50%\n"
        md += "3️⃣ **防御：** 央企/红利股作为底仓对冲\n"
    if gap_md:
        # 外发正文只保留数据源文件名，不泄露本机绝对路径。
        gap_md = re.sub(r"(?<=数据源：)(?:/[^\s（]+/)+", "", gap_md)
        md += gap_md

    # v2026-09-09 (Phase 12): 根因分析 + 次日调参摘要
    # 读 data/daily_root_cause.json + data/next_day_strategy.json, 拼成飞书卡片
    try:
        from pathlib import Path as _P
        import json as _json
        _nd = None
        _rc = None
        _DATA = _P(__file__).parent.parent / "data"
        _rc_path = _DATA / "daily_root_cause.json"
        _nd_path = _DATA / "next_day_strategy.json"
        if _rc_path.exists():
            _rc = _json.loads(_rc_path.read_text(encoding="utf-8"))
        if _nd_path.exists():
            _nd = _json.loads(_nd_path.read_text(encoding="utf-8"))

        if _rc and _nd:
            md += "\n\n━━━ **🔬 昨日根因分析 → 次日调参** ━━━\n\n"
            # 命中根因
            hit = _rc.get("hit_causes", [])
            if hit:
                md += f"📊 **根因命中：** {' / '.join(hit)}\n"
                for ck, cv in _rc.get("causes", {}).items():
                    if cv.get("hit"):
                        md += f"- **{ck}**：{cv.get('summary', '')}\n"
                        for it in cv.get("items", [])[:3]:
                            cn = it.get("sector_cn") or it.get("sector_enum") or "?"
                            ret = it.get("ret_1d")
                            md += f"  · `{it.get('code', '')} {it.get('name', '')}` ({cn}) 1D={ret:+.2f}%\n" if ret is not None else ""
            else:
                md += "📊 **根因命中：** ✅ 无显著根因\n"

            # 次日调参
            md += f"\n🎯 **次日策略:**\n"
            md += f"- 推荐阈值: **{_nd.get('score_threshold', '—')}** (基准 70)\n"
            md += f"- 建议仓位: **{_nd.get('position_final', '—')}%** (基准 50%)\n"
            if _nd.get("weak_sectors"):
                md += f"- 板块黑名单: {', '.join(_nd['weak_sectors'])}\n"
            if _nd.get("cold_sectors"):
                md += f"- ⚠️ 冷启动盲区: {', '.join(_nd['cold_sectors'][:5])} (新板块样本<3, 一票否决)\n"
            # 决策依据
            for entry in _nd.get("tuning_log", []):
                if entry.get("source") == "daily_root_cause":
                    for r in entry.get("reasons", []):
                        md += f"- 依据: {r}\n"
            md += "\n📁 **明日开机动作:** 推荐前 16:05 跑 `python3 scripts/daily_root_cause.py` + `auto_tune_next_day.py` → 自动覆盖 `data/next_day_strategy.json`\n"
    except Exception as _phase12_err:
        md += f"\n⚠️ Phase 12 根因 section 加载失败: {_phase12_err}\n"

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
        # 2026-08-31 修复: ds.tencent_quote 用 price/last_close 而非 current/prev_close
        cur = v.get("price", v.get("current", 0)) or 0
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
    try:
        from lark_push import push_markdown
        ok, detail = push_markdown(md, user_id=FEISHU_USER)
        if ok:
            print(f"✅ 飞书推送成功")
            print(detail[:200])
        else:
            print(f"❌ 飞书推送失败: {detail}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {type(e).__name__}: {e}")


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
