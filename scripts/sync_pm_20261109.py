#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东财同步 2026-11-09 尾盘: 建组 20261109PP 只含深度 Top1 (600501 航天晨光)。

背景 (10-28 撞名教训):
  PP 组缓存 key 必须 = 服务端组名 `20261109PP`, 严禁写裸日期 `20261109`
  (那是早盘 Top10 组独占, gid=1906)。裸日期 key 覆盖早盘条目 → 同日早盘同步命中污染条目
  → 早盘 Top10 灌进 PP 组 (服务端 9 只, 本地记 1 只)。

防御 (沿用 11-04 / 11-05 sync_pm_*.py 口径):
  1. 服务端并发预扫当日 (updatetime[:8]==20261109) 所有存活 gid, 记下"非 PP 组" gid 集合
     —— find_group_gid() 只比日期前缀, 对 `20261109PP` 会误命中早盘组, 不可作为唯一依据
  2. create_group("20261109PP") 拿干净 gid; 若返回的 gid 落在已知当日组集合 → 中止
  3. add_stocks 只加唯一 1 只 (深度 Top1 = 600501)
  4. gstkinfos 服务端验证: 恰好 1 只且代码 == TOP1
  5. groups.json 只新增 `20261109PP` key, 碰都不碰裸日期 key; 备份 + 位置参数 + 写后校验
