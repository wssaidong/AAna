"""
AAna 推荐追踪系统 — 记录、评估、修正推荐决策
每天盘前生成推荐记录 → 复盘对比实际结果 → 输出修正建议
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = os.path.expanduser("~/code/AAna")
TRACKER_DIR = os.path.join(PROJECT_DIR, "state", "recommendations")

def _ensure_tracker_dir():
    os.makedirs(TRACKER_DIR, exist_ok=True)

def _record_path(date_str):
    _ensure_tracker_dir()
    return os.path.join(TRACKER_DIR, f"{date_str}.json")

def _stats_path():
    _ensure_tracker_dir()
    return os.path.join(TRACKER_DIR, "stock_stats.json")

# ──────────────────────────────────────────────
# 盘前：保存当日推荐记录
# ──────────────────────────────────────────────

def save_recommendation(date_str, recommended_stocks, market_prediction, focus_sectors, sentiment):
    """
    记录当日推荐
    
    recommended_stocks: [
        {"code": "300308", "name": "中际旭创", "sector": "ai_chip",
         "sector_name": "AI算力/芯片", "reason": "光模块龙头",
         "expected_change": "+2~5%", "expected_high": 5.0, "expected_low": 2.0},
        ...
    ]
    """
    record = {
        "date": date_str,
        "market_prediction": market_prediction,
        "sentiment": sentiment,
        "focus_sectors": focus_sectors,
        "recommended_stocks": recommended_stocks,
        "created_at": datetime.now().isoformat(),
    }
    
    with open(_record_path(date_str), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    
    return record

def load_recommendation(date_str):
    """读取指定日期的推荐记录"""
    path = _record_path(date_str)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ──────────────────────────────────────────────
# 复盘：评估推荐效果
# ──────────────────────────────────────────────

def evaluate_recommendations(date_str, actual_prices):
    """
    对比推荐与实际表现
    
    actual_prices: {code: {"close": float, "change_pct": float, "name": str}, ...}
    
    返回评估报告 dict
    """
    record = load_recommendation(date_str)
    if not record:
        return {"error": f"找不到 {date_str} 的推荐记录"}

    recommended = record["recommended_stocks"]
    predictions = record.get("market_prediction", "未知")
    
    results = []
    for stock in recommended:
        code = stock["code"]
        actual = actual_prices.get(code, {})
        
        if not actual or actual.get("close", 0) == 0:
            results.append({
                "code": code,
                "name": stock["name"],
                "sector": stock["sector"],
                "sector_name": stock["sector_name"],
                "reason": stock["reason"],
                "expected_high": stock.get("expected_high", 0),
                "expected_low": stock.get("expected_low", 0),
                "expected_change": stock.get("expected_change", "?"),
                "actual_close": None,
                "actual_change": None,
                "hit": False,
                "assessment": "无数据",
            })
            continue
        
        actual_change = actual.get("change_pct", 0)
        expected_high = stock.get("expected_high", 0)
        expected_low = stock.get("expected_low", 0)
        
        # 判断是否命中预期
        if expected_high > 0:
            hit = expected_low <= actual_change <= expected_high
        elif expected_high < 0:
            hit = expected_high <= actual_change <= expected_low
        else:
            hit = abs(actual_change) < 1  # 预期震荡
        
        # 评估等级
        diff = actual_change - (expected_high + expected_low) / 2
        if hit:
            assessment = "✅ 符合预期"
        elif abs(diff) <= 2:
            assessment = "⚠️ 小幅偏差"
        elif diff > 2:
            assessment = "🔥 超预期"
        else:
            assessment = "❌ 偏离预期"
        
        results.append({
            "code": code,
            "name": stock["name"],
            "sector": stock["sector"],
            "sector_name": stock["sector_name"],
            "reason": stock["reason"],
            "expected_high": expected_high,
            "expected_low": expected_low,
            "expected_change": stock.get("expected_change", "?"),
            "actual_close": actual.get("close", 0),
            "actual_change": actual_change,
            "hit": hit,
            "assessment": assessment,
        })
    
    # 统计
    total = len([r for r in results if r["actual_change"] is not None])
    hits = len([r for r in results if r["hit"]])
    beat_expected = len([r for r in results if "超预期" in r["assessment"]])
    miss_expected = len([r for r in results if "偏离预期" in r["assessment"]])
    
    hit_rate = hits / total * 100 if total > 0 else 0
    
    # 板块表现汇总
    sector_results = {}
    for r in results:
        if r["actual_change"] is None:
            continue
        sect = r["sector"]
        if sect not in sector_results:
            sector_results[sect] = {"name": r["sector_name"], "changes": [], "hits": 0, "total": 0}
        sector_results[sect]["changes"].append(r["actual_change"])
        sector_results[sect]["total"] += 1
        if r["hit"]:
            sector_results[sect]["hits"] += 1
    
    sector_eval = []
    for sect, data in sector_results.items():
        avg = sum(data["changes"]) / len(data["changes"])
        sr = data["hits"] / data["total"] * 100 if data["total"] > 0 else 0
        sector_eval.append({
            "sector": sect,
            "name": data["name"],
            "avg_change": avg,
            "hit_rate": sr,
            "assessment": "✅ 准确" if sr >= 60 else ("⚠️ 一般" if sr >= 40 else "❌ 偏差大"),
        })
    sector_eval.sort(key=lambda x: x["avg_change"], reverse=True)
    
    return {
        "date": date_str,
        "market_prediction": predictions,
        "results": results,
        "stats": {
            "total": total,
            "hits": hits,
            "beat_expected": beat_expected,
            "miss_expected": miss_expected,
            "hit_rate": hit_rate,
        },
        "sector_eval": sector_eval,
    }

# ──────────────────────────────────────────────
# 长期追踪：个股/板块命中率统计
# ──────────────────────────────────────────────

def update_stock_stats(date_str, eval_result):
    """更新个股/板块历史命中率（最近N天）"""
    stats_path = _stats_path()
    
    if os.path.exists(stats_path):
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
    else:
        stats = {"stocks": {}, "sectors": {}, "updated": []}
    
    # 保留最近30天记录
    stats["updated"] = [d for d in stats.get("updated", []) if d >= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")]
    
    if date_str not in stats["updated"]:
        stats["updated"].append(date_str)
    
    # 更新个股
    for r in eval_result.get("results", []):
        code = r["code"]
        if code not in stats["stocks"]:
            stats["stocks"][code] = {"name": r["name"], "records": [], "consecutive_bad": 0}
        
        rec = stats["stocks"][code]["records"]
        rec.append({"date": date_str, "change": r["actual_change"], "hit": r["hit"], "sector": r["sector"]})
        # 只保留最近30天
        rec[:] = rec[-30:]
        
        # 计算连续不良
        recent = rec[-3:]
        if len(recent) >= 3 and all(not x["hit"] and x["change"] < 0 for x in recent):
            stats["stocks"][code]["consecutive_bad"] = 3
        elif len(recent) >= 2 and all(not x["hit"] and x["change"] < 0 for x in recent):
            stats["stocks"][code]["consecutive_bad"] = 2
        else:
            stats["stocks"][code]["consecutive_bad"] = 0
    
    # 更新板块
    for sev in eval_result.get("sector_eval", []):
        sect = sev["sector"]
        if sect not in stats["sectors"]:
            stats["sectors"][sect] = {"name": sev["name"], "records": []}
        
        rec = stats["sectors"][sect]["records"]
        rec.append({"date": date_str, "avg_change": sev["avg_change"], "hit_rate": sev["hit_rate"]})
        rec[:] = rec[-30:]
    
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    return stats

def load_stock_stats():
    """加载个股/板块统计"""
    stats_path = _stats_path()
    if not os.path.exists(stats_path):
        return None
    with open(stats_path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_corrections(date_str, eval_result):
    """根据评估结果生成修正建议"""
    stats = load_stock_stats()
    corrections = []
    
    # 1. 个股连续失败检测
    if stats:
        for code, sdata in stats.get("stocks", {}).items():
            cons_bad = sdata.get("consecutive_bad", 0)
            if cons_bad >= 3:
                corrections.append({
                    "type": "🚨 强制关注",
                    "target": f"{sdata['name']}({code})",
                    "issue": f"连续{cons_bad}天推荐未命中且下跌",
                    "action": "建议降低推荐权重或移出股票池",
                })
            elif cons_bad >= 2:
                corrections.append({
                    "type": "⚠️ 警告",
                    "target": f"{sdata['name']}({code})",
                    "issue": f"连续{cons_bad}天表现不佳",
                    "action": "观察是否继续走弱，及时止损",
                })
    
    # 2. 板块命中率分析
    for sev in eval_result.get("sector_eval", []):
        if sev["hit_rate"] < 30 and sev["avg_change"] < -1:
            corrections.append({
                "type": "🔄 板块轮动",
                "target": sev["name"],
                "issue": f"推荐命中率{sev['hit_rate']:.0f}%，平均涨幅{sev['avg_change']:+.2f}%",
                "action": "该板块短期承压，降低推荐优先级",
            })
        elif sev["avg_change"] > 3 and sev["hit_rate"] >= 70:
            corrections.append({
                "type": "➕ 强势确认",
                "target": sev["name"],
                "issue": f"命中率{sev['hit_rate']:.0f}%，平均涨幅{sev['avg_change']:+.2f}%",
                "action": "该板块短期强势，可维持或提升推荐仓位",
            })
    
    # 3. 超预期个股
    for r in eval_result.get("results", []):
        if "超预期" in r.get("assessment", "") and r.get("actual_change", 0) > 5:
            corrections.append({
                "type": "⭐ 重点关注",
                "target": f"{r['name']}({r['code']})",
                "issue": f"今日涨幅{r['actual_change']:+.2f}%，超预期",
                "action": "纳入重点观察，若持续强势建议加入股票池",
            })
    
    # 4. 明日推荐调整
    good_sectors = [s for s in eval_result.get("sector_eval", []) if s["avg_change"] > 1 and s["hit_rate"] >= 50]
    bad_sectors = [s for s in eval_result.get("sector_eval", []) if s["avg_change"] < -1 or s["hit_rate"] < 30]
    
    return {
        "corrections": corrections,
        "good_sectors": good_sectors,
        "bad_sectors": bad_sectors,
    }

if __name__ == "__main__":
    # 简单测试
    print("推荐追踪系统已就绪")
    print(f"记录目录: {TRACKER_DIR}")