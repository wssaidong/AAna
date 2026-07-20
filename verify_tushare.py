"""End-to-end verification of AAna Tushare integration."""
import os
from data.fundamentals import FundamentalService, get_fundamental_score

print("=" * 60)
print("AAna Fundamentals - Tushare Token Verification")
print("=" * 60)
token = os.getenv("TUSHARE_TOKEN")
print(f"TUSHARE_TOKEN env:  {'set (' + str(len(token)) + ' chars)' if token else 'NOT SET'}")
print()

fs = FundamentalService()
print(f"fs.token loaded: {'yes (' + str(len(fs.token)) + ' chars)' if fs.token else 'NO'}")
print(f"fs._pro init:    {'yes' if fs._pro else 'NO'}")
print()

test_codes = [
    ("000001.SZ", "平安银行 (深主板)"),
    ("600519.SH", "贵州茅台 (沪主板)"),
    ("000858.SZ", "五粮液"),
    ("300750.SZ", "宁德时代 (创业板)"),
    ("688981.SH", "中芯国际 (科创板)"),
]

print(f"{'代码':<12} {'名称':<20} {'PE/PB/ROE':<30} {'评分':>8}")
print("-" * 75)
for code, name in test_codes:
    pe_pb = fs.get_pe_pb(code)
    score = get_fundamental_score(code)
    if pe_pb:
        pe = pe_pb.get("pe") or 0
        pb = pe_pb.get("pb") or 0
        roe = pe_pb.get("roe") or 0
        pe_pb_str = f"PE={pe:.1f} PB={pb:.1f} ROE={roe:.1f}%"
    else:
        pe_pb_str = "N/A"
    print(f"{code:<12} {name:<20} {pe_pb_str:<30} {str(score):>8}")