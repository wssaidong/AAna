import sys, json
sys.path.insert(0, '/Users/cai/code/AAna/scripts')

def show(code, keys):
    import akshare as ak
    df = ak.stock_financial_abstract(symbol=code)
    cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
    print("=" * 72)
    print(code, "periods:", cols[:4])
    for k in keys:
        rows = df[df['指标'].astype(str).str.contains(k, na=False, regex=True)]
        for _, r in rows.head(3).iterrows():
            vals = []
            for c in cols[:4]:
                try:
                    v = float(r[c])
                    vals.append(f"{c}={v:.2f}")
                except Exception:
                    vals.append(f"{c}=NA")
            print(f"  [{r['指标']}] {' | '.join(vals)}")

for c in ["600096", "000700"]:
    show(c, ["资产负债率", "归属母公司股东的净利润", "扣除非经常性损益的净利润", "营业总收入", "经营活动产生的现金流量净额", "每股净资产"])

print("\n### 分红 (云天化高股息是核心多头逻辑)")
try:
    import data_sources as ds
    for c in ["600096", "000700"]:
        d = ds.dividend_history(c, page_size=4)
        print(c, d)
except Exception as e:
    print("div FAIL", e)

print("\n### 新闻/公告")
try:
    import data_sources as ds
    for c in ["600096", "000700"]:
        n = ds.eastmoney_global_news(page_size=6, code=c)
        print(f"--- {c} ---")
        for x in (n or [])[:6]:
            t = x.get('title') or x.get('Title') or str(x)[:120]
            print("   ", t[:110])
except Exception as e:
    print("news FAIL", e)
