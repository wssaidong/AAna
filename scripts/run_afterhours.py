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


def _code_prefix(code):
    """6位代码 → 腾讯市场前缀（北交所 920xxx 走 bj，勿按 "9 开头 → sh"）。

    ⚠️ 2026-11-11 修复（v1.38）: 本文件原有 3 处内联前缀逻辑
    `'sh' if c.startswith('6') else 'sz'`，把北交所 920xxx 拼成 `sh920xxx`
    → 腾讯返回无行情 → 涨跌幅静默为 0 → 该股在同花顺强势股池里被当成
    "非涨停"过滤掉（2026-11-11 实测：920157 宇特光电 +29.99% 涨停，
    当日北交所涨幅第一，却因取不到价而从"新晋异动 Top5"候选池消失）。

    统一走 ds.get_prefix()（已修 920/43/83/87/88 → bj），避免三处逻辑漂移。
    """
    try:
        return ds.get_prefix(str(code).strip())
    except Exception:
        return "sz"


def enrich_with_quote(hot_list):
    if not hot_list:
        return hot_list
    codes = []
    for h in hot_list:
        c = h.get("code", "")
        if not c:
            continue
        codes.append(f"{_code_prefix(c)}{c}")
    q = tencent_quote(codes)
    for h in hot_list:
        c = h.get("code", "")
        if not c:
            continue
        prefix = _code_prefix(c)
        # 2026-08-31 修复: ds.tencent_quote 用 price/last_close (而非 current/prev_close)
        # 同时兼容两种命名: 优先 ds 标准字段, fallback 到旧字段
        q_entry = q.get(f"{prefix}{c}") or q.get(c) or {}
        if q_entry:
            h["change_pct"] = q_entry.get("change_pct", 0)
            h["current"] = q_entry.get("price", q_entry.get("current"))
            h["prev_close"] = q_entry.get("last_close", q_entry.get("prev_close"))
    return hot_list


#: 同花顺「名称派生伪题材」标签 —— 这些不是板块主线，是按**股票名称**归的类目。
#: 2026-11-09 实战: "“东方”"(7 次) / "“羊”字辈"(4 次) 分列题材热度榜 #2/#4，
#: 把真实主线（商业航天/人形机器人）挤到后面，且 "“东方”" 会通过
#: dynamic_top → final_priority 泄漏进新晋异动标签与"明日观察要点"的主线句。
#: 识别特征: 标签被**中文双引号包裹**（同花顺只对名称派生类目加引号）。
#: 已逐日核验 2026-11-02/03/04/05/06/09 六天，引号标签**全部**是名称派生伪题材：
#:   "“东方”"    → 东方创业/东方环宇/东方通信/大东方/东方嘉盛/日出东方/东方新能（名称含"东方"）
#:   "“羊”字辈"  → 红太阳/东方海洋/阳光照明/大西洋/鲁阳节能/安阳钢铁/光洋股份/盛洋科技
#:                  （名称含"羊/洋/阳"）
PSEUDO_THEME_QUOTE = "“"


def is_pseudo_theme(tag):
    """判断一个同花顺题材标签是否为「名称派生伪题材」。

    ⚠️ 2026-11-09 新增（v1.36）: 伪题材会被当真实主线展示**并泄漏进建议**，
    必须与 "ST板块" 一样在**展示层**过滤（不改 ths_hot 源数据）。

    与 "ST板块" 的区别: ST板块 是**投机类目**（退市/摘帽/扭亏），
    伪题材是**名称派生类目**（按股票名里的字归类），两者都不是板块主线。
    """
    return str(tag or "").strip().startswith(PSEUDO_THEME_QUOTE)


def theme_counter(hot_list):
    c = Counter()
    for item in hot_list:
        for r in str(item.get("reason") or "").split("+"):
            if r.strip():
                c[r.strip()] += 1
    return c


def filter_real_themes(counter, top_n=10):
    """从题材计数中滤掉伪类目，返回真实主线题材列表。

    ⚠️ 2026-11-09 新增（v1.36）: 同时过滤 "ST板块"（投机类目）与
    引号包裹的**名称派生伪题材**。两类都不是板块主线。
    """
    return [t for t, _ in counter.most_common()
            if t != "ST板块" and not is_pseudo_theme(t)][:top_n]


def _ths_industry_page(session, page, url_tmpl, headers, retries=4):
    """抓同花顺行业板块单页，带 WAF 重试。

    ⚠️ 2026-11-04 实战: 同花顺对无 v-cookie 的请求会**间歇性**返回 WAF 挡板页
    (实测 http 无 cookie 只有 4/6 次成功)。挡板页仍含 `<tbody>` 与一行占位
    `['1', '', '0.00', ...]`，**长度仅 ~1.8KB**。

    ⚠️ 更危险的坑: akshare 的 `stock_board_industry_summary_ths()` 用
    `pd.read_html` 解析，挡板页会被解析成"1 行空板块"而不报错 → 若恰好第 1 页
    被挡、第 2 页成功，函数会**静默返回第 2 页的部分数据**（实测 41 行、
    序号从 51 开始），当天涨幅第一的板块（半导体 +10.55%）直接丢失，
    "行业今日全貌"和"明日观察要点"的板块名全部失真。

    对策（本函数）：
      1. 带 v-cookie 请求（实测 6/6 稳定，挡板率 0）
      2. 逐页重试，挡板页（无 page_info / 无有效板块名）视为失败重试
      3. 校验完整性：总行数与 page_info 声明的分页规模一致才返回
    """
    import time

    for attempt in range(retries):
        try:
            r = session.get(url_tmpl.format(page=page), headers=headers, timeout=15)
            text = r.text
            # 挡板页判定：没有分页信息，或表格里没有真实板块名
            if 'class="page_info"' not in text:
                raise ValueError("WAF 挡板页（无 page_info）")
            if len(text) < 5000:
                raise ValueError(f"WAF 挡板页（内容过短 {len(text)}B）")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, features="lxml")
            rows = []
            for tr in soup.select("table tbody tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                name = tds[1].strip()
                if not name:          # 占位行（挡板页特征）
                    continue
                try:
                    pct = float(tds[2])
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "name": name,
                    "change_pct": pct,
                    "code": "",
                    "up_count": tds[6] if len(tds) > 6 else 0,
                    "down_count": tds[7] if len(tds) > 7 else 0,
                    "leader": tds[9] if len(tds) > 9 else "",
                    "leader_change": tds[11] if len(tds) > 11 else 0,
                })
            if not rows:
                raise ValueError("表格无有效板块行")
            import re as _re
            m = _re.search(r'class="page_info"[^>]*>\s*(\d+)\s*/\s*(\d+)', text)
            total_pages = int(m.group(2)) if m else page
            return rows, total_pages
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.6 * (attempt + 1))
    return [], 0


def _industry_ranking_ths(top_n=10):
    """同花顺行业板块 fallback — 东财 push2 全断时使用。

    ⚠️ 2026-10-26 实战: 东财 push2 **主域 + push2delay 双双 RemoteDisconnected**
    (已连续多日不可用), 行业全貌整段降级为"无数据" → 战报丢失最重要的
    "行业今日全貌"章节。同花顺行业接口返回 90 个行业板块的涨跌幅/净流入/涨跌家数。

    ⚠️ 2026-11-04 实战: 不再用 akshare 的 `stock_board_industry_summary_ths()`。
    该函数有两个叠加缺陷：
      (a) 首次请求常撞同花顺 WAF 挡板页 → `soup.find('span.page_info')` 返回
          None → AttributeError，整个 fallback 抛异常（实测 6 次里 4 次失败）
      (b) 更糟：它用 `pd.read_html` 解析，挡板页会被解析成"1 行空板块"而**不报错**；
          若第 1 页被挡、第 2 页成功，就**静默返回第 2 页的部分数据**
          （实测 41 行、序号从 51 开始），当天涨幅第一的板块（半导体 +10.55%）
          直接丢失 → "行业今日全貌"与"明日观察要点"里的板块名全部失真，
          且失真方式很隐蔽（不报错、有数据、只是不完整）。
    改为自带 WAF 重试 + 完整性校验的直接抓取（见 _ths_industry_page）。

    返回契约与东财一致: {top, bottom, total, fetched, universe, source}
      - top:    涨幅榜（降序）
      - bottom: 跌幅榜（升序，最差在前）
    """
    rows, err = [], ""
    try:
        import requests as _rq
        from py_mini_racer import MiniRacer
        from akshare.stock_feature.stock_board_industry_ths import _get_file_content_ths

        # 同花顺需要 JS 生成的 v cookie，无 cookie 会间歇性撞 WAF
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"),
        }
        try:
            _js = MiniRacer()
            _js.eval(_get_file_content_ths("ths.js"))
            headers["Cookie"] = f"v={_js.call('v')}"
        except Exception as e:
            err = f"(v-cookie 生成失败，退化为无 cookie 请求: {e})"

        url_tmpl = ("http://q.10jqka.com.cn/thshy/index/field/199112/order/desc/"
                    "page/{page}/ajax/1/")
        sess = _rq.Session()
        page, total_pages = 1, 0
        while page <= 10:
            page_rows, total_pages = _ths_industry_page(sess, page, url_tmpl, headers)
            if not page_rows:
                err = (err + "; " if err else "") + f"第 {page} 页抓取失败（WAF 挡板或超时）"
                break
            rows.extend(page_rows)
            if total_pages and page >= total_pages:
                break
            page += 1
        # 完整性校验：THS 行业一览表共 90 个板块（2 页 50+40）
        if rows and len(rows) < 80:
            err = (err + "; " if err else "") + \
                f"数据不完整（仅 {len(rows)}/90 个板块，疑似部分页被 WAF 拦截）"
    except Exception as e:
        return {"top": [], "bottom": [], "total": 0, "fetched": 0,
                "universe": 0, "source": "ths", "error": f"ths 行业接口失败: {e}"}

    if not rows:
        return {"top": [], "bottom": [], "total": 0, "fetched": 0,
                "universe": 0, "source": "ths",
                "error": f"ths 行业接口未取到有效数据: {err or '未知原因'}"}

    # 去重（同页可能重复），保留最后一次出现的涨跌幅
    dedup = {r["name"]: r for r in rows}
    rows = list(dedup.values())
    rows.sort(key=lambda x: -x["change_pct"])
    result = {
        "top": rows[:top_n],
        "bottom": list(reversed(rows[-top_n:])) if rows else [],
        "total": len(rows),
        "fetched": len(rows),
        "universe": 90,
        "source": "ths",
    }
    if err:
        result["error"] = err
    return result


def _industry_base_name(name):
    """去掉东财行业名末尾的层级后缀（Ⅰ/Ⅱ/Ⅲ/Ⅳ），得到板块"基名"。

    ⚠️ 2026-11-09 新增（v1.36）: 东财 m:90+t:2 的 496 个行业板块里，
    **同一板块会按申万层级重复出现**（如 焦炭Ⅱ 与 焦炭Ⅲ 涨跌幅完全相同）。
    全量实测 456 个基名 / 496 条记录 → 39 个基名存在层级重复（38 个 ×2 + 1 个 ×3）。
    """
    return re.sub(r"[ⅠⅡⅢⅣIV]+$", "", str(name or "")).strip()


def dedupe_industry_hierarchy(rows):
    """按基名去重行业板块（保留首次出现的层级）。

    ⚠️ 2026-11-09 实战（v1.36）: 涨幅 Top10 里 **焦炭Ⅲ +5.39%** 和
    **焦炭Ⅱ +5.39%** 是同一板块的两个层级，占掉 2 个席位；燃气Ⅲ/燃气Ⅱ 同理。
    战报会让人误以为"有两个板块领涨"，实际只是同一个板块被计了两次。

    去重后 Top10 变成真正 10 个不同板块（焦炭/卫浴电器/汽车综合服务/煤炭/燃气/
    动力煤/印制电路板/煤炭开采/稀土/视频媒体），跌幅榜同理。
    """
    seen = set()
    out = []
    for r in rows:
        base = _industry_base_name(r.get("name"))
        if base in seen:
            continue
        seen.add(base)
        out.append(r)
    return out


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

    ⚠️ 2026-11-09 新增（v1.36）: **层级去重**。东财 496 个板块里同一板块按
    申万层级重复出现（焦炭Ⅱ/焦炭Ⅲ 涨跌幅完全相同），Top10 会被同一个板块
    占掉多个席位。这里**多取 6 倍**行再去重切片，保证去重后仍能填满 top_n 条
    （去重最多把 3 条压成 1 条，6 倍冗余足够）。
    """
    # ⚠️ 去重前多取冗余行，否则同一板块的层级重复会让榜单条目不足 top_n。
    fetch_n = max(top_n * 6, 60)
    raw = ds.industry_comparison(top_n=fetch_n)  # ds 已同时给出 top/bottom 各 top_n 条
    if not isinstance(raw, dict):
        raw = {"top": [], "bottom": [], "total": 0, "error": "ds 返回非 dict"}
    top = dedupe_industry_hierarchy(raw.get("top", []) or [])
    bottom = dedupe_industry_hierarchy(raw.get("bottom", []) or [])
    source = raw.get("source", "scripts.data_sources.industry_comparison")
    error = raw.get("error", "")

    if not top:
        # 东财不可用 → 同花顺行业板块兜底
        ths = _industry_ranking_ths(top_n)
        if ths.get("top"):
            ths["error"] = error  # 保留东财失败原因用于展示
            return {
                "top": dedupe_industry_hierarchy(ths["top"]),
                "bottom": dedupe_industry_hierarchy(ths["bottom"]),
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

    ⚠️ 2026-11-02 实战（v1.33）: ds 层在拿不到数据时统一返回
    "无数据（非交易日或盘后未更新）" —— 但**今日是交易日**，真实原因是
    东财龙虎榜在**收盘后尚未发布**（通常盘后 17:00 前后才出当日榜）。
    战报若照抄这句话，用户会以为"今天不是交易日"，是**事实性错误**。
    故本层用同花顺强势股数据判定当日是否交易日，据实区分:
      - 非交易日 → "当日非交易日（无龙虎榜）"
      - 交易日但无榜 → "东财龙虎榜当日尚未发布（通常盘后 17:00 前后更新）"
    """
    raw = ds.daily_dragon_tiger(trade_date=date_str)
    if isinstance(raw, dict):
        # 2026-08-31 修复: ds 返回 key 是 "stocks", 转换为 "rows" 兼容下游
        if "rows" in raw:
            return raw
        if "stocks" in raw:
            stocks = raw.get("stocks", [])
            note = raw.get("note", "")
            if not stocks:
                note = _dragon_tiger_absence_note(date_str, note)
            return {
                "rows": stocks,
                "date": raw.get("date", date_str),
                "total_records": raw.get("total_records", 0),
                "source": "scripts.data_sources.daily_dragon_tiger",
                "note": note,
            }
    return {"rows": [], "note": "scripts.data_sources.daily_dragon_tiger 未返回 rows", "date": date_str}


