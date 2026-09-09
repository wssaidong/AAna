#!/usr/bin/env python3
"""
test_phase12_root_cause.py — Phase 12 根因 + 调参 单元测试

跑法: python3 test_phase12_root_cause.py
"""
import os
import sys
import json
import subprocess
from pathlib import Path

os.chdir("/Users/cai/Code/AAna")
sys.path.insert(0, "scripts")

passed = 0
failed = 0


def check(name, actual, expected):
    global passed, failed
    a = json.dumps(actual, ensure_ascii=False) if not isinstance(actual, str) else actual
    e = json.dumps(expected, ensure_ascii=False) if not isinstance(expected, str) else expected
    if a == e:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}: 期望 {e}, 实际 {a}")
        failed += 1


def approx(name, actual, expected, tol=0.5):
    global passed, failed
    if abs(actual - expected) <= tol:
        print(f"  ✅ {name}: {actual:.2f} ≈ {expected}")
        passed += 1
    else:
        print(f"  ❌ {name}: 期望 {expected}±{tol}, 实际 {actual}")
        failed += 1


# ============ 测试 1: daily_root_cause 5 大根因分类 ============
print("\n【测试 1】daily_root_cause 5 大根因分类")
from daily_root_cause import (
    detect_板块错配, detect_题材错配, detect_技术面虚高,
    detect_大盘错配, detect_冷启动盲区, suggest_tuning,
    make_sector_resolver, _sector_info,
)

# 模拟 resolver (避免外部 API 调用)
fake_resolver_db = {
    "600641": {"cn": "房地产开发", "enum": "realestate"},
    "605303": {"cn": "园林工程", "enum": ""},
    "605566": {"cn": "纺织化学用品", "enum": "chem"},
    "002491": {"cn": "通信传输设备", "enum": ""},
}
def fake_resolver(code):
    return fake_resolver_db.get(code, {"cn": "", "enum": ""})

# 场景 A: 板块错配命中
tuning_a = {
    "weak_sectors": ["chem", "elec"],
    "sector_stats": {"chem": {"count": 22, "win_rate": 0}, "elec": {"count": 11, "win_rate": 0}}
}
day_a = [
    {"code": "605566", "name": "福莱蒽特", "sector": "", "ret_1d": "-1.51", "score": "100", "macd_gold": "False"},
]
result_a = detect_板块错配(day_a, tuning_a, fake_resolver)
check("A. 板块错配 命中 (chem enum)", result_a["hit"], True)
check("A. 板块错配 1 只", len(result_a["items"]), 1)
if result_a["items"]:
    check("A. 板块错配 sector_cn", result_a["items"][0]["sector_cn"], "纺织化学用品")
    check("A. 板块错配 sector_enum", result_a["items"][0]["sector_enum"], "chem")

# 场景 B: 题材错配命中
tuning_b = {
    "weak_sectors": [],
    "sector_stats": {"chem": {"count": 22, "win_rate": 0}}  # n=22 >= 5
}
day_b = [
    {"code": "605566", "name": "福莱蒽特", "sector": "", "ret_1d": "-1.51", "score": "100", "macd_gold": "False"},
]
result_b = detect_题材错配(day_b, tuning_b, fake_resolver)
check("B. 题材错配 命中 (chem n=22)", result_b["hit"], True)

# 场景 C: 技术面虚高命中
day_c = [
    {"code": "300750", "name": "宁德时代", "sector": "energy", "ret_1d": "-2.5", "score": "95", "macd_gold": "True"},
]
result_c = detect_技术面虚高(day_c, {})
check("C. 技术面虚高 命中 (score≥90 + MACD + 亏)", result_c["hit"], True)

# 场景 C 反例: score≥90 + MACD 但赚钱
day_c2 = [
    {"code": "300750", "name": "宁德", "sector": "energy", "ret_1d": "+2.5", "score": "95", "macd_gold": "True"},
]
result_c2 = detect_技术面虚高(day_c2, {})
check("C. 技术面虚高 反例 (赚钱不算)", result_c2["hit"], False)

# 场景 D: 大盘错配
# 大盘 -2%, 候选池 -3% (跑输大盘) → 命中
day_d = [{"code": "X", "name": "Y", "ret_1d": "-3.0"}]
result_d = detect_大盘错配(day_d, day_baseline=-2.0)
check("D. 大盘错配 大盘 -2% + 候选池 -3% 命中", result_d["hit"], True)
result_d2 = detect_大盘错配(day_b, day_baseline=0.5)
check("D. 大盘错配 大盘 +0.5% 不命中", result_d2["hit"], False)
result_d3 = detect_大盘错配(day_b, day_baseline=None)
check("D. 大盘错配 大盘 None 不命中", result_d3["hit"], False)

