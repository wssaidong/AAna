#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东财同步 2026-11-10 早盘: 建组 20261110ZZ 只含深度 Top1 (002420 毅昌科技, 80.0 买入)。

背景地雷 (10-28 撞名教训 + 今日实测):
  1. 今日裸日期组 20261110 (gid=1921, 今晨 08:03 已持 8 只 Top8) 严禁触碰
  2. gid=1916 (key=20261109, 昨 17:03 晚间链刷新) 与今日池同 8 只 — updatetime=20261109 不会被
     当日预扫命中, 但仍在 groups.json 历史内 → 只新增 ZZ key, 碰都不碰
  3. find_group_gid() 只比日期前缀, 对 `20261110ZZ` 会误命中裸日期组 → 不可作为唯一依据

防御 (沿用 sync_pm_20261109 / sync_zz_20261106 口径):
  1. 服务端并发预扫当日 (updatetime[:8]==20261110) 所有存活 gid, 记下占用集合
  2. create_group("20261110ZZ") 拿干净 gid; 若返回空 (-131 组名已存在) → 按内容定位 (恰 == [TOP1])
  3. 新建 gid 落在占用集 → 中止
  4. add_stocks 只加唯一 1 只 (深度 Top1 = 002420)
  5. gstkinfos 服务端验证: 恰好 1 只且代码 == TOP1
  6. groups.json 只新增 `20261110ZZ` key; 备份 + 写后校验 + 裸日期 key 不动断言
"""
import sys, os, json, shutil
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
import eastmoney_portfolio as ep

GROUP_NAME = "20261110ZZ"
DATE8 = "20261110"
TOP1 = "002420"
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
    center = max(gids) if gids else 1920
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
    print(f"groups.json 裸日期 key {DATE8} -> gid={morning_gid} (今晨 Top8 组, 必须不动)")

    # 1. 服务端预扫当日存活组 (识别已存在的非 ZZ 组, 防撞名)
    found, rng = scan_today_groups()
    print(f"服务端当日 (updatetime[:8]=={DATE8}) 存活组: {len(found)} 个, 扫描区间 {rng}")
    for g, (ut, codes) in sorted(found.items()):
        tag = "⚠️裸日期Top8组" if str(g) == str(morning_gid) else "其他组"
        print(f"  gid={g} {tag} updatetime={ut} 含 {len(codes)} 只 {codes}")
    occupied_gids = set(found.keys())

    # 2. 创建 ZZ 组 (幂等: 缓存已有 gid 时先服务端验证复用, 避免重复建组)
    cached = history.get(GROUP_NAME)
    gid = None
    located_existing = False
    if isinstance(cached, dict) and cached.get('gid'):
        cgid = int(cached['gid'])
        cr, _ = ep.api_call(ep.mkurl('gstkinfos', g=cgid), max_retries=1)
        if cr.get('state') == 0:
            gid = cgid
            located_existing = True
            print(f"复用缓存 ZZ 组 gid={gid} (服务端验证存活)")
        else:
            print(f"缓存 gid={cgid} 服务端已失效 (state={cr.get('state')}), 走创建路径")
    if gid is None:
        gid = ep.create_group(GROUP_NAME)
        if not gid:
            # -131: 组名已存在 → 按内容定位: 非裸日期 gid 且内容恰好 == [TOP1]
            cands = [g for g, (ut, cs) in found.items()
                     if str(g) != str(morning_gid) and cs == [TOP1]]
            print(f"create_group 返回空 (组名已存在), 按内容定位候选: {cands}")
            if len(cands) == 1:
                gid = cands[0]
                located_existing = True
                print(f"命中唯一候选 gid={gid} (服务端内容 == [{TOP1}])")
            else:
                raise SystemExit(f"create_group 失败且无法唯一定位 ZZ 组 (候选={cands}), 中止不写缓存")
        else:
            print(f"create_group({GROUP_NAME}) -> gid={gid}")

    # 3. 防御: 新建 gid 不得等于任何已存在的当日组 (裸日期 Top8 组等)
    if gid in occupied_gids and not located_existing:
        raise SystemExit(f"gid={gid} 与服务端已存在的当日组冲突 (裸日期组), 中止不写缓存")
    if morning_gid and str(gid) == str(morning_gid):
        raise SystemExit(f"gid={gid} 是裸日期 Top8 组, 中止不写缓存")

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

    # 6. 更新 groups.json (只新增 ZZ key, 碰都不碰裸日期 key)
    shutil.copy2(GROUPS_FILE, GROUPS_FILE + '.bak')
    history[GROUP_NAME] = {
        "gid": gid,
        "date": DATE8,
        "stocks": codes,
        "type": "morning_deep_analysis_top1",
        "note": (f"2026-11-10 早盘深度分析 Top1 毅昌科技002420 (深度评分80.0买入, 技术55/55+估值15/15双满分, "
                 f"池8只铁律合格4只居首; 板块显示器件80%(4/5), 行业双源sina彩电/东财综合Ⅱ); "
                 f"11-09基准+1.95%胜大盘(-0.04%)+正盈利, 守卫放行55回暖仓位50%; "
                 f"裸日期组20261110(gid={morning_gid})未受影响; autopilot ca411dd3 run 01a1c2dd"),
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