"""
import sys, os, json, shutil
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

GROUP_NAME = "20261109PP"
DATE8 = "20261109"
TOP1 = "600501"
GROUPS_FILE = os.path.expanduser(
    "~/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")


def scan_today_groups():
    """并发扫 gid 区间, 找出 updatetime 前 8 位 == DATE8 的所有存活组。"""
    gids = []
    try:
        with open(GROUPS_FILE) as f:
            hist = json.load(f)
        gids = [int(v['gid']) for v in hist.values() if v.get('gid')]
    except Exception:
        pass
    center = max(gids) if gids else 1900
    lo, hi = max(136, center - 60), center + 60

    def probe(g):
        try:
            r, _ = ep.api_call(ep.mkurl('gstkinfos', g=g), max_retries=0)
            if r.get('state') != 0:
                return None
            stks = r.get('data', {}).get('stkinfolist', [])
            if not stks:
                return None
            ut = str(stks[0].get('updatetime', ''))
            if len(ut) >= 8 and ut[:8] == DATE8:
                codes = [s.get('security', '').split('$')[1] for s in stks]
                return (g, ut, codes)
        except Exception:
            return None
        return None

    found = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        for res in ex.map(probe, range(lo, hi)):
            if res:
                found[res[0]] = (res[1], res[2])
    return found, (lo, hi)


def main():
    ok = ep.load_cookie()
    print("cookie ok:", bool(ok))

    with open(GROUPS_FILE) as f:
        history = json.load(f)
    morning_entry = history.get(DATE8)
    morning_gid = morning_entry.get('gid') if isinstance(morning_entry, dict) else None
    print(f"groups.json 裸日期 key {DATE8} -> gid={morning_gid} (早盘组, 必须不动)")

    # 1. 服务端预扫当日存活组 (识别已存在的非 PP 组, 防撞名)
    found, rng = scan_today_groups()
    print(f"服务端当日 (updatetime[:8]=={DATE8}) 存活组: {len(found)} 个, 扫描区间 {rng}")
    for g, (ut, codes) in sorted(found.items()):
        tag = "⚠️早盘组" if str(g) == str(morning_gid) else "其他组"
        print(f"  gid={g} {tag} updatetime={ut} 含 {len(codes)} 只 {codes}")
    occupied_gids = set(found.keys())

    # 2. 创建 PP 组 (幂等: 缓存已有 gid 时先服务端验证复用, 避免重复建组)
    cached = history.get(GROUP_NAME)
    gid = None
    located_existing = False
    if isinstance(cached, dict) and cached.get('gid'):
        cgid = int(cached['gid'])
        cr, _ = ep.api_call(ep.mkurl('gstkinfos', g=cgid), max_retries=1)
        if cr.get('state') == 0:
            gid = cgid
            located_existing = True
            print(f"复用缓存 PP 组 gid={gid} (服务端验证存活)")
        else:
            print(f"缓存 gid={cgid} 服务端已失效 (state={cr.get('state')}), 走创建路径")
    if gid is None:
        gid = ep.create_group(GROUP_NAME)
        if not gid:
            # -131: 组名已存在 (上一轮建组成功但缓存写失败) → 按内容定位:
            # 当日存活组中, gid != 早盘 gid 且内容恰好 == [TOP1] 的那个即 PP 组
            cands = [g for g, (ut, cs) in found.items()
                     if str(g) != str(morning_gid) and cs == [TOP1]]
            print(f"create_group 返回空 (组名已存在), 按内容定位候选: {cands}")
            if len(cands) == 1:
                gid = cands[0]
                located_existing = True
                print(f"命中唯一候选 gid={gid} (服务端内容 == [{TOP1}])")
            else:
                raise SystemExit(f"create_group 失败且无法唯一定位 PP 组 (候选={cands}), 中止不写缓存")
        else:
            print(f"create_group({GROUP_NAME}) -> gid={gid}")

    # 3. 防御: 新建 gid 不得等于任何已存在的当日组 (早盘/ZZ 组)
    #    (沿用/按内容定位到的既有 PP 组不在此列 — 它本身就是那一个)
    if gid in occupied_gids and not located_existing:
        raise SystemExit(f"gid={gid} 与服务端已存在的当日组冲突 (早盘/ZZ 组), 中止不写缓存")
    if morning_gid and str(gid) == str(morning_gid):
        raise SystemExit(f"gid={gid} 是早盘组, 中止不写缓存")

    # 4. 加唯一 1 只
    n = ep.add_stocks(gid, [TOP1])
    print("add_stocks:", n)

    # 5. 服务端验证: 恰好 1 只且代码 == TOP1
    r, _ = ep.api_call(ep.mkurl('gstkinfos', g=gid), max_retries=2)
    stks = r.get('data', {}).get('stkinfolist', [])
    codes = [s.get('security', '').split('$')[1] for s in stks]
    print(f"gstkinfos gid={gid}: {len(stks)} 只 {codes} "
          f"updatetime={stks[0].get('updatetime') if stks else '-'}")
    assert len(stks) == 1 and codes == [TOP1], f"验证失败: {codes}"

    # 6. 更新 groups.json (只新增 PP key, 碰都不碰裸日期 key)
    shutil.copy2(GROUPS_FILE, GROUPS_FILE + '.bak')
    history[GROUP_NAME] = {
        "gid": gid,
        "date": DATE8,
        "stocks": codes,
        "type": "afternoon_deep_analysis_top1",
        "note": (f"2026-11-09 尾盘深度分析 Top1 航天晨光600501 (深度评分69.7增持, 池均值56.9); "
                 f"尾盘报告14:47情绪回暖55仓位70%守卫放行; 早盘组20261109(gid={morning_gid})未受影响; "
                 f"cron 49bbdf3c555a 14:45 深度精选"),
    }
    with open(GROUPS_FILE, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    with open(GROUPS_FILE) as f:
        recheck = json.load(f)
    assert recheck[GROUP_NAME]["gid"] == gid
    assert recheck[GROUP_NAME]["stocks"] == codes
    assert (recheck.get(DATE8) or {}).get("gid") == morning_gid, "裸日期 key 被改动!"
    print(f"groups.json: {GROUP_NAME} -> gid={gid} 写入+校验 OK; "
          f"裸日期 key 未动 (gid={recheck[DATE8]['gid']})")
    print(f"DONE: {GROUP_NAME} gid={gid} 含 {codes}")


if __name__ == "__main__":
    main()
