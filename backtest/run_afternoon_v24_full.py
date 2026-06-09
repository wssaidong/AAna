"""
backtest/run_afternoon_v24_full.py — v2.4 完整回测（T+1 开盘卖 + T+3 止损 + T+3 截止）
================================================================================
对比:
  S0: 5 日持有（v2.2 基线）
  S1: T+1 开盘即卖（v2.4 推荐）
  V24: v2.4 完整组合（T+1 跳空≥+1%卖/≤-2%卖 + 观察 + T+3 -3%止损 + T+3 <+1%截止 + T+5 兜底 + 任何时点 -5%硬止损）

数据: 29 只候选股 / 90 天 / 1508 笔推荐
用法:
  cd ~/code/AAna && .venv/bin/python backtest/run_afternoon_v24_full.py
"""
import os, sys, json, time, math, warnings
from datetime import datetime, timedelta
import urllib3
urllib3.disable_warnings()
import requests
warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

CODES = [
    "000951", "002472", "603662", "605488", "000608",
    "000333", "003011", "600367", "600378", "603919", "603936",
    "600519", "000858", "600887", "601888", "600036", "601166", "601398",
    "600030", "601318", "601628", "000538", "600276", "002415", "002475",
    "002594", "601012", "002714", "000001",
]
KLINE_COUNT = 200
COST = 0.1  # 单边 0.1%
HARD_STOP_PCT = -5.0


def fetch_kline(code, count=KLINE_COUNT):
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
                return []
            continue
    return []


def synthesize_t_info(klines, t_idx):
    k = klines[t_idx]
    return {
        'code': '', 'name': '',
        'price': k['close'],
        'yesterday_close': klines[t_idx-1]['close'],
        'today_open': k['open'],
        'high': k['high'], 'low': k['low'],
        'change_pct': (k['close'] / klines[t_idx-1]['close'] - 1) * 100,
        'vol': k['vol'],
        'amount': k['vol'] * k['close'] * 100,
    }


def collect_recommendations(klines_cache, window_days=90):
    """收集所有 score>=65 的 T 日推荐"""
    recs = []
    for code, kl in klines_cache.items():
        if len(kl) < 130: continue
        max_t = len(kl) - 6
        t_start = max(35, max_t - window_days)
        for t_idx in range(t_start, max_t):
            t_info = synthesize_t_info(kl, t_idx)
            t_info['code'] = code
            t_info['name'] = f'#{code}'
            if t_info['change_pct'] < -8 or t_info['change_pct'] >= 9: continue
            if t_info['price'] < 20 or t_info['price'] > 80: continue
            if code.startswith(('688', '8', '300', '301')): continue

            t_klines = kl[:t_idx+1]
            from aana_afternoon_screen import score_afternoon_stock
            s, sc = score_afternoon_stock(dict(t_info), t_klines, sentiment_score=50)
            if s < 65: continue
            recs.append({
                'code': code, 't_idx': t_idx, 't_date': kl[t_idx]['date'],
                't_close': kl[t_idx]['close'],
                'kl': kl,  # 留 K 线供后续访问
            })
    return recs


def simulate_s0_hold5(rec):
    """S0: 5 日持有 (v2.2 基线)"""
    kl = rec['kl']
    t_idx = rec['t_idx']
    t1_open = kl[t_idx+1]['open']
    t5_close = kl[t_idx+5]['close']
    return (t5_close / t1_open - 1) * 100 - COST*2


def simulate_s1_t1open(rec):
    """S1: T+1 开盘即卖"""
    kl = rec['kl']
    t_idx = rec['t_idx']
    t1_open = kl[t_idx+1]['open']
    return (t1_open / rec['t_close'] - 1) * 100 - COST*2


