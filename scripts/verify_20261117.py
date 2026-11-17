import sys, json
sys.path.insert(0, '/Users/cai/code/AAna/scripts')

def abstract_rows(code, keys):
    import akshare as ak
    df = ak.stock_financial_abstract(symbol=code)
    cols = [c for c in df.columns if c not in ('选项', '指标', '指标说明')]
    latest = cols[0]
    print("=" * 70)
    print(code, "latest period:", latest)
    for k in keys:
        rows = df[df['指标'].astype(str).str.contains(k, na=False, regex=True)]
        for _, r in rows.head(4).iterrows():
            vals = []
            for c in cols[:4]:
                try: vals.append(f"{c}={float(r[c])/1e8:.3f}亿")
                except Exception: vals.append(f"{c}=NA")
            print(f"  [{r['指标']}] {' | '.join(vals)}")

for c in ["600096", "000700"]:
    try:
        abstract_rows(c, ["资产负债率", "净资产收益率", "归属母公司股东的净利润", "经营活动产生的现金流量净额"])
    except Exception as e:
        print(c, "FAIL", e)

# 002432 九安医疗 收入 vs 利润 真实性核验
try:
    abstract_rows("002432", ["营业总收入", "归属母公司股东的净利润", "扣除非经常性损益的净利润", "投资收益", "公允价值变动"])
except Exception as e:
    print("002432 FAIL", e)
