"""回归测试: rec_optimizer.load_feedback_data 必须按 (code, rec_date) 去重

修复 #12 (v2026-10-21 cron 反馈闭环审计): rec_feedback.csv 历史行被
record_recommendation 重复追加 (5-6 月最高 9.6x), 而 rec_optimizer 逐行读取
→ 同一条推荐被当成多个独立样本。

实测后果 (修复前):
  - records 1024 → 唯一 (code, rec_date) 仅 295 (虚增 247%)
  - overall_win_rate 32.42% (真实 38.31%, 被稀释 5.9pp)
  - sector_stats.count 灌水 (ai_app 11 → 真实 1), 导致 strategy_policy 的
    MIN_SECTOR_SAMPLES=10 门槛误判 + weak_sectors 错挂 8 个板块
"""
import os
import sys
import csv
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.rec_optimizer import _dedup_rows, load_feedback_data


FIELDS = ["date", "code", "name", "rec_date", "trend",
          "ret_1d", "ret_3d", "ret_5d", "ret_15d",
          "score", "sentiment_score", "macd_gold", "macd_confirmed", "sector"]


def _write(rows):
    fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                      newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in FIELDS})
    fh.close()
    return fh.name


def test_dedup_rows_collapses_same_code_and_rec_date():
    """同一 (code, rec_date) 的多行必须折叠成一行。"""
    rows = [
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "1.0"},
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "2.0"},
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "3.0"},
        {"code": "600001", "rec_date": "2026-05-22", "ret_1d": "-1.0"},
    ]
    out = _dedup_rows(rows)
    assert len(out) == 2, f"去重后应剩 2 行, 实际 {len(out)}"
    codes = sorted(r["code"] for r in out)
    assert codes == ["600000", "600001"], codes


def test_dedup_rows_keeps_most_complete_row():
    """完整度更高的行优先保留 (ret_* 填得最全)。"""
    rows = [
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "1.0"},
        {"code": "600000", "rec_date": "2026-05-22",
         "ret_1d": "1.0", "ret_3d": "2.0", "ret_5d": "3.0", "ret_15d": "4.0"},
    ]
    out = _dedup_rows(rows)
    assert len(out) == 1
    assert out[0].get("ret_15d") == "4.0", out[0]


def test_dedup_rows_keeps_later_row_on_tie():
    """完整度相同时保留文件靠后的一行 (最新一次追加)。"""
    rows = [
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "1.0"},
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "9.9"},
    ]
    out = _dedup_rows(rows)
    assert len(out) == 1
    assert out[0]["ret_1d"] == "9.9", out[0]


def test_dedup_rows_distinct_rec_dates_kept():
    """同一 code 不同 rec_date 是不同推荐, 必须都保留。"""
    rows = [
        {"code": "600000", "rec_date": "2026-05-22", "ret_1d": "1.0"},
        {"code": "600000", "rec_date": "2026-05-25", "ret_1d": "2.0"},
    ]
    out = _dedup_rows(rows)
    assert len(out) == 2, f"不同 rec_date 应保留 2 行, 实际 {len(out)}"


def test_load_feedback_data_dedups_real_csv():
    """端到端: 真实 rec_feedback.csv 里 (code, rec_date) 不得重复计数。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "rec_feedback.csv")
    if not os.path.exists(path):
        return
    recs = load_feedback_data(path)
    keys = [(r.code, r.date) for r in recs]
    assert len(keys) == len(set(keys)), (
        f"load_feedback_data 返回了重复的 (code, rec_date): "
        f"{len(keys)} 条里只有 {len(set(keys))} 个唯一键"
    )


def test_load_feedback_data_no_duplicate_sector_samples():
    """去重后 sector_stats.count 不得被同一推荐灌水。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "rec_feedback.csv")
    if not os.path.exists(path):
        return
    recs = load_feedback_data(path)
    if not recs:
        return
    # 任何板块的样本数都不能超过该板块唯一 (code,date) 组合数
    from collections import Counter
    per_sector = Counter(r.sector for r in recs if r.sector)
    uniq = Counter()
    seen = set()
    for r in recs:
        if not r.sector:
            continue
        k = (r.code, r.date, r.sector)
        if k in seen:
            continue
        seen.add(k)
        uniq[r.sector] += 1
    for sector, n in per_sector.items():
        assert n == uniq[sector], f"板块 {sector} 样本数 {n} != 唯一组合 {uniq[sector]}"


def test_unsettled_record_not_counted_as_zero_loss():
    """ret_1d 为空的未结算记录不得当成 0% 亏损计入统计。

    🔴 2026-11-12 修正断言口径 (原断言过宽, 在 HEAD 上就已失败):
    原写法是「不得存在 actual_change == 0.0 的记录」, 用**代理指标**表达
    「空值不得被当成 0%」。但 11-11 的 falsy-zero 修复 (commit 5912833) 让
    **合法**的 ret_1d == 0.0 (T+1 恰好平盘, 真实市场状态) 第一次进入 CSV ——
    全表唯一一只就是 600418 江淮汽车 (2026-11-10 池, 昨收 20.03 → T+1 收盘
    20.03, 腾讯实时独立复核一致)。旧断言把这个**真实平盘**误判成「未结算被
    当成 0% 亏损」→ 11-11 起每次跑全量测试都 1 failed (与本次改动无关)。

    ⇒ 改为断言**真正的不变量**: 每一条 actual_change == 0.0 的记录,
      其源 CSV 行的 ret_1d 必须**非空且确为 0.0** (即真实平盘);
      若源行 ret_1d 为空 → 说明未结算被伪造成 0% 亏损 → 才是真缺陷。
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "rec_feedback.csv")
    if not os.path.exists(path):
        return
    recs = load_feedback_data(path)

    # 源表 ret_1d 原文: (code, date) → ret_1d 字符串
    with open(path, newline="", encoding="utf-8") as f:
        raw = {(r.get("code", ""), r.get("date", "")): (r.get("ret_1d") or "").strip()
               for r in csv.DictReader(f)}

    fabricated = []
    for r in recs:
        if r.actual_change != 0.0 or r.is_win:
            continue
        src = raw.get((r.code, r.date))
        # 源行缺失或 ret_1d 为空 → 未结算被伪造成 0% 亏损 (真缺陷)
        if src is None or src in ("", "--", "-"):
            fabricated.append((r.code, r.date, src))
    assert not fabricated, (
        f"仍有 {len(fabricated)} 条未结算记录被当成 0% 亏损: "
        f"{[(c, d) for c, d, _ in fabricated[:5]]}"
    )


def test_unsettled_record_does_not_blacklist_sector():
    """未结算记录不得让板块凭空多出一条'亏损'样本。

    回归场景 (2026-10-21): 造纸 n=3, 其中 000815 美利云 尚未结算,
    被算成 0% 亏损后 wr=0% → 错进 weak_sectors。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "rec_feedback.csv")
    if not os.path.exists(path):
        return
    recs = load_feedback_data(path)
    paper = [r for r in recs if r.sector == "造纸"]
    for r in paper:
        assert r.actual_change != 0.0 or r.is_win, (
            f"造纸板块出现未结算的零收益记录: {(r.code, r.date)}"
        )
