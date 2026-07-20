"""AAna deep analysis of a single stock — side-by-side with Vibe-Trading later."""
import sys
import json
sys.path.insert(0, "/Users/cai/code/AAna")

from analysis_tools.data_fetcher import fetch_stock_data
from analysis_tools.financial_analyzer import FinancialAnalyzer

CODE = "000001.SZ"  # 平安银行
NAME = "平安银行"

print("=" * 70)
print(f"AAna 深度分析 - {CODE} {NAME}")
print("=" * 70)

data = fetch_stock_data(CODE, data_type="all", years=3, use_cache=False)
print(f"数据获取完成: {len(data)} 个字段, fetch_time={data.get('fetch_time','?')}")
print()

analyzer = FinancialAnalyzer(data)
analyzer.stock_data = data

# 跑全套分析
results = {}
for method_name in [
    "analyze_profitability",
    "analyze_solvency",
    "analyze_operation",
    "analyze_growth",
    "analyze_dupont",
    "detect_anomalies",
    "generate_summary",
]:
    try:
        method = getattr(analyzer, method_name)
        results[method_name] = method()
    except Exception as e:
        results[method_name] = {"error": f"{type(e).__name__}: {e}"}

# 输出
print(json.dumps(results, ensure_ascii=False, indent=2, default=str)[:6000])
print("\n" + "=" * 70)
print("AAna 综合评分:")
print(json.dumps(results.get("generate_summary", {}), ensure_ascii=False, indent=2, default=str))