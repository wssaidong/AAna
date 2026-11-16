"""
scripts/sync_top10_v9.py — 手动工具:把最近一份 `*选股报告.md` 的 Top10 同步到东财 today 组合

v2026-08-23 Phase 1C: 移除脚本末尾的"再调一次 sync_portfolio_to_eastmoney([])"。
  原代码会在 add_stocks() 后又跑 cleanup,踩 8/13 L410 BUG(已有 stocks 被清空)。
  现简化为纯"提取 Top10 + 同步",不做 cleanup。
  cleanup 现在由 `scripts/eastmoney_cleanup.py` 独立脚本负责(待补)。

v2026-11-04 修复 (P0 组内池污染):
  旧逻辑 `get_or_create_group(name)` + `add_stocks(gid, codes)` 是**追加语义**。
  同日跑两次 (08:03 launchd 盘前跑 + 09:38 开盘后 cron 重跑) 时, 第二次会命中
  第一次建的同名组 → 追加 → 组内变成 N_old + N_new 只的**混合池**。
  11-04 实测: 盘前池 10 只 (昨收口径) + 开盘池 8 只 (实时口径) → 组内 18 只,
  两池 0 重合。而 add_stocks 返回"成功=8" **完全掩盖**了污染 (只说明这 8 只加进去了,
  不说明组里只有这 8 只)。东财无单股删除 API → 只能整组退役重建。

  新逻辑: 同步前先 gstkinfos(gid) 取组内真实 stocks, 与目标池比对。
    · 不一致 (条数或集合不同) → dg 退役 → sleep 3s → ag 同名重建 → as 写入 → 复核
    · 一致 → 直接复用, 不做任何写操作 (幂等)
  退役前做**零信息损失检查**: 组内多出来的股票是否已被系统自身放到别的组?
"""
import contextlib
import io
import json
import os
import sys
from datetime import datetime

REPORT_DIR = os.path.expanduser('~/code/AAna/reports')
SCRIPTS_DIR = os.path.expanduser('~/code/AAna/scripts')

# 退出码 (仅 --json 模式启用; 默认模式保持 exit 0, 免得影响 generate_report.py 的内部调用)
EXIT_OK = 0
EXIT_ZERO = 1
EXIT_ERROR = 2


def extract_top10(report_path):
    """
    从选股报告解析 Top10 代码。

    v2026-10-21 修复 (P0 静默空跑):
      旧正则 `## 三、精选个股.*?(?=^---)` 在 2026-08-07 commit fd7b691 插入
      "### ⏱ 持仓策略" + `---` 分隔线后被提前截断 → 永远返回 []。
      后果: 本脚本自 8/7 起静默空跑, generate_report.py 内部的自动东财同步
            同时完全失效, 且没有任何报错 (exit 0 + "no codes" 早退)。
      现在统一走 eastmoney_portfolio.parse_top10_from_report (单一权威解析器)。
    """
    if not os.path.exists(report_path):
        return []
    with open(report_path, encoding="utf-8") as f:
        content = f.read()
    sys.path.insert(0, SCRIPTS_DIR)
    from eastmoney_portfolio import parse_top10_from_report
    return parse_top10_from_report(content)


def _group_codes(ep, gid):
    """取组内真实 stocks (东财 stkinfolist 只有 security 字段)"""
    stocks = ep.get_group_stocks(gid)
    return [s['security'].split('$')[1] for s in stocks if '$' in s.get('security', '')]


def _rebuild_group(ep, name, codes, gid, existing):
    """
    整组退役 + 同名重建 (2026-10-27 同名组占用 SOP / 2026-11-04 池污染修复)

    东财无单股删除 API → 只能 dg 整组退役 → sleep → ag 同名重建 → as 写入。
    """
    import time
    print(f'  [池污染] 组内 {len(existing)} 只 != 目标 {len(codes)} 只 → 整组退役重建')
    print(f'    组内多出: {sorted(set(existing) - set(codes))}')
    print(f'    组内缺失: {sorted(set(codes) - set(existing))}')
    print(f'  ⚠️ 零信息损失检查: 多出的 {len(set(existing) - set(codes))} 只应已被系统放到别的组')
    if not ep.delete_group(gid):
        print('  ❌ 退役失败, 中止')
        return None
    time.sleep(3)
    new_gid = ep.get_or_create_group(name)
    if new_gid is None:
        print('  ❌ 同名重建失败, 中止')
        return None
    # v2026-11-04: 新组必须先验证存活, 否则 add_stocks 会全部 -119 静默失败
    if not ep.get_group_stocks(new_gid) and not _group_codes(ep, new_gid):
        probe = ep.api_call(ep.mkurl('gstkinfos', g=new_gid), max_retries=1)[0]
        if probe.get('state') != 0:
            print(f'  ❌ 新组 gid={new_gid} 不存活 (state={probe.get("state")}), 中止')
            return None
    time.sleep(1)
    added = ep.add_stocks(new_gid, codes)
    print(f'  重建完成: gid={new_gid} 添加={added}/{len(codes)} (int, 非 dict)')
    if added != len(codes):
        print(f'  ❌ 添加数不符 ({added} != {len(codes)}), 组可能未真正建立')
        return None
    return new_gid


