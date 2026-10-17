#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2: K线 + RSI + MA5/MA20 + 量比 + PE — 6 维评分"""
import sys, json, os, requests
from datetime import datetime
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import data_sources as ds
from aana_afternoon_screen import get_tencent_kline

# Reload pool
with open('/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/pool.json') as f:
    pool = json.load(f)
NORMAL = pool['filtered']

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(-d)
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calc_metrics_from_kline(klines, current_price):
    if not klines or len(klines) < 20:
        return None
    closes = [k['close'] for k in klines]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    rsi = calc_rsi(closes, 14)
    chg_60d = None
    if len(closes) >= 60:
        chg_60d = (closes[-1] - closes[-60]) / closes[-60] * 100
    # 量比: 近 5 日均量 / 20 日均量 (proxied)
    vols = [k['vol'] for k in klines[-20:]]
    if len(vols) >= 20:
        vol_avg_20 = sum(vols) / 20
        vol_avg_5 = sum(vols[-5:]) / 5
        vol_ratio_proxy = vol_avg_5 / vol_avg_20 if vol_avg_20 else 1.0
    else:
        vol_ratio_proxy = 1.0
    return {
        'ma5': round(ma5, 2),
        'ma20': round(ma20, 2),
        'rsi': round(rsi, 1) if rsi else None,
        'chg_60d': round(chg_60d, 1) if chg_60d is not None else None,
        'vol_ratio_5d_20d': round(vol_ratio_proxy, 2),
        'price_vs_ma5_pct': round((current_price - ma5) / ma5 * 100, 2),
        'price_vs_ma20_pct': round((current_price - ma20) / ma20 * 100, 2),
    }


# Get tencent quote for PE/PB
print("拉 tencent quote (PE/PB/量比) ...")
codes = [s['code'] for s in NORMAL]
quotes = ds.tencent_quote(codes)
print(f"quote 返回 {len(quotes)} 条")

# Get kline for each
print("拉 kline (120 天) ...")
kline_data = {}
for s in NORMAL[:50]:
    code = s['code']
    try:
        k = get_tencent_kline(code, count=120)
        kline_data[code] = k
    except Exception as e:
        print(f"  [warn] {code} kline fail: {e}")
        kline_data[code] = []
print(f"kline 成功: {sum(1 for v in kline_data.values() if v)}/{len(kline_data)}")

# Get industry
print("拉行业归属 ...")
industries = ds.industry_for_codes(codes)

# Compose
enriched = []
for s in NORMAL:
    code = s['code']
    q = quotes.get(code, {})
    k = kline_data.get(code, [])
    cur_price = s['price']
    metrics = calc_metrics_from_kline(k, cur_price)
    if not metrics:
        continue
    enriched.append({
        'code': code,
        'name': s['name'],
        'price': cur_price,
        'change_pct': s['change_pct'],
        'amount_yi': round(s['amount'] / 1e8, 1),
        'pe_ttm': q.get('pe_ttm'),
        'pe_static': q.get('pe_static'),
        'pb': q.get('pb'),
        'mcap_yi': q.get('mcap_yi'),
        'industry': industries.get(code, 'unknown'),
        **metrics,
    })

print(f"\n全量字段样本: enriched {len(enriched)} 只")
for e in enriched[:3]:
    print(json.dumps(e, ensure_ascii=False, default=str, indent=2))

out_path = '/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/enriched.json'
with open(out_path, 'w') as f:
    json.dump({'items': enriched, 'ts': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2, default=str)
print(f"\n保存到 {out_path}")
