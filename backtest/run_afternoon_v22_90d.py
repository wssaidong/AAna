"""
backtest/run_afternoon_v22_90d.py — AAna 尾盘选股 v2.2 90 天回测
================================================================
v2.2 + 90 天 + 29 只候选股 + 显著性检验

设计要点：
- 候选池 29 只（用户持仓 + Top10 常客 + 行业龙头）
- T 日窗口：90 个交易日（约 4.5 个月）
- K 线拉 200 根（覆盖 90 T 日 + 5 持有 + 60 buffer + EMA26 起步 + 边界余量）
- 每天 14:45 模拟评分 → 次日开盘买入 → 持有 5 日 → T+5 收盘卖
- 同时跑 v1.0 (备份) 和 v2.2 对比
- v2.2 内拆分：二次确认 / 金叉无确认 / 无金叉 三个子集
- 显著性检验：二次确认 vs 无确认 的胜率差是否显著（Fisher 精确检验）

使用：
  cd ~/code/AAna && .venv/bin/python backtest/run_afternoon_v22_90d.py
"""
import os
import sys
import json
import importlib.util
import warnings
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import urllib3
urllib3.disable_warnings()

import requests
import math

warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

# ═══════════════════════════════════════════════════════════
# 参数配置
# ═══════════════════════════════════════════════════════════
LOOKBACK_T = 90              # 90 个交易日
HOLD_DAYS = 5                # 持有 5 日
KLINE_COUNT = 200            # K 线拉 200 根（覆盖 buffer + EMA + T+5）
MIN_KLINES = LOOKBACK_T + HOLD_DAYS + 30  # 至少需要 125 根

# 29 只候选股（用户持仓 + Top10 常客 + 行业龙头）
CANDIDATE_CODES = [
    # 现有 Top10 常客
    "000951", "002472", "603662", "605488", "000608",
    # 用户实际持仓
    "000333", "003011", "600367", "600378", "603919", "603936",
    # 行业龙头（消费）
    "600519", "000858", "600887", "601888",
    # 行业龙头（金融）
    "600036", "601166", "601398", "600030", "601318", "601628",
    # 行业龙头（医药）
    "000538", "600276",
    # 行业龙头（科技/电子）
    "002415", "002475", "002594", "601012",
    # 农业
    "002714",
    # 银行
    "000001",
]


# ═══════════════════════════════════════════════════════════
# 数据层
# ═══════════════════════════════════════════════════════════
def fetch_kline(code: str, count: int = KLINE_COUNT) -> List[Dict]:
    """腾讯 K 线（前复权）"""
    mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayhfq&param={mkt}{code},day,,,{count},qfq"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, verify=False)
            text = r.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1]
            data = json.loads(text)
            day = data.get('data', {}).get(f'{mkt}{code}', {}).get('qfqday', [])
            if not day:
                day = data.get('data', {}).get(f'{mkt}{code}', {}).get('day', [])
            return [
                {'date': d[0], 'open': float(d[1]), 'high': float(d[2]),
                 'low': float(d[3]), 'close': float(d[4]), 'vol': float(d[5])}
                for d in day
            ]
        except Exception as e:
            if attempt == 2:
                print(f"  K线失败 {code}: {e}")
                return []
            continue
    return []


def synthesize_T_day_info(klines: List[Dict], t_idx: int) -> Dict:
    """从 T 日 K 线构造 14:45 行情"""
    k = klines[t_idx]
    return {
        'code': '', 'name': '',
        'price': k['close'],
        'yesterday_close': klines[t_idx - 1]['close'],
        'today_open': k['open'],
        'high': k['high'],
        'low': k['low'],
        'change_pct': (k['close'] / klines[t_idx - 1]['close'] - 1) * 100,
        'vol': k['vol'],
        'amount': k['vol'] * k['close'] * 100,
    }