def _dragon_tiger_absence_note(date_str, fallback_note=""):
    """龙虎榜缺失原因 —— 区分"非交易日"与"交易日但尚未发布"。"""
    try:
        is_trading = bool(ths_hot(date_str))
    except Exception:
        is_trading = None
    if is_trading is True:
        return "东财龙虎榜当日尚未发布（通常盘后 17:00 前后更新），已降级同花顺涨停股池"
    if is_trading is False:
        return "当日非交易日（无龙虎榜），已降级同花顺涨停股池"
    return fallback_note or "龙虎榜无数据，已降级同花顺涨停股池"


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
    rows, _, _, _ = resolve_candidate_pool(date_str)
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


# 深度分析报告里承载"候选池"的二级标题在不同日期叫法不同:
#   候选池 (10-27 / 10-30 / 11-01 / 11-02) | 深度排名 (10-29) | 逐股深度评分 (11-03)
# ⚠️ 2026-11-03 实战: 旧实现只认 "候选池" → 10-29 的"深度排名"、11-03 的
# "逐股深度评分" 整张池表被漏掉, 回捞恒为 0 行。
#   11-03 后果: 08:03 盘前版选股报告**从未被 git 提交**(深度分析 autopilot 的
#   commit 只带 深度分析.md/脚本/data, 不带当日选股报告), 而 09:37 开盘后
#   重跑又覆盖了工作区那份 → 盘前池四源(工作区/HEAD/git 历史/深度分析表)全落空,
#   盘后战报只能输出"三源均无候选池", 11-02 修的"虚假 100% 命中率"虽不复现,
#   但**真实 5 只盘前池被整个丢弃** → 盘后战报缺失盘前池评估。
#   修法: 标题关键词白名单 + 表头**结构语义**双重判定(见下)。
_POOL_SECTION_KEYWORDS = ("候选池", "深度排名", "逐股深度评分")


def _is_pool_table_header(cells):
    """池表表头判定: 必须同时含精确单元格"代码" + 基准日涨跌幅列。

    涨跌幅列以 "涨跌" 结尾 ("10-26 涨跌" / "11-02 涨跌"), 但**排除**
    "涨跌幅" / "实时涨跌%" —— 那是复核表/盘中表的列名, 不是基准日池表。
    """
    if "代码" not in cells:
        return False
    return any(c.endswith("涨跌") for c in cells)


def _parse_top10_from_deep_analysis(date_str):
    """从 {date}-深度分析.md 的候选池表格回捞候选池。

    ⚠️ 2026-10-26 实战: 选股报告的 Top10 section 会被**盘中重跑覆盖**成空
    (09:37 重跑用盘中实时情绪把"停止交易"状态写回同一个文件, 把 08:02 盘前
    版的 10 只候选池清空)。深度分析报告 08:34 生成时读的还是盘前版,
    其候选池表格保留了完整的 10 只 + 基准日涨跌幅 → 作为回捞来源。

    ⚠️ 2026-11-03 实战: 池表所在二级标题按日改名 (候选池/深度排名/逐股深度评分),
    旧实现只认"候选池" → 10-29 起漏解析。现改为:
      1) 二级标题命中 _POOL_SECTION_KEYWORDS 任一关键词;
      2) 本节内**按表头结构语义**定位池表 (精确列"代码" + 以"涨跌"结尾的
         基准日涨跌幅列) —— 不依赖固定表名, 也不误取"昨日复核"表的
         "10-29 收盘 / 实收" 列。
      3) 只解析该表的连续数据行 (表结束即停), 不跨表捞。

    表格形如:
      | 深度排名 | 股票 | 代码 | 10-23 涨跌 | ... |
      | 1 | 🥇**西麦食品** | **002956** | **+4.73%** | ... |
    """
    path = f"{REPORT_DIR}/{date_str}-深度分析.md"
    try:
        with open(path) as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return []
    lines = content.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("##") and any(k in line for k in _POOL_SECTION_KEYWORDS):
            start = i
            break
    if start is None:
        return []

    def _cells_of(line):
        return [c.strip().replace("**", "").replace("🥇", "").replace("🥈", "")
                .replace("🥉", "").replace("🆕", "") for c in line.split("|")]

    # 在本节内按结构语义定位池表表头
    header_idx = None
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if re.match(r"^#{1,3}\s+", line):
            break
        if not line.startswith("|"):
            continue
        if _is_pool_table_header(_cells_of(line)):
            header_idx = j
            break
    if header_idx is None:
        return []

    rows = []
    seen = set()
    for line in lines[header_idx + 1:]:
        if re.match(r"^#{1,3}\s+", line):
            break
        if not line.startswith("|"):
            break  # 表结束
        if set(line.replace("|", "").replace(":", "").strip()) <= {"-"}:
            continue  # 分隔行
        cells = _cells_of(line)
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


def detect_baseline_semantics(content, date_str=None):
    """判定选股报告 "涨跌幅" 列的口径。

    返回:
      "prev_close" — 昨收涨跌幅（盘前生成, 市场未开盘）→ **可作延续性 baseline**
      "intraday"   — 当日盘中/盘后实时涨跌幅 → 与当日收盘涨跌自指, **不可作 baseline**
      "unknown"    — 无生成时间且无盘前标记（保守按 prev_close 使用, 但需标注不确定）

    ⚠️ 2026-10-27 实战（v1.30）: 同一份 {date}-选股报告.md 可能存在**两个版本**——
    08:0x 盘前版（"涨跌幅"=昨收）与 09:3x 开盘后重跑版（"涨跌幅"=当日盘中实时）。
    后者若被当作 baseline, Δ 变成"当日盘中 vs 当日收盘"的自指比较,
    会得出完全虚假的命中率/超额结论（实战: 误用得 40% 命中 +1.98pp 超额,
    真实盘前池为 12.5% 命中 -0.74pp 超额）。
    """
    if not content:
        return "unknown"
    m = re.search(r"\*\*生成时间：\*\*\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})", content)
    if m:
        gen_date, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        if date_str and gen_date != date_str:
            return "unknown"
        # 09:30 开盘后重跑版 → 当日盘中口径
        if (hh, mm) >= (9, 30):
            return "intraday"
        return "prev_close"
    # 无生成时间: 盘前版带 "涨跌幅"=**昨收涨跌幅** 副标题
    if "昨收涨跌幅" in content:
        return "prev_close"
    return "unknown"


def _git_head_content(date_str):
    """取 git HEAD 的 {date}-选股报告.md 原文（取不到返回 ""）。"""
    import subprocess
    rel = f"reports/{date_str}-选股报告.md"
    repo = os.path.dirname(REPORT_DIR.rstrip("/"))
    try:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return ""
    if out.returncode != 0 or not out.stdout.strip():
        return ""
    return out.stdout


def _git_history_premarket_top10(date_str, max_commits=12):
    """从 git 历史回捞**盘前口径**版本的 Top10。

    返回 (rows, sha, found_prev_close):
      - rows: 解析出的候选池（可能为空 list）
      - sha: 命中的盘前口径版本 commit 短 hash（可能 None）
      - found_prev_close: 历史中**确实存在**盘前口径版本（哪怕其 Top10 表为空）

    ⚠️ 2026-10-27 实战（v1.30）: 工作区**和 git HEAD** 的 {date}-选股报告.md
    都可能已被开盘后重跑覆盖（09:38 开盘后版）, 盘前版只存在于 git 历史里。
    必须按提交顺序（新→旧）回捞第一个 prev_close 口径的版本。

    ⚠️ 2026-10-28 实战（v1.31）: 盘前口径版本**可能存在但 Top10 表为空** ——
    上游冰点守卫短路时**有意**输出 0 推荐（"情绪=冰点/仓位=10%/停止交易"）,
    属**设计行为**而非数据故障。旧实现把"空表"和"版本不存在"混为一谈
    (`if rows:` 才返回), 导致空池被静默跳过、最终回落到开盘后重跑版,
    战报给出虚假的"命中率 7/7 = 100%"。故新增 found_prev_close 标志。
    """
    import subprocess
    rel = f"reports/{date_str}-选股报告.md"
    repo = os.path.dirname(REPORT_DIR.rstrip("/"))
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", "--format=%H", "--", rel],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return [], None, False
    if out.returncode != 0 or not out.stdout.strip():
        return [], None, False
    found_sha = None
    for sha in out.stdout.split()[:max_commits]:
        try:
            show = subprocess.run(
                ["git", "-C", repo, "show", f"{sha}:{rel}"],
                capture_output=True, text=True, timeout=20,
            )
        except Exception:
            continue
        if show.returncode != 0 or not show.stdout.strip():
            continue
        content = show.stdout
        if detect_baseline_semantics(content, date_str) != "prev_close":
            continue
        if found_sha is None:
            found_sha = sha[:7]
        rows = parse_top10_content(content)
        if rows:
            return rows, sha[:7], True
    # 盘前口径版本存在但 Top10 为空 → found_prev_close=True, rows=[]
    return [], found_sha, found_sha is not None


def _git_head_top10_with_semantics(date_str):
    """git HEAD 版选股报告 Top10 + 口径判定。HEAD 缺失/解析空 → ([], "unknown")。"""
    import subprocess
    rel = f"reports/{date_str}-选股报告.md"
    repo = os.path.dirname(REPORT_DIR.rstrip("/"))
    try:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return [], "unknown"
    if out.returncode != 0 or not out.stdout.strip():
        return [], "unknown"
    content = out.stdout
    sem = detect_baseline_semantics(content, date_str)
    return parse_top10_content(content), sem


