"""Step 1: 拉 sina 涨幅榜 + 主板过滤"""
import sys, json, os
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
from datetime import datetime
try:
    from dynamic_stocks import get_stock_pool_split
    print("开始拉 sina 涨幅榜 + 8 维过滤...")
    t0 = datetime.now()
    normal_pool, risk_pool = get_stock_pool_split()
    print(f"用时 {(datetime.now()-t0).total_seconds():.1f}s")
    print(f"normal_pool (推荐): {len(normal_pool)} 只")
    print(f"risk_pool (风险): {len(risk_pool)} 只")
    def is_mainboard(code):
        if code.startswith(('300','301','688','8','43','83','87','92')):
            return False
        return code.startswith(('600','601','603','605','000','002','003'))
    NORMAL = []
    for s in normal_pool:
        if is_mainboard(s['code']) and 10 <= s.get('price', 0) <= 80 and not ('ST' in s.get('name','') or '*' in s.get('name','') or 'N' in s.get('code','')):
            NORMAL.append(s)
    print(f"过滤后主板候选池: {len(NORMAL)} 只")
    for i, s in enumerate(NORMAL[:20], 1):
        print(f"  {i}. {s['code']} {s['name']} ¥{s.get('price',0):.2f} +{s.get('changepercent',0):.2f}%")
    out_path = '/Users/cai/code/AAna/reports/2026-10-13-deep-analysis-data/pool.json'
    with open(out_path, 'w') as f:
        json.dump({'normal': normal_pool, 'risk': risk_pool, 'filtered': NORMAL,
                   'ts': datetime.now().isoformat()}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n保存到 {out_path}")
except Exception as e:
    import traceback
    print(f"FAIL: {e}")
    traceback.print_exc()
