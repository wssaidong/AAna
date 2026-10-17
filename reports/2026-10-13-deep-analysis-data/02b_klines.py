#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2b: 用腾讯 K 线 (直连 web.ifzq.gtimg.cn) 替代东财 fallback"""
import sys, json, requests, time
from datetime import datetime

with open('/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/pool.json') as f:
    pool = json.load(f)
NORMAL = pool['filtered']


def get_tencent_kline_direct(code, count=120):
    """直连腾讯 K线 qfq (web.ifzq.gtimg.cn) — aana_afternoon_screen fallback 1 (东财) 挂掉"""
    mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={mkt}{code},day,,,{count},qfq'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    resp = requests.get(url, headers=headers, timeout=8)
    text = resp.text.strip()
    if '=' in text:
        text = text.split('=', 1)[1]
    data = json.loads(text)
    day_data = data.get('data', {}).get(f'{mkt}{code}', {}).get('qfqday', [])
    if not day_data:
        day_data = data.get('data', {}).get(f'{mkt}{code}', {}).get('day', [])
    result = []
    for item in day_data:
        if len(item) >= 6:
            try:
                result.append({
                    'date': item[0],
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'high': float(item[3]),
                    'low': float(item[4]),
                    'vol': float(item[5]) if len(item) > 5 else 0,
                })
            except (ValueError, TypeError):
                continue
    return result


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


print("拉 48 只 K 线 ...")
kline_cache = {}
fail_count = 0
for s in NORMAL:
    code = s['code']
    try:
        k = get_tencent_kline_direct(code, count=120)
        if k:
            kline_cache[code] = k
        else:
            fail_count += 1
    except Exception as e:
        print(f"  [warn] {code} {e}")
        fail_count += 1
    time.sleep(0.2)  # 限速
print(f"成功: {len(kline_cache)}/{len(NORMAL)}, 失败 {fail_count}")

# Save kline cache (use existing dir)
out_path = '/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/klines.json'
with open(out_path, 'w') as f:
    json.dump(kline_cache, f, ensure_ascii=False, default=str)
print(f"\nK线缓存: {out_path}")

# Sample print latest close for verification
for code in ['000651','600660','000993','600406','002714']:
    k = kline_cache.get(code, [])
    if k:
        print(f"  {code}: latest={k[-1]} (60 days back: {k[-60] if len(k)>=60 else k[0]})")