def resolve_candidate_pool(date_str):
    """解析候选池, 返回 (rows, source_label, note, semantics)。

    来源优先级（全部要求 **昨收口径**, 否则 baseline 与当日收盘自指）:
      1. 工作区 {date}-选股报告.md（若为盘前口径）
      2. git HEAD 的同名文件（若为盘前口径）
      3. git 历史中最新的盘前口径版本（HEAD 已被开盘后重跑覆盖时）
      4. {date}-深度分析.md 的"二、候选池"表格（列名即基准日涨跌）
    兜底: 任意版本 + 明确的口径警示

    ⚠️ 2026-10-26 实战: 工作区文件 09:39 被重跑覆盖成 Top10 空表
    (情绪 25 冰点/停止交易), 直接读会把**真实存在并已同步东财**的
    10 只候选池误判为"上游报告缺失"。三源回捞后命中率评估恢复正常。

    ⚠️ 2026-10-27 实战（v1.30）: 工作区被 09:38 **开盘后重跑**覆盖成
    另一只 5 只池, 且 "涨跌幅" 列已变成**当日盘中实时涨跌**。若直接当
    baseline 用, Δ = 当日收盘涨跌 − 当日 09:38 盘中涨跌 = 自指比较,
    会得出"40% 命中 / +1.98pp 超额"的虚假结论; 真实盘前池（8 只, 已同步
    东财 20261027ZZ）为 **12.5% 命中 / −0.74pp 超额**（vs 上证）。
    故新增 git 历史盘前版回捞 + 口径判定。

    ⚠️ 2026-10-28 实战（v1.31）: **盘前口径版本存在但 Top10 表为空** ——
    上游冰点守卫短路（情绪 20 冰点 / 仓位 10% / "停止交易"）时**有意**
    输出 0 推荐，属**设计行为**而非数据故障。
    旧实现（v1.30）把"盘前版空表"与"盘前版不存在"混为一谈:
      `rows, sha = _git_history_premarket_top10(...)` 只在 `if rows:` 时返回,
    空表版本被**静默跳过** → 继续回落到深度分析(空) → 最后落到工作区
    **开盘后重跑版**的 7 只池, 并标注成"盘前口径"。
    后果: 战报输出虚假的 **"命中率 7/7 = 100.0% / vs 上证超额 +4.29pp"**
    （实测该 7 只的实际命中率 5/7=71.4%, 且该池是开盘后选出来的,
    用盘中涨跌当 baseline 与收盘自指 → Δ 完全失效）。
    修复: 新增 found_prev_close 标志, 盘前版存在但空表时**明确返回空池**
    并标注"上游冰点守卫短路, 0 推荐属设计行为", 绝不回落到开盘后重跑版。
    """
    notes = []

    # 1) 工作区
    try:
        with open(f"{REPORT_DIR}/{date_str}-选股报告.md") as f:
            content = f.read()
        rows = parse_top10_content(content)
        sem = detect_baseline_semantics(content, date_str)
        if rows and sem == "prev_close":
            return rows, "选股报告(工作区·盘前口径)", "", sem
        if rows and sem == "intraday":
            notes.append(
                "⚠️ 工作区选股报告为**开盘后重跑版**（'涨跌幅'列为当日盘中实时口径，"
                "与当日收盘自指，不能作延续性 baseline），已回捞盘前口径候选池。"
            )
        elif rows and sem == "unknown":
            # ⚠️ v1.31: 口径未确认 ≠ 盘前口径。旧代码用 `sem != "intraday"` 判定，
            # 导致 unknown 口径（无生成时间、无盘前标记）被直接标注成"盘前口径"。
            # 未确认口径必须继续往下走，优先用 git HEAD/历史的**已确认**盘前版；
            # 只有全部源都不可用时才由末尾兜底返回，并标注"口径未确认"。
            notes.append(
                "⚠️ 工作区选股报告口径未确认（无生成时间/盘前标记），"
                "已继续回捞已确认的盘前口径版本。"
            )
    except FileNotFoundError:
        pass

    # 2) git HEAD（**必须是**盘前口径）
    #    ⚠️ v1.31: 旧代码只看 `if rows:` 就返回，但 HEAD 可能同样是开盘后重跑版
    #    （当日只提交过一次 intraday 版），返回后被标注成"git HEAD·盘前口径"
    #    而实际口径是 intraday —— 战报出现"来源=盘前口径，口径=intraday"的
    #    自相矛盾标注，且 baseline 与收盘自指。必须按口径过滤。
    rows, sem = _git_head_top10_with_semantics(date_str)
    if rows and sem == "prev_close":
        return rows, "选股报告(git HEAD·盘前口径)", "".join(notes), sem
    if rows and sem == "intraday":
        notes.append(
            "⚠️ git HEAD 版选股报告亦为**开盘后重跑版**（盘中实时口径），"
            "已继续回捞已确认的盘前口径版本。"
        )

    # 3) git 历史中最新盘前口径版本
    #    ⚠️ v1.31: rows 可能为空但 found_prev_close=True —— 盘前版**存在**，
    #    只是上游冰点守卫有意输出 0 推荐。此时**必须返回空池**，
    #    不得继续回落到开盘后重跑版（那会产出虚假命中率）。
    rows, sha, found_prev_close = _git_history_premarket_top10(date_str)
    if rows:
        notes.append(
            f"已回捞 git 历史盘前口径候选池（commit {sha}）"
        )
        return rows, f"选股报告(git 历史盘前版·{sha})", "".join(notes), "prev_close"
    if found_prev_close:
        notes.append(
            f"⚠️ 上游盘前版选股报告（git commit {sha}）**Top10 为空** —— "
            f"冰点守卫短路（情绪冰点/仓位 10%/停止交易）时**有意**输出 0 推荐，"
            f"属**设计行为**而非数据故障。今日盘前无候选池，"
            f"故**不做候选池命中率评估**（已跳过 09:37 开盘后重跑版，"
            f"其涨跌幅为盘中实时口径、与收盘自指，评估无效）"
        )
        return [], f"选股报告(git 历史盘前版·{sha}·Top10 空表)", "".join(notes), "prev_close"

    # 4) 深度分析报告候选池表（列名即基准日涨跌，天然昨收口径）
    rows = _parse_top10_from_deep_analysis(date_str)
    if rows:
        notes.append("已从深度分析报告的候选池表格回捞")
        return rows, "深度分析报告候选池表", "".join(notes), "prev_close"

    # 4.6) ⚠️ 2026-11-05 实战（v1.35 新增·第 5 真源）: 深度分析 JSON 机器快照
    #      （data/deep_analysis_YYYYMMDD.json, session=pre_market）。当日盘前版
    #      选股报告从未被 git 提交且工作区被 09:37 重跑覆盖、深度分析.md 的
    #      池表也被重跑清空/文件消失时，v1.31/v1.33 的四源全落空 → 兜底把
    #      重跑版当"盘前池"，输出虚假 100% 命中率（本会话实测 9/9=100%/
    #      +6.34pp，真实盘前池 9/10=90%/+1.21pp）。JSON 快照的 chg_pct 经
    #      腾讯 K 线逐股核对 == base_date 收盘涨跌幅（天然 prev_close 口径）。
    #      ⚠️ 顺序纪律: 排在 git 历史盘前版/深度分析.md 之后 —— 有文本报告
    #      优先用文本报告；JSON 是最后的"真值兜底"，仍优先于"口径未确认"的重跑版。
    try:
        json_rows, json_meta = _deep_analysis_json_top10(date_str)
    except Exception:
        json_rows, json_meta = [], None
    if json_rows and json_meta:
        notes.append(
            f"已从深度分析 JSON 快照回捞盘前候选池（session=pre_market, "
            f"base_date={json_meta['base_date']}，chg_pct=基准日收盘涨跌幅·昨收口径）"
        )
        return (json_rows, f"深度分析JSON快照盘前池(base {json_meta['base_date']})",
                "".join(notes), "prev_close")
    if json_meta and json_meta.get("empty"):
        notes.append(json_meta["evidence"])
        return [], f"深度分析JSON快照确认空池（{date_str}）", "".join(notes), "prev_close"

    # 4.5) ⚠️ 2026-11-02 实战（v1.33 新增）: 深度分析报告是**盘前候选池是否为空
    #      （冰点守卫·设计行为）**的单一真源。当日 08:03 盘前版选股报告**从未
    #      被 git 提交**（只有 09:38 开盘后重跑版入库），于是 v1.31 的三源回捞
    #      全部落空:
    #        1) 工作区 = 09:38 重跑版（intraday 口径）→ 口径不符，拒绝
    #        2) git HEAD = 同一份 09:38 重跑版（intraday 口径）→ 口径不符，拒绝
    #        3) git 历史 = 只有 intraday 那一次提交 → found_prev_close=False
    #        4) 深度分析候选池**表** = 空表（只有文字说明，无表格行）→ 解析 0 行
    #      结果回落到兜底分支，把 09:38 的 6 只当"盘前池"评估 → 战报输出
    #      **虚假的「命中率 6/6 = 100.0% / vs 上证超额 +4.08pp」**。
    #      而 08:34 提交的深度分析报告明确记载: 盘前 Top10 空表 + 冰点守卫短路，
    #      候选池 0 只（**设计行为，非故障**）。
    #      故新增第 4 个真源: 深度分析报告（盘前时段生成并入库）里的空池声明。
    #      ⚠️ 顺序纪律: 本检查**排在 git 历史盘前版(有行)之后** —— 真实
    #      prev_close 数据优先于空池声明，两者冲突时以有行的盘前版为准。
    empty_flag, empty_evidence = detect_empty_premarket_pool_from_deep_analysis(date_str)
    if empty_flag:
        notes.append(empty_evidence)
        return [], f"深度分析报告确认空池（{date_str}·冰点守卫）", "".join(notes), "prev_close"

    # 兜底: 工作区任意版本（口径异常时显式警示）
    try:
        with open(f"{REPORT_DIR}/{date_str}-选股报告.md") as f:
            content = f.read()
        rows = parse_top10_content(content)
        if rows:
            notes.append("⚠️ 未能回捞到盘前口径版本，'涨跌幅'列口径未确认")
            return rows, "选股报告(工作区·口径未确认)", "".join(notes), "unknown"
    except FileNotFoundError:
        pass

    return [], "无", "⚠️ 三源均无候选池（选股报告/深度分析报告）", "unknown"


def _deep_analysis_json_top10(date_str):
    """从 data/deep_analysis_YYYYMMDD.json 机器快照回捞盘前候选池（第 5 真源）。

    ⚠️ 2026-11-05 实战（v1.35 新增）: 深度分析 autopilot 每天把盘前池快照写进
    data/deep_analysis_YYYYMMDD.json（session="pre_market"、base_date=前一交易日、
    results[].chg_pct=基准日涨跌、results[].price=基准日收盘价）。当日盘前版
    选股报告**从未被 git 提交**且工作区被 09:37 开盘后重跑覆盖时
    （v1.33 的"从未入库"变体），四源回捞全落空 → 兜底把盘中重跑版当
    "盘前池"评估，输出虚假命中率（本会话实测：9/9=100% / +6.34pp 超额，
    而真实盘前池 9/10=90% / +1.21pp）。

    快照语义（已用腾讯 K 线逐股核对）:
      chg_pct == base_date 当日收盘涨跌幅（昨收口径），price == base_date 收盘价
      → 天然 prev_close baseline，与选股报告的"涨跌幅"列同语义。

    返回 (rows, meta):
      rows: [(code6, name, baseline_pct)]（可空）
      meta: None = 快照不可用/非盘前快照（调用方继续走后续来源）;
            dict = 快照存在且为盘前快照（rows 空时 meta["empty"]/meta["evidence"]
            描述空池原因，供空池判定使用）。

    ⚠️ 防自指纪律:
      - 只认 session == "pre_market" 的快照（盘后/尾盘变体文件名 deep_analysis_pm_*
        没有 session/base_date 字段，天然被排除）;
      - 只认 base_date < date_str 的快照（base_date 即当日 → baseline 与收盘自指）;
      - 历史 JSON（2026-10 及更早）没有 session/base_date 字段 → 排除，行为不变。
    """
    import json as _json
    data_dir = os.path.join(os.path.dirname(REPORT_DIR.rstrip("/")), "data")
    path = os.path.join(data_dir, f"deep_analysis_{date_str.replace('-', '')}.json")
    if not os.path.exists(path):
        return [], None
    try:
        with open(path) as f:
            jd = _json.load(f)
    except (OSError, ValueError):
        return [], None
    if not isinstance(jd, dict):
        return [], None
    if jd.get("session") != "pre_market":
        return [], None
    base_date = jd.get("base_date")
    if not base_date or str(base_date) >= date_str:
        # base_date 缺失或 ≥ 当日 → 口径无法确认，宁可不用
        return [], None
    results = jd.get("results") or []
    rows, seen = [], set()
    for r in results:
        code = str((r or {}).get("code") or "")
        if not re.match(r"^\d{6}$", code) or code in seen:
            continue
        pct = (r or {}).get("chg_pct")
        if pct is None:
            continue
        rows.append((code, (r or {}).get("name") or code, float(pct)))
        seen.add(code)
        if len(rows) >= 10:
            break
    meta = {"session": "pre_market", "base_date": str(base_date),
            "guard_ice": bool(jd.get("guard_ice")), "pool_size": jd.get("pool_size")}
    if rows:
        return rows, meta
    # 盘前快照存在但 results 为空 → 结合 guard_ice 给出空池证据
    reason = "冰点守卫短路（设计行为）" if meta["guard_ice"] else "上游无推荐"
    meta["empty"] = True
    meta["evidence"] = (
        f"⚠️ 深度分析 JSON 快照（session=pre_market, base_date={base_date}）确认 "
        f"{date_str} 盘前候选池为空（{reason}）—— 机器快照是盘前池真值，"
        f"绝不回落到开盘后重跑版"
    )
    return [], meta


def detect_empty_premarket_pool_from_deep_analysis(date_str):
    """深度分析报告是**盘前候选池是否为空（冰点守卫·设计行为）**的单一真源。

    返回 (is_empty: bool, evidence: str)。

    ⚠️ 2026-11-02 实战（v1.33 新增）: 当日 08:03 盘前版选股报告**从未被 git
    提交** —— 只有 09:38 开盘后重跑版入库（git log 只有 1 条 commit）。于是
    v1.31 的三源回捞全部落空:
      1) 工作区 = 09:38 重跑版（'涨跌幅'为当日盘中实时口径）→ 口径不符，拒绝
      2) git HEAD = 同一份 09:38 重跑版（盘中口径）→ 口径不符，拒绝
      3) git 历史 = 只有 intraday 那一次提交 → found_prev_close=False
      4) 深度分析"候选池"**表格** = 空表（只有文字说明，无表格行）→ 解析 0 行
    结果回落到兜底分支，把 09:38 的 6 只当"盘前池"评估 → 战报输出**虚假的**
    「命中率 6/6 = 100.0% / vs 上证超额 +4.08pp」。而 08:34 提交的深度分析
    报告明确记载: 盘前 Top10 空表 + 冰点守卫短路，候选池 0 只（**设计行为，
    非故障**）—— 这才是当日盘前池的真值。

    深度分析报告（08:3x 生成、盘前时段入库）记录了三项可判定信号：
      - "候选池 | **空 (0 只)**"                → 池确实为空
      - "采用报告 Top10 表 | ⛔ **0 只 (空表)**" → 盘前报告 Top10 是空表
      - 标题 "## 二、候选池: 0 只"             → 池为空的独立声明
    任一命中即判定为空池。

    ⚠️ 必须与"有池"的日子区分: 10-29 深度分析写的是
    "| 候选池 | **4 只** — 晶华新材 603683 / ...", 标题为
    "## 二、市场环境与守卫"（无"候选池: 0 只"）→ 不应被判为空。
    """
    path = f"{REPORT_DIR}/{date_str}-深度分析.md"
    try:
        with open(path) as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return False, ""

    # 信号 1: 表格行 "| 候选池 | **空 (0 只)** ..."（要求出现"空"或"0 只"）
    m_pool = re.search(r"\|\s*候选池\s*\|([^\n]*)", content)
    if not m_pool:
        return False, ""
    pool_cell = m_pool.group(1)
    if not re.search(r"空\s*\(0\s*只\)|0\s*只", pool_cell):
        # 有池的日子（如 10-29 "| 候选池 | **4 只** — ..."）→ 不是空池
        return False, ""

    # 信号 2: "采用报告 Top10 表 | ⛔ **0 只 (空表)**"
    m_top10 = re.search(r"\|\s*采用报告\s*Top10\s*表\s*\|([^\n]*)", content)
    top10_cell = m_top10.group(1) if m_top10 else ""
    empty_top10 = bool(re.search(r"0\s*只\s*\(空表\)|空表", top10_cell))

    # 信号 3: 二级标题 "## 二、候选池: 0 只 ..."（独立声明）
    m_head = re.search(r"^##+\s*二、候选池[:：]\s*0\s*只", content, re.M)
    empty_heading = bool(m_head)

    if not (empty_top10 or empty_heading):
        return False, ""

    # 证据文本: 说明这是"冰点守卫·设计行为"而非数据故障
    ice = bool(re.search(r"冰点守卫|is_ice_point", content))
    reason = "冰点守卫短路" if ice else "上游无推荐"
    evidence = (
        f"⚠️ 深度分析报告（盘前时段生成）确认 {date_str} 盘前候选池为空"
        f"（{reason}，**设计行为而非数据故障**）—— "
        f"「采用报告 Top10 表 = 0 只(空表)」+「候选池 = 空 (0 只)」双重声明。"
        f"当日 08:03 盘前版选股报告**未入库 git**（只有 09:38 开盘后重跑版入库，"
        f"其'涨跌幅'为当日盘中实时口径、与当日收盘自指，不能作延续性 baseline），"
        f"故**不做候选池命中率评估**（已跳过开盘后重跑版，避免虚假命中率）"
    )
    return True, evidence


def resolve_previous_pool(date_str, max_lookback=6):
    """回捞**上一个交易日**的盘前候选池（昨收口径），用于 T+1 闭环复核。

    ⚠️ 2026-10-28 新增（v1.31）: 当日盘前池为空（冰点守卫短路）时，
    "候选池命中率"整段退化成 N/A，战报就**失去了与盘前情报的闭环** ——
    而闭环正是本 skill 的核心目的（"与盘前情报联动形成闭环"）。
    此时唯一有意义的评估对象是**上一交易日的盘前池在今日收盘的表现**
    （T+1 真实收益），它直接回答"选股策略昨天选的东西今天表现如何"。

    返回 (rows, prev_date, source_label)：
      - rows: [(code, name, baseline_pct)]，baseline = 上一交易日报告里的昨收涨跌
      - prev_date: 该池的报告日期（找不到返回 None）
      - source_label: 来源说明

    ⚠️ 口径纪律: 只接受**已确认的昨收口径**版本（prev_close），
    否则 baseline 与收盘自指，T+1 收益完全失真。
    """
    cursor = datetime.strptime(date_str, "%Y-%m-%d")
    for offset in range(1, max_lookback + 1):
        day = (cursor - timedelta(days=offset)).strftime("%Y-%m-%d")
        # 先看该日是否真的是有行情的交易日（同花顺强势股非空）
        if not ths_hot(day):
            continue
        try:
            rows, source, _note, sem = resolve_candidate_pool(day)
        except Exception:
            continue
        if rows and sem == "prev_close":
            return rows, day, source
    return [], None, "无"


def evaluate_t1_pool(prev_rows, prev_date, indices):
    """用**今日收盘价**评估上一交易日盘前池的 T+1 表现。

    返回 dict: {rows, hits, n, avg, alpha_sh, avg_baseline, deltas, best, worst}
      - rows: [(code, name, baseline, today_pct, delta)]，delta = 今日涨跌 - baseline
      - alpha_sh: 池内均值 - 今日上证涨跌（真实超额，非自指）
    """
    if not prev_rows:
        return {}
    codes = [c for c, _, _ in prev_rows]
    q = tencent_quote([f"{_code_prefix(c)}{c}" for c in codes])
    rows = []
    for code, name, baseline in prev_rows:
        key = f"{_code_prefix(code)}{code}"
        entry = q.get(key) or q.get(code) or {}
        pct = entry.get("change_pct")
        if pct is None:
            continue
        rows.append((code, name, baseline, pct, pct - baseline))
    if not rows:
        return {}
    hits = [r for r in rows if r[3] > 0]
    avg = sum(r[3] for r in rows) / len(rows)
    sh_pct = indices.get("sh000001", {}).get("change_pct", 0)
    sorted_rows = sorted(rows, key=lambda x: x[4], reverse=True)
    return {
        "rows": rows,
        "hits": len(hits),
        "n": len(rows),
        "hit_rate": len(hits) / len(rows) * 100,
        "avg": avg,
        "alpha_sh": avg - sh_pct,
        "avg_baseline": sum(r[2] for r in rows) / len(rows),
        "neg_continuation": sum(1 for r in rows if r[4] < 0),
        "best": sorted_rows[0],
        "worst": sorted_rows[-1],
        "prev_date": prev_date,
    }


def pool_theme_overlap(pool_codes, themes):
    """测算候选池与当日主线题材的**概念级重合度**。

    ⚠️ 2026-11-10 新增（v1.37）: **不能用"候选池有没有进入同花顺涨停池"
    来推断题材是否错配**。

    同花顺 `getharden` 是**涨停股池**（当日强势/涨停标的），它只能证明
    "这只票今天涨停了"，**不能证明"这只票不属于某个题材"**。二者在
    大盘股普涨日会系统性背离：题材对、但票没涨停 → 涨停池重合度 0，
    而真实题材重合度可能很高。

    2026-11-10 实战: 候选池 8 只中 **6 只持有当日 #1 题材（人形机器人）
    与 #3 题材（商业航天）**（拓普集团=机器人执行器 / 中国卫星=小卫星总装），
    涨停池重合度却是 0/8 → 旧口径输出**事实错误**的归因
    "题材完全错配 —— 所选标的未参与当日主线"，而实际候选池整体跑赢大盘
    +3.05pp、7/8 命中。

    本函数改用东财 F10 核心概念（`ds.em_core_concepts`）做**概念级**匹配：
    候选池个股的概念板块 ∩ 当日 Top 题材 → 真实主线重合度。

    返回 (overlap_count, detail)：
      overlap_count: 命中当日主线的候选池只数
      detail:        [{code, name, themes:[...]}, ...]
    """
    if not pool_codes or not themes:
        return 0, []
    try:
        from data_sources import em_core_concepts as _ecc
    except Exception:
        return 0, []
    theme_list = [t for t in themes if t]
    detail = []
    for code in pool_codes:
        try:
            boards = _ecc(code) or []
        except Exception:
            boards = []
        if not boards:
            continue
        hits = [t for t in theme_list
                if any(t in b or b in t for b in boards)]
        if hits:
            detail.append({"code": code, "themes": hits})
    return len(detail), detail


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
            if t.strip() and t.strip() != "ST板块" and not is_pseudo_theme(t)]
    # ⚠️ 2026-11-09 修订（v1.36）: priority 列表本身也要过滤。
    # 旧实现用 `theme in str(reason)` 匹配**原始** reason 字符串，
    # 所以 priority 里若混进伪题材（dynamic_top 场景），仍会被选中。
    # 现在生产链路上 dynamic_top 已过滤，但让本函数**自洽**更安全。
    priority = [t for t in (final_priority or [])
                if t != "ST板块" and not is_pseudo_theme(t)]
    matched = next((theme for theme in priority if theme in str(reason or "")), None)
    if matched:
        cands = [t for t in tags if matched in t]
        if cands:
            return max(cands, key=len)
        return matched
    return tags[0] if tags else None


def _gap_source_warning(gap_source, date_str):
    """时点差数据源的可靠性提示 —— **按文件自身口径判定**，不按文件名一刀切。

    ⚠️ 2026-11-02 实战（v1.33 新增）: 旧代码只要数据源文件名是
    「尾盘选股.md」就无条件挂上"历史已连续确认失真"警示。但**失真不是文件名
    属性，而是文件内容属性**：
      - 失真案例（2026-06-16/23、07-02、07-13）: 该文件写的是**早盘/更早
        快照**的指数值（如 07-02 写上证 +1.18% 而 15:00 收盘实为 -2.03%），
        与目标交易日不匹配。
      - 2026-11-02: 该文件生成时间 14:46:55，指数值为 **14:46 真实盘中快照**
        （上证 +0.89% vs 收盘 +1.08%，Δ 仅 0.19pp），**完全可信**。
    继续无条件挂警示会**误伤可信数据源**，让用户对正确的时点差也产生怀疑。

    判定方法（读文件自身"生成时间"）:
      - 生成日期 == 目标交易日 且 生成时间在 14:00-15:00 之间 → 可信盘中快照，
        不加警示，只标注生成时刻。
      - 否则（生成日期不符 / 时间不在尾盘窗口 / 读不到生成时间）→ 保留原警示。
    """
    if not gap_source:
        return ""
    try:
        with open(gap_source) as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return "⚠️ 该源生成时间不可读，可能为陈旧快照；"
    m = re.search(r"\*\*生成时间：\*\*\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})", content)
    if not m:
        # 2026-06-16/23、07-02、07-13 这批失真文件**根本没有**生成时间字段
        return ("⚠️ 该源（尾盘选股.md）无生成时间字段，历史已连续确认失真，"
                "优先级应低于盘中报告，此处为兜底；")
    gen_date, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    if gen_date == date_str and (14, 0) <= (hh, mm) <= (15, 5):
        return f"（{gen_date} {hh:02d}:{mm:02d} 真实盘中快照）"
    return (f"⚠️ 该源生成时间为 {gen_date} {hh:02d}:{mm:02d}，"
            f"与目标交易日 {date_str} 的尾盘窗口不符，疑为陈旧快照；")


def _growth_top_industries(industry):
    """成长领涨日：涨幅榜前几名的真实行业名（数据驱动，不写死板块）。

    ⚠️ v1.31 旧代码在建议里写死"今日涨幅榜集中在半导体/自动化设备/电子化学品"
    —— 那是 2026-10-28 当天的真实板块名，写死在代码里会在别的日子**说错**。
    改为从当次 industry 数据里取涨幅榜前 3 名。
    """
    ind = industry or {}
    top = ind.get("top") or []
    if not top:
        return "今日涨幅榜领涨方向未知"
    names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in top[:3])
    return f"今日涨幅榜领涨方向为 {names}"


def _growth_dump_spread(cyb_pct, kc50_pct, sh_pct):
    """成长方向杀跌的**价差口径**判定（v1.34 新增，_growth_lead_spread 的镜像）。

    ⚠️ 2026-11-03 实战: v1.29 的"主板稳态 + 成长方向杀跌型"用**绝对阈值**
    `kc50<-2.0 and cyb<-1.5 and sh>-0.5` 判"主板稳态"。当日实测
    上证 **-0.82%** / 创业板 **-2.73%** / 科创50 **-3.81%**：
      - 上证 -0.82% 不 > -0.5% → 窄口径不命中
      - v1.27 第七层要求创业板也破 -3.0%（实测 -2.73%，差 0.27pp）→ 也不命中
    结果战报把一个"成长方向被单边绞杀"的日子标成"➡️ 震荡"，
    只字未提当日真正的结构（元件 -5.13% / 半导体 -5.09% / 电子化学品 -5.05%
    vs 保险 +2.67% / 机场航运 +2.01%）。

    价差口径（不看绝对值，看**相对强弱**）:
      1. 创业板与科创50 **同时**下跌（成长方向整体走弱）
      2. 科创50 相对上证 **落后** ≥ 1.5pp（主板明显抗跌 → 结构分化而非普跌）
      3. 上证 ≥ -1.5%（排除全市场杀跌 —— 那种情况交给模式⑤/模式⑦处理）

    与窄口径**取并集**：窄口径命中时仍按原逻辑走，两者合并覆盖面更大
    但不改变原有已验证场景的判定。
    """
    if cyb_pct >= 0 or kc50_pct >= 0:
        return False
    if sh_pct < -1.5:                      # 上证自身已重挫 → 全市场杀跌
        return False
    return (sh_pct - kc50_pct) >= 1.5     # 科创50 相对主板明显落后


def _defensive_strong_industries(industry):
    """红利防御板块今日**领涨**情况（数据驱动，不写死板块）。

    ⚠️ v1.33 已把"建议里写死的板块名"改成数据驱动（_growth_top_industries /
    _defensive_weak_industries）。但"成长方向杀跌日"的防御建议仍沿用
    v1.29 写死的"央企/红利股作为底仓对冲"，在红利防御**全线下跌**的日子
    会给出方向完全相反的建议（v1.31 已在领涨日踩过这个坑）。
    """
    ind = industry or {}
    top = ind.get("top") or []
    defense_kw = ("银行", "保险", "证券", "白酒", "贵金属", "煤炭", "石油", "石油开采",
                  "燃气", "电力", "公用事业", "高速公路", "机场", "航运", "港口",
                  # ⚠️ 2026-11-09 新增: 焦炭/动力煤 是煤炭的申万子板块，
                  # 同属资源+高股息防御资产。2026-11-09 焦炭Ⅲ +5.39% 是**全市场涨幅
                  # 第一**，若关键词漏掉它，防御建议会报"煤炭 +3.47%"而漏掉真正领涨的
                  # 焦炭板块（战报"行业全貌"里排 #1 的板块在建议里消失）。
                  "焦炭", "动力煤")
    hits = [r for r in top if any(k in str(r.get("name", "")) for k in defense_kw)]
    if hits:
        names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in hits[:3])
        return f"红利防御今日领涨（{names}）"
    if top:
        names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in top[:3])
        return f"涨幅榜以 {names} 为主，未见红利防御领涨"
    return "行业涨跌数据缺失，无法确认防御方向强弱"


def _growth_bottom_industries(industry):
    """成长方向今日**领跌**板块（数据驱动，不写死板块名）。

    v1.29 的建议写死"杀跌中的半导体/元件等成长板块"—— 那是 2026-10-26 当天的
    真实板块名，写死在代码里会在别的日子**说错**（2026-11-03 领跌的是
    元件/半导体/电子化学品/通信设备/自动化设备，恰好撞上，但不可依赖）。
    """
    ind = industry or {}
    bottom = ind.get("bottom") or []
    if bottom:
        names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in bottom[:3])
        return f"今日跌幅榜集中在 {names}"
    return "行业跌幅榜数据缺失，无法定位领跌方向"


def _growth_top_branch_names(industry, n=3):
    """成长领涨日：涨幅榜前列**真实板块名**（供"该跟哪条主线"给出可执行指引）。

    ⚠️ 2026-11-11 新增（v1.38）: 成长领涨分支的建议里写死了
    "（半导体/设备/材料）"—— 那是 2026-10-28 当天的真实板块名。写死即
    每日可能说错: 2026-11-11 实测当日涨幅榜前三是
    **其他数字媒体 +7.27% / 通信网络设备及器件 +7.19% / 通信线缆及配套 +6.04%**，
    与"半导体/设备/材料"毫无关系 —— 照抄会让用户去跟一条当日根本没涨的线。
    与 v1.33/v1.35/v1.36 记录的"写死板块名"同类，此处一并数据驱动。
    """
    ind = industry or {}
    top = ind.get("top") or []
    if not top:
        return "当日涨幅榜数据缺失，无法确认该跟哪条主线"
    names = " / ".join(str(r.get("name", "")) for r in top[:n])
    return names


def _defensive_weak_industries(industry):
    """成长领涨日：真实走弱的防御/红利板块（数据驱动，不写死板块）。

    ⚠️ v1.31 旧代码写死"白酒/证券/银行/保险等红利防御板块全线下跌"，
    同样是 10-28 当天的快照。改为从跌幅榜里筛出红利/防御相关关键词，
    命中则列出真实板块名与涨跌幅；没命中则如实说明"跌幅榜未见红利防御居前"。
    """
    ind = industry or {}
    bottom = ind.get("bottom") or []
    defense_kw = ("银行", "保险", "证券", "白酒", "贵金属", "煤炭", "石油", "石油开采",
                  "燃气", "电力", "公用事业", "高速公路", "机场", "航运", "港口",
                  # ⚠️ 2026-11-09 新增: 焦炭/动力煤 是煤炭的申万子板块，
                  # 同属资源+高股息防御资产。2026-11-09 焦炭Ⅲ +5.39% 是**全市场涨幅
                  # 第一**，若关键词漏掉它，防御建议会报"煤炭 +3.47%"而漏掉真正领涨的
                  # 焦炭板块（战报"行业全貌"里排 #1 的板块在建议里消失）。
                  "焦炭", "动力煤")
    hits = [r for r in bottom if any(k in str(r.get("name", "")) for k in defense_kw)]
    if hits:
        names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in hits[:4])
        return f"红利防御板块走弱（{names}）"
    if bottom:
        names = " / ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in bottom[:3])
        return f"跌幅榜以 {names} 为主，红利防御未见系统性杀跌但同样缺乏资金关注"
    return "红利防御板块今日涨跌幅数据缺失，无法确认防御方向强弱"


def _growth_lead_spread(cyb_pct, kc50_pct, sh_pct):
    """成长领涨的**价差口径**判定（v1.33 新增，v1.31 窄口径的补充）。

    ⚠️ 2026-11-02 实战: v1.31 的成长领涨检测用**绝对阈值**
    (`cyb>=2.0 and kc50>=1.5 and sh<1.0`)，当日实测
    上证 +1.08% / 创业板 +1.87% / 科创50 **+3.11%**：
      - 创业板 +1.87% < 2.0 → 窄口径不命中
      - 上证 +1.08% ≥ 1.0 → 窄口径不命中
    结果战报把一个"科创50 单点暴涨 3.11%、四大核心均值 +1.92%"的日子
    标成"➡️ 震荡"，并给出"央企/红利股作为底仓对冲"的建议 ——
    而当日贵金属 -1.45% / 银行 -0.83% / 煤炭 -0.35%，**红利防御全线下跌**，
    建议方向与当日实际资金流向完全相反（与 v1.31 记录的 10-28 同型失败）。

    价差口径（不看绝对值，看**相对强弱**）:
      1. 科创50 与创业板**同时**上涨（成长方向整体走强）
      2. 科创50 相对上证领先 ≥ 1.5pp（主板明显滞涨）
      3. 上证未单边下跌（上证 > 0%）—— 排除"全市场下跌中的相对抗跌"

    ⚠️ 2026-11-05 实战（v1.35 修订）: 防御条件 `sh_pct < 0.5` 是**错误的排除**——
    当日上证 **+0.10%**（平盘微红，绝非普跌）、创业板 +0.87%、科创50 +1.68%
    （领先 1.58pp ≥ 1.5pp），三大成长信号全部满足，仅因 0.10% < 0.5% 被
    误杀 → 战报再次标"震荡"并给"央企/红利对冲"建议；而当日行业榜
    **光伏辅材 +9.94% / 光伏加工设备 +9.58% / 视频媒体 +9.27% 领涨，
    动力煤 -2.20% / 煤炭开采 -1.97% / 油气开采 -1.92% / 电信运营商 -1.81%
    垫底**——红利防御全线垫底，"震荡→红利对冲"建议第三次买在当日最弱板块。
    "排除全市场下跌"的本意只需上证**未单边下跌**（> 0），不需要 ≥ +0.5%；
    上证 +0.1%~+0.5% 的"主板平盘滞涨"正是成长领涨型的典型形态。

    与窄口径并存：窄口径命中时（创业板 ≥2.0 且上证 <1.0）仍按原逻辑走，
    两者取或集，扩大召回但不改变原有已验证场景的判定。
    """
    if cyb_pct <= 0 or kc50_pct <= 0:
        return False
    if sh_pct <= 0:                       # 上证单边下跌 → 相对抗跌不叫"领涨"
        return False
    return (kc50_pct - sh_pct) >= 1.5     # 科创50 相对主板明显领先


def classify_market_feature(market_avg, sh_pct, cyb_pct, kc50_pct, gap_rows,
                            other_5_avg=None, other_idx_pcts=None):
    """按方向区分尾盘急涨/急跌，并覆盖极端情绪及科创单点分化。

    ⚠️ 2026-10-29 新增（v1.32）: **v1.27 第七层**「主板稳态 + 成长方向集体杀跌型」
    此前只在 changelog 里写了检测条件（`kc50_pct < -3.0 and cy_pct < -3.0`），
    **代码从未实现** —— 2026-10-29 实战（创业板 -4.45% / 科创50 -4.27% 双双破 -3%，
    其余 4 指数全部未破 -3%）正好落在这个盲区里，只被判成"极端情绪日（模式⑤）"，
    丢掉了"主板未破 -3%、杀跌集中在成长方向"这个结构性信息。
    按 v1.19「双重满足须双层嵌套」原则，与模式⑤ 同时命中时输出双层标签。

    `other_idx_pcts`: 非成长指数的涨跌幅列表（上证/深证/中小100/沪深300）。
    用于校验"主板稳态"语义 —— 只有其余指数都未破 -3% 才算主板稳态，
    否则是全市场普跌（此时不该叫"主板稳态"）。
    """
    deltas = [row[3] for row in gap_rows]
    max_delta = max(deltas, default=0.0)
    min_delta = min(deltas, default=0.0)
    # v1.27 第七层: 成长双指数集体破 -3%，而主板指数未破 -3%
    growth_collective_dump = (
        kc50_pct < -3.0 and cyb_pct < -3.0
        and (other_idx_pcts is None or all(p >= -3.0 for p in other_idx_pcts))
    )
    if market_avg < -3.0 and min_delta <= -3.5:
        base = "💥 极端情绪日（模式⑤）+ 假突破后尾盘跳水（v1.22第四层）"
    elif market_avg < -3.0:
        base = "💥 极端情绪日（模式⑤）"
    elif max_delta >= 3.5:
        base = "📈 假平稳真急涨型（v1.22第五层）"
    elif min_delta <= -3.5:
        base = "📉 假突破后尾盘跳水型（v1.22第四层）"
    elif growth_collective_dump:
        # v1.27 第七层放在急涨/急跌之后、V型之前：它描述的是**结构**（杀跌集中在
        # 成长方向），不是**时点**（尾盘反转），两者正交。
        base = "📊 主板稳态 + 成长方向集体杀跌型（v1.27第七层）"
    else:
        # ⚠️ 2026-10-21 新增（v1.28）: 单点 V 型反转层
        # 触发条件: 某个指数 14:45→15:00 **跨越零点**（正负号翻转）且 |Δ| >= 2pp，
        # 同时大盘整体为负（其余指数在跌）→ 该指数是当日唯一逆势方向。
        # 与 v1.24 第六层（科创50 单点跳水）是**镜像场景**: 那次是 kc50 独跌，
        # 这次是 kc50 独涨/翻红，v1.14/v1.22/v1.24 六层检测全部落空 →
        # 战报会写"震荡"，掩盖"盘中冰点读数被收盘推翻"的关键信息。
        v_flip = None
        for name, v1445, v1500, delta in (gap_rows or []):
            if (v1445 < 0 < v1500) or (v1500 < 0 < v1445):
                if abs(delta) >= 2.0 and market_avg < 0:
                    v_flip = (name, v1445, v1500, delta)
                    break
        if v_flip:
            direction = "翻红" if v_flip[2] > 0 else "翻绿"
            return (f"🔄 单点V型反转型（{v_flip[0]} 尾盘{direction} {v_flip[3]:+.2f}pp，"
                    f"其余指数普跌）")
        if sh_pct < -1.5 and kc50_pct < -5:
            base = "📉 平稳转急跌型（模式⑦）"
        elif ((kc50_pct < -2.0 and cyb_pct < -1.5 and sh_pct > -0.5)
              or _growth_dump_spread(cyb_pct, kc50_pct, sh_pct)):
            # ⚠️ 2026-11-03 新增（v1.34）: 价差口径并入窄口径（union）。
            # 窄口径用绝对阈值 sh>-0.5 判"主板稳态"，2026-11-03 实测上证 -0.82%
            # 差 0.32pp 落空 → 成长方向被单边绞杀的日子被标成"震荡"。
            # 价差口径看的是**相对强弱**（科创50 相对上证落后 ≥1.5pp），
            # 对"主板小跌 + 成长被杀"的真实结构性分化更稳健。
            base = "📊 主板稳态 + 成长方向杀跌型（结构性分化）"
        elif other_5_avg is not None and kc50_pct < -3.0 and abs(other_5_avg) < 0.5:
            base = "📊 主板稳态 + 科创50单点跳水型"
        elif (cyb_pct >= 2.0 and kc50_pct >= 1.5 and sh_pct < 1.0) or _growth_lead_spread(cyb_pct, kc50_pct, sh_pct):
            base = "📈 成长领涨型（主板滞涨，结构性走强）"
        elif sh_pct > 1.5:
            base = "📈 强势行情"
        elif sh_pct < -1.0:
            base = "📉 震荡偏弱"
        else:
            base = "➡️ 震荡"
    if growth_collective_dump and "成长方向集体杀跌" not in base:
        # 双层嵌套：模式⑤（外层大盘）+ 第七层（内层结构）
        base += " + 主板稳态·成长方向集体杀跌（v1.27第七层）"
    return base


def _alpha_zone(alpha):
    """Alpha 区间描述（数据驱动，v1.34 新增）。

    ⚠️ 旧代码在"模式①"分支硬编码"（中性区间）"字样，与它自己打印的
    Alpha 数值可能自相矛盾 —— 2026-11-03 实测 Alpha **-1.73pp** 被标成
    "中性区间"。措辞必须由数值决定。
    """
    if alpha > 0.5:
        return "正 Alpha"
    if alpha >= 0.0:
        return "中性区间"
    if alpha >= -1.0:
        return "小幅负 Alpha"
    return "显著负 Alpha"


def _theme_group_split(hit_rows, theme_overlap_detail):
    """按"概念级是否持有当日主线题材"把候选池切成两组，返回两组的收益对比。

    ⚠️ 2026-11-11 新增（v1.38）: 判断"题材错配"是不是**主因**，不能只看
    命中只数（theme_overlap_count）—— 必须看**题材命中组 vs 未命中组的收益差**。
    2026-11-11 实战: 候选池 5/10 命中、Alpha -0.55pp，旧代码直接归因
    "模式① 风格切换（题材错配）"；但概念级拆分显示 —— 持有当日主线题材的
    6 只均值 **+2.70%**，未持有的 4 只均值 **-4.28%**（差 **+6.97pp**），
    **题材选择其实是有效的**；真正拖累来自"昨日 +4% 追高"的延续性失败
    （8/10 负延续、Δ 均值 -4.47pp）。照旧输出"题材错配"等于把**有效的**
    选股能力说成失效 —— 与 v1.35 ④-a 文案自相矛盾属同一类缺陷
    （"说错话但不报错"）。

    返回 dict 或 None（无法拆分时）:
      n_hit / avg_hit: 命中当日主线的只数 / 均值
      n_miss / avg_miss: 未命中的只数 / 均值
      spread: avg_hit - avg_miss（正 = 题材选择有效）
    """
    if not hit_rows or not theme_overlap_detail:
        return None
    codes = {d.get("code") for d in theme_overlap_detail if d.get("code")}
    if not codes:
        return None
    hit_group = [r for r in hit_rows if r[0] in codes]
    miss_group = [r for r in hit_rows if r[0] not in codes]
    if not hit_group or not miss_group:
        return None
    avg_hit = sum(r[3] for r in hit_group) / len(hit_group)
    avg_miss = sum(r[3] for r in miss_group) / len(miss_group)
    return {
        "n_hit": len(hit_group), "avg_hit": avg_hit,
        "n_miss": len(miss_group), "avg_miss": avg_miss,
        "spread": avg_hit - avg_miss,
    }