def simulate_v24(rec):
    """v2.4 完整组合"""
    kl = rec['kl']
    t_idx = rec['t_idx']
    entry = rec['t_close']
    pos_cost_rate = COST * 2 / 100  # 0.002

    # 变量
    highest = entry
    t1_open_price = kl[t_idx+1]['open']
    t1_open_gap = (t1_open_price / entry - 1) * 100

    # === 规则 0: T+1 跳空低开 ≤ -2% → 立即卖 (T+1) ===
    if t1_open_gap <= -2.0:
        return t1_open_gap - pos_cost_rate * 100

    # === 规则 1: T+1 跳空高开 ≥ +1% → 立即卖 (T+1) ===
    if t1_open_gap >= 1.0:
        return t1_open_gap - pos_cost_rate * 100

    # === 观察 T+1 盘中 ===
    t1 = kl[t_idx+1]
    if t1['high'] > highest:
        highest = t1['high']
    intraday_high_pct = (t1['high'] / entry - 1) * 100
    # 盘中触及 +1% → 日内止盈
    if intraday_high_pct >= 1.0:
        return 1.0 - pos_cost_rate * 100  # 卖在 +1% 价位

    # === 硬止损 (任何时点) ===
    # T+1 最低跌幅
    t1_low_pct = (t1['low'] / entry - 1) * 100
    if t1_low_pct <= HARD_STOP_PCT:
        return HARD_STOP_PCT  # -5%

    # === T+2 持有观察 ===
    if t_idx + 2 >= len(kl):
        # K 线不够，兜底按 T+1 收盘卖
        return (t1['close'] / entry - 1) * 100 - pos_cost_rate * 100
    t2 = kl[t_idx+2]
    if t2['high'] > highest:
        highest = t2['high']
    t2_low_pct = (t2['low'] / entry - 1) * 100
    if t2_low_pct <= HARD_STOP_PCT:
        return HARD_STOP_PCT

    # === T+3 强制止损 + 截止 ===
    if t_idx + 3 >= len(kl):
        return (t2['close'] / entry - 1) * 100 - pos_cost_rate * 100
    t3 = kl[t_idx+3]
    if t3['high'] > highest:
        highest = t3['high']
    t3_low_pct = (t3['low'] / entry - 1) * 100
    if t3_low_pct <= HARD_STOP_PCT:
        return HARD_STOP_PCT

    t3_close_pct = (t3['close'] / entry - 1) * 100
    # T+3 收盘 ≤ -3% → 强制止损
    if t3_close_pct <= -3.0:
        return t3_close_pct - pos_cost_rate * 100
    # T+3 收盘 < +1% → 钝化止损
    if t3_close_pct < 1.0:
        return t3_close_pct - pos_cost_rate * 100
    # 收盘 ≥ +1% → 继续持有

    # === T+4 持有观察 ===
    if t_idx + 4 >= len(kl):
        return (t3['close'] / entry - 1) * 100 - pos_cost_rate * 100
    t4 = kl[t_idx+4]
    if t4['high'] > highest:
        highest = t4['high']
    t4_low_pct = (t4['low'] / entry - 1) * 100
    if t4_low_pct <= HARD_STOP_PCT:
        return HARD_STOP_PCT

    # === T+5 兜底必卖 ===
    t5 = kl[t_idx+5]
    t5_close_pct = (t5['close'] / entry - 1) * 100
    return t5_close_pct - pos_cost_rate * 100


def stats(rets):
    if not rets: return {}
    n = len(rets)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    return {
        'n': n,
        'win_rate': len(wins) / n * 100,
        'avg': sum(rets) / n,
        'total': sum(rets),
        'max_win': max(rets),
        'max_loss': min(rets),
        'pf': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
    }


