#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, json

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
from lark_push import push_markdown

FEISHU_USER_ID = "ou_5d0124d26ed21365f74764fcb9fa01b7"

MD = """**📊 AAna 深度分析 2026-11-26 (周四交易日盘前) — 0 推荐 · 冰点守卫 · 不建组**

**📄 报告**: **reports/2026-11-26-选股报告.md** (08:01:54 盘前版) · Top10 表 **0 只** · 快照 **情绪 25 冰点** · 仓位 10% 空仓观望 · 涨停 57/跌停 6 · **⚠️停止交易**

**🔍 空表根因** (cron.log 实证, 四链条均为设计行为非故障): 股票池 230 只 → ① 冰点情绪修正全池 -10 分 ② 资金流接口全挂 东财 3 连试 RemoteDisconnected → 30/30 fallback (money_score 恒 50) ③ 涨停池不入 (情绪≤40 防追高) ④ 阈值 60 (昨晚回落基线 63→60) + 黑名单 9 弱势板块 → 全池不过线。🛡 守卫双口径一致 (快照 25 + live ths 25, fallback=False 真实非脏数据) → **放行失败**

**🏁 今日结论: 0 推荐 → 不创建东财 20261126ZZ** (三重归因: ① 报告池 0 只 ② 冰点守卫放行失败 ③ 停止交易口径互证)。基准 = 11-25 周三收盘: 四均 **-3.645%** (上证-2.03/深成-3.24/创业板-4.19/科创50-5.12 极端下跌日) / 大盘均 -2.78%, 铁律「当日胜出+正盈利」无候选可验证; 板块胜率库 129 板块 48.9% (489 笔); 与 11-13/11-14/11-15/11-19/11-21/11-22/11-23 先例同款

**🟡 实持双票贴线预警** (11-25 收盘冻结口径, 开盘后以实时为准): 许继电气 000400 (20261125ZZ) 收 25.60 -2.36%, **距止损 25.43 仅 +0.67%** · 菜百股份 605599 (20261124ZZ) 收 14.66 -2.20%, **距止损 14.51 仅 +1.03%** — 破位即出不死扛, 卖出腿归 daily_v24_sell; 淘汰对照 常山北明 11-25 **-8.95%** 印证淘汰正确

**⚠️ 早盘简报异常第 4 天 (不采信)**: 08:30 简报记「上证指数 ¥12.30 +0.08%」(¥12.30=000001.SZ 平安银行昨收, 真值 3476.47 -2.03%) + 「科创50 ¥16.83」(=000688.SZ 国城矿业昨收, 真值 1186.14) + 深成/创业板用 11-24 前日收盘陈旧链路 + 四值族虚构 + 情绪「乐观」与主链 25 冰点矛盾 + 17 行伪「今日涨幅」 → 候选池只认主链报告

**📅 今日看点**: 情绪 25 冰点第 2 个交易日 + 四核极端下跌次日 — 关注 10-28 V 型修复先例 (20→58→75), 若开盘后情绪回 30+ 断点 + 进攻主线 = 修复信号; 09:00 开盘版报告由 cron 另行生成; 今晚 21:3x 判罚窗第 3 采样 (盘后链)"""

if __name__ == "__main__":
    ok, detail = push_markdown(MD, user_id=FEISHU_USER_ID)
    print(f"ok: {ok}")
    print(f"detail: {detail[:200] if detail else detail}")
    mid = None
    try:
        dec = json.JSONDecoder()
        for i in range(len(detail)):
            if detail[i] == '{':
                d, _ = dec.raw_decode(detail[i:])
                if isinstance(d, dict) and d.get("ok") is True:
                    mid = d.get("data", {}).get("message_id")
                    break
    except Exception:
        pass
    print(f"message_id: {mid}")
