#!/usr/bin/env python3
"""
AAna 基金 vs 股票风险收益对比报告
对比用户持仓的基金和股票，从收益、波动率、最大回撤、夏普比率角度分析
数据来源: 基金 = fund_tracker.py, 股票 = portfolio.py + 腾讯K线
"""
import sys, os, json
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'data'))

# 尝试导入
try:
    from fund_tracker import _load as fund_load, get_nav, get_hist_nav
    from portfolio import _load as port_load
    HAS_FUND = True
except ImportError:
    HAS_FUND = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ── 股票历史数据 ─────────────────────────────────────────────────────────────

def get_stock_kline(code: str, days: int = 90) -> list:
    """从腾讯API获取股票历史K线"""
    if not HAS_REQUESTS:
        return []
    try:
        # 转换代码格式
        if code.startswith('0') or code.startswith('3'):
            sc = f'sz{code}'
        elif code.startswith('6'):
            sc = f'sh{code}'
        else:
            sc = code
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayfqk&param={sc},day,,,{days},qfq"
        r = requests.get(url, timeout=8)
        text = r.text.strip()
        prefix = "var kline_dayfqk="
        if prefix in text:
            text = text[len(prefix):]
        d = json.loads(text)
        # 取日K线
        day_data = d.get('data', {}).get(sc, {}).get('day', [])
        return [
            {'date': x[0], 'open': float(x[1]), 'high': float(x[2]),
             'low': float(x[3]), 'close': float(x[4]), 'volume': float(x[5])}
            for x in day_data[-days:]
        ]
    except Exception:
        return []


# ── 风险收益指标计算 ─────────────────────────────────────────────────────────

