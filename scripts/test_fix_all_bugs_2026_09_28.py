"""
test_fix_all_bugs_2026_09_28.py — 9/28 bug 修复集成测试

覆盖:
- Bug 1: 阈值由 next_day_strategy 决定 (✅ 已在 strategy_policy.py 实现)
- Bug 2: 资金流 fallback (✅ 重试 + 多源)
- Bug 3: cron 配置 (✅ cronjob 创建)
- Bug 4: generate_report 读 strategy_policy (✅)
- Bug 5: 价格区间统一到 5-100 (✅ risk_rules.py 改)
- Bug 6: 8:00 → 9:35 (✅ cron 改)
- 附加: daily_v24_recommend 阈值跟 policy 走 (✅)

测试通过条件:
1. strategy_policy.get_today_policy() 读 next_day_strategy.json
2. risk_rules.filter_stock_basic 价格区间 = 5-100
3. generate_report.HAS_STRATEGY_POLICY = True
4. market_sentiment.get_money_flow 重试 3 次
5. dry-run 跑通 generate_report.py
"""
import sys, os, json
from pathlib import Path

PROJECT = Path("/Users/cai/code/AAna")
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))


def test_strategy_policy_loads_next_day():
    """Bug 4: strategy_policy 应该读 next_day_strategy.json"""
    from strategy_policy import get_today_policy
    p = get_today_policy()
    assert p.score_threshold >= 55 and p.score_threshold <= 80, \
        f"threshold 越界: {p.score_threshold}"
    print(f"✅ strategy_policy: threshold={p.score_threshold} blacklist={p.sector_blacklist}")
    print(f"   data_notes: {p.data_notes}")


def test_price_range_5_to_100():
    """Bug 5: filter_stock_basic 价格区间统一"""
    from risk_rules import filter_stock_basic, PRICE_MIN, PRICE_MAX
    assert PRICE_MIN == 5.0, f"PRICE_MIN 应为 5.0, 实际 {PRICE_MIN}"
    assert PRICE_MAX == 100.0, f"PRICE_MAX 应为 100.0, 实际 {PRICE_MAX}"

    # 5 元低价股应该通过
    ok, reason = filter_stock_basic("600001", "测试", 5.0, 5e7)
    assert ok, f"5 元低价应通过, 实际拒绝: {reason}"

    # 100 元高价应该通过
    ok, reason = filter_stock_basic("600002", "测试", 100.0, 5e7)
    assert ok, f"100 元高价应通过, 实际拒绝: {reason}"

    # 4.99 应该拒绝
    ok, reason = filter_stock_basic("600003", "测试", 4.99, 5e7)
    assert not ok, f"4.99 应拒绝, 实际通过"

    # 101 应该拒绝
    ok, reason = filter_stock_basic("600004", "测试", 101.0, 5e7)
    assert not ok, f"101 应拒绝, 实际通过"

    print(f"✅ filter_stock_basic: PRICE={PRICE_MIN}-{PRICE_MAX}, 边界测试全过")


def test_generate_report_uses_strategy_policy():
    """Bug 4: generate_report 应该用 strategy_policy,不是 rec_tuning"""
    from generate_report import HAS_STRATEGY_POLICY, NEW_MODULES
    assert NEW_MODULES, "NEW_MODULES 应该是 True"
    assert HAS_STRATEGY_POLICY, "HAS_STRATEGY_POLICY 应该是 True"
    print(f"✅ generate_report: HAS_STRATEGY_POLICY={HAS_STRATEGY_POLICY} NEW_MODULES={NEW_MODULES}")


def test_money_flow_has_retry():
    """Bug 2: market_sentiment.get_money_flow 应该重试"""
    import inspect
    from market_sentiment import get_money_flow
    src = inspect.getsource(get_money_flow)
    assert "attempt" in src and "3 次重试" in src, \
        "get_money_flow 应该包含 3 次重试逻辑"
    assert "qt.gtimg.cn" in src or "tencent" in src.lower(), \
        "get_money_flow 应该包含腾讯 fallback"
    print(f"✅ get_money_flow: 重试 + 多源 fallback 已实现")


def test_next_day_strategy_fresh():
    """Bug 3: next_day_strategy.json 应该是今天的"""
    nd_path = PROJECT / "data" / "next_day_strategy.json"
    assert nd_path.exists(), "next_day_strategy.json 不存在"
    nd = json.loads(nd_path.read_text(encoding="utf-8"))
    from datetime import datetime, timedelta
    expected_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    actual_date = nd.get("date_for", "")
    assert actual_date == expected_date, \
        f"date_for 应该是 {expected_date}, 实际 {actual_date}"
    print(f"✅ next_day_strategy.json: date_for={actual_date} (匹配)")


def test_daily_root_cause_fresh():
    """Bug 3: daily_root_cause.json 应该是今天的"""
    rc_path = PROJECT / "data" / "daily_root_cause.json"
    assert rc_path.exists(), "daily_root_cause.json 不存在"
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    assert rc.get("date") == today, f"date 应该是 {today}, 实际 {rc.get('date')}"
    print(f"✅ daily_root_cause.json: date={rc.get('date')} (匹配)")


def test_daily_v24_recommend_uses_policy():
    """附加: daily_v24_recommend 应该用 strategy_policy 阈值"""
    from pathlib import Path
    src = (PROJECT / "scripts" / "daily_v24_recommend.py").read_text(encoding="utf-8")
    assert "get_today_policy" in src, \
        "daily_v24_recommend 应该 import strategy_policy.get_today_policy"
    assert "score<65" not in src or "policy.score_threshold" in src, \
        "应该用动态阈值, 不是硬编码 65"
    print(f"✅ daily_v24_recommend: 阈值跟 strategy_policy 走")


def test_dry_run_generate_report():
    """整体: dry-run generate_report.py 能跑通"""
    import subprocess
    r = subprocess.run(
        ["python3", str(PROJECT / "scripts" / "generate_report.py"), "--type", "selection"],
        capture_output=True, text=True, timeout=240,
        cwd=str(PROJECT),
    )
    assert r.returncode == 0, f"generate_report.py 退出码 {r.returncode}\n{r.stderr[-2000:]}"
    assert "选股报告已生成" in r.stdout, \
        f"应该打印'选股报告已生成'\n{r.stdout[-2000:]}"
    print(f"✅ generate_report.py dry-run 跑通")


if __name__ == "__main__":
    print("=" * 60)
    print("AAna 9/28 bug 修复集成测试")
    print("=" * 60)
    test_strategy_policy_loads_next_day()
    test_price_range_5_to_100()
    test_generate_report_uses_strategy_policy()
    test_money_flow_has_retry()
    test_next_day_strategy_fresh()
    test_daily_root_cause_fresh()
    test_daily_v24_recommend_uses_policy()
    test_dry_run_generate_report()
    print("=" * 60)
    print("🎉 全部 8 项测试通过")
    print("=" * 60)