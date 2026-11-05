#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财同步 2026-11-05 早盘深度: 建组 20261105ZZ 只含铁律合格池 Top1 (001287 中电港, 深度94.5买入)。
缓存 SOP: 只新增 key `20261105ZZ` (严禁写裸日期 `20261105`, 那是早盘报告组 1871),
备份 + 位置参数 json.dump + 写后校验 + stocks 用 gstkinfos 真实 codes。
"""
import sys, os, json, shutil

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

GROUP_NAME = "20261105ZZ"
TOP1 = "001287"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def main():
    # 0. cookie
    ok = ep.load_cookie()
    print("cookie ok:", bool(ok))

    # 1. 防御: 精确确认服务端无同名组 (ag 对已存在名称返回 -131 + data.gid,
    #    那会撞进别组; 先扫描确认 20261105ZZ 不存在)
    exist = ep.find_group_gid(GROUP_NAME)
    print("pre-check find_group_gid(20261105ZZ):", exist)

    # 2. 创建新组
    gid = ep.create_group(GROUP_NAME)
    if not gid:
        raise SystemExit("create_group 失败, 中止 (不写缓存)")
    if gid == 1871:
        raise SystemExit(f"gid={gid} 是早盘报告组, ag 返回了已存在组的 gid — 中止不写缓存")

    # 3. 加唯一 1 只
    n = ep.add_stocks(gid, [TOP1])
    print("add_stocks:", n)

    # 4. 服务端验证: 恰好 1 只且代码=TOP1
    r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid), max_retries=2)
    stks = r.get('data', {}).get('stkinfolist', [])
    codes = [s.get('security', '').split('$')[1] for s in stks]
    print(f"gstkinfos gid={gid}: {len(stks)} 只 {codes} updatetime={stks[0].get('updatetime') if stks else '-'}")
    assert len(stks) == 1 and codes == [TOP1], f"验证失败: {codes}"

    # 5. 更新 groups.json (只新增 ZZ key, 碰都不碰裸日期 key 20261105)
    with open(GROUPS_FILE) as f:
        history = json.load(f)
    shutil.copy2(GROUPS_FILE, GROUPS_FILE + '.bak')
    morning_entry = history.get("20261105")
    history[GROUP_NAME] = {
        "gid": gid,
        "date": "20261105",
        "stocks": codes,
        "type": "deep_analysis_zz",
        "note": ("2026-11-05 早盘深度分析铁律 Top1 中电港001287 (深度评分94.5买入, 唯一合格: 技术49/55"
                 "+基本面30/30满分(ROE20%/净利+360%/营收+192%)+估值15/15满分(PE13/PB2.43)); "
                 f"亢奋第1日(85,涨停119)守卫放行; 追高窗口披露: 全池11-04均+6.5~7%; "
                 f"早盘报告组20261105(gid={morning_entry.get('gid') if isinstance(morning_entry, dict) else '?'})未受影响; "
                 "autopilot 01a1a91d 深度分析"),
    }
    with open(GROUPS_FILE, 'w', ) as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    # 写后校验
    with open(GROUPS_FILE) as f:
        assert json.load(f)[GROUP_NAME]["gid"] == gid
    print(f"groups.json 已更新: {GROUP_NAME} gid={gid} (裸日期 key 20261105 未动, 备份 .bak)")
    print(f"✅ 东财组合 {GROUP_NAME} = {codes}")


if __name__ == "__main__":
    main()