# 场景 E: 冷启动盲区
tuning_e = {
    "weak_sectors": [],
    "sector_stats": {"chem": {"count": 22, "win_rate": 0}, "energy": {"count": 5, "win_rate": 100}}
}
day_e = [
    {"code": "605303", "name": "园林股份", "sector": "", "ret_1d": "-0.93", "score": "100", "macd_gold": "False"},
    {"code": "002491", "name": "通鼎互联", "sector": "", "ret_1d": "-2.18", "score": "100", "macd_gold": "False"},
    {"code": "688111", "name": "金山办公", "sector": "", "ret_1d": "-1.5", "score": "100", "macd_gold": "False"},
]
fake_resolver_db["688111"] = {"cn": "软件开发", "enum": ""}
result_e = detect_冷启动盲区(day_e, tuning_e, fake_resolver)
check("E. 冷启动盲区 命中", result_e["hit"], True)
check("E. 冷启动盲区 3 只", len(result_e["items"]), 3)
check("E. 冷启动盲区 cold_sectors 3 个", len(result_e["cold_sectors"]), 3)
# 节能 energy n=5 已覆盖, 不应该出现在 cold
energy_in_cold = "energy" in result_e["cold_sectors"] or any(
    "储能" in s for s in result_e["cold_sectors"]
)
check("E. energy 不在 cold (n>=3)", energy_in_cold, False)

# 场景 F: 全部未命中 (健康日)
tuning_f = {"weak_sectors": [], "sector_stats": {"energy": {"count": 5, "win_rate": 80}}}
day_f = [
    {"code": "300750", "name": "宁德时代", "sector": "energy", "ret_1d": "+3.0", "score": "75", "macd_gold": "False"},
]
result_a_f = detect_板块错配(day_f, tuning_f, fake_resolver)
result_e_f = detect_冷启动盲区(day_f, tuning_f, fake_resolver)
check("F. 板块错配 健康日不命中", result_a_f["hit"], False)
check("F. 冷启动盲区 健康日不命中", result_e_f["hit"], False)

# ============ 测试 2: suggest_tuning 综合建议 ============
print("\n【测试 2】suggest_tuning 综合调参建议")

# 场景 G: 冷启动命中 + 板块错配命中
tuning_g = {
    "weak_sectors": ["chem"],
    "sector_stats": {"chem": {"count": 22, "win_rate": 0}, "elec": {"count": 11, "win_rate": 0}}
}
result_g = {
    "date": "2026-09-09",
    "causes": {
        "A_板块错配": {"hit": True, "items": [
            {"code": "605566", "name": "福莱蒽特", "sector_enum": "chem", "sector_cn": "纺织化学用品", "ret_1d": -1.51}
        ], "summary": "1/3 命中"},
        "B_题材错配": {"hit": False, "items": [], "summary": ""},
        "C_技术面虚高": {"hit": False, "items": [], "summary": ""},
        "D_大盘错配": {"hit": True, "items": [], "summary": "大盘 -2% 普跌"},
        "E_冷启动盲区": {"hit": True, "items": [
            {"code": "605303", "name": "园林股份", "sector_cn": "园林工程", "sector_enum": "", "n": 0, "ret_1d": -0.93},
            {"code": "002491", "name": "通鼎互联", "sector_cn": "通信传输设备", "sector_enum": "", "n": 0, "ret_1d": -2.18},
        ], "cold_sectors": ["园林工程", "通信传输设备"], "summary": "2 只冷启动"},
    },
    "hit_causes": ["A_板块错配", "D_大盘错配", "E_冷启动盲区"],
}
suggestion_g = suggest_tuning(result_g, tuning_g)
check("G. 综合 score_threshold_delta ≥ 5", suggestion_g["score_threshold_delta"] >= 5, True)
check("G. 综合 position_delta ≤ -10 (大盘-10 + 冷启动-5)", suggestion_g["position_delta"] <= -10, True)
check("G. 综合 weak_sectors_add 含 chem", "chem" in suggestion_g["weak_sectors_add"], True)
check("G. 综合 cold_sectors 含 园林工程", "园林工程" in suggestion_g.get("cold_sectors", []), True)
check("G. 综合 reasons 3 条以上", len(suggestion_g["reasons"]) >= 3, True)

# ============ 测试 3: auto_tune_next_day 边界钳制 ============
print("\n【测试 3】auto_tune_next_day 边界钳制")

# 直接调 auto_tune_next_day main 模拟
import importlib
auto_tune_mod = importlib.import_module("auto_tune_next_day")

# 用 mock 文件测试边界
test_tuning = {
    "recommended_score_threshold": 70,
    "weak_sectors": ["chem"],
    "sector_stats": {"chem": {"count": 22, "win_rate": 0}}
}
test_rc = {
    "tuning_suggestion": {
        "score_threshold_delta": 100,  # 极端值
        "position_delta": -100,        # 极端值
        "weak_sectors_add": ["chem", "robot"],
        "watchlist": [],
        "cold_sectors": ["光伏"],
        "reasons": ["test"]
    }
}

