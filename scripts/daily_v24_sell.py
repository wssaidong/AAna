#!/usr/bin/env python3
"""
scripts/daily_v24_sell.py — AAna 每日 09:30 T+1 开盘卖出 runner
================================================================
v2.4 实盘链路第二步: A 股工作日 09:30 (集合竞价完成后) 自动取开盘价 → 触发 v2.4 卖出

执行流程:
  1. 读 data/paper_trades.json 获取所有持仓
  2. 对每只持仓用腾讯实时行情接口取 T+1 开盘价 (09:30 集合竞价后立即可用)
  3. 调 paper_trading.auto_sell_v24() 触发 v2.4 卖出决策
  4. 生成 Markdown 卖出报告
  5. 推送到飞书

⚠️ 重要：09:30 集合竞价 09:25 出价, 09:30 撮合后才有 "open" 字段
   所以这个 cron 必须在 09:30 之后 (建议 09:32) 跑

Cron 设置 (A 股工作日 09:32):
  32 9 * * 1-5 /Users/cai/.openclaw/scripts/run_aana_sell.sh

用法 (手动调试):
  cd ~/code/AAna && .venv/bin/python scripts/daily_v24_sell.py
  cd ~/code/AAna && .venv/bin/python scripts/daily_v24_sell.py --dry-run
"""
import os
import sys
import json
import time
import argparse
import warnings
from datetime import datetime, timedelta
import urllib3
urllib3.disable_warnings()
import requests
warnings.filterwarnings('ignore')

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
sys.path.insert(0, os.path.join(PROJECT, "data"))

# ── 配置 ──
FEISHU_USER_ID = "ou_5d0124d26ed21365f74764fcb9fa01b7"
COST_RATE = 0.002
LOG_FILE = os.path.expanduser("~/.openclaw/scripts/cron.log")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [daily_v24_sell] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def push_feishu(markdown: str):
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


def fetch_t1_open(code: str, max_retry: int = 3) -> dict:
    """
    用腾讯 K 线接口取 T+1 当日 K 线 (含 open/high/low/close)
    ⚠️ 09:30 之前调用会拿不到当日数据
    """
    mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayhfq&param={mkt}{code},day,,,3,qfq"
    for attempt in range(max_retry):
        try:
            r = requests.get(url, timeout=10, verify=False)
            text = r.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1]
            data = json.loads(text)
            day = data.get('data', {}).get(f'{mkt}{code}', {}).get('qfqday', [])
            if not day:
                day = data.get('data', {}).get(f'{mkt}{code}', {}).get('day', [])
            if not day:
                return {}
            # 取最后一日
            last = day[-1]
            return {
                'date': last[0],
                'open': float(last[1]),
                'high': float(last[2]),
                'low': float(last[3]),
                'close': float(last[4]),
            }
        except Exception as e:
            if attempt == max_retry - 1:
                log(f"  ❌ {code} 取行情失败: {e}")
                return {}
            time.sleep(1)
    return {}


def main(dry_run=False):
    log("=" * 60)
    log(f"AAna v2.4 T+1 开盘卖出启动 (dry_run={dry_run})")

    # 1. 读持仓
    log("[1/4] 读 paper_trades.json 持仓...")
    from paper_trading import _load, auto_sell_v24
    d = _load()
    positions = d.get("positions", {})
    if not positions:
        log("  ⚠️ 无持仓，跳过")
        return True
    log(f"  持仓 {len(positions)} 只: {', '.join(positions.keys())}")

    # 2. 取 T+1 行情 + 触发卖出
    log("[2/4] 取 T+1 行情 + 调用 auto_sell_v24()...")
    # 关键逻辑: 09:32 跑 = 卖的是"昨天 14:45 建仓"的票
    # 实盘 today = 实际日期, 但持仓 entry_date = 今天-1 (昨天)
    # dry-run 时用 today = entry_date + 1 来正确模拟
    today = datetime.now().strftime("%Y-%m-%d")
    if dry_run:
        # dry-run 模式: 找到最早的 entry_date, 用 entry+1 作为 today
        earliest_entry = min(pos["entry_date"] for pos in positions.values())
        from datetime import datetime as _dt, timedelta
        simulated_today = (_dt.strptime(earliest_entry, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        log(f"  DRY-RUN: 模拟次日 = {simulated_today} (最早 entry={earliest_entry})")
        today = simulated_today
    quotes_ohlc = {}
    for code in positions.keys():
        ohlc = fetch_t1_open(code)
        if ohlc:
            quotes_ohlc[code] = ohlc
            log(f"  {code} T+1: O={ohlc['open']} H={ohlc['high']} L={ohlc['low']} C={ohlc['close']}")
        time.sleep(0.3)

    if not quotes_ohlc:
        log("  ❌ 没有任何 T+1 行情（可能 09:30 之前）")
        push_feishu(
            "**AAna v2.4 T+1 卖出** · " + datetime.now().strftime("%Y-%m-%d %H:%M") +
            "\n\n❌ 拉不到 T+1 行情（请在 09:30 集合竞价后跑）"
        )
        return False

    if dry_run:
        log("  DRY-RUN 模式，不触发实际卖出")
        # 用 sell_strategy_v24 模拟一下决策
        from sell_strategy_v24 import make_sell_decision
        decisions = []
        for code, pos in positions.items():
            ohlc = quotes_ohlc.get(code, {})
            if not ohlc:
                continue
            d_decision = make_sell_decision(
                code=code, name=pos["name"],
                entry_date=pos["entry_date"], entry_price=pos["entry_price"],
                shares=pos["shares"], today=today,
                open_price=ohlc['open'], high_price=ohlc['high'],
                low_price=ohlc['low'], close_price=ohlc['close'],
                cost_rate=COST_RATE,
            )
            decisions.append((code, pos, d_decision))
            log(f"  {code} T+1 决策: {d_decision.action} {d_decision.reason} {d_decision.pnl_pct:+.2f}%")
    else:
        log("  调用 paper_trading.auto_sell_v24()...")
        triggered = auto_sell_v24(today, quotes_ohlc, cost_rate=COST_RATE)
        log(f"  触发卖出 {len(triggered)} 笔")

    # 3. 生成报告
    log("[3/4] 生成 Markdown 报告...")
    md_lines = [
        f"**AAna v2.4 T+1 开盘卖出** · {today} 09:30",
        "",
    ]
    if dry_run:
        md_lines.append("**⚠️ DRY-RUN 模式**（仅模拟决策，未实际成交）")
        md_lines.append("")
        for code, pos, d_decision in decisions:
            ohlc = quotes_ohlc.get(code, {})
            gap = (ohlc.get('open', 0) / pos['entry_price'] - 1) * 100 if pos['entry_price'] else 0
            md_lines.append(
                f"- {code} {pos['name']} | 成本 {pos['entry_price']:.2f} → T+1 开盘 {ohlc.get('open', 0):.2f} ({gap:+.2f}%) | "
                f"**{d_decision.action}** {d_decision.reason} {d_decision.pnl_pct:+.2f}%"
            )
    else:
        md_lines.append(f"**触发卖出**: {len(triggered)} 笔")
        md_lines.append("")
        for t in triggered:
            md_lines.append(
                f"- {t['code']} {t['name']} | 成本 {t['price']:.2f} → 卖 {t['price']:.2f} | "
                f"**{t['action']}** {t.get('stop_reason', '?')} pnl {t.get('pnl_pct', 0):+.2f}%"
            )

    md_lines.append("")
    md_lines.append("**v2.4 卖出规则**: T+1 09:30 开盘即卖（90 天回测 80.2% 胜率 / 11.83 盈亏比）")
    md_lines.append("")
    md_lines.append("> 仅供参考，不构成投资建议")

    markdown = "\n".join(md_lines)

    # 写本地报告
    report_dir = os.path.join(PROJECT, "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = f"{report_dir}/{today}-v24-T1卖出.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# AAna v2.4 T+1 开盘卖出 · {today}\n\n")
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
    parser.add_argument('--dry-run', action='store_true', help='不实际卖出，只模拟决策')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
