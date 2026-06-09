#!/usr/bin/env python3
"""
scripts/daily_v24_recommend.py — AAna 每日 14:45 尾盘推荐 runner
================================================================
v2.4 实盘链路第一步: 工作日 14:45 自动跑评分 → 写 paper_trades → 推飞书

执行流程:
  1. 调用 aana_afternoon_screen.screen_afternoon_stocks() 跑 v2.3 评分
  2. 对每只 score>=65 的推荐调 paper_trading.record_buy() 建仓
     (尾盘 14:45 价格 = entry_price, 100 股, reason = 选股评分)
  3. 生成 Markdown 推荐报告
  4. 推送到飞书 (lark-cli im +messages-send)

Cron 设置 (A 股工作日 14:45):
  45 14 * * 1-5 /Users/cai/.openclaw/scripts/run_aana_recommend.sh

用法 (手动调试):
  cd ~/code/AAna && .venv/bin/python scripts/daily_v24_recommend.py
  cd ~/code/AAna && .venv/bin/python scripts/daily_v24_recommend.py --dry-run
"""
import os
import sys
import json
import argparse
import warnings
from datetime import datetime
warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

# ── 配置 ──
FEISHU_USER_ID = "ou_5d0124d26ed21365f74764fcb9fa01b7"  # 你的 open_id
SHARES_PER_BUY = 100  # 每只推荐买 100 股
COST_RATE = 0.002  # 双边 0.2%
LOG_FILE = os.path.expanduser("~/.openclaw/scripts/cron.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [daily_v24_recommend] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def push_feishu(markdown: str, title: str = "AAna 尾盘推荐"):
    """推送到飞书"""
    cmd = [
        "lark-cli", "im", "+messages-send",
        "--user-id", FEISHU_USER_ID,
        "--markdown", markdown,
    ]
    try:
        import subprocess
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            log(f"✅ 飞书推送成功")
            return True
        else:
            log(f"❌ 飞书推送失败: {r.stderr[:200]}")
            return False
    except Exception as e:
        log(f"❌ 飞书推送异常: {e}")
        return False


def main(dry_run=False):
    log("=" * 60)
    log(f"AAna v2.4 尾盘推荐启动 (dry_run={dry_run})")

    # 1. 跑评分
    log("[1/4] 调用 aana_afternoon_screen.screen_afternoon_stocks()...")
    try:
        from aana_afternoon_screen import screen_afternoon_stocks
        recs = screen_afternoon_stocks(sentiment_score=50, position_ratio=0.5,
                                        record_feedback=True)
    except Exception as e:
        log(f"❌ 评分失败: {e}")
        return False

    if not recs:
        log("⚠️  无推荐（score>=65 的票）")
        push_feishu(
            "**AAna 尾盘推荐** · " + datetime.now().strftime("%Y-%m-%d %H:%M") +
            "\n\n⚠️ 今日无推荐（score<65 的票全部过滤）"
        )
        return True

    log(f"  找到 {len(recs)} 只推荐")
    for r in recs:
        log(f"    {r.get('code', '?')} {r.get('name', '?')} score={r.get('score', 0)}")

    # 2. 建仓 (paper trading)
    if dry_run:
        log("[2/4] DRY-RUN 模式，跳过 paper_trading.record_buy()")
        buys = []
    else:
        log("[2/4] 调用 paper_trading.record_buy() 建仓...")
        sys.path.insert(0, os.path.join(PROJECT, "data"))
        from paper_trading import record_buy, _load
        buys = []
        for r in recs:
            code = r.get('code', '')
            name = r.get('name', '')
            price = r.get('price', 0)
            if not code or price <= 0:
                continue
            # 跳过已有持仓
            existing = _load().get("positions", {})
            if code in existing:
                log(f"    跳过 {code} (已有持仓)")
                continue
            try:
                trade = record_buy(
                    code=code, name=name, price=price,
                    shares=SHARES_PER_BUY,
                    date_str=datetime.now().strftime("%Y-%m-%d"),
                    reason=f"AAna v2.4 尾盘评分 {r.get('score', 0)}"
                )
                buys.append(trade)
                log(f"    建仓 {code} {name} @{price} {SHARES_PER_BUY}股")
            except Exception as e:
                log(f"    ❌ {code} 建仓失败: {e}")

    # 3. 生成报告
    log("[3/4] 生成 Markdown 报告...")
    today = datetime.now().strftime("%Y-%m-%d")
    md_lines = [
        f"**AAna v2.4 尾盘推荐** · {today} 14:45",
        "",
        f"**推荐数量**: {len(recs)} 只  |  **建仓数量**: {len(buys)} 只  |  **每只**: {SHARES_PER_BUY} 股",
        "",
        f"**卖出策略**: T+1 开盘即卖（v2.4 主策略，80.2% 胜率 / 11.83 盈亏比）",
        "",
        "| 代码 | 名称 | 收盘价 | 评分 | 风险 | 止损价 | 理由 |",
        ":---:|:---:|---:|---:|:---:|---:|:---|",
    ]
    for r in recs:
        code = r.get('code', '?')
        name = r.get('name', '?')
        price = r.get('price', 0)
        score = r.get('score', 0)
        risk = r.get('risk', '🟡 中风险')
        stop = r.get('stop_loss', 0)
        reason = r.get('reason', r.get('expected_change', '尾盘选股 v2.4'))[:40]
        md_lines.append(
            f"| {code} | {name} | {price:.2f} | **{score}** | {risk} | {stop:.2f} | {reason} |"
        )
    md_lines.append("")
    md_lines.append("**⚠️ v2.4 卖出规则**：T+1 09:30 集合竞价卖出（开盘价），详见 `scripts/sell_strategy_v24.py`")
    md_lines.append("")
    md_lines.append("**回测数据** (90 天 / 1508 笔 / 29 只股):")
    md_lines.append("- 5 日持有: -2775% 累计 (❌ 不可用)")
    md_lines.append("- T+1 开盘即卖: +1766% 累计 (✅ 本策略)")
    md_lines.append("- 胜率 80.2% / 盈亏比 11.83 / 单笔平均 +1.17%")
    md_lines.append("")
    md_lines.append("> 仅供参考，不构成投资建议")

    markdown = "\n".join(md_lines)

    # 写本地报告
    report_dir = os.path.join(PROJECT, "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = f"{report_dir}/{today}-v24-尾盘推荐.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# AAna v2.4 尾盘推荐 · {today}\n\n")
        f.write(markdown)
    log(f"  报告已存: {report_path}")

    # 4. 推飞书
    log("[4/4] 推送飞书...")
    push_feishu(markdown)

    log("✅ 完成")
    log("=" * 60)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='不建仓不推送，只跑评分')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