def calc_metrics(prices: list) -> dict:
    """从价格列表计算风险收益指标"""
    if len(prices) < 5:
        return {'return_pct': 0, 'volatility': 0, 'max_drawdown': 0, 'sharpe': 0}

    # 日收益率
    returns = []
    for i in range(1, len(prices)):
        r = (prices[i] - prices[i-1]) / prices[i-1]
        returns.append(r)

    if not returns:
        return {'return_pct': 0, 'volatility': 0, 'max_drawdown': 0, 'sharpe': 0}

    import statistics
    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns) if len(returns) > 1 else 0

    # 年化收益率 (假设252交易日)
    ann_return = mean_r * 252
    ann_vol = std_r * (252 ** 0.5)

    # 夏普比率 (无风险利率假设2%)
    sharpe = (ann_return - 0.02) / ann_vol if ann_vol else 0

    # 最大回撤
    peak = prices[0]
    max_dd = 0
    for p in prices:
        if p > peak:
            peak = p
        dd = (peak - p) / peak
        if dd > max_dd:
            max_dd = dd

    total_return = (prices[-1] - prices[0]) / prices[0] * 100

    return {
        'return_pct': round(total_return, 2),
        'volatility': round(ann_vol * 100, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'sharpe': round(sharpe, 2),
    }


# ── 综合对比报告 ─────────────────────────────────────────────────────────────

def get_comparison_report() -> str:
    """生成基金 vs 股票风险收益对比报告"""
    today = datetime.now().strftime('%Y-%m-%d')
    lines = [f"## 📊 基金 vs 股票风险收益对比 · {today}\n"]

    # 读取基金持仓
    fund_positions = []
    if HAS_FUND:
        fd = fund_load()
        for code, pos in fd['positions'].items():
            hist = get_hist_nav(code, days=90)
            if len(hist) >= 5:
                prices = [float(x['nav']) for x in hist]
                m = calc_metrics(prices)
                fund_positions.append({
                    'code': code, 'name': pos['name'], 'type': pos['type'],
                    'cost': pos['cost'], 'shares': pos['shares'],
                    'current_nav': prices[-1] if prices else pos['cost'],
                    **m
                })

    # 读取股票持仓
    stock_positions = []
    if HAS_FUND:  # portfolio also loaded
        try:
            pd = port_load()
            for code, pos in pd.get('positions', {}).items():
                kline = get_stock_kline(code, days=90)
                if len(kline) >= 5:
                    prices = [x['close'] for x in kline]
                    m = calc_metrics(prices)
                    cost = pos.get('avg_cost', 0)
                    current = prices[-1] if prices else 0
                    stock_positions.append({
                        'code': code, 'name': pos.get('name', code),
                        'cost': cost, 'shares': pos.get('shares', 0),
                        'current': current, **m
                    })
        except Exception:
            pass

    if not fund_positions and not stock_positions:
        lines.append("\n**暂无持仓数据，请先添加基金或股票持仓**\n")
        return ''.join(lines)

    # ── 对比表格 ──────────────────────────────────────────────────

    # 基金 section
    if fund_positions:
        lines.append("\n### 📈 基金持仓\n")
        lines.append(f"\n| 代码 | 名称 | 类型 | 近90天收益 | 年化波动率 | 最大回撤 | 夏普比率 |\n")
        lines.append(f"|------|------|------|-----------|-----------|---------|---------|\n")
        for f in sorted(fund_positions, key=lambda x: x['return_pct'], reverse=True):
            emoji = "🟢" if f['return_pct'] >= 0 else "🔴"
            lines.append(
                f"| {f['code']} | {f['name'][:12]} | {f['type']} | "
                f"{emoji}{f['return_pct']:+.2f}% | {f['volatility']:.1f}% | "
                f"🔴{f['max_drawdown']:.1f}% | {f['sharpe']:+.2f} |\n"
            )

    # 股票 section
    if stock_positions:
        lines.append(f"\n### 📉 股票持仓\n")
        lines.append(f"\n| 代码 | 名称 | 近90天收益 | 年化波动率 | 最大回撤 | 夏普比率 |\n")
        lines.append(f"|------|------|-----------|-----------|---------|---------|\n")
        for s in sorted(stock_positions, key=lambda x: x['return_pct'], reverse=True):
            emoji = "🟢" if s['return_pct'] >= 0 else "🔴"
            lines.append(
                f"| {s['code']} | {s['name'][:12]} | "
                f"{emoji}{s['return_pct']:+.2f}% | {s['volatility']:.1f}% | "
                f"🔴{s['max_drawdown']:.1f}% | {s['sharpe']:+.2f} |\n"
            )

    # ── 综合评估 ───────────────────────────────────────────────
    all_items = fund_positions + stock_positions
    if len(all_items) >= 2:
        avg_fund_ret = sum(x['return_pct'] for x in fund_positions) / len(fund_positions) if fund_positions else 0
        avg_stock_ret = sum(x['return_pct'] for x in stock_positions) / len(stock_positions) if stock_positions else 0
        avg_fund_vol = sum(x['volatility'] for x in fund_positions) / len(fund_positions) if fund_positions else 0
        avg_stock_vol = sum(x['volatility'] for x in stock_positions) / len(stock_positions) if stock_positions else 0

        lines.append(f"\n### ⚖️ 综合对比\n")
        lines.append(f"\n| 指标 | 基金（平均） | 股票（平均） | 对比 |\n")
        lines.append(f"|:----:|:-----------:|:-----------:|:----:|\n")
        ret_diff = avg_fund_ret - avg_stock_ret
        diff_emoji = "🥇" if ret_diff > 0 else "🏆"
        lines.append(f"| 近90天收益 | {avg_fund_ret:+.2f}% | {avg_stock_ret:+.2f}% | {diff_emoji} 基金{'领先' if ret_diff > 0 else '落后'}{abs(ret_diff):.1f}% |\n")
        vol_diff = avg_stock_vol - avg_fund_vol
        lines.append(f"| 年化波动率 | {avg_fund_vol:.1f}% | {avg_stock_vol:.1f}% | {'股票波动更大' if vol_diff > 0 else '基金更稳定'} {abs(vol_diff):.1f}% |\n")

    lines.append("\n---\n*数据说明: 基金净值来源天天基金(估算)，股票价格来源腾讯K线；均为近90天历史数据，非收益承诺*\n")
    return ''.join(lines)


# ── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(get_comparison_report())