"""
backtest/run_afternoon_v21.py — AAna 尾盘选股 v2.2 30 天回测
================================================================
v2.2 变更：MACD 二次确认机制、集成 feedback_loop hook、lookback 3→5
回测逻辑：
  1. 选 10 只候选股（Top10 常客 + 不同行业）
  2. 对每只股拉 90 日 K 线（覆盖 30 交易日 + buffer）
  3. 在每个交易日 T (i=60..89)：
     - 模拟 T 日 14:45 尾盘：用 T 日 K 线 + T 日实时行情做评分
     - 若 score >= 65：次日 T+1 开盘买入，持有 5 日，T+5 收盘卖出
  4. 统计所有 (T, code) 组合的实际收益
  5. 重点对比：v2.2 普通信号 vs v2.2 二次确认信号（验证 MACD 二次确认价值）

对比 v1.0 (aana_afternoon_screen.py.bak) 看胜率/平均收益差异

使用：
  cd ~/code/AAna && .venv/bin/python backtest/run_afternoon_v21.py
"""
import os
import sys
import json
import importlib.util
import warnings
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

# 修复请求证书问题
import urllib3
urllib3.disable_warnings()

import requests

# ── 候选股池（10 只，覆盖多个行业）──────────────────────
CANDIDATE_CODES = [
    "000951",  # 中国重汽 (重卡龙头)
    "002472",  # 双环传动 (齿轮/机器人)
    "603662",  # 柯力传感 (传感器)
    "605488",  # 福莱新材
    "600367",  # 红星发展
    "603919",  # 金徽酒
    "603936",  # 博敏电子
    "600378",  # 昊华科技
    "003011",  # 海象新材
    "000608",  # 阳光股份
]


# ── K线数据获取 ────────────────────────────────────────────
def fetch_kline(code: str, count: int = 90) -> List[Dict]:
    """腾讯 API 拉日 K 线（前复权）"""
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
                {
                    'date': d[0],
                    'open': float(d[1]),
                    'high': float(d[2]),
                    'low': float(d[3]),
                    'close': float(d[4]),
                    'vol': float(d[5]),
                }
                for d in day
            ]
        except Exception as e:
            if attempt == 2:
                print(f"  K线失败 {code}: {e}")
                return []
            continue
    return []


# ── 模拟 T 日 14:45 实时行情（从 T 日 K 线推算）──────────
def synthesize_T_day_info(klines: List[Dict], t_idx: int) -> Dict:
    """从 K 线第 t_idx 根构造 T 日 14:45 行情（已知 T 日 OHLC）"""
    k = klines[t_idx]
    return {
        'code': '', 'name': '',
        'price': k['close'],  # 收盘价（已知）
        'yesterday_close': klines[t_idx - 1]['close'],
        'today_open': k['open'],
        'high': k['high'],
        'low': k['low'],
        'change_pct': (k['close'] / klines[t_idx - 1]['close'] - 1) * 100,
        'vol': k['vol'],
        'amount': k['vol'] * k['close'] * 100,  # 估算
    }


# ── 加载模块（v2.1 / v1.0 切换）─────────────────────────
def load_module(module_name: str, path: str):
    """从指定路径动态加载模块（用 exec + types.ModuleType，兼容所有环境）"""
    import types
    src = open(path, encoding='utf-8').read()
    mod = types.ModuleType(module_name)
    # 先把 scripts/ 加入 sys.path，让 from data import ... 能找到
    if os.path.join(PROJECT, "scripts") not in sys.path:
        sys.path.insert(0, os.path.join(PROJECT, "scripts"))
    # 屏蔽子模块再导入
    if module_name in sys.modules:
        del sys.modules[module_name]
    sys.modules[module_name] = mod
    try:
        exec(compile(src, path, 'exec'), mod.__dict__)
    except Exception as e:
        # 移除失败模块避免污染 sys.modules
        if module_name in sys.modules:
            del sys.modules[module_name]
        raise RuntimeError(f"加载 {path} 失败: {e}")
    return mod


def main():
    print("=" * 70)
    print("AAna 尾盘选股 v2.1 30 天回测")
    print("=" * 70)

    # 加载 v2.1 和 v1.0
    v21_path = os.path.join(PROJECT, "scripts", "aana_afternoon_screen.py")
    v10_path = os.path.join(PROJECT, "scripts", "aana_afternoon_screen.py.bak")

    print(f"\n[1] 加载模块")
    print(f"  v2.1: {v21_path}")
    v21 = load_module("afternoon_v21", v21_path)
    if os.path.exists(v10_path):
        print(f"  v1.0: {v10_path}")
        v10 = load_module("afternoon_v10", v10_path)
    else:
        v10 = None
        print("  v1.0 备份不存在，跳过对比")

    # 回测参数
    LOOKBACK_DAYS = 30  # 30 个交易日
    MIN_HOLD_BARS = 5   # 持有 5 日
    MIN_KLINES = 65     # 至少需要 65 根 K 线（buffer + 30 + 5）

    results = {"v2.1": [], "v1.0": []} if v10 else {"v2.1": []}
    skipped = {"v2.1": 0, "v1.0": 0}

    print(f"\n[2] 拉取 K 线 ({len(CANDIDATE_CODES)} 只股 × 90 日)")
    klines_cache = {}
    for code in CANDIDATE_CODES:
        kl = fetch_kline(code, count=90)
        if len(kl) >= MIN_KLINES:
            klines_cache[code] = kl
            print(f"  {code}: {len(kl)} 根 ({kl[0]['date']} → {kl[-1]['date']})")
        else:
            print(f"  {code}: ❌ K线不足 ({len(kl)}/{MIN_KLINES})")
        import time
        time.sleep(0.3)  # 避免频率限制

    print(f"\n[3] 跑回测 (30 个 T 日 × {len(klines_cache)} 只股 × v2.1{'/v1.0' if v10 else ''})")

    # 每个 T 日从 t_idx=60..89（倒数 30 根）回测
    # T+1..T+5 必须有数据 → t_idx 最大 = len(kl) - 6
    for code, kl in klines_cache.items():
        max_t = len(kl) - MIN_HOLD_BARS - 1
        for t_idx in range(MIN_KLINES - 5, max_t):  # 留 buffer
            # 模拟 T 日 14:45 信息
            t_info = synthesize_T_day_info(kl, t_idx)
            t_info['code'] = code
            t_info['name'] = f'#{code}'

            # T 日 K 线（用于评分）= kl[0..t_idx]
            t_klines = kl[:t_idx + 1]

            # 涨跌范围过滤（与 screen_afternoon_stocks 一致）
            change_pct = t_info['change_pct']
            if change_pct < -8 or change_pct >= 9:
                continue
            if change_pct > 5:
                continue
            if t_info['price'] < 20 or t_info['price'] > 80:
                continue
            if code.startswith(('688', '8')) or code.startswith(('300', '301')):
                continue

            # T+1 开盘、T+5 收盘
            t1_open = kl[t_idx + 1]['open']
            t5_close = kl[t_idx + MIN_HOLD_BARS]['close']
            ret_5d = (t5_close / t1_open - 1) * 100

            # 用 v2.1 评分
            try:
                info_copy = dict(t_info)
                score21, scored21 = v21.score_afternoon_stock(info_copy, t_klines, sentiment_score=50)
            except Exception as e:
                score21 = 0
                scored21 = {}
                skipped["v2.1"] += 1

            if score21 >= 65:
                rec = {
                    'code': code, 't_date': kl[t_idx]['date'],
                    'score': score21, 'entry': t1_open, 'exit': t5_close,
                    'return_5d': ret_5d,
                    'macd_gold': bool(scored21.get('macd_gold', False)),
                    'macd_confirmed': bool(scored21.get('macd_confirmed', False)),
                }
                results["v2.1"].append(rec)

            # 用 v1.0 评分（如果存在）
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

    # ── 统计 ──
    print(f"\n[4] 回测结果")
    print("=" * 70)

    summary = {}
    for version, trades in results.items():
        if not trades:
            print(f"\n【{version}】 无交易信号")
            summary[version] = {"trades": 0}
            continue

        n = len(trades)
        returns = [t['return_5d'] for t in trades]
        win = [r for r in returns if r > 0]
        loss = [r for r in returns if r <= 0]
        hit_target = [r for r in returns if r >= 5.0]  # 达到 +5% 目标
        hit_stop = [r for r in returns if r <= -5.0]   # 触发 -5% 止损

        avg_ret = sum(returns) / n
        win_rate = len(win) / n * 100
        avg_win = sum(win) / len(win) if win else 0
        avg_loss = sum(loss) / len(loss) if loss else 0
        max_win = max(returns)
        max_loss = min(returns)
        # 最大回撤（累计收益曲线）
        cum = 0
        peak = 0
        max_dd = 0
        for r in returns:
            cum += r
            peak = max(peak, cum)
            dd = peak - cum
            max_dd = max(max_dd, dd)
        # 盈亏比
        profit_factor = abs(sum(win) / sum(loss)) if loss and sum(loss) != 0 else float('inf')

        print(f"\n【{version}】 共 {n} 笔交易")
        print(f"  胜率:       {win_rate:.1f}%  ({len(win)}/{n})")
        print(f"  平均收益:   {avg_ret:+.2f}%")
        print(f"  平均盈利:   {avg_win:+.2f}% ({len(win)} 笔)")
        print(f"  平均亏损:   {avg_loss:+.2f}% ({len(loss)} 笔)")
        print(f"  最大单笔:   {max_win:+.2f}%")
        print(f"  最大亏损:   {max_loss:+.2f}%")
        print(f"  盈亏比:     {profit_factor:.2f}")
        print(f"  最大回撤:   {max_dd:.2f}%")
        print(f"  命中+5%目标: {len(hit_target)}/{n} = {len(hit_target)/n*100:.1f}%")
        print(f"  触发-5%止损: {len(hit_stop)}/{n} = {len(hit_stop)/n*100:.1f}%")

        # 收益率分布
        buckets = [(0, 5), (5, 10), (10, 100), (-5, 0), (-100, -5)]
        print(f"\n  收益分布:")
        for lo, hi in buckets:
            cnt = sum(1 for r in returns if lo <= r < hi)
            bar = '█' * cnt
            label = f"  [{lo:+4d}%, {hi:+3d}%)"
            print(f"  {label}: {cnt:>3d} {bar}")

        summary[version] = {
            "trades": n, "win_rate": win_rate, "avg_return": avg_ret,
            "avg_win": avg_win, "avg_loss": avg_loss,
            "max_win": max_win, "max_loss": max_loss,
            "profit_factor": profit_factor, "max_dd": max_dd,
            "hit_target": len(hit_target), "hit_stop": len(hit_stop),
        }

    # ── 对比 ──
    if "v1.0" in summary and "v2.1" in summary:
        print(f"\n[5] v2.1 vs v1.0 对比")
        print("=" * 70)
        print(f"{'指标':<18s} {'v1.0':>10s} {'v2.1':>10s} {'Δ':>10s}")
        print("-" * 50)
        for key in ["trades", "win_rate", "avg_return", "avg_win", "avg_loss",
                    "max_win", "max_loss", "profit_factor", "max_dd", "hit_target", "hit_stop"]:
            v1 = summary["v1.0"].get(key, 0)
            v2 = summary["v2.1"].get(key, 0)
            diff = v2 - v1
            if key in ("win_rate",):
                print(f"  {key:<16s} {v1:>9.1f}% {v2:>9.1f}% {diff:>+9.1f}%")
            elif key in ("avg_return", "avg_win", "avg_loss", "max_win", "max_loss", "max_dd"):
                print(f"  {key:<16s} {v1:>+9.2f}% {v2:>+9.2f}% {diff:>+9.2f}%")
            elif key == "profit_factor":
                print(f"  {key:<16s} {v1:>10.2f} {v2:>10.2f} {diff:>+10.2f}")
            else:
                print(f"  {key:<16s} {v1:>10d} {v2:>10d} {diff:>+10d}")

    # ── MACD 二次确认子集对比（v2.2 核心） ──
    if "v2.1" in summary and results.get("v2.1"):
        print(f"\n[6] v2.2 MACD 二次确认子集对比")
        print("=" * 70)
        v2_trades = results["v2.1"]
        confirmed = [t for t in v2_trades if t.get('macd_confirmed')]
        no_confirm = [t for t in v2_trades if t.get('macd_gold') and not t.get('macd_confirmed')]
        no_gold = [t for t in v2_trades if not t.get('macd_gold')]

        def _stats(trades, label):
            if not trades:
                return
            n = len(trades)
            rets = [t['return_5d'] for t in trades]
            wins = sum(1 for r in rets if r > 0)
            avg = sum(rets) / n
            wr = wins / n * 100
            hit = sum(1 for r in rets if r >= 5)
            print(f"  {label:30s}: {n:3d} 笔  胜率 {wr:5.1f}%  平均 {avg:+5.2f}%  命中+5% {hit}/{n}")

        _stats(confirmed, "v2.2 二次确认通过")
        _stats(no_confirm, "v2.2 有金叉无确认")
        _stats(no_gold, "v2.2 无金叉")
        _stats(v2_trades, "v2.2 全部")

        if confirmed and no_confirm:
            conf_avg = sum(t['return_5d'] for t in confirmed) / len(confirmed)
            noc_avg = sum(t['return_5d'] for t in no_confirm) / len(no_confirm)
            delta = conf_avg - noc_avg
            print(f"\n  💡 二次确认贡献: 平均收益 {delta:+.2f}% (确认-无确认)")

    # ── 保存报告 ──
    out_dir = os.path.join(PROJECT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d')}-回测v2.1.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"# AAna 尾盘选股 v2.1 30 天回测报告\n\n")
        f.write(f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**候选股池：** {', '.join(CANDIDATE_CODES)}\n\n")
        f.write(f"**回测参数：** 30 个 T 日 / 持有 5 日 / 阈值 score>=65\n\n")
        f.write(f"**跳过评分：** v2.1: {skipped['v2.1']} 次, v1.0: {skipped['v1.0']} 次\n\n")
        f.write("## 结果对比\n\n")
        f.write("| 指标 | v1.0 | v2.1 | Δ |\n")
        f.write("|:---|---:|---:|---:|\n")
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
            ("hit_target", "命中+5%目标"),
            ("hit_stop", "触发-5%止损"),
        ]:
            v1 = summary.get("v1.0", {}).get(key, "-")
            v2 = summary.get("v2.1", {}).get(key, "-")
            diff = (v2 - v1) if (isinstance(v1, (int, float)) and isinstance(v2, (int, float))) else "-"
            f.write(f"| {label} | {v1} | {v2} | {diff} |\n")

        f.write("\n## 结论\n\n")
        if "v1.0" in summary and "v2.1" in summary:
            v1 = summary["v1.0"]
            v2 = summary["v2.1"]
            if v2.get("avg_return", 0) > v1.get("avg_return", 0):
                f.write("✅ v2.1 平均收益高于 v1.0\n\n")
            else:
                f.write("⚠️ v2.1 平均收益低于 v1.0\n\n")
            if v2.get("win_rate", 0) > v1.get("win_rate", 0):
                f.write("✅ v2.1 胜率高于 v1.0\n\n")
            else:
                f.write("⚠️ v2.1 胜率低于 v1.0\n\n")
            if v2.get("max_dd", 100) < v1.get("max_dd", 100):
                f.write("✅ v2.1 最大回撤小于 v1.0（更稳）\n\n")
            else:
                f.write("⚠️ v2.1 最大回撤大于 v1.0\n\n")

    print(f"\n报告已保存: {out_path}")
    print("=" * 70)


if __name__ == '__main__':
    main()