# 写 mock 文件
data_dir = Path("/Users/cai/Code/AAna/data")
(test_dir := data_dir).mkdir(exist_ok=True)
(data_dir / "rec_tuning.json").write_text(json.dumps(test_tuning, ensure_ascii=False), encoding="utf-8")
(data_dir / "daily_root_cause.json").write_text(json.dumps(test_rc, ensure_ascii=False), encoding="utf-8")

# 跑 auto_tune_next_day
r = subprocess.run(
    ["python3", "scripts/auto_tune_next_day.py"],
    capture_output=True, text=True, timeout=15,
    cwd="/Users/cai/Code/AAna"
)
check("auto_tune_next_day EXIT 0", r.returncode, 0)

# 读 next_day_strategy.json
nd = json.loads((data_dir / "next_day_strategy.json").read_text(encoding="utf-8"))
check("next_day_strategy.score_threshold ≤ 80 (钳制)", nd["score_threshold"] <= 80, True)
check("next_day_strategy.score_threshold ≥ 55", nd["score_threshold"] >= 55, True)
check("next_day_strategy.position_final ≥ 10", nd["position_final"] >= 10, True)
check("next_day_strategy.position_final ≤ 90", nd["position_final"] <= 90, True)
check("next_day_strategy.cold_sectors 含 光伏", "光伏" in nd["cold_sectors"], True)
check("next_day_strategy.tuning_log ≥ 2 entries", len(nd["tuning_log"]) >= 2, True)

# ============ 测试 4: 真实数据回测 9/3 + 9/8 ============
print("\n【测试 4】真实数据回测 9/3 + 9/8")

# 跑 daily_root_cause 9/3
r = subprocess.run(
    ["python3", "scripts/daily_root_cause.py", "2026-09-03"],
    capture_output=True, text=True, timeout=60,
    cwd="/Users/cai/Code/AAna"
)
check("9/3 daily_root_cause EXIT 0", r.returncode, 0)

rc_3 = json.loads((data_dir / "daily_root_cause.json").read_text(encoding="utf-8"))
# 9/3 应该命中 E 冷启动
check("9/3 hit_causes 含 E", "E_冷启动盲区" in rc_3["hit_causes"], True)

# 跑 auto_tune
r2 = subprocess.run(
    ["python3", "scripts/auto_tune_next_day.py"],
    capture_output=True, text=True, timeout=15,
    cwd="/Users/cai/Code/AAna"
)
nd_3 = json.loads((data_dir / "next_day_strategy.json").read_text(encoding="utf-8"))
check("9/3 auto_tune cold_sectors ≥ 2", len(nd_3["cold_sectors"]) >= 2, True)
check("9/3 score_threshold ≥ 70 (调高)", nd_3["score_threshold"] >= 70, True)
check("9/3 position_final ≤ 50 (调低)", nd_3["position_final"] <= 50, True)

# 跑 9/8
r3 = subprocess.run(
    ["python3", "scripts/daily_root_cause.py", "2026-09-08"],
    capture_output=True, text=True, timeout=60,
    cwd="/Users/cai/Code/AAna"
)
rc_8 = json.loads((data_dir / "daily_root_cause.json").read_text(encoding="utf-8"))
# 9/8 应该命中 E (先导基电 sector=房地产开发, cold)
check("9/8 hit_causes 含 E", "E_冷启动盲区" in rc_8["hit_causes"], True)

r4 = subprocess.run(
    ["python3", "scripts/auto_tune_next_day.py"],
    capture_output=True, text=True, timeout=15,
    cwd="/Users/cai/Code/AAna"
)
nd_8 = json.loads((data_dir / "next_day_strategy.json").read_text(encoding="utf-8"))
check("9/8 cold_sectors 含 房地产开发", "房地产开发" in nd_8["cold_sectors"], True)

# ============ 测试 5: strategy_policy 集成 ============
print("\n【测试 5】strategy_policy.next_day_strategy 集成")

r5 = subprocess.run(
    ["python3", "-c", """
import sys
sys.path.insert(0, 'scripts')
from strategy_policy import get_today_policy
p = get_today_policy()
print(f'threshold={p.score_threshold}')
print(f'blacklist={p.sector_blacklist}')
print(f'notes={p.data_notes}')
"""],
    capture_output=True, text=True, timeout=15,
    cwd="/Users/cai/Code/AAna"
)
check("strategy_policy 加载 OK", r5.returncode, 0)
# threshold 应该含 next_day_strategy 的影响 (>= 70)
import re
m = re.search(r'threshold=(\d+)', r5.stdout)
if m:
    threshold = int(m.group(1))
    check(f"strategy_policy threshold ≥ 70 (含 next_day_strategy)", threshold >= 70, True)

# ============ 汇总 ============
print("\n" + "=" * 60)
print(f"测试结果: ✅ {passed} pass / ❌ {failed} fail")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
