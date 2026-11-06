#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财同步 2026-11-06 早盘深度: 建组 20261106ZZ 只含铁律合格池 Top1 (600633 浙数文化, 深度80.0买入)。
缓存 SOP: 只新增 key `20261106ZZ` (严禁写裸日期 `20261106`, 那是今晨盘前占位组 gid=1896, 股票待写入;
也严禁碰 `20261105` gid=1891 — 其现持 3 只恰为今日池, 系 11-05 晚间 selection 所建, 与本组语义无关)。
find_group_gid 前 8 位日期匹配 → '20261106ZZ' 探测大概率歧义命中 1896 (先例 11-05: 命中 1871 早盘组),
故 pre-check 仅记录不拦截, 拦截靠创建后 gid≠已知组 防御校验。
备份 + 位置参数 json.dump + 写后校验 + stocks 用 gstkinfos 真实 codes。
"""
import sys, os, json, shutil

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

GROUP_NAME = "20261106ZZ"
TOP1 = "600633"
KNOWN_GIDS = {1896: "20261106 盘前占位组(空)", 1891: "20261105 晚间selection组(3只)",
              1876: "20261105ZZ(中电港)", 1886: "20261105PP(智度股份)"}
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def main():
    # 0. cookie
    ok = ep.load_cookie()
    print("cookie ok:", bool(ok))

    # 1. 防御: 探测 20261106ZZ (预期歧义命中 1896 早盘占位组, 仅记录)
    exist = ep.find_group_gid(GROUP_NAME)
    print(f"pre-check find_group_gid({GROUP_NAME}):", exist,
          f"(已知组: {KNOWN_GIDS.get(exist, '未知/无命中')} — 前 8 位日期歧义口径, 仅记录不拦截)")

    # 2. 创建新组
    gid = ep.create_group(GROUP_NAME)
    if not gid:
        raise SystemExit("create_group 失败, 中止 (不写缓存)")
    if gid in KNOWN_GIDS:
        raise SystemExit(f"gid={gid} 是已知组 {KNOWN_GIDS[gid]} — ag 返回了已存在组的 gid, 中止不写缓存")

    # 3. 加唯一 1 只
    n = ep.add_stocks(gid, [TOP1])
    print("add_stocks:", n)

    # 4. 服务端验证: 恰好 1 只且代码=TOP1
    r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid), max_retries=2)
    stks = r.get('data', {}).get('stkinfolist', [])
    codes = [s.get('security', '').split('$')[1] for s in stks]
    print(f"gstkinfos gid={gid}: {len(stks)} 只 {codes} updatetime={stks[0].get('updatetime') if stks else '-'}")
    assert len(stks) == 1 and codes == [TOP1], f"验证失败: {codes}"

    # 5. 更新 groups.json (只新增 ZZ key, 碰都不碰裸日期 key 20261106)
    with open(GROUPS_FILE) as f:
        history = json.load(f)
    shutil.copy2(GROUPS_FILE, GROUPS_FILE + '.bak')
    morning_entry = history.get("20261106")
    history[GROUP_NAME] = {
        "gid": gid,
        "date": "20261106",
        "stocks": codes,
        "type": "deep_analysis_zz",
        "note": ("2026-11-06 早盘深度分析铁律 Top1 浙数文化600633 (深度评分80.0买入; 技术55/55满分"
                 "(MA多头/RSI57/量比1.47/20日区间97%突破区) + 估值15/15满分(PE29/PB1.39); 基本面数据缺失"
                 "10/30兜底, 评分由技术+估值驱动; 板块键移动互联网服务75%(3/4)有效样本暖键+传媒邻键100%); "
                 "回暖73/仓位70%守卫放行; 池3只全胜大盘+正盈利(11-05 +4.51~4.79% vs 大盘+0.61%), "
                 "次优电魂69.3增持(PE-14亏损), 统一股份47.7减持(PE167/PB9.46)未入组; "
                 f"今晨占位组20261106(gid={morning_entry.get('gid') if isinstance(morning_entry, dict) else '?'})未受影响; "
                 "autopilot 01a1ae43 深度分析"),
    }
    with open(GROUPS_FILE, 'w', ) as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    # 写后校验
    with open(GROUPS_FILE) as f:
        assert json.load(f)[GROUP_NAME]["gid"] == gid
    print(f"groups.json 已更新: {GROUP_NAME} gid={gid} (裸日期 key 20261106 未动, 备份 .bak)")
    print(f"✅ 东财组合 {GROUP_NAME} = {codes}")


if __name__ == "__main__":
    main()
