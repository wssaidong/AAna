#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, json

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
from lark_push import push_markdown

FEISHU_USER_ID = "ou_5d0124d26ed21365f74764fcb9fa01b7"

MD = """**📊 AAna 深度分析 2026-11-23 (周一交易日盘前) — 0 推荐 · 冰点守卫 · 不建组**

**📄 报告**: **reports/2026-11-23-选股报告.md** (08:01:55 盘前版) · Top10 表 **0 只** · 快照 **情绪 20 冰点** · 仓位 10% 空仓观望 · 涨停 30/跌停 3 · **⚠️停止交易**

**🔍 空表根因** (cron.log 实证, 四链条均为设计行为非故障): 股票池 413 只 → ① 冰点情绪修正全池 -10 分 ② 资金流接口全挂 30/30 fallback (money_score 恒 50) ③ 涨停池不入 (情绪≤40 防追高) ④ 阈值 60 + 黑名单 8 板块 → 全池不过线。🛡 守卫双口径一致 (快照 20 + live ths 20, fallback=False 真实数据)

**🏁 今日结论: 0 推荐 → 不创建东财 20261123ZZ** (三重归因: ① 报告池 0 只 ② 冰点守卫放行失败 ③ 停止交易口径互证; 与 11-13/11-14/11-15/11-19/11-21/11-22 先例同款)

**📅 11-20 深度池 T+1 复核预检** (盘前零漂移 10/10, 真值判定待今日收盘复盘链): 池均值 -0.79% (超额 vs 大盘均 **+1.37pp**) · 双达标 4 只: 宇通客车 +3.47% / 中国平安 +1.46% / 兴业银行 +1.05% / 国电南瑞 +0.40% · ❌ Top1 铁律未达标: 海康威视 -1.29% (fail_negative_and_below_sh) · 张江高科 -10.01% 跌停破止损 (池内最低评级 减持, 反向印证评级区分度)

**📉 实持复核** (周五收盘): 20261120ZZ 海康威视 35.25 (软止损 34.64 未破) · 20261118ZZ 宁波银行 35.24 = -0.82% (软止损 34.34 未破) · 开盘后跌破即出不死扛, 卖出腿归 daily_v24_sell

**⚠️ 早盘简报异常 (不采信)**: agent 链 08:30 简报记「上证 ¥12.04 +0.42%」(真值 3533.79 -1.22%) + 盘前开盘前伪实时涨幅 17 行 → 数据失真, 属 agent 链 P1 造假判罚窗内 (今晚 21:3x 到期) 产物; 深度分析候选池只认主链报告

**📅 今日看点**: 情绪 20 冰点第 1 个交易日 — 若开盘后情绪回 30+ 断点 + 进攻主线 = 修复信号 (10-28 V 型修复 20→58→75 先例); 板块胜率库 122 板块 49.7% (461 笔)"""

if __name__ == "__main__":
    ok, detail = push_markdown(MD, user_id=FEISHU_USER_ID)
    print(f"ok: {ok}")
    print(f"detail: {detail}")
    mid = None
    try:
        # lark-cli stdout = 结果 JSON + 追加的 _notice 版本 JSON, 取第一个完整对象
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
