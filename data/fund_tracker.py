#!/usr/bin/env python3
"""
AAna 基金持仓追踪模块
数据来源: fundgz.1234567.com.cn (天天基金实时估值)
支持: 定投记录、每日净值更新、收益计算、持仓报告
"""
import sys
import json
import os
import urllib3
from datetime import datetime, timedelta
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 数据文件路径 ─────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent.parent
TRACK_FILE = PROJECT_DIR / "data" / "fund_portfolio.json"

# ── 天天基金实时净值 API ─────────────────────────────────────────────────────
NAV_API = "https://fundgz.1234567.com.cn/js/{code}.js"
HIST_API = "https://api.fund.eastmoney.com/f10/lsjz"


# ── 核心数据结构 ─────────────────────────────────────────────────────────────

def _load() -> dict:
    if TRACK_FILE.exists():
        with open(TRACK_FILE) as f:
            return json.load(f)
    return {
        "positions": {},   # {code: {name, cost, shares, buy_date, type}}
        "dwm": [],         # 每日净值快照 [{date, positions: {code: nav}}]
        "init_cash": 0,    # 总投入本金
    }


def _save(data: dict):
    TRACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACK_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 净值获取 ──────────────────────────────────────────────────────────────────

def get_nav(code: str) -> dict | None:
    """获取基金实时估算净值，返回dict或None"""
    try:
        import requests
        r = requests.get(NAV_API.format(code=code), timeout=8)
        text = r.text.strip()
        if text.startswith('jsonpgz('):
            inner = text[8:-2]
            d = json.loads(inner)
            return {
                'code': d['fundcode'],
                'name': d['name'],
                'nav_date': d['jzrq'],
                'nav': float(d['dwjz']),
                'est_nav': float(d['gsz']),
                'est_pct': float(d['gszzl']),
                'update_time': d['gztime'],
            }
    except Exception:
        pass
    return None


def get_hist_nav(code: str, days: int = 90) -> list:
    """获取基金历史净值（近days天）"""
    try:
        import requests
        params = {
            'fundCode': code,
            'pageIndex': 1,
            'pageSize': days,
            'startDate': '',
            'endDate': '',
        }
        r = requests.get(HIST_API, params=params, timeout=10)
        d = r.json()
        if d.get('Data') and d['Data'].get('LSJZList'):
            return [
                {'date': x['FSRQ'], 'nav': x['DWJZ'], 'pct': x['JZZZL']}
                for x in d['Data']['LSJZList']
            ]
    except Exception:
        pass
    return []


# ── 持仓操作 ─────────────────────────────────────────────────────────────────

def add_position(code: str, name: str, shares: float, cost: float,
                 buy_date: str = None, fund_type: str = '混合型'):
    """添加或追加基金持仓"""
    data = _load()
    if buy_date is None:
        buy_date = datetime.now().strftime('%Y-%m-%d')

    if code in data['positions']:
        pos = data['positions'][code]
        # 成本均价法
        old_shares = pos['shares']
        old_cost_total = pos['cost'] * old_shares
        new_cost_total = cost * shares
        total_shares = old_shares + shares
        pos['shares'] = total_shares
        pos['cost'] = (old_cost_total + new_cost_total) / total_shares
        pos['buy_date'] = min(pos['buy_date'], buy_date)
    else:
        data['positions'][code] = {
            'name': name,
            'shares': shares,
            'cost': cost,          # 买入均价
            'buy_date': buy_date,
            'type': fund_type,
        }
    _save(data)
    return data['positions'][code]


def remove_position(code: str, shares: float = None):
    """卖出基金（减少持仓）"""
    data = _load()
    if code not in data['positions']:
        return None
    pos = data['positions'][code]
    if shares is None or shares >= pos['shares']:
        del data['positions'][code]
    else:
        pos['shares'] -= shares
    _save(data)


# ── 每日快照 ─────────────────────────────────────────────────────────────────

def snapshot() -> dict:
    """记录今日净值快照，返回所有持仓的当日估值"""
    data = _load()
    today = datetime.now().strftime('%Y-%m-%d')

    snapshot_entry = {'date': today, 'positions': {}}
    total_value = 0
    total_cost = 0

    for code, pos in data['positions'].items():
        info = get_nav(code)
        if info:
            nav = info['est_nav']
            value = nav * pos['shares']
            cost = pos['cost'] * pos['shares']
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else 0
            snapshot_entry['positions'][code] = {
                'name': pos['name'],
                'nav': nav,
                'value': value,
                'cost': cost,
                'pnl': pnl,
                'pnl_pct': round(pnl_pct, 2),
                'est_pct': info['est_pct'],
            }
            total_value += value
            total_cost += cost

    # 更新dwm快照（保留近180天）
    data['dwm'] = [s for s in data['dwm'] if s['date'] != today]
    data['dwm'].append(snapshot_entry)
    data['dwm'] = data['dwm'][-180:]
    _save(data)

    snapshot_entry['total_value'] = total_value
    snapshot_entry['total_cost'] = total_cost
    snapshot_entry['total_pnl'] = total_value - total_cost
    snapshot_entry['total_pnl_pct'] = round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0
    return snapshot_entry


