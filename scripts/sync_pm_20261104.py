#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财同步 2026-11-04 尾盘: 建组 20261104PP 只含深度 Top1 (002352 顺丰控股)。
缓存 SOP: 只新增 key `20261104PP` (严禁写裸日期 `20261104`, 那是早盘组 1856),
备份 + 位置参数 json.dump + 写后校验 + stocks 用 gstkinfos 真实 codes。
"""
import sys, os, json, shutil, time

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

GROUP_NAME = "20261104PP"
TOP1 = "002352"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def main():
    # 0. cookie
    ok = ep.load_cookie()
    print("cookie ok:", bool(ok))

    # 1. 防御: 精确确认服务端无同名组 (ag 对已存在名称返回 -131 + data.gid,
    #    那会撞进早盘组; 先扫描确认 20261104PP 不存在)
    exist = ep.find_group_gid(GROUP_NAME)
    print("pre-check find_group_gid(20261104PP):", exist)

    # 2. 创建新组
    gid = ep.create_group(GROUP_NAME)
    if not gid:
        raise SystemExit("create_group 失败, 中止 (不写缓存)")
    if gid == 1856:
        raise SystemExit(f"gid={gid} 是早盘组, ag 返回了已存在组的 gid — 中止不写缓存")

    # 3. 加唯一 1 只
    n = ep.add_stocks(gid, [TOP1])
    print("add_stocks:", n)

    # 4. 服务端验证: 恰好 1 只且代码=TOP1
    r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid), max_retries=2)
    stks = r.get('data', {}).get('stkinfolist', [])
    codes = [s.get('security', '').split('$')[1] for s in stks]
    print(f"gstkinfos gid={gid}: {len(stks)} 只 {codes} updatetime={stks[0].get('updatetime') if stks else '-'}")
    assert len(stks) == 1 and codes == [TOP1], f"验证失败: {codes}"

    # 5. 更新 groups.json (只新增 PP key, 碰都不碰裸日期 key)
    with open(GROUPS_FILE) as f:
        history = json.load(f)
    shutil.copy2(GROUPS_FILE, GROUPS_FILE + '.bak')
    morning_entry = history.get("20261104")
    history[GROUP_NAME] = {
        "gid": gid,
        "date": "20261104",
        "stocks": codes,
        "type": "afternoon_deep_analysis_top1",
        "note": ("2026-11-04 尾盘深度分析 Top1 顺丰控股002352 (深度评分72.8增持, 池均值56.5); "
                 f"尾盘报告14:46情绪亢奋+5.26%守卫放行; 早盘组20261104(gid={morning_entry.get('gid') if isinstance(morning_entry, dict) else '?'})未受影响; "
                 "cron 49bbdf3c555a 14:45 深度精选"),
    }
    with open(GROUPS_FILE, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    with open(GROUPS_FILE) as f:
        recheck = json.load(f)  # 写后校验
    assert recheck[GROUP_NAME]["gid"] == gid
    assert recheck.get("20261104", {}).get("gid") == (morning_entry or {}).get("gid"), "裸日期 key 被改动!"
    print(f"groups.json: {GROUP_NAME} -> gid={gid} 写入+校验 OK; 裸日期 key 未动 (gid={recheck['20261104']['gid']})")
    print(f"DONE: {GROUP_NAME} gid={gid} 含 {codes}")


if __name__ == "__main__":
    main()