def classify_pool_failure_mode(hit_rows, avg, positives, negatives, avg_pos, avg_neg,
                               sh_pct, market_avg, market_feature="",
                               tail_dive=False, in_hot_count=0, hot_count=0,
                               theme_overlap_count=0, theme_overlap_detail=None):
    """候选池失败模式判定 —— 八态速查表 + ⑩ 系列（v1.32 新增）。

    返回 (mode_key, label, attribution_text) 或 (None, None, None)。

    ⚠️ 2026-11-10 新增参数（v1.37）:
      theme_overlap_count: 候选池中**概念级**持有当日 Top 题材的只数
        （东财 F10 概念 ∩ 当日主线题材）。⚠️ 这与 `in_hot_count`（进入同花顺
        **涨停池**的只数）是**两个不同口径** —— 旧代码用 in_hot_count==0 断言
        "题材完全错配"，在"题材对但票没涨停"的日子会输出**事实错误**的归因。
        详见函数体内 v1.37 注释。
      theme_overlap_detail: [{code, themes:[...]}, ...]，用于列出命中详情。

    判定依据（references/candidate-pool-failure-modes.md 八态速查表 +
    ⑩-a..⑩-g 子类）：

      命中率 ≤ 20%  → 均值 < -3% ? (baseline > +4% → ② 追高杀跌 / < +2% → ⑤ 系统性崩盘)
      命中率 20-40% → 均值 -2%~-3% + baseline +5~+7% → ⑦
                    → 均值 -1%~-2% + baseline +4~+5% + 正负差距 ≥10pp → ⑧
                    → 均值 < -3% + baseline > +4% → ⑩-h（v1.32 新增）
      命中率 40-60% → Alpha ≈ 0 → ①/⑥ ; Alpha 显著负 → ⑥
      命中率 ≥ 60%  → Alpha > 0.5pp → ④-a ; 0~0.5pp → ④-b

    ⚠️ 2026-10-29 实战新增 **模式 ⑩-h**：「极端情绪日 + 昨日+5%追高 +
    全天单边杀跌（无尾盘跳水）」。原八态速查表的 20-40% 命中率分支只覆盖
    均值 -2%~-3%（模式⑦）与 -1%~-2%（模式⑧），**没有覆盖均值破 -3% 的情形**；
    而 ⑩-f/⑩-g 两条新模式又都是 **0% 命中**，也覆盖不到 1/4 命中。
    2026-10-29 实战正好落在这个空档：命中率 25%（1/4）+ 均值 -4.03%（破 -3%）
    + baseline 全部 +4.62%~+4.99%（昨日+5% 追高）+ 大盘极端情绪日，
    且 **14:45→15:00 最大时点差仅 0.20pp**（杀跌全天发生、盘中已同步杀跌，
    与模式⑦/⑩-c/⑩-f 的"尾盘跳水"机制完全不同）。

    `in_hot_count`: 候选池中进入今日同花顺强势股/涨停池的只数（题材主线命中数）。
    `tail_dive`: 14:45→15:00 是否发生 ≥3.5pp 的尾盘跳水。
    """
    n = len(hit_rows)
    if not n:
        return None, None, None
    hit_rate = len(positives) / n
    alpha = avg - sh_pct
    baseline_avg = sum(r[2] for r in hit_rows) / n
    neg_cont = sum(1 for r in hit_rows if r[4] < 0)
    gap = abs(avg_pos) + abs(avg_neg)          # 正负差距
    extreme = market_avg < -3.0                # 大盘极端情绪日（模式⑤）
    small_sample = n < 5                       # v1.19: N<5 置信度低，须降级措辞
    miss_rate = (n - in_hot_count) / n if n else 1.0

    if hit_rate <= 0.20:
        if avg < -3.0:
            if baseline_avg > 4.0:
                mode, label = "②", "模式② 追高杀跌（系统性追高风险）"
                attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%（破 -3%），"
                        f"baseline 均值 {baseline_avg:+.2f}%（昨日强势股追高）—— "
                        f"在大盘杀跌中被系统性绞杀")
            elif extreme:
                # ⚠️ 2026-11-12 修订（v1.39）: 只有**大盘真·极端情绪日**（四大核心
                # 均值 < -3%）才配叫"系统性崩盘"；且 v1.37 之后"题材错配"必须
                # 由证据决定（见下方 theme_overlap 分支），不得写死在标签里。
                mode, label = "⑤", "模式⑤ 系统性崩盘（大盘系统性风险）"
                attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%，"
                        f"baseline 均值 {baseline_avg:+.2f}%（未达追高门槛）—— "
                        f"主因是大盘系统性风险（四大核心均值 {market_avg:+.2f}%），非追高")
            else:
                # ★ v1.39 新模式 ⑩-j —— "⑤" 的**非极端情绪日**变体（2026-11-12 实战:
                # 候选池 2/10 命中、均值 -4.44%、Alpha -3.77pp，但四大核心均值仅
                # -1.01%、科创50 还 +0.73% —— 旧代码落进 ⑤ 分支，标签写死
                # "系统性崩盘（大盘系统性风险 + 题材错配）"，与它自己打印的
                # "主因是大盘系统性风险" + "主线题材命中 8/10…非题材错配" 三处
                # 自相矛盾。大盘没崩 → 池子自己崩 → 主因必须按
                # _theme_group_split 的组间收益差数据分流，不得预判。
                _split = _theme_group_split(hit_rows, theme_overlap_detail)
                if _split and _split["spread"] > 0:
                    mode, label = "⑩-j", "模式⑩-j 候选池局部崩盘（大盘未崩，题材选择有效、非题材标的拖累）"
                    attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%（破 -3%）、"
                            f"Alpha {alpha:+.2f}pp（{_alpha_zone(alpha)}）；大盘**未崩**"
                            f"（四大核心均值 {market_avg:+.2f}%，未达极端情绪阈值 -3%）—— "
                            f"**非系统性崩盘**；持有当日主线题材的 {_split['n_hit']} 只均值 "
                            f"{_split['avg_hit']:+.2f}%，未命中的 {_split['n_miss']} 只均值 "
                            f"{_split['avg_miss']:+.2f}%（差 {_split['spread']:+.2f}pp）—— "
                            f"题材选择有效，拖累来自**未持有主线**的标的；"
                            f"baseline 均值 {baseline_avg:+.2f}%（未达追高门槛）、{neg_cont}/{n} 负延续")
                else:
                    _s = (f"持有主线题材的 {_split['n_hit']} 只均值 {_split['avg_hit']:+.2f}%，"
                          f"未命中的 {_split['n_miss']} 只均值 {_split['avg_miss']:+.2f}%"
                          f"（差 {_split['spread']:+.2f}pp）—— 拖累集中在**题材方向本身**"
                          if _split else "题材组拆分样本不足，无法定位拖累方向")
                    mode, label = "⑩-j", "模式⑩-j 候选池局部崩盘（大盘未崩，题材方向被集中抛售）"
                    attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%（破 -3%）、"
                            f"Alpha {alpha:+.2f}pp（{_alpha_zone(alpha)}）；大盘**未崩**"
                            f"（四大核心均值 {market_avg:+.2f}%，未达极端情绪阈值 -3%）—— "
                            f"**非系统性崩盘**，是候选池自身被抛售；{_s}；"
                            f"baseline 均值 {baseline_avg:+.2f}%（未达追高门槛）、{neg_cont}/{n} 负延续")
        else:
            # ⚠️ 2026-11-03 修订（v1.34）: 旧代码硬编码"（中性区间）"字样，
            # 与它自己打印的 Alpha 数值可能自相矛盾（2026-11-03 实测
            # Alpha -1.73pp 却被标成"中性区间"）。改为**数据驱动**。
            if baseline_avg >= 5.0 and avg <= -1.5 and not tail_dive:
                # ★ v1.34 新模式 ⑩-i —— ⑩-h 的"非极端情绪日"变体
                mode, label = "⑩-i", "模式⑩-i 昨日+6%追高 + 成长方向全天单边杀跌（均值未破 -3%）"
                attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%（未破 -3%），"
                        f"baseline 全部为昨日 +5% 以上强势股（均值 {baseline_avg:+.2f}%），"
                        f"{neg_cont}/{n} 负延续、Δ 均值 {avg - baseline_avg:+.2f}pp；"
                        f"杀跌全天发生、盘中已同步（14:45→15:00 无 ≥3.5pp 尾盘跳水）—— "
                        f"主因是**昨日强势股追高**在成长方向单边杀跌中被反向兑现")
            else:
                mode, label = "①", "模式① 风格切换 / 边缘归因"
                attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%、"
                        f"Alpha {alpha:+.2f}pp（{_alpha_zone(alpha)}）—— 主因偏题材错配")
    elif hit_rate <= 0.40:
        if avg < -3.0 and baseline_avg > 4.0:
            # ★ v1.32 新模式 ⑩-h
            mode, label = "⑩-h", "模式⑩-h 极端情绪日 + 昨日+5%追高 + 全天单边杀跌"
            mech = ("杀跌全天发生、盘中已同步（14:45→15:00 无 ≥3.5pp 尾盘跳水）"
                    if not tail_dive else "尾盘再度跳水")
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%（破 -3%），"
                    f"baseline 全部为昨日 +4% 以上强势股（均值 {baseline_avg:+.2f}%），"
                    f"{neg_cont}/{n} 负延续、Δ 均值 {avg - baseline_avg:+.2f}pp；"
                    f"{mech} —— 主因是**昨日强势股追高**在大盘极端情绪日被反向兑现")
        elif -3.0 < avg <= -2.0 and baseline_avg >= 5.0:
            mode, label = "⑦", "模式⑦ 昨日+6%追高 + 大盘平稳转急跌"
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%，"
                    f"baseline 均值 {baseline_avg:+.2f}%（昨日+5~+7% 强势股）—— "
                    f"追高 + 大盘急跌双层绞杀")
        elif -2.0 <= avg <= -1.0 and baseline_avg >= 4.0 and gap >= 10.0:
            mode, label = "⑧", "模式⑧ 昨日+5%追高 + 高Beta个股分化 + 题材错配"
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%、"
                    f"正负差距 {gap:.2f}pp（高Beta分化）、baseline 均值 {baseline_avg:+.2f}%"
                    f"（昨日+5% 强势股）—— 内部分化 + 追高延续性失败")
        else:
            mode, label = "①/⑥", "模式①/⑥ 风格切换或高Beta+题材错配混合"
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%、"
                    f"Alpha {alpha:+.2f}pp、正负差距 {gap:.2f}pp")
    elif hit_rate <= 0.60:
        if alpha <= -1.0:
            mode, label = "⑥", "模式⑥ 高Beta个股分化 + 题材错配混合"
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%、"
                    f"Alpha {alpha:+.2f}pp（显著负）、正负差距 {gap:.2f}pp —— "
                    f"高Beta分化 + 题材错配双层")
        else:
            # ⚠️ 2026-11-11 修订（v1.38）: "题材错配"必须**先验证据**再断言。
            # 旧代码在 40-60% 命中率 + 中性 Alpha 时无条件写"模式① 风格切换
            # （题材错配）"，与它自己打印的"主线题材命中 6/10"同屏打架。
            # 2026-11-11 实战: 概念级拆分显示题材命中组 +2.70% vs 未命中组
            # -4.28%（差 +6.97pp）→ **题材选择是有效的**，真正的拖累是
            # "昨日+4%追高"（baseline≥4.4% 组 -2.83% vs 低位组 +2.64%）。
            # 断言"题材错配"会把**有效的**选股能力说成失效 → 必须按数据分流。
            _split = _theme_group_split(hit_rows, theme_overlap_detail)
            _theme_effective = bool(_split and _split["spread"] > 0)
            if _split and _split["spread"] > 0:
                # 题材命中组跑赢未命中组 → 题材选择有效，不是错配主因。
                mode, label = "①*", "模式①* 追高延续性失败（题材选择有效，非题材错配）"
                attr = (f"候选池 {len(positives)}/{n} 命中、Alpha {alpha:+.2f}pp"
                        f"（{_alpha_zone(alpha)}）—— **题材选择有效**：命中当日主线题材的 "
                        f"{_split['n_hit']} 只均值 {_split['avg_hit']:+.2f}%，"
                        f"未命中的 {_split['n_miss']} 只均值 {_split['avg_miss']:+.2f}%"
                        f"（差 {_split['spread']:+.2f}pp），**主因不是题材错配**；"
                        f"实际拖累是昨日强势股追高（baseline 均值 {baseline_avg:+.2f}%，"
                        f"{neg_cont}/{n} 负延续、Δ 均值 {avg - baseline_avg:+.2f}pp）")
            else:
                mode, label = "①", "模式① 风格切换（题材错配）"
                attr = (f"候选池 {len(positives)}/{n} 命中、Alpha {alpha:+.2f}pp"
                        f"（{_alpha_zone(alpha)}）—— 主因是题材错配")
    else:
        if alpha > 0.5:
            mode, label = "④-a", "模式④-a 健康中等命中（跑赢大盘）"
            # ⚠️ 2026-11-05 修订（v1.35）: 旧文案写死"个别标的题材错配"，
            # 与末尾 in_hot_count==0 时追加的"**题材完全错配**"自相矛盾
            # （当日实战 9/10 命中 +1.21pp 却 0/10 进强势股池，两句话同屏打架）。
            # 题材错配度由下方 in_hot 分支按数据生成，此处不再预判。
            attr = (f"候选池 {len(positives)}/{n} 命中、整体均值 {avg:+.2f}%、"
                    f"Alpha {alpha:+.2f}pp —— 策略有效（超额为正）")
        elif alpha >= 0.0:
            mode, label = "④-b", "模式④-b 边缘中等命中（大盘托底但延续性差）"
            attr = (f"候选池 {len(positives)}/{n} 命中、Alpha {alpha:+.2f}pp（边缘），"
                    f"{neg_cont}/{n} 负延续 —— 表面命中实为大盘托底")
        else:
            mode, label = "③", "模式③ 高Beta个股分化（个股选择问题）"
            attr = (f"候选池 {len(positives)}/{n} 命中、Alpha {alpha:+.2f}pp、"
                    f"正负差距 {gap:.2f}pp —— 主因是个股选择而非系统性")

    # 题材错配度 —— ⚠️ 2026-11-10 修订（v1.37）
    # 旧口径: `in_hot_count == 0` → 直接断言"题材完全错配 —— 所选标的未参与
    # 当日主线"。**这是事实错误**: 同花顺 getharden 是**涨停股池**，
    # in_hot_count == 0 只说明"候选池今天没涨停"，**不能**说明"候选池不属于
    # 当日主线题材"。2026-11-10 实测: 候选池 8 只中 6 只持有当日 #1 题材
    # （人形机器人）与 #3 题材（商业航天），涨停池重合度却是 0/8 ——
    # 旧口径把"题材对但没涨停"误报成"题材完全错配"，且同日战报同时打印
    # "策略有效（超额为正）+3.05pp"，两句自相矛盾。
    # 新口径: 以**概念级主线重合度**（东财 F10 概念 ∩ 当日 Top 题材）为准，
    # 涨停池重合度只作为"当日涨停参与度"的补充口径单独陈述。
    if n:
        theme_overlap_detail = theme_overlap_detail or []
        _hit_themes = sorted({t for d in theme_overlap_detail for t in d.get("themes", [])})
        if theme_overlap_count > 0:
            attr += (f"；**主线题材命中 {theme_overlap_count}/{n}**"
                     f"（概念级口径：{'/'.join(_hit_themes)}）")
            if in_hot_count == 0:
                attr += (f"；但候选池 {in_hot_count}/{n} 进入今日涨停池"
                         f"（{hot_count} 只涨停）—— 属**题材对但未涨停**，"
                         f"非题材错配")
            else:
                attr += (f"；候选池 {in_hot_count}/{n} 同时进入今日涨停池"
                         f"（{hot_count} 只）")
        elif in_hot_count == 0:
            attr += ("；**题材完全错配** —— 候选池无一只持有当日 Top 题材，"
                     f"且无一进入今日涨停池（{hot_count} 只）")
        else:
            attr += (f"；候选池 {in_hot_count}/{n} 只进入今日强势股/涨停池"
                     f"（主线命中率 {in_hot_count / n * 100:.0f}%，概念级题材未命中）")

    if extreme:
        attr += f"。**大盘层**：模式⑤ 极端情绪日（四大核心均值 {market_avg:+.2f}%）"
    if small_sample:
        attr += (f"。⚠️ **样本仅 {n} 只（<5），本次命中率评估置信度低，"
                 f"结论按近似模式处理**")
    return mode, label, attr


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
    top10, pool_source, pool_note, pool_semantics = resolve_candidate_pool(date_str)
    print(f"      Top10 {len(top10)} 只（来源: {pool_source}；口径: {pool_semantics}）")
    if pool_note:
        print(f"      {pool_note}")
    if pool_semantics != "prev_close" and top10:
        pool_note = (pool_note + " " if pool_note else "") + (
            "⚠️ 候选池 '涨跌幅' 列口径未确认为昨收口径，"
            "延续性 Δ 仅供参考"
        )

    print(f"[4/5] 计算题材热度对比…")
    comparison_date, hot_yest = previous_nonempty_hot_day(date_str)
    if comparison_date:
        print(f"      环比基准: {comparison_date}（最近非空日期；不宣称交易日）")
    else:
        print("      ⚠️ 最近10日无非空题材数据，环比按0处理")
    ct = theme_counter(hot)
    cy = theme_counter(hot_yest)
    themes = filter_real_themes(ct, 10)

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
    qq = tencent_quote([f"{_code_prefix(c)}{c}" for c in top10_codes])
    hit_rows = []
    for code, name, baseline in top10:
        key = f"{_code_prefix(code)}{code}"
        actual = qq.get(key, {}).get("change_pct", 0)
        delta = actual - baseline
        hit_rows.append((code, name, baseline, actual, delta))

    # ⚠️ v1.31: 当日盘前池为空（冰点守卫短路）时，退化为 T+1 闭环复核 ——
    # 用**上一交易日**的盘前池在**今日收盘**的真实表现评估策略有效性。
    # 否则"候选池命中率"整段 N/A，战报失去与盘前情报的闭环。
    t1 = {}
    t1_mode = t1_label = t1_attr = None
    t1_theme_detail = []
    if not hit_rows:
        prev_rows, prev_date, prev_source = resolve_previous_pool(date_str)
        if prev_rows:
            t1 = evaluate_t1_pool(prev_rows, prev_date, indices)
            print(f"      T+1 闭环: {prev_date} 盘前池 {len(prev_rows)} 只 → 今日收盘 "
                  f"命中 {t1.get('hits', 0)}/{t1.get('n', 0)}，"
                  f"均值 {t1.get('avg', 0):+.2f}% vs 上证超额 {t1.get('alpha_sh', 0):+.2f}pp")
        else:
            print("      ⚠️ 无上一交易日盘前池，T+1 闭环复核不可用")

    positives = [r for r in hit_rows if r[3] > 0]
    negatives = [r for r in hit_rows if r[3] <= 0]
    avg = sum(r[3] for r in hit_rows) / max(len(hit_rows), 1)
    avg_pos = sum(r[3] for r in positives) / max(len(positives), 1) if positives else 0
    avg_neg = sum(r[3] for r in negatives) / max(len(negatives), 1) if negatives else 0

    # ⚠️ 2026-10-29（v1.32）候选池**偏差归因**输入: 候选池与今日主线（同花顺
    # 强势股/涨停池）的重合度。此前战报只有数字（命中率/均值/超额），没有
    # "为什么"——skill 交付物 #2 明确要求"命中率 vs 预期 + **偏差归因**"。
    hot_code_set = {h.get("code", "") for h in hot}
    in_hot_count = sum(1 for c in top10_codes if c in hot_code_set)
    # ⚠️ v1.37（2026-11-10）: **概念级主线重合度**。
    # in_hot_count（同花顺涨停池重合度）**不能**替代它 —— 涨停池只证明
    # "今天涨停了"，不证明"不属于某题材"。见 pool_theme_overlap() 文档。
    theme_overlap_count, theme_overlap_detail = pool_theme_overlap(top10_codes, themes)
    # 候选池行业暴露（偏差归因用，东财 f127；失败时静默降级为空 dict）
    pool_industries = {}
    try:
        from data_sources import industry_for_codes as _ifc
        pool_industries = _ifc(top10_codes) or {}
    except Exception:
        pool_industries = {}

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

    # ⚠️ v1.32 候选池偏差归因（需 gap_rows 判断是否有尾盘跳水）
    tail_dive = bool(gap_rows) and min(r[3] for r in gap_rows) <= -3.5
    core_pcts = [indices.get(k, {}).get("change_pct", 0)
                 for k in ("sh000001", "sz399001", "sz399006", "sh000688")]
    market_avg = sum(core_pcts) / len(core_pcts)
    pool_mode, pool_label, pool_attr = classify_pool_failure_mode(
        hit_rows, avg, positives, negatives, avg_pos, avg_neg,
        sh_pct, market_avg,
        tail_dive=tail_dive, in_hot_count=in_hot_count, hot_count=len(hot),
        theme_overlap_count=theme_overlap_count,
        theme_overlap_detail=theme_overlap_detail,
    )
    if pool_mode:
        print(f"      候选池归因: {pool_mode} {pool_label}")
        print(f"      涨停池重合: {in_hot_count}/{len(hit_rows)} 进入今日强势股池")
        print(f"      概念级题材重合: {theme_overlap_count}/{len(hit_rows)} 持有当日 Top 题材")

    # ⚠️ 2026-11-13 新增（v1.40）: T+1 池也要跑**偏差归因**。
    # skill 交付物 #2 是"命中率 vs 预期 + 偏差归因"；此前 T+1 段只给数字
    # （命中率/均值/超额），不给"为什么" —— 2026-11-13 实战正是纯数字段：
    # 1/10 命中、均值 -3.13%、10/10 负延续，用户看不到"题材方向本身被集中
    # 抛售"（命中主线组 -4.14% vs 未命中组 -1.61%）这一关键结构。
    # 归因输入与当日池同构：baseline=昨收涨跌、actual=今日收盘涨跌、Δ=延续性。
    # 题材重合度用**今日** Top 题材做概念级匹配（与当日池同一口径，v1.37），
    # 涨停池重合用今日强势股池。放在此处是因为需要 gap_rows（尾盘跳水判定）
    # 与 hot_code_set，两者都在上面才算出来。
    if t1.get("rows"):
        try:
            _t1_codes = [r[0] for r in t1["rows"]]
            _t1_ov_n, _t1_ov_detail = pool_theme_overlap(_t1_codes, themes)
            _t1_in_hot = sum(1 for c in _t1_codes if c in hot_code_set)
            _t1_rows = t1["rows"]
            _t1_pos = [r for r in _t1_rows if r[3] > 0]
            _t1_neg = [r for r in _t1_rows if r[3] <= 0]
            _t1_avg_pos = (sum(r[3] for r in _t1_pos) / len(_t1_pos)) if _t1_pos else 0
            _t1_avg_neg = (sum(r[3] for r in _t1_neg) / len(_t1_neg)) if _t1_neg else 0
            _t1_tail_dive = bool(gap_rows) and min(r[3] for r in gap_rows) <= -3.5
            t1_mode, t1_label, t1_attr = classify_pool_failure_mode(
                _t1_rows, t1.get("avg", 0), _t1_pos, _t1_neg,
                _t1_avg_pos, _t1_avg_neg, sh_pct, market_avg,
                tail_dive=_t1_tail_dive, in_hot_count=_t1_in_hot,
                hot_count=len(hot),
                theme_overlap_count=_t1_ov_n, theme_overlap_detail=_t1_ov_detail,
            )
            t1_theme_detail = _t1_ov_detail
            if t1_mode:
                print(f"      T+1 归因: {t1_mode} {t1_label}")
        except Exception as _t1_attr_err:
            print(f"      ⚠️ T+1 归因失败（不影响主流程）: {_t1_attr_err}")

    # 飞书版（短）
    feishu_md = format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                              positives, negatives, avg, avg_pos, avg_neg,
                              sh_pct, cyb_pct, kc50_pct, selected, len(hot),
                              gap_md, gap_rows, comparison_date, industry, dragon,
                              pool_note=pool_note, gap_source=gap_source, t1=t1,
                              pool_mode=pool_mode, pool_label=pool_label,
                              pool_attr=pool_attr, pool_industries=pool_industries,
                              theme_overlap_detail=theme_overlap_detail,
                              t1_mode=t1_mode, t1_label=t1_label, t1_attr=t1_attr,
                              t1_theme_detail=t1_theme_detail)

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