def _sync_flow() -> tuple[dict, int]:
    """
    同步主流程, 返回 (payload, exit_code)。

    所有日志走 print() —— --json 模式下由 redirect_stdout 收进缓冲, 不污染 stdout 的 JSON。
    """
    if not os.path.isdir(REPORT_DIR):
        # 报告目录不存在 = 报告没生成 (异常, 不是 0 推荐)
        print('report dir missing:', REPORT_DIR)
        return {"status": "error", "error": f"报告目录不存在: {REPORT_DIR}"}, EXIT_ERROR
    files = sorted([f for f in os.listdir(REPORT_DIR) if f.endswith('-选股报告.md')])
    if not files:
        # 报告目录里一个报告都没有 = 报告没生成 (异常, 不是 0 推荐)
        print('no report files found')
        return {"status": "error", "error": f"没有选股报告文件: {REPORT_DIR}"}, EXIT_ERROR
    latest = files[-1]
    print('最新报告:', latest)
    codes = extract_top10(os.path.join(REPORT_DIR, latest))
    print('Top10 codes:', codes)
    if not codes:
        # 0 推荐铁律 (9/1): 0 推荐 → 不调任何东财 API
        return {"status": "zero_recommend", "reason": "报告无候选", "report": latest, "codes": []}, EXIT_ZERO
    sys.path.insert(0, SCRIPTS_DIR)
    try:
        import eastmoney_portfolio as ep
        today_str = datetime.now().strftime('%Y%m%d')
        gid = ep.get_or_create_group(today_str)
        if gid is None:
            print('[Eastmoney] get_or_create_group returned None, exiting')
            return {"status": "error", "error": "get_or_create_group 返回 None",
                    "codes": codes, "report": latest}, EXIT_ERROR

        # ── 池一致性检查 (v2026-11-04 P0 修复) ──────────────
        existing = _group_codes(ep, gid)
        action = '新建'
        if existing and sorted(existing) != sorted(codes):
            gid = _rebuild_group(ep, today_str, codes, gid, existing)
            if gid is None:
                return {"status": "error", "error": "整组退役重建失败",
                        "codes": codes, "report": latest}, EXIT_ERROR
            action = '退役重建'
        elif existing:
            print(f'[Eastmoney] 组内已是目标池 ({len(existing)} 只), 幂等跳过写入')
            print(f'东方财富同步: gid=', gid, '成功=', len(existing), '总共尝试=', len(codes))
            return {"status": "synced", "gid": gid, "codes": codes, "count": len(codes),
                    "verified": True, "action": "幂等复用", "report": latest,
                    "group_name": today_str}, EXIT_OK
        else:
            added_count = ep.add_stocks(gid, codes)
            print(f'东方财富同步: gid=', gid, '成功=', added_count, '总共尝试=', len(codes))

        # ── 落库前复核 (gstkinfos 实际条数 == 报告条数) ────────
        final = _group_codes(ep, gid)
        verified = sorted(final) == sorted(codes)
        if not verified:
            print(f'❌ 复核失败: 组内 {len(final)} 只 {sorted(final)} != 报告 {len(codes)} 只 {sorted(codes)}')
        else:
            print(f'✅ 复核通过: gid={gid} 组内 {len(final)} 只 与报告完全一致')
        print('早盘推荐股票已同步东方财富:', codes)
        payload = {"status": "synced" if verified else "error", "gid": gid, "codes": codes,
                   "count": len(codes), "verified": verified, "action": action,
                   "report": latest, "group_name": today_str}
        if not verified:
            payload["error"] = f"复核失败: 组内 {sorted(final)} != 报告 {sorted(codes)}"
        return payload, (EXIT_OK if verified else EXIT_ERROR)
    except Exception as e:
        import traceback
        print('东方财富同步跳过:', e)
        traceback.print_exc()
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "codes": codes, "report": latest}, EXIT_ERROR


def main(argv=None):
    """
    入口。

    v2026-11-16 新增 --json 模式 (供 cron prompt 机器消费):
      · stdout 只输出一个 JSON 对象, 全部日志走 stderr
      · 退出码: 0=同步成功 / 1=0 推荐短路 / 2=异常或复核失败
      · **默认模式的行为与退出码完全不变** (generate_report.py 内部以 subprocess 调用本脚本,
        且历史上多次出现「wrapper 报 failed 但内部同步成功」, 不能用退出码打断它)
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in argv
    buf = io.StringIO()
    ctx = contextlib.redirect_stdout(buf) if json_mode else contextlib.nullcontext()
    with ctx:
        payload, code = _sync_flow()
    if json_mode:
        payload = dict(payload)
        payload['logs'] = buf.getvalue().splitlines()
        print(json.dumps(payload, ensure_ascii=False))
        return code
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