# ═══════════════════════════════════════════════════════════
# 模块加载（v2.2 / v1.0）
# ═══════════════════════════════════════════════════════════
def load_module(module_name: str, path: str):
    """从路径动态加载模块（exec 模式）"""
    import types
    src = open(path, encoding='utf-8').read()
    mod = types.ModuleType(module_name)
    if os.path.join(PROJECT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(PROJECT, "scripts"))
    if module_name in sys.modules:
        del sys.modules[module_name]
    sys.modules[module_name] = mod
    try:
        exec(compile(src, path, 'exec'), mod.__dict__)
    except Exception as e:
        if module_name in sys.modules:
            del sys.modules[module_name]
        raise RuntimeError(f"加载 {path} 失败: {e}")
    return mod


# ═══════════════════════════════════════════════════════════
# 统计 + 显著性检验
# ═══════════════════════════════════════════════════════════
def compute_stats(trades: List[Dict]) -> Dict:
    """计算回测统计指标"""
    if not trades:
        return {"trades": 0}
    n = len(trades)
    returns = [t['return_5d'] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    hit_target = [r for r in returns if r >= 5.0]
    hit_stop = [r for r in returns if r <= -5.0]

    avg_ret = sum(returns) / n
    win_rate = len(wins) / n * 100
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    max_win = max(returns)
    max_loss = min(returns)
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')

    # 最大回撤（按时间排序的累计收益）
    cum = 0
    peak = 0
    max_dd = 0
    for r in returns:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # 夏普比率（年化，假设 252 交易日）
    if n > 1:
        mean = avg_ret
        var = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0
        sharpe = (mean * 252 / 5) / std if std > 0 else 0  # 5日持有 -> 年化
    else:
        sharpe = 0

    return {
        "trades": n,
        "win_rate": win_rate,
        "avg_return": avg_ret,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_win": max_win,
        "max_loss": max_loss,
        "profit_factor": profit_factor,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "hit_target": len(hit_target),
        "hit_stop": len(hit_stop),
    }


def fisher_exact_test(group_a_wins: int, group_a_n: int,
                       group_b_wins: int, group_b_n: int) -> Tuple[float, float]:
    """
    Fisher 精确检验：两组胜率差异是否显著
    返回 (p_value, odds_ratio)
    简化实现：使用 Python 标准库（无 scipy 依赖）
    """
    try:
        from math import comb, log, exp
    except ImportError:
        return 1.0, 1.0

    # 2x2 列联表
    a_win, a_lose = group_a_wins, group_a_n - group_a_wins
    b_win, b_lose = group_b_wins, group_b_n - group_b_wins

    # 边缘合计
    n = group_a_n + group_b_n
    row1 = a_win + b_win      # 总胜
    col1 = group_a_n          # a 总
    col2 = group_b_n          # b 总

    # Fisher 精确检验：枚举所有可能的 a_win 值
    # P = sum of hypergeometric probabilities
    def hypergeom_pmf(k, n1, n2, total):
        if k < max(0, n1 - (total - n2)) or k > min(n1, n2):
            return 0
        return comb(n2, k) * comb(total - n2, n1 - k) / comb(total, n1)

    obs_p = hypergeom_pmf(a_win, col1, row1, n)
    # p-value (双侧) = sum of P(x) for x where P(x) <= P(observed)
    p_val = 0
    for k in range(0, col1 + 1):
        p_x = hypergeom_pmf(k, col1, row1, n)
        if p_x <= obs_p * 1.0001:  # 加一点容差
            p_val += p_x

    # Odds ratio
    if a_lose == 0 or b_lose == 0 or b_win == 0 or a_win == 0:
        odds = float('inf')
    else:
        odds = (a_win * b_lose) / (a_lose * b_win)

    return min(p_val, 1.0), odds


def welch_t_test(group_a: List[float], group_b: List[float]) -> Tuple[float, float]:
    """
    Welch t 检验：两组均值差异
    返回 (t_stat, p_value_approx)
    """
    n1, n2 = len(group_a), len(group_b)
    if n1 < 2 or n2 < 2:
        return 0, 1.0

    m1, m2 = sum(group_a) / n1, sum(group_b) / n2
    v1 = sum((x - m1) ** 2 for x in group_a) / (n1 - 1)
    v2 = sum((x - m2) ** 2 for x in group_b) / (n2 - 1)

    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 0, 1.0
    t = (m1 - m2) / se
    # Welch-Satterthwaite 自由度
    df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    # 简化 p-value：使用正态近似（df 大时接近正态）
    # 实际应该用 t 分布 CDF，但标准库没有
    # 简化：|t| > 1.96 视为 p<0.05，> 2.58 视为 p<0.01
    abs_t = abs(t)
    if abs_t > 2.58:
        p_approx = 0.01
    elif abs_t > 1.96:
        p_approx = 0.05
    elif abs_t > 1.645:
        p_approx = 0.10
    else:
        p_approx = 0.20
    return t, p_approx


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print(f"AAna 尾盘选股 v2.2 {LOOKBACK_T} 天回测 (含显著性检验)")
    print("=" * 70)

    # 加载模块
    v22_path = os.path.join(PROJECT, "scripts", "aana_afternoon_screen.py")
    v10_path = os.path.join(PROJECT, "scripts", "aana_afternoon_screen.py.bak")
    print(f"\n[1] 加载 v2.2: {v22_path}")
    v22 = load_module("afternoon_v22", v22_path)
    v10 = None
    if os.path.exists(v10_path):
        print(f"    加载 v1.0: {v10_path}")
        v10 = load_module("afternoon_v10", v10_path)
    else:
        print("    v1.0 备份不存在")

    # 拉 K 线
    print(f"\n[2] 拉取 K 线 ({len(CANDIDATE_CODES)} 只 × {KLINE_COUNT} 日)")
    klines_cache = {}
    import time
    for i, code in enumerate(CANDIDATE_CODES):
        kl = fetch_kline(code, KLINE_COUNT)
        if len(kl) >= MIN_KLINES:
            klines_cache[code] = kl
        else:
            print(f"  {code}: ❌ K线不足 ({len(kl)}/{MIN_KLINES})")
        time.sleep(0.2)
    print(f"  实际可用: {len(klines_cache)} 只")

    # 跑回测
    print(f"\n[3] 跑回测 (90 T 日 × {len(klines_cache)} 只股 × v2.2{'/v1.0' if v10 else ''})")
    results = {"v2.2": []}
    if v10:
        results["v1.0"] = []
    skipped = {"v2.2": 0, "v1.0": 0}

    for code, kl in klines_cache.items():
        max_t = len(kl) - HOLD_DAYS - 1
        # 90 个 T 日 = kl 末尾 90 个
        t_start = max(35, max_t - LOOKBACK_T)  # 至少留 EMA26 + buffer
        for t_idx in range(t_start, max_t):
            t_info = synthesize_T_day_info(kl, t_idx)
            t_info['code'] = code
            t_info['name'] = f'#{code}'

            # 过滤（与 screen_afternoon_stocks 一致）
            if t_info['change_pct'] < -8 or t_info['change_pct'] >= 9:
                continue
            if t_info['change_pct'] > 5:
                continue
            if t_info['price'] < 20 or t_info['price'] > 80:
                continue
            if code.startswith(('688', '8', '300', '301')):
                continue

            t_klines = kl[:t_idx + 1]
            t1_open = kl[t_idx + 1]['open']
            t5_close = kl[t_idx + HOLD_DAYS]['close']
            ret_5d = (t5_close / t1_open - 1) * 100

            # v2.2 评分
            try:
                info_copy = dict(t_info)
                score, scored = v22.score_afternoon_stock(info_copy, t_klines, sentiment_score=50)
            except Exception as e:
                score = 0
                scored = {}
                skipped["v2.2"] += 1

            if score >= 65:
                results["v2.2"].append({
                    'code': code, 't_date': kl[t_idx]['date'],
                    'score': score, 'entry': t1_open, 'exit': t5_close,
                    'return_5d': ret_5d,
                    'macd_gold': bool(scored.get('macd_gold', False)),
                    'macd_confirmed': bool(scored.get('macd_confirmed', False)),
                    'macd_vol_shrink': bool(scored.get('macd_vol_shrink', False)),
                })

            # v1.0 评分
            if v10:
                try:
                    info_copy2 = dict(t_info)
                    score10 = v10.score_afternoon_stock(info_copy2, t_klines)[0]
                except Exception as e:
                    score10 = 0
                    skipped["v1.0"] += 1
                if score10 >= 65:
                    results["v1.0"].append({
                        'code': code, 't_date': kl[t_idx]['date'],
                        'score': score10, 'entry': t1_open, 'exit': t5_close,
                        'return_5d': ret_5d,
                    })

    # 统计
    print(f"\n[4] 回测结果")
    print("=" * 70)
    summary = {}
    for version, trades in results.items():
        print(f"\n【{version}】 共 {len(trades)} 笔交易")
        if not trades:
            summary[version] = {"trades": 0}
            continue
        s = compute_stats(trades)
        summary[version] = s
        print(f"  胜率:        {s['win_rate']:.1f}%")
        print(f"  平均收益:    {s['avg_return']:+.2f}%")
        print(f"  平均盈利:    {s['avg_win']:+.2f}% ({sum(1 for t in trades if t['return_5d']>0)} 笔)")
        print(f"  平均亏损:    {s['avg_loss']:+.2f}% ({sum(1 for t in trades if t['return_5d']<=0)} 笔)")
        print(f"  最大单笔:    {s['max_win']:+.2f}%")
        print(f"  最大亏损:    {s['max_loss']:+.2f}%")
        print(f"  盈亏比:      {s['profit_factor']:.2f}")
        print(f"  最大回撤:    {s['max_dd']:.2f}%")
        print(f"  夏普比率:    {s['sharpe']:.2f}")
        print(f"  命中 +5% 目标: {s['hit_target']}/{s['trades']} = {s['hit_target']/s['trades']*100:.1f}%")
        print(f"  触发 -5% 止损: {s['hit_stop']}/{s['trades']} = {s['hit_stop']/s['trades']*100:.1f}%")

    # ── v1.0 vs v2.2 对比 ──
    if "v1.0" in summary and "v2.2" in summary:
        print(f"\n[5] v1.0 vs v2.2 对比")
        print("=" * 70)
        print(f"{'指标':<18s} {'v1.0':>10s} {'v2.2':>10s} {'Δ':>10s}")
        print("-" * 50)
        for key, label in [
            ("trades", "交易笔数"),
            ("win_rate", "胜率(%)"),
            ("avg_return", "平均收益(%)"),
            ("avg_win", "平均盈利(%)"),
            ("avg_loss", "平均亏损(%)"),
            ("max_win", "最大单笔(%)"),
            ("max_loss", "最大亏损(%)"),
            ("profit_factor", "盈亏比"),
            ("max_dd", "最大回撤(%)"),
            ("sharpe", "夏普比率"),
            ("hit_target", "命中+5%目标"),
            ("hit_stop", "触发-5%止损"),
        ]:
            v1 = summary["v1.0"].get(key, 0)
            v2 = summary["v2.2"].get(key, 0)
            diff = v2 - v1
            if key in ("win_rate",):
                print(f"  {label:<16s} {v1:>9.1f}% {v2:>9.1f}% {diff:>+9.1f}%")
            elif key in ("avg_return", "avg_win", "avg_loss", "max_win", "max_loss", "max_dd"):
                print(f"  {label:<16s} {v1:>+9.2f}% {v2:>+9.2f}% {diff:>+9.2f}%")
            elif key == "sharpe":
                print(f"  {label:<16s} {v1:>10.2f} {v2:>10.2f} {diff:>+10.2f}")
            elif key == "profit_factor":
                print(f"  {label:<16s} {v1:>10.2f} {v2:>10.2f} {diff:>+10.2f}")
            else:
                print(f"  {label:<16s} {v1:>10d} {v2:>10d} {diff:>+10d}")

    # ── MACD 二次确认子集 + 显著性检验 ──
    if "v2.2" in summary and results.get("v2.2"):
        print(f"\n[6] v2.2 MACD 信号分层 + 显著性检验")
        print("=" * 70)
        v2_trades = results["v2.2"]
        # 拆分
        groups = {
            "二次确认通过": [t for t in v2_trades if t.get('macd_confirmed')],
            "有金叉无确认": [t for t in v2_trades if t.get('macd_gold') and not t.get('macd_confirmed')],
            "无金叉": [t for t in v2_trades if not t.get('macd_gold')],
            "量缩价稳": [t for t in v2_trades if t.get('macd_vol_shrink')],
        }
        print(f"\n  {'分组':<14s} {'笔数':>5s} {'胜率':>7s} {'平均收益':>10s} {'命中+5%':>10s} {'盈亏比':>8s}")
        print("  " + "-" * 60)
        group_stats = {}
        for name, trades in groups.items():
            if not trades:
                print(f"  {name:<12s}     0      -          -          -        -")
                continue
            s = compute_stats(trades)
            group_stats[name] = s
            wins = sum(1 for t in trades if t['return_5d'] > 0)
            hit = s['hit_target']
            print(f"  {name:<12s} {s['trades']:>5d} {s['win_rate']:>6.1f}% {s['avg_return']:>+9.2f}% "
                  f"{hit:>4d}/{s['trades']:<4d} {s['profit_factor']:>7.2f}")

        # ── 显著性检验 ──
        print(f"\n  📊 显著性检验 (二次确认 vs 有金叉无确认)")
        a_trades = groups["二次确认通过"]
        b_trades = groups["有金叉无确认"]
        if a_trades and b_trades:
            a_wins = sum(1 for t in a_trades if t['return_5d'] > 0)
            b_wins = sum(1 for t in b_trades if t['return_5d'] > 0)
            a_n = len(a_trades)
            b_n = len(b_trades)

            # Fisher 精确检验（胜率）
            p_fisher, odds = fisher_exact_test(a_wins, a_n, b_wins, b_n)
            print(f"    Fisher 精确检验（胜率）: p={p_fisher:.4f}, odds_ratio={odds:.2f}")
            if p_fisher < 0.05:
                print(f"    ✅ 胜率差异显著 (p<0.05)")
            elif p_fisher < 0.10:
                print(f"    🟡 胜率差异边缘显著 (p<0.10)")
            else:
                print(f"    ⚠️ 胜率差异不显著 (p={p_fisher:.4f})")

            # Welch t 检验（均值）
            a_rets = [t['return_5d'] for t in a_trades]
            b_rets = [t['return_5d'] for t in b_trades]
            t_stat, p_t = welch_t_test(a_rets, b_rets)
            print(f"    Welch t 检验（收益）: t={t_stat:.3f}, p_approx={p_t:.2f}")
            if p_t <= 0.05:
                print(f"    ✅ 均值差异显著")
            elif p_t <= 0.10:
                print(f"    🟡 均值差异边缘显著")
            else:
                print(f"    ⚠️ 均值差异不显著")
        else:
            print("    ⚠️ 样本不足，跳过显著性检验")

        # 二次确认 vs 全部无金叉
        if groups["二次确认通过"] and groups["无金叉"]:
            print(f"\n  📊 显著性检验 (二次确认 vs 无金叉)")
            a_trades = groups["二次确认通过"]
            b_trades = groups["无金叉"]
            a_wins = sum(1 for t in a_trades if t['return_5d'] > 0)
            b_wins = sum(1 for t in b_trades if t['return_5d'] > 0)
            a_n, b_n = len(a_trades), len(b_trades)
            p_fisher, odds = fisher_exact_test(a_wins, a_n, b_wins, b_n)
            print(f"    Fisher 精确检验: p={p_fisher:.4f}, odds_ratio={odds:.2f}")
            if p_fisher < 0.05:
                print(f"    ✅ 二次确认 vs 无金叉，胜率差异显著")
            else:
                print(f"    ⚠️ 胜率差异未达显著水平")

            a_rets = [t['return_5d'] for t in a_trades]
            b_rets = [t['return_5d'] for t in b_trades]
            t_stat, p_t = welch_t_test(a_rets, b_rets)
            print(f"    Welch t 检验: t={t_stat:.3f}, p_approx={p_t:.2f}")
            if p_t <= 0.05:
                print(f"    ✅ 均值差异显著")
            else:
                print(f"    ⚠️ 均值差异不显著")

    # ── 保存报告 ──
    out_dir = os.path.join(PROJECT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d')}-回测v2.2-90天.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"# AAna 尾盘选股 v2.2 {LOOKBACK_T} 天回测报告\n\n")
        f.write(f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**候选股池：** {len(CANDIDATE_CODES)} 只\n\n")
        f.write(f"**回测参数：** {LOOKBACK_T} 个 T 日 / 持有 {HOLD_DAYS} 日 / 阈值 score>=65\n\n")
        f.write(f"**跳过评分：** v2.2: {skipped['v2.2']} 次, v1.0: {skipped['v1.0']} 次\n\n")

        f.write("## 一、整体结果对比\n\n")
        f.write("| 指标 | v1.0 | v2.2 | Δ |\n")
        f.write("|:---|---:|---:|---:|\n")
        for key, label in [
            ("trades", "交易笔数"),
            ("win_rate", "胜率(%)"),
            ("avg_return", "平均收益(%)"),
            ("avg_win", "平均盈利(%)"),
            ("avg_loss", "平均亏损(%)"),
            ("profit_factor", "盈亏比"),
            ("max_dd", "最大回撤(%)"),
            ("sharpe", "夏普比率"),
            ("hit_target", "命中+5%目标"),
            ("hit_stop", "触发-5%止损"),
        ]:
            v1 = summary.get("v1.0", {}).get(key, "-")
            v2 = summary.get("v2.2", {}).get(key, "-")
            diff = (v2 - v1) if (isinstance(v1, (int, float)) and isinstance(v2, (int, float))) else "-"
            f.write(f"| {label} | {v1} | {v2} | {diff} |\n")

        # 二次确认子集
        if "v2.2" in summary and results.get("v2.2"):
            v2_trades = results["v2.2"]
            groups = {
                "二次确认通过": [t for t in v2_trades if t.get('macd_confirmed')],
                "有金叉无确认": [t for t in v2_trades if t.get('macd_gold') and not t.get('macd_confirmed')],
                "无金叉": [t for t in v2_trades if not t.get('macd_gold')],
            }
            f.write("\n## 二、v2.2 MACD 信号分层\n\n")
            f.write("| 分组 | 笔数 | 胜率 | 平均收益 | 命中+5% | 盈亏比 |\n")
            f.write("|:---|---:|---:|---:|---:|---:|\n")
            for name, trades in groups.items():
                if not trades:
                    f.write(f"| {name} | 0 | - | - | - | - |\n")
                    continue
                s = compute_stats(trades)
                f.write(f"| {name} | {s['trades']} | {s['win_rate']:.1f}% | {s['avg_return']:+.2f}% | "
                        f"{s['hit_target']}/{s['trades']} | {s['profit_factor']:.2f} |\n")

    print(f"\n报告已保存: {out_path}")
    print("=" * 70)


if __name__ == '__main__':
    main()