def phase12_section(date_str, rc, nd):
    """Phase 12 段：昨日根因分析 + 策略参数摘要（独立成函数便于单测）。

    ⚠️ 2026-11-13 新增（v1.40）: 三处"说错话但不报错"的修复都落在这里 ——
    ① **无样本 ≠ 无根因**: `total_recs == 0` 说明当日**没有推荐记录可供分析**
       （冰点守卫短路日常见），旧代码写"✅ 无显著根因"会被读成"分析过了、
       策略没问题"，与事实相反。2026-11-13 实战: 根因文件 date=2026-11-12 /
       total_recs=0 / hit_causes=[]，该日尾盘冰点守卫 0 推荐，本就无推荐可复盘。
    ② **策略段标题必须按 `date_for` 分流**: 战报 15:30 跑，而根因检测(16:05)
       + 次日调参(16:10) 在**收盘后**才跑 —— 此刻盘上的 next_day_strategy.json
       仍是**昨天**生成的、date_for=**今天**的那份（今日 08:03 盘前已用过它）。
       旧代码无条件写"次日策略"，把"今天已生效的参数"说成"明天的参数"。
    ③ 策略段额外标注 `date_for`，让读者能自己核对参数管哪一天。
    """
    md = "\n\n━━━ **🔬 昨日根因分析 → 次日调参** ━━━\n\n"

    # 命中根因
    hit = rc.get("hit_causes", [])
    _rc_n = rc.get("total_recs", 0)
    _rc_date = rc.get("date", "")
    if hit:
        md += f"📊 **根因命中：** {' / '.join(hit)}\n"
        for ck, cv in rc.get("causes", {}).items():
            if cv.get("hit"):
                md += f"- **{ck}**：{cv.get('summary', '')}\n"
                for it in cv.get("items", [])[:3]:
                    cn = it.get("sector_cn") or it.get("sector_enum") or "?"
                    ret = it.get("ret_1d")
                    md += (f"  · `{it.get('code', '')} {it.get('name', '')}` ({cn}) "
                           f"1D={ret:+.2f}%\n") if ret is not None else ""
    elif _rc_n == 0:
        md += (f"📊 **根因命中：** ⚠️ **无样本**（{_rc_date} 推荐记录 "
               f"{_rc_n} 条 —— 当日无推荐可复盘，非「分析后无显著根因」）\n")
    else:
        md += (f"📊 **根因命中：** ✅ 无显著根因"
               f"（{_rc_date} 已复盘 {_rc_n} 条推荐）\n")

    # 策略参数
    _nd_for = nd.get("date_for") or ""
    _today = None
    _nd_dt = None
    try:
        _today = datetime.strptime(date_str, "%Y-%m-%d")
        _nd_dt = datetime.strptime(_nd_for, "%Y-%m-%d") if _nd_for else None
    except Exception:
        _today = None
        _nd_dt = None
    if _nd_dt is None or _today is None:
        _scope_label = "策略参数"
        _scope_note = ""
    elif _nd_dt == _today:
        _scope_label = "今日已生效策略"
        _scope_note = (f"（date_for={_nd_for} = **今日**，今日盘前已按此参数执行；"
                       f"明日的参数将在今日 16:05 根因检测 + 16:10 自动调参后重算）")
    elif _nd_dt > _today:
        _scope_label = "次日策略"
        _scope_note = f"（date_for={_nd_for}）"
    else:
        _scope_label = "过期策略参数"
        _scope_note = (f"（date_for={_nd_for} < 报告日 {date_str}，"
                       f"已不是当前生效参数，请以最新 next_day_strategy.json 为准）")
    md += f"\n🎯 **{_scope_label}:**{_scope_note}\n"
    md += f"- 推荐阈值: **{nd.get('score_threshold', '—')}** (基准 70)\n"
    md += f"- 建议仓位: **{nd.get('position_final', '—')}%** (基准 50%)\n"
    if nd.get("weak_sectors"):
        md += f"- 板块黑名单: {', '.join(nd['weak_sectors'])}\n"
    if nd.get("cold_sectors"):
        md += (f"- ⚠️ 冷启动盲区: {', '.join(nd['cold_sectors'][:5])} "
               f"(新板块样本<3, 一票否决)\n")
    # 决策依据
    for entry in nd.get("tuning_log", []):
        if entry.get("source") == "daily_root_cause":
            for r in entry.get("reasons", []):
                md += f"- 依据: {r}\n"
    md += ("\n📁 **明日开机动作:** 推荐前 16:05 跑 "
           "`python3 scripts/daily_root_cause.py` + `auto_tune_next_day.py` "
           "→ 自动覆盖 `data/next_day_strategy.json`\n")
    return md


