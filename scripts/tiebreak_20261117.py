import sys, json, re
sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import requests

def bs(code):
    import akshare as ak
    df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
    print("=" * 70)
    print(code, "资产负债表 cols:", list(df.columns)[:3])
    def row(name):
        r = df[df['报表名称'].astype(str).str.contains(name, na=False)]
        return r.iloc[0] if not r.empty else None
    names = ["负债合计", "资产总计", "所有者权益\\(或股东权益\\)合计", "归属于母公司股东权益", "货币资金", "存货", "应收账款"]
    for n in names:
        r = row(n)
        if r is None:
            print(f"  {n}: 未找到"); continue
        # 取最新一列 (日期列)
        cols = [c for c in df.columns if c not in ('报表名称', '报表日期', '货币单位', '报表类型')]
        vals = []
        for c in cols[:2]:
            try: vals.append(f"{c}={float(r[c])/1e8:.2f}亿")
            except Exception: vals.append(f"{c}=NA")
        print(f"  {n}: {' | '.join(vals)}")
    # 负债率
    ta = row("资产总计"); tl = row("负债合计")
    try:
        t = float(tl.iloc[0][cols[0]]); a = float(ta.iloc[0][cols[0]])
        print(f"  → 资产负债率(最新期): {t/a*100:.2f}%")
    except Exception as e:
        print("  → 负债率失败", e)

def pledge(code):
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_CSDC_MARKET_STA&columns=ALL&filter="
           f'(SECURITY_CODE="{code}")&pageNumber=1&pageSize=5&sortColumns=TRADE_DATE&sortTypes=-1')
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()
        res = d.get("result")
        if not res: return "datacenter result=None"
        out = []
        for it in res.get("data", [])[:3]:
            out.append(f"{it.get('TRADE_DATE')} 质押比例 {it.get('TOTAL_SHARES_PLEDGE_RATIO')}%")
        return " | ".join(out)
    except Exception as e:
        return f"ERR {e}"

def guarantee(code):
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_CSDC_LIST&columns=ALL&filter="
           + '(SECURITY_CODE="%s")&pageNumber=1&pageSize=3' % code)
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()
        res = d.get("result")
        if not res: return "result=None"
        return json.dumps(res.get("data", [])[:2], ensure_ascii=False)[:300]
    except Exception as e:
        return "ERR %s" % e

for c in ["600096", "000700", "002432"]:
    try: bs(c)
    except Exception as e: print(c, "BS FAIL", e)
    print("  质押:", pledge(c))