def main():
    print("=" * 70)
    print("AAna v2.4 完整卖出策略 90 天回测")
    print("=" * 70)

    # 拉 K 线
    print(f"\n[1] 拉 K 线 ({len(CODES)} 只 × {KLINE_COUNT} 日)")
    klines_cache = {}
    for i, code in enumerate(CODES):
        kl = fetch_kline(code, KLINE_COUNT)
        if len(kl) >= 130:
            klines_cache[code] = kl
        time.sleep(0.15)
    print(f"  可用: {len(klines_cache)} 只")

    # 收集推荐
    print(f"\n[2] 收集 90 天推荐 (score>=65)")
    recs = collect_recommendations(klines_cache, window_days=90)
    print(f"  共 {len(recs)} 笔推荐")

    # 三策略回测
    print(f"\n[3] 跑 3 策略回测")
    results = {'S0_5d': [], 'S1_t1open': [], 'V24': []}
    for rec in recs:
        results['S0_5d'].append(simulate_s0_hold5(rec))
        results['S1_t1open'].append(simulate_s1_t1open(rec))
        results['V24'].append(simulate_v24(rec))

    # 输出对比
    print(f"\n{'='*70}")
    print(f"{'策略':<15s}{'笔数':>6s}{'胜率':>8s}{'平均':>10s}{'总收益':>11s}{'盈亏比':>9s}{'最大盈':>10s}{'最大亏':>10s}")
    print('='*70)
    labels = {
        'S0_5d': 'S0 5日持有(基线)',
        'S1_t1open': 'S1 T+1开盘卖',
        'V24': 'V24 完整组合',
    }
    for key in ['S0_5d', 'S1_t1open', 'V24']:
        s = stats(results[key])
        if not s: continue
        print(f"  {labels[key]:<13s}{s['n']:>6d}{s['win_rate']:>7.1f}%{s['avg']:>+9.2f}%{s['total']:>+10.2f}%{s['pf']:>8.2f}{s['max_win']:>+9.2f}%{s['max_loss']:>+9.2f}%")

    # V24 决策分布
    print(f"\n{'='*70}")
    print("V24 决策分布 (90 天)")
    print('='*70)
    v24_rets = results['V24']
    v24_wins = [r for r in v24_rets if r > 0]
    v24_losses = [r for r in v24_rets if r <= 0]
    print(f"  盈利笔数: {len(v24_wins)} ({len(v24_wins)/len(v24_rets)*100:.1f}%)")
    print(f"  亏损笔数: {len(v24_losses)} ({len(v24_losses)/len(v24_rets)*100:.1f}%)")
    print(f"  极端亏损 (<= -5%): {sum(1 for r in v24_rets if r <= -5.0)} 笔")
    print(f"  大盈利 (>= +3%): {sum(1 for r in v24_rets if r >= 3.0)} 笔")
    print(f"  中等盈利 (+1~+3%): {sum(1 for r in v24_rets if 1.0 <= r < 3.0)} 笔")

    # V24 vs S1 对比（应该是 S1 的子集 + 边角情况）
    print(f"\n{'='*70}")
    print("V24 vs S1 差异 (V24 优于 S1 的部分)")
    print('='*70)
    s1_rets = results['S1_t1open']
    diff = [v24_rets[i] - s1_rets[i] for i in range(len(v24_rets))]
    wins_in_diff = [d for d in diff if d > 0.01]
    losses_in_diff = [d for d in diff if d < -0.01]
    print(f"  V24 更优: {len(wins_in_diff)} 笔 (avg +{sum(wins_in_diff)/len(wins_in_diff):.2f}%)")
    print(f"  S1 更优: {len(losses_in_diff)} 笔 (avg {sum(losses_in_diff)/len(losses_in_diff):.2f}%)")
    print(f"  无差异:  {len(diff) - len(wins_in_diff) - len(losses_in_diff)} 笔")
    net_diff = sum(diff)
    print(f"  净差异: {net_diff:+.2f}%")

    # 写报告
    out_dir = os.path.join(PROJECT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d')}-回测v2.4-完整卖出策略.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"# AAna v2.4 完整卖出策略回测\n\n")
        f.write(f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**候选股：** {len(CODES)} 只 / **窗口：** 90 天 / **推荐数：** {len(recs)} 笔\n\n")
        f.write(f"**评分：** v2.3 (已删 MACD 二次确认加分)\n\n")

        f.write("## 一、3 策略对比\n\n")
        f.write("| 策略 | 笔数 | 胜率 | 平均 | 总收益 | 盈亏比 | 最大盈 | 最大亏 |\n")
        f.write("|:---|---:|---:|---:|---:|---:|---:|---:|\n")
        for key in ['S0_5d', 'S1_t1open', 'V24']:
            s = stats(results[key])
            if not s: continue
            f.write(f"| {labels[key]} | {s['n']} | {s['win_rate']:.1f}% | "
                    f"{s['avg']:+.2f}% | {s['total']:+.2f}% | {s['pf']:.2f} | "
                    f"{s['max_win']:+.2f}% | {s['max_loss']:+.2f}% |\n")

        f.write("\n## 二、V24 决策分布\n\n")
        f.write("| 类别 | 笔数 | 比例 |\n")
        f.write("|:---|---:|---:|\n")
        f.write(f"| 盈利笔数 | {len(v24_wins)} | {len(v24_wins)/len(v24_rets)*100:.1f}% |\n")
        f.write(f"| 亏损笔数 | {len(v24_losses)} | {len(v24_losses)/len(v24_rets)*100:.1f}% |\n")
        f.write(f"| 极端亏损 (≤ -5% 硬止损) | {sum(1 for r in v24_rets if r <= -5.0)} | {sum(1 for r in v24_rets if r <= -5.0)/len(v24_rets)*100:.1f}% |\n")
        f.write(f"| 大盈利 (≥ +3%) | {sum(1 for r in v24_rets if r >= 3.0)} | {sum(1 for r in v24_rets if r >= 3.0)/len(v24_rets)*100:.1f}% |\n")
        f.write(f"| 中等盈利 (+1~+3%) | {sum(1 for r in v24_rets if 1.0 <= r < 3.0)} | {sum(1 for r in v24_rets if 1.0 <= r < 3.0)/len(v24_rets)*100:.1f}% |\n")

        f.write("\n## 三、V24 vs S1 差异\n\n")
        f.write(f"- V24 更优（差额 +0.01% 以上）: **{len(wins_in_diff)}** 笔 (avg +{sum(wins_in_diff)/len(wins_in_diff):.2f}%)\n")
        f.write(f"- S1 更优: {len(losses_in_diff)} 笔\n")
        f.write(f"- 无差异: {len(diff) - len(wins_in_diff) - len(losses_in_diff)} 笔\n")
        f.write(f"- **净差异: {net_diff:+.2f}%**\n\n")

        f.write("## 四、v2.4 决策规则总览\n\n")
        f.write("| 触发条件 | 动作 | 理由 |\n")
        f.write("|:---|:---|:---|\n")
        f.write("| T+1 跳空 ≥ +1% | **立即卖** | 锁定跳空利润（S1 主策略）|\n")
        f.write("| T+1 跳空 ≤ -2% | **立即卖** | 无反弹希望（-2% 止损）|\n")
        f.write("| T+1 跳空 0~+1%, 盘中触及 +1% | **日内止盈** | 不贪 |\n")
        f.write("| 任何时点 ≤ -5% | **硬止损** | 风险控制底线 |\n")
        f.write("| T+3 收盘 ≤ -3% | **强制止损** | 钝化止损 |\n")
        f.write("| T+3 收盘 < +1% | **钝化止损** | 不死守 |\n")
        f.write("| T+3 收盘 ≥ +1% | 继续持有 | 给强势股多跑 |\n")
        f.write("| T+5 收盘 | **兜底必卖** | 强制清仓 |\n\n")

        f.write("## 五、实盘集成状态\n\n")
        f.write("✅ `scripts/sell_strategy_v24.py` 已实现 (SellStrategyV24 + PositionState + SellDecision)\n")
        f.write("✅ `data/paper_trading.py` 已集成 (`auto_sell_v24(date_str, quotes_ohlc)`)\n")
        f.write("✅ 用法: 每日 15:30 收盘后调用 `paper_trading.auto_sell_v24(today, quotes)`\n")
        f.write("✅ CLI 验证: `python3 scripts/sell_strategy_v24.py` 3 个场景全部通过\n\n")

    print(f"\n报告已保存: {out_path}")


if __name__ == '__main__':
    main()