def format_feishu(date_str, indices, themes, ct, cy, hit_rows,
                   positives, negatives, avg, avg_pos, avg_neg,
                   sh_pct, cyb_pct, kc50_pct, selected, hot_count,
                   gap_md="", gap_rows=None, comparison_date=None,
                   industry=None, dragon=None, pool_note="",
                   gap_source=None, t1=None, pool_mode=None, pool_label=None,
                   pool_attr=None, pool_industries=None,
                   theme_overlap_detail=None,
                   t1_mode=None, t1_label=None, t1_attr=None,
                   t1_theme_detail=None):
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
        # ⚠️ 2026-10-27 修复（来源标注缺陷）: 东财双域断连时降级到同花顺行业板块，
        # 旧代码硬编码"东财行业"标签 → 数据来自 THS 却标"东财"，来源标注失实。
        ind_source = industry.get("source", "")
        if ind_source == "ths":
            ind_label = "同花顺行业"
        elif "push2" in ind_source:
            ind_label = "东财行业"
        else:
            ind_label = "行业"
        md += f"📈 **{ind_label}涨幅 Top5：** {top_text}\n"
        md += f"📉 **{ind_label}跌幅 Bottom5：** {bottom_text}\n"
        if ind_source == "ths":
            md += (f"> 口径：东财行业板块不可用（{industry.get('error', '原因未知')}），"
                   f"已降级同花顺行业板块（{industry.get('returned', 0)}/"
                   f"{industry.get('universe', 0)} 个）。\n")
        else:
            md += (f"> 口径：已分页拉取 {industry.get('returned', 0)}/{industry.get('universe', 0)} "
                   f"个行业板块（m:90+t:2 全量）。\n")
        if "push2delay" in ind_source:
            md += "> 数据源降级：东财 push2 主域断连，已切换官方 push2delay 域。\n\n"
        else:
            md += "\n"
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
        market_avg, sh_pct, cyb_pct, kc50_pct, gap_rows or [], other_5_avg,
        other_idx_pcts=[indices.get(k, {}).get("change_pct", 0)
                        for k in ("sh000001", "sz399001", "sz399005", "sz399300")],
    )
    md += f"\n⚠️ **市场特征：** {market_feature}\n"
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
    if hit_rows:
        md += "> 注：报告 08:03 生成，'baseline' 实为昨日(昨-1)收盘涨跌幅\n\n"
    if pool_note:
        md += f"> {pool_note}\n\n"
    md += "| 代码 | 名称 | baseline | 今日实际 | Δ | 评估 |\n"
    md += "|:----:|:----:|:------:|:------:|:----:|:----:|\n"
    if not hit_rows:
        # ⚠️ v1.31: 区分「上游冰点守卫主动 0 推荐（设计行为）」与「上游报告缺失（故障）」。
        # 两者对用户的含义完全不同：前者是策略主动空仓（不是系统坏了），
        # 后者才是链路故障。旧代码一律写"上游报告缺失"，会把"策略正确地空仓"
        # 误报成"数据丢了"，误导用户排查。
        if pool_note and any(k in pool_note for k in ("Top10 为空", "空表", "候选池为空", "空池")):
            md += "| ⚠️ | 上游冰点守卫短路（0 推荐·设计行为） | N/A | N/A | N/A | 无候选池评估 |\n"
        else:
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
        # ⚠️ v1.32 候选池偏差归因（skill 交付物 #2: 命中率 vs 预期 + 偏差归因）
        if pool_mode:
            md += f"\n🔍 **偏差归因：{pool_mode} {pool_label}**\n"
            if pool_attr:
                md += f"- {pool_attr}\n"
            # ⚠️ v1.37（2026-11-10）: 概念级主线命中明细 —— 让用户看到
            # "哪几只候选池持有当日主线题材"，而不是只看到一个合计数字。
            if theme_overlap_detail:
                _name_by_code = {r[0]: r[1] for r in hit_rows}
                ov_parts = " / ".join(
                    f"{d['code']}{_name_by_code.get(d['code'], '')}·{'+'.join(d['themes'])}"
                    for d in theme_overlap_detail[:8]
                )
                md += f"- 主线题材命中明细（概念级）：{ov_parts}\n"
            if pool_industries:
                # ⚠️ v1.37: 旧代码 `[:6]` 静默截断 —— 2026-11-10 实测 8 只候选池
                # 只显示 6 个（603131/600118 被丢），渲染层谎报行业暴露范围。
                # 数据层 8/8 全量可得 → 展示全量，不做静默截断。
                ind_summary = " / ".join(
                    f"{code}·{pool_industries[code]}" for code in
                    [r[0] for r in hit_rows if r[0] in pool_industries]
                )
                if ind_summary:
                    md += f"- 行业暴露：{ind_summary}\n"
    else:
        md += "\n⚠️ **候选池评估：** 上游选股报告 Top10 为空，本次无候选池命中率评估\n"
        md += f"- 大盘参考：上证 {sh_pct:+.2f}%；候选池超额：**N/A**\n"
        # ⚠️ v1.31: 当日池为空时用 T+1 闭环补上"策略到底行不行"的答案。
        # 没有这一段，战报只剩"没数据"，用户拿不到任何策略有效性信息。
        if t1 and t1.get("rows"):
            prev_date = t1.get("prev_date")
            md += (f"\n📈 **T+1 闭环复核（{prev_date} 盘前池 → {date_str} 收盘）：**\n\n")
            md += "> 口径：上一交易日盘前候选池（昨收口径 baseline）在**今日收盘**的真实表现，\n"
            md += f"> 非当日自指比较；今日上证 {sh_pct:+.2f}%\n\n"
            md += "| 代码 | 名称 | baseline(昨收) | 今日实际 | Δ | 评估 |\n"
            md += "|:----:|:----:|:------:|:------:|:----:|:----:|\n"
            for code, name, baseline, actual, delta in t1["rows"]:
                if delta >= 3:
                    ev = "✅ 强势延续"
                elif delta >= 0:
                    ev = "✅ 延续"
                elif delta >= -3:
                    ev = "⚠️ 高位震荡"
                else:
                    ev = "❌ 高位回吐"
                md += f"| {code} | {name} | {baseline:+.2f}% | {actual:+.2f}% | {delta:+.2f}% | {ev} |\n"
            hit_prefix = "⚠️ " if t1["n"] < 7 else ""
            md += (f"\n{hit_prefix}📊 **T+1 命中率：** {t1['hits']}/{t1['n']} = "
                   f"{t1['hit_rate']:.1f}%\n")
            md += (f"- 今日实际均值：{t1['avg']:+.2f}% | "
                   f"baseline均值：{t1['avg_baseline']:+.2f}% | "
                   f"{t1['neg_continuation']}/{t1['n']} 负延续\n")
            md += f"- vs 上证 {sh_pct:+.2f}% 超额：**{t1['alpha_sh']:+.2f}pp**\n"
            best, worst = t1.get("best"), t1.get("worst")
            if best and worst:
                # ⚠️ best/worst 按 **Δ**（延续性）排序，不是按绝对涨跌。
                # 旧写法只打印今日涨跌幅，会出现"最大回吐：+0.45%"这种自相矛盾
                # 的标签（实际是最差 Δ 但当日仍上涨）。两个数都要给。
                md += (f"- 最强延续：{best[1]}({best[0]}) 今日 {best[3]:+.2f}%"
                       f"（Δ {best[4]:+.2f}pp）；"
                       f"最弱延续：{worst[1]}({worst[0]}) 今日 {worst[3]:+.2f}%"
                       f"（Δ {worst[4]:+.2f}pp）\n")
            md += (f"> ⚠️ 样本为**上一交易日**盘前池（{prev_date}），"
                   f"用于回答「策略选股 T+1 是否有效」，**不代表今日新推荐**。\n")
            # ⚠️ 2026-11-13 新增（v1.40）: T+1 闭环复核段也要有**偏差归因**。
            # skill 交付物 #2 是"命中率 vs 预期 + 偏差归因"；此前 T+1 段只给
            # 数字（命中率/均值/超额），不给"为什么"—— 2026-11-13 实战正是
            # 纯数字段：1/10 命中、均值 -3.13%、10/10 负延续，用户看不到
            # "题材方向本身被集中抛售"（命中组 -4.14% vs 未命中组 -1.61%）
            # 这一关键结构，只能自己从表格里推。
            if t1_mode:
                md += (f"\n🔍 **偏差归因（{prev_date} 盘前池 → 今日收盘）："
                       f"{t1_mode} {t1_label}**\n")
                if t1_attr:
                    md += f"- {t1_attr}\n"
                if t1_theme_detail:
                    _t1_name_by_code = {r[0]: r[1] for r in t1["rows"]}
                    _t1_ov = " / ".join(
                        f"{d['code']}{_t1_name_by_code.get(d['code'], '')}·{'+'.join(d['themes'])}"
                        for d in t1_theme_detail[:8]
                    )
                    md += f"- 主线题材命中明细（概念级）：{_t1_ov}\n"

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
    elif ((other_5_avg is not None and kc50_pct < -2.0 and cyb_pct < -1.5 and sh_pct > -0.5)
              or _growth_dump_spread(cyb_pct, kc50_pct, sh_pct)):
        # ⚠️ 2026-10-26 新增（v1.29）: 主板稳态 + 成长方向杀跌（结构性分化）
        # 明日观察要点要指出"成长杀跌但候选池跑赢"的仓位含义：结构市不追成长回撤。
        # ⚠️ 2026-11-03 修订（v1.34）: ① 触发条件并入价差口径（见 _growth_dump_spread）；
        # ② 删除 v1.29 写死的"+1.01pp 超额 / 9/10 负延续"（2026-10-26 当天的快照），
        #    改为按**当日实测**候选池数据生成；③ 删除写死的"半导体/元件"板块名，
        #    改为数据驱动的跌幅榜；④ 防御建议按当日红利防御真实涨跌给出。
        pool_neg_cont = sum(1 for r in hit_rows if r[4] < 0) if hit_rows else 0
        if hit_rows:
            pool_line = (f"候选池 {len(positives)}/{len(hit_rows)} 命中、较上证 "
                         f"{avg - sh_pct:+.2f}pp、{pool_neg_cont}/{len(hit_rows)} 负延续")
        else:
            pool_line = "候选池无有效样本，不据此调仓"
        md += (f"1️⃣ **大盘性质：** 📊 主板稳态（上证 {sh_pct:+.2f}%）+ 成长方向杀跌"
               f"（创业板 {cyb_pct:+.2f}% / 科创50 {kc50_pct:+.2f}%），结构性分化——"
               f"明日看点是成长杀跌是否向主板扩散（上证跌破 -1.5% 即确认）\n")
        # ⚠️ 2026-11-03 修订（v1.34）: "今日热度回落"是**写死**的措辞，
        # 但当日 Top3 题材里 羊字辈 ↑2 / 固态电池 ↑2 / 三季报增长 ↓16 ——
        # 混合方向，说"回落"与数据不符。改为按当日**实际**环比方向描述。
        _top3 = themes[:3]
        _diffs = [(t, ct.get(t, 0) - cy.get(t, 0)) for t in _top3]
        _up = sum(1 for _, d in _diffs if d > 0)
        _down = sum(1 for _, d in _diffs if d < 0)
        if _up > _down:
            _heat_dir = "热度整体回升"
        elif _down > _up:
            _heat_dir = "热度整体回落"
        else:
            _heat_dir = "热度方向分化"
        md += (f"2️⃣ **主线持续性：** {', '.join(_top3)} {_heat_dir}"
               f"（对比 {comparison_date or '上期'}），"
               f"延续条件：龙头不跌停、成交不萎缩50%；{_growth_bottom_industries(industry)}，"
               f"先看企稳再接\n")
        md += (f"3️⃣ **防御/仓位：** {pool_line}；追高资金退潮期优先低位补涨方向，"
               f"不追昨日+4%强势股。{_defensive_strong_industries(industry)} —— "
               f"防御方向按当日真实涨跌选，不要凭固定印象买红利\n")
    elif (cyb_pct >= 2.0 and kc50_pct >= 1.5 and sh_pct < 1.0) or _growth_lead_spread(cyb_pct, kc50_pct, sh_pct):
        # ⚠️ 2026-10-28 新增（v1.31）: 成长领涨型（主板滞涨 + 成长集体走强）
        # 建议方向必须与"成长强、主板弱"的资金流向一致 —— 旧的"央企/红利对冲"
        # 在这种日子里恰好买在今日最弱的板块（当日白酒/证券/银行/保险全跌）。
        md += (f"1️⃣ **大盘性质：** 📈 成长领涨型（结构性走强）—— 创业板 {cyb_pct:+.2f}% / "
               f"科创50 {kc50_pct:+.2f}% 明显强于上证 {sh_pct:+.2f}%，"
               f"四大核心指数均值 {market_avg:+.2f}%；属成长主导的**结构性**上涨，"
               f"非普涨，明日看点是成长能否延续、主板能否补涨\n")
        md += (f"2️⃣ **主线持续性：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、"
               f"成交不萎缩50%；{_growth_top_industries(industry)}，"
               f"明日若成长高开回落而主板补涨，说明是单日资金切换而非趋势\n")
        md += (f"3️⃣ **防御方向：** ⚠️ 今日{_defensive_weak_industries(industry)}，"
               "「央企/红利对冲」在成长领涨日恰好买在弱势侧 —— 明日防御应转向"
               f"**跟随主线的高景气分支**（当日涨幅榜前列："
               f"{_growth_top_branch_names(industry)}），红利仅作低位观察而非对冲盘\n")
    else:
        md += f"1️⃣ **大盘：** 上证 {sh_pct:+.2f}%，{'强势' if sh_pct > 1.5 else ('震荡偏弱' if sh_pct < -1 else '震荡')}；关注明日开盘30分钟量能\n"
        md += f"2️⃣ **主线：** {', '.join(themes[:3])} — 延续条件：龙头不跌停、成交不萎缩50%\n"
        # ⚠️ 2026-11-09 修订（v1.36）: "央企/红利股作为底仓对冲"是**写死**的措辞。
        # v1.31/v1.33/v1.35 已连续三次记录"红利对冲"建议买在当日最弱板块
        # （写死的板块名/方向不随当日行情变）。本兜底分支是**最常走**的分支，
        # 同样必须数据驱动: 按当日涨幅榜里的红利防御真实表现给方向。
        md += (f"3️⃣ **防御方向：** {_defensive_strong_industries(industry)} —— "
               "防御方向按当日真实涨跌选，不要凭固定印象买红利\n")
    if gap_md:
        # 外发正文只保留数据源文件名，不泄露本机绝对路径。
        gap_md = re.sub(r"(?<=数据源：)(?:/[^\s（]+/)+", "", gap_md)
        md += gap_md
    elif gap_rows:
        # ⚠️ 2026-10-27 修复（时点差静默缺失缺陷）: 未触发也必须显式披露
        # （skill v1.13/v1.19 规范），否则"盘中报告缺失的静默降级"与
        # "稳态日"在战报里不可区分。
        src_name = (gap_source or "").rsplit("/", 1)[-1]
        max_abs = max((abs(r[3]) for r in gap_rows), default=0.0)
        src_warn = _gap_source_warning(gap_source, date_str)
        md += (f"\n> 时点差：数据源 {src_name}（{len(gap_rows)}/6 指数）{src_warn}"
               f"最大 |Δ| {max_abs:.2f}pp < 2.0pp 阈值未触发，盘中信号与收盘方向一致。\n")
    else:
        md += ("\n> 时点差：⚠️ 无 14:45 盘中报告且尾盘选股.md 不可用，"
               "无法对比盘中→收盘；以下全部按 15:00 收盘数据复盘。\n")

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
            md += phase12_section(date_str, _rc, _nd)
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
    """推送飞书。

    ⚠️ 2026-10-28 新增（v1.31）: **cron 自动投递场景下默认跳过手动推送**。
    本 cron 的最终回复会由 Hermes 自动投递到 origin chat
    (oc_936c9bc353220399455da6c1a919eb62) —— 再手动 lark-cli 推一遍会造成
    **重复消息**（2026-10-26 实际发生：手动 om_x100b62dbe4b... + cron
    om_x100b62dbe20... 两条内容相同的战报）。

    跳过条件（任一命中即跳过，不推送）：
      - 环境变量 HERMES_CRON_AUTO_DELIVERY=1（cron 环境由 Hermes 注入时推荐设置）
      - 环境变量 AANA_SKIP_FEISHU=1
    手动/交互场景（直接跑脚本、不在 cron 里）仍会正常推送。
    用 --force-feishu 可强制推送（即使在自动投递环境）。
    """
    if dry:
        print("=== DRY RUN: 飞书Markdown ===")
        print(md)
        return
    if os.environ.get("AANA_FORCE_FEISHU") == "1":
        pass
    elif (os.environ.get("HERMES_CRON_AUTO_DELIVERY") == "1"
          or os.environ.get("AANA_SKIP_FEISHU") == "1"):
        print("ℹ️ 跳过飞书手动推送（cron 自动投递环境，避免重复消息）")
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
    parser.add_argument("--force-feishu", action="store_true",
                        help="强制推送飞书（即使在 cron 自动投递环境）")
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

    if args.force_feishu:
        os.environ["AANA_FORCE_FEISHU"] = "1"
    if not args.no_feishu:
        send_feishu(feishu_md, dry=False)


if __name__ == "__main__":
    main()
