#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 3: 计算 MA5/MA20/RSI/60日%/PE + 6 维评分"""
import sys, json
from datetime import datetime

with open('/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/pool.json') as f:
    pool = json.load(f)
with open('/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/klines.json') as f:
    KLINES = json.load(f)
NORMAL = pool['filtered']

# 已知 PE (从 tencent qt.gtimg.cn quote batch 取得的快照 — 见 02_metrics.py 之前的执行)
# 重新以单只 qt.gtimg.cn 接口获取实时 PE / 量比
import requests
def get_one_quote_full(code):
    mkt = 'sh' if code.startswith(('6','9')) else 'sz'
    url = f'https://qt.gtimg.cn/q={mkt}{code}'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        text = r.text.strip()
        # v_sh600660="1~福耀玻璃~600660~..."
        key = 'v_' + mkt + code
        if text.startswith('v_'):
            end = text.find('="')
            if end > 0:
                content = text[end+2:-1] if text.endswith('"') else text[end+2:]
                fields = content.split('~')
                if len(fields) >= 50:
                    return {
                        'name': fields[1],
                        'price': float(fields[3]),
                        'change_pct': float(fields[32]),
                        'amount_wan': float(fields[37]) if fields[37] else 0,
                        'pe_ttm': float(fields[39]) if fields[39] and fields[39] != '' else None,
                        'vol_ratio': float(fields[49]) if fields[49] else None,
                    }
    except Exception as e:
        return None
    return None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(d) if d > 0 else losses.append(-d)
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def metrics(code):
    k = KLINES.get(code, [])
    if len(k) < 21:
        return None
    closes = [x['close'] for x in k]
    ma5 = round(sum(closes[-5:]) / 5, 2)
    ma20 = round(sum(closes[-20:]) / 20, 2)
    rsi = calc_rsi(closes, 14)
    chg60 = round((closes[-1] - closes[-60]) / closes[-60] * 100, 1) if len(closes) >= 60 else None
    vols = [x['vol'] for x in k[-20:]]
    vol_avg_5 = sum(vols[-5:]) / 5
    vol_avg_20 = sum(vols) / 20
    vr_proxy = round(vol_avg_5 / vol_avg_20, 2) if vol_avg_20 else 1.0
    return {'ma5': ma5, 'ma20': ma20, 'rsi': rsi, 'chg_60d': chg60, 'vr_proxy': vr_proxy}


print("取实时 quote (PE / vol_ratio) ...")
QUOTES = {}
for s in NORMAL:
    q = get_one_quote_full(s['code'])
    if q:
        QUOTES[s['code']] = q

print(f"quote: {len(QUOTES)}/{len(NORMAL)}")

# Compose
enriched = []
for s in NORMAL:
    code = s['code']
    m = metrics(code)
    if not m:
        continue
    q = QUOTES.get(code, {})
    cur_price = s['price']   # 用 sina 价 (更实时)
    pe_ttm = q.get('pe_ttm')
    vr_real = q.get('vol_ratio')
    enriched.append({
        'code': code,
        'name': s['name'],
        'price': cur_price,
        'change_pct': s['change_pct'],
        'amount_yi': round(s['amount'] / 1e8, 1),
        'pe_ttm': pe_ttm,
        'vol_ratio': vr_real,
        'mcap_yi': q.get('amount_wan', 0) and round(q.get('amount_wan') * 1e4 / 1e8, 0),
        **m,
        'price_vs_ma5_pct': round((cur_price - m['ma5']) / m['ma5'] * 100, 2),
        'price_vs_ma20_pct': round((cur_price - m['ma20']) / m['ma20'] * 100, 2),
    })

with open('/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/enriched.json', 'w') as f:
    json.dump({'items': enriched, 'ts': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
print(f"\n保存 enriched {len(enriched)}")
for e in enriched[:6]:
    print(json.dumps(e, ensure_ascii=False, default=str, indent=2))