# ── 报告生成 ─────────────────────────────────────────────────────────────────

def get_tracker_report() -> str:
    """生成基金持仓追踪报告 Markdown"""
    data = _load()
    today = datetime.now().strftime('%Y-%m-%d')

    if not data['positions']:
        return (
            f"## 📊 基金持仓追踪 · {today}\n\n"
            "**暂无持仓记录**\n\n"
            "使用 `fund_tracker.add_position('代码', '名称', 份额, 成本)` 添加持仓\n\n"
        )

    lines = [f"## 📊 基金持仓追踪 · {today}\n"]

    # 实时估值
    rows = []
    total_value = 0
    total_cost = 0
    for code, pos in data['positions'].items():
        info = get_nav(code)
        if info:
            value = info['est_nav'] * pos['shares']
            cost = pos['cost'] * pos['shares']
            pnl = value - cost
            pnl_pct = round(pnl / cost * 100, 2) if cost else 0
            days = (datetime.now() - datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days
            rows.append({
                'code': code,
                'name': pos['name'],
                'type': pos['type'],
                'nav': info['est_nav'],
                'est_pct': info['est_pct'],
                'value': round(value, 2),
                'cost': round(cost, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': pnl_pct,
                'days': days,
            })
            total_value += value
            total_cost += cost
        else:
            rows.append({
                'code': code, 'name': pos['name'], 'type': pos['type'],
                'nav': pos['cost'], 'est_pct': 0,
                'value': pos['shares'] * pos['cost'],
                'cost': pos['cost'] * pos['shares'],
                'pnl': 0, 'pnl_pct': 0, 'days': 0,
            })
            total_cost += pos['cost'] * pos['shares']

    # 总览
    total_pnl = total_value - total_cost
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost else 0
    lines.append(f"\n**总持仓：{len(rows)} 只 | 总市值：{total_value:.2f}元 | 总收益：{total_pnl:.2f}元({total_pnl_pct:+.2f}%)**\n")

    # 按收益排序
    rows.sort(key=lambda x: x['pnl_pct'], reverse=True)

    lines.append(f"\n| 代码 | 名称 | 类型 | 估算净值 | 估算涨幅 | 市值 | 成本 | 收益/损失 | 持有天数 |\n")
    lines.append(f"|------|------|------|---------|---------|------|------|---------|---------|\n")
    for r in rows:
        pnl_emoji = "🟢" if r['pnl'] >= 0 else "🔴"
        lines.append(
            f"| {r['code']} | {r['name'][:12]} | {r['type']} | "
            f"{r['nav']:.4f} | {pnl_emoji}{r['est_pct']:+.2f}% | "
            f"{r['value']:.2f} | {r['cost']:.2f} | "
            f"{pnl_emoji}{r['pnl_pct']:+.2f}% | {r['days']}天 |\n"
        )

    # 近30日收益曲线（如果有快照数据）
    if len(data['dwm']) >= 2:
        lines.append(f"\n### 📈 近30日收益走势\n")
        recent = data['dwm'][-30:]
        if len(recent) >= 2:
            start_val = recent[0]['total_value'] if 'total_value' in recent[0] else sum(
                p.get('value', 0) for p in recent[0].get('positions', {}).values())
            end_val = recent[-1]['total_value'] if 'total_value' in recent[-1] else sum(
                p.get('value', 0) for p in recent[-1].get('positions', {}).values())
            period_pct = round((end_val - start_val) / start_val * 100, 2) if start_val else 0
            lines.append(f"\n**近30天：{'🟢+' if period_pct >= 0 else '🔴'}{period_pct}%**\n")
            lines.append(f"起始市值：{start_val:.2f} → 当前估算：{end_val:.2f}\n")

    lines.append("\n*⚠️ 估值为盘中估算，实际净值以晚间公布为准*\n")
    return ''.join(lines)


# ── 快捷命令 ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='AAna 基金持仓追踪')
    sub = parser.add_subparsers(dest='cmd')

    p = sub.add_parser('show', help='显示持仓报告')
    p = sub.add_parser('snap', help='获取今日净值快照')
    p = sub.add_parser('snapshot', help='记录今日快照')

    p = sub.add_parser('add', help='添加持仓')
    p.add_argument('code')
    p.add_argument('name')
    p.add_argument('shares', type=float)
    p.add_argument('cost', type=float)
    p.add_argument('--date', default=None)

    p = sub.add_parser('list', help='列出所有持仓')

    args = parser.parse_args()

    if args.cmd == 'show':
        print(get_tracker_report())
    elif args.cmd == 'snap' or args.cmd == 'snapshot':
        result = snapshot()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == 'add':
        pos = add_position(args.code, args.name, args.shares, args.cost, args.date)
        print(f"✅ 已添加 {args.code} {args.name} {args.shares}份 成本{args.cost}")
    elif args.cmd == 'list':
        data = _load()
        for code, pos in data['positions'].items():
            print(f"{code} {pos['name']} {pos['shares']}份 均价{pos['cost']}")
    else:
        parser.print_help()