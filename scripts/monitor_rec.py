#!/usr/bin/env python3
"""
monitor_rec.py — 推荐股池实时监控告警
=====================================
读取最近N天推荐股票，检测以下告警条件（任一满足即触发）：
  1. 涨跌幅突破 ±5%
  2. 量比 > 2.0
  3. 股价突破 MA20
  4. 股价突破 BOLL 上轨/下轨

用法：
  python3 scripts/monitor_rec.py              # 最近7天
  python3 scripts/monitor_rec.py --days 3      # 最近3天
  python3 scripts/monitor_rec.py --days 14     # 最近14天

输出：Markdown 告警表格
"""

import sys
import os
import argparse
import csv
from datetime import datetime, timedelta

# 确保项目根目录在路径中
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from data.quotes import QuoteService


# ── BOLL 计算 ──────────────────────────────────────────────
def calc_boll(klines, period=20):
    """基于K线计算BOLL指标。返回 {ma20, boll_upper, boll_lower} 或 None"""
    if len(klines) < period:
        return None
    closes = [k['close'] for k in klines[-period:]]
    if None in closes:
        return None
    ma20 = sum(closes) / period
    variance = sum((c - ma20) ** 2 for c in closes) / period
    std = variance ** 0.5
    return {
        'ma20': round(ma20, 3),
        'boll_upper': round(ma20 + 2 * std, 3),
        'boll_lower': round(ma20 - 2 * std, 3),
    }


# ── 读取推荐池 ─────────────────────────────────────────────
def load_recent_recs(csv_path: str, days: int = 7) -> list:
    """
    读取 recommendations.csv，返回最近 days 天内的推荐股票列表。
    返回: [{date, code, name, sector, reason, expected_high, expected_low}, ...]
    """
    recs = []
    cutoff = datetime.now() - timedelta(days=days)
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rec_date = datetime.strptime(row['date'].strip(), '%Y-%m-%d')
                except (ValueError, KeyError):
                    continue
                if rec_date >= cutoff:
                    recs.append({
                        'date': row['date'].strip(),
                        'code': row['code'].strip().zfill(6),
                        'name': row['name'].strip(),
                        'sector': row.get('sector', '').strip(),
                        'sector_name': row.get('sector_name', '').strip(),
                        'reason': row.get('reason', '').strip(),
                        'expected_high': float(row['expected_high']) if row.get('expected_high') else None,
                        'expected_low': float(row['expected_low']) if row.get('expected_low') else None,
                    })
    except Exception as e:
        print(f"❌ 读取推荐池失败: {e}")
        sys.exit(1)
    return recs


# ── 告警检测 ──────────────────────────────────────────────
def check_alerts(qs: QuoteService, recs: list) -> list:
    """
    对推荐股票检测告警条件。
    返回告警列表: [{code, name, date, sector, reason, alert_type, detail}, ...]
    """
    alerts = []
    codes = [r['code'] for r in recs]

    # 批量获取实时行情（减少网络请求）
    rt_data = qs.realtime(codes)

    for rec in recs:
        code = rec['code']
        name = rec['name']

        # 获取技术指标（含MA5/10/20/60、vol_ratio、change_pct等）
        tech = qs.technical(code)
        if not tech or tech.get('price') is None:
            # 行情获取失败，标记为暂无数据
            alerts.append({
                **rec,
                'alert_type': '⚠️ 数据异常',
                'detail': '行情数据获取失败',
                'price': None,
                'change_pct': None,
                'vol_ratio': None,
                'ma20': None,
                'boll_upper': None,
                'boll_lower': None,
            })
            continue

        price = tech['price']
        change_pct = tech['change_pct'] or 0
        vol_ratio = tech['vol_ratio']
        ma20 = tech.get('ma20')
        ma5 = tech.get('ma5')
        ma10 = tech.get('ma10')

        # 获取K线用于BOLL计算
        klines = qs.kline(code, period='daily', count=30)
        boll = calc_boll(klines, period=20) if klines else None

        alert_types = []
        detail_parts = []

        # 条件1: 涨跌幅突破 ±5%
        if abs(change_pct) > 5.0:
            alert_types.append('📈 涨跌幅异动')
            detail_parts.append(f"涨跌幅 {change_pct:+.2f}%（阈值 ±5%）")

        # 条件2: 量比 > 2.0
        if vol_ratio is not None and vol_ratio > 2.0:
            alert_types.append('🔥 放量异动')
            detail_parts.append(f"量比 {vol_ratio}（阈值 >2.0）")

        # 条件3: 股价突破 MA20
        if ma20 is not None and price is not None:
            if price > ma20:
                alert_types.append('⬆️ 突破MA20')
                detail_parts.append(f"股价 {price} > MA20 {ma20:.2f}")
            elif price < ma20:
                alert_types.append('⬇️ 跌破MA20')
                detail_parts.append(f"股价 {price} < MA20 {ma20:.2f}")

        # 条件4: 股价突破 BOLL 上轨/下轨
        if boll:
            if price > boll['boll_upper']:
                alert_types.append('🔴 突破BOLL上轨')
                detail_parts.append(f"股价 {price} > BOLL上轨 {boll['boll_upper']}")
            elif price < boll['boll_lower']:
                alert_types.append('🟢 突破BOLL下轨')
                detail_parts.append(f"股价 {price} < BOLL下轨 {boll['boll_lower']}")

        if alert_types:
            alerts.append({
                **rec,
                'alert_type': ' / '.join(alert_types),
                'detail': '；'.join(detail_parts),
                'price': price,
                'change_pct': change_pct,
                'vol_ratio': vol_ratio,
                'ma20': ma20,
                'boll_upper': boll['boll_upper'] if boll else None,
                'boll_lower': boll['boll_lower'] if boll else None,
            })

    return alerts


# ── 格式化输出 ─────────────────────────────────────────────
def format_markdown(alerts: list, days: int) -> str:
    """生成 Markdown 告警表格"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [
        f"# 📊 推荐股池告警报告",
        f"**时间**: {now}  |  **监控范围**: 最近 {days} 天推荐股票  |  **触发告警数**: {len(alerts)}",
        "",
        "## 🚨 告警明细",
        "",
        "| 日期 | 代码 | 名称 | 板块 | 告警类型 | 价格 | 涨跌幅 | 量比 | MA20 | BOLL上轨 | BOLL下轨 | 详细 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    if not alerts:
        lines.append("| — | — | — | — | 暂无触发告警 | — | — | — | — | — | — | — |")
    else:
        for a in alerts:
            # 涨跌颜色标记
            cp = a['change_pct']
            cp_str = f"{cp:+.2f}%" if cp is not None else "—"

            # 量比颜色标记
            vr = a['vol_ratio']
            vr_str = f"{vr:.2f}" if vr is not None else "—"

            # MA20
            ma20_str = f"{a['ma20']:.2f}" if a['ma20'] is not None else "—"

            # BOLL
            bu_str = f"{a['boll_upper']:.2f}" if a['boll_upper'] is not None else "—"
            bl_str = f"{a['boll_lower']:.2f}" if a['boll_lower'] is not None else "—"

            price_str = f"{a['price']:.2f}" if a['price'] is not None else "—"

            lines.append(
                f"| {a['date']} | {a['code']} | {a['name']} | {a['sector_name'] or a['sector'] or '—'} "
                f"| {a['alert_type']} | {price_str} | {cp_str} | {vr_str} | "
                f"{ma20_str} | {bu_str} | {bl_str} | {a['detail']} |"
            )

    # 告警类型统计
    if alerts:
        type_counts = {}
        for a in alerts:
            for t in a['alert_type'].split(' / '):
                t = t.strip()
                type_counts[t] = type_counts.get(t, 0) + 1

        lines.append("")
        lines.append("## 📈 告警类型统计")
        lines.append("")
        for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {t}: **{cnt}** 只")

    lines.append("")
    lines.append("---")
    lines.append(f"*报告生成时间: {now}*")

    return '\n'.join(lines)


# ── 主入口 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='推荐股池实时监控告警',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/monitor_rec.py              # 最近7天
  python3 scripts/monitor_rec.py --days 3     # 最近3天
  python3 scripts/monitor_rec.py --days 14    # 最近14天
        """
    )
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=7,
        help='读取最近N天的推荐股票（默认: 7）'
    )
    parser.add_argument(
        '--csv',
        default=None,
        help=f'推荐池CSV路径（默认: {{PROJECT}}/data/recommendations.csv）'
    )

    args = parser.parse_args()
    days = args.days

    # CSV 路径
    if args.csv:
        csv_path = args.csv
    else:
        csv_path = os.path.join(PROJECT, 'data', 'recommendations.csv')

    if not os.path.exists(csv_path):
        print(f"❌ 推荐池文件不存在: {csv_path}")
        sys.exit(1)

    print(f"📖 读取推荐池: {csv_path}（最近 {days} 天）")

    # 加载推荐股票
    recs = load_recent_recs(csv_path, days)
    if not recs:
        print("⚠️  最近 {} 天内无推荐记录".format(days))
        print(format_markdown([], days))
        sys.exit(0)

    codes = [r['code'] for r in recs]
    print(f"📋  待监控股票数: {len(codes)} 只")
    print(f"   代码列表: {', '.join(codes[:10])}{'...' if len(codes) > 10 else ''}")

    # 初始化行情服务
    qs = QuoteService()
    print("🔍  开始检测告警...")

    alerts = check_alerts(qs, recs)
    alert_count = len([a for a in alerts if '⚠️' not in a['alert_type']])

    # 输出结果
    md = format_markdown(alerts, days)
    print("\n" + md)

    if alert_count > 0:
        print(f"\n✅ 检测完成，共触发 {alert_count} 条告警")
    else:
        print(f"\n✅ 检测完成，暂无触发告警（{len(recs)} 只股票正常）")


if __name__ == '__main__':
    main()