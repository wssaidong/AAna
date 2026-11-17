#!/usr/bin/env python3
"""
tests/test_sync_top10_pool_pollution.py — 2026-11-04 P0 回归测试

覆盖两个真实修复:
  1. `get_or_create_group` 缓存 gid 未验证 → 返回已被 dg 掉的死组
     (11-04 实测: 退役 gid=1846 后 groups.json 仍存 1846 → 返回死组 → add_stocks 全 -119)
  2. `sync_top10_v9.py` 纯追加语义 → 同日跑两次造成组内池污染
     (11-04 实测: 盘前池 10 只 + 开盘池 8 只 → 18 只, 两池 0 重合)

设计原则 (遵循 SKILL.md 教训 c): **不硬编码历史快照数字**, 用动态断言 / 完全 mock。
陷阱 (11-04 实测): monkeypatch 打错符号 → 静默无效 → 测试恒绿假绿。
             ⇒ 本文件每个测试都必须**对旧代码 failed** 才算数 (已实测验证)。
"""
import os
import sys
import pytest

SCRIPTS = os.path.expanduser('~/code/AAna/scripts')
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.expanduser('~/code/AAna'))

import eastmoney_portfolio as ep
import sync_top10_v9


class FakeEp:
    """可编程的东财替身 —— 记录调用序列, 模拟服务端状态机"""

    def __init__(self, groups, cache):
        # groups: {gid: [codes]}   cache: {name: gid}
        self.groups = groups
        self.cache = cache
        self.calls = []
        self._next_gid = max(groups.keys()) + 1 if groups else 1000

    # ── api_call 替身 ──
    def api_call(self, url, max_retries=2):
        self.calls.append(('api_call', url))
        if 'gstkinfos' in url:
            gid = self._gid_from_url(url)
            if gid not in self.groups:
                return ({'state': -119, 'message': '分组信息不存在'}, '')
            return ({'state': 0, 'data': {'stkinfolist': [
                {'security': f'0${c}$x', 'updatetime': '20261104093948'}
                for c in self.groups[gid]]}}, '')
        if 'ag' in url and 'gn=' in url:
            # 创建组合 → 分配新 gid 并返回 data.gid (真实 API 语义)
            name = url.split('gn=')[1].split('&')[0]
            if name in self.cache and self.cache[name] in self.groups:
                return ({'state': -131, 'message': '分组名已存在'}, '')  # 真实 API 不带 data.gid
            gid = self._next_gid
            self._next_gid += 1
            self.groups[gid] = []
            self.cache[name] = gid
            return ({'state': 0, 'data': {'gid': gid}}, '')
        return ({'state': 0}, '')

    @staticmethod
    def _gid_from_url(url):
        for part in url.split('?')[-1].split('&'):
            if part.startswith('g='):
                return int(part[2:])
        raise ValueError(f'url 无 gid: {url}')

    def mkurl(self, cmd, **kw):
        return cmd + '?' + '&'.join(f'{k}={v}' for k, v in kw.items())

    def get_group_stocks(self, gid):
        self.calls.append(('get_group_stocks', gid))
        return [{'security': f'0${c}$x', 'updatetime': '20261104093948'}
                for c in self.groups.get(gid, [])]

    def delete_group(self, gid):
        self.calls.append(('delete_group', gid))
        self.groups.pop(gid, None)
        return True

    def get_or_create_group(self, name):
        self.calls.append(('get_or_create_group', name))
        if name in self.cache:
            gid = self.cache[name]
            if gid in self.groups:
                return gid
        gid = self._next_gid
        self._next_gid += 1
        self.groups[gid] = []
        self.cache[name] = gid
        return gid

    def add_stocks(self, gid, codes):
        self.calls.append(('add_stocks', gid, tuple(codes)))
        if gid not in self.groups:
            return 0
        self.groups[gid].extend(c for c in codes if c not in self.groups[gid])
        return len(codes)


@pytest.fixture
def fake_service(monkeypatch):
    """
    只替换**底层 API** (api_call / mkurl), 保留被测函数本体
    (get_or_create_group / delete_group / add_stocks) 真跑。

    ⚠️ 不要在这里 patch ep.get_or_create_group —— 那会连被测函数一起替换掉,
    测试就变成"测 fake 自己", 恒绿假绿 (11-04 实测踩到)。

    服务端初始态: gid=1841 持有 OLD1/OLD2 (模拟一个**已存在**的组),
    服务端名字映射里**不含** 20261104 → `ag` 会真正创建新组。
    """
    fake = FakeEp({1841: ['OLD1', 'OLD2']}, {})
    _install(fake, monkeypatch)
    return fake


def _install(fake, monkeypatch):
    monkeypatch.setattr(ep, 'api_call', fake.api_call)
    monkeypatch.setattr(ep, 'mkurl', fake.mkurl)
    monkeypatch.setattr(ep, 'get_group_stocks', fake.get_group_stocks)
    monkeypatch.setattr(ep, 'delete_group', fake.delete_group)
    monkeypatch.setattr(ep, 'add_stocks', fake.add_stocks)


def _patch_groups_file(monkeypatch, tmp_path, content):
    """
    把模块读 groups.json 的路径指向 tmp。

    ⚠️ 必须打在被真正调用的符号上: eastmoney_portfolio.py 用
    **os.path.expanduser** (= posixpath.expanduser)。打到 os.expanduser 上
    会静默无效 → 测试恒绿 (11-04 实测踩到)。
    """
    cache_file = tmp_path / 'groups.json'
    cache_file.write_text(content, encoding='utf-8')
    monkeypatch.setattr(ep.os.path, 'expanduser',
                        lambda p: str(cache_file) if 'groups.json' in p else p)
    return cache_file


# ─────────────────────────────────────────────────────────────
# 1) get_or_create_group 必须验证缓存 gid 是否存活
# ─────────────────────────────────────────────────────────────

def test_cache_gid_dead_group_is_rejected(fake_service, monkeypatch, tmp_path):
    """缓存里记着一个已被 dg 掉的 gid → 必须丢弃缓存, 不能返回死组"""
    _patch_groups_file(monkeypatch, tmp_path, '{"20261104": {"gid": 9999}}')

    gid = ep.get_or_create_group('20261104')
    assert gid != 9999, '死组 gid 必须被丢弃, 不能原样返回'
    assert gid in fake_service.groups, '应新建一个组'


def test_cache_gid_alive_group_is_reused(fake_service, monkeypatch, tmp_path):
    """缓存 gid 存活 → 直接复用, 不新建 (幂等)"""
    _patch_groups_file(monkeypatch, tmp_path, '{"20261104": {"gid": 1841}}')

    gid = ep.get_or_create_group('20261104')
    assert gid == 1841
    assert not any(c[0] == 'delete_group' for c in fake_service.calls)

def test_new_group_gid_persisted_to_cache(fake_service, monkeypatch, tmp_path):
    """
    新建的组必须立刻写回缓存 —— 否则空组(无 updatetime)永远扫不回来。

    11-04 实测: ag 建出空组后, 按日期前缀扫描 1786..1906 全部 -119,
    只有缓存里记下 gid 才能找回它。
    """
    cache_file = _patch_groups_file(monkeypatch, tmp_path, '{}')

    gid = ep.get_or_create_group('20261104')
    assert gid is not None
    import json
    saved = json.loads(cache_file.read_text(encoding='utf-8'))
    assert saved.get('20261104', {}).get('gid') == gid, '新组 gid 必须落缓存'


# ─────────────────────────────────────────────────────────────
# 2) sync_top10_v9 的池一致性检查 / 重建
# ─────────────────────────────────────────────────────────────

def test_rebuild_when_pool_mismatch(fake_service):
    """组内池 != 报告池 → 必须整组退役重建, 结果与报告完全一致"""
    codes = ['NEW1', 'NEW2', 'NEW3']
    fake_service.groups[1841] = ['OLD1', 'OLD2']   # 污染状态

    new_gid = sync_top10_v9._rebuild_group(fake_service, '20261104', codes, 1841,
                                            fake_service.groups[1841])
    assert new_gid is not None
    assert new_gid != 1841, '必须换新 gid (东财无单股删除 API)'
    assert sorted(fake_service.groups[new_gid]) == sorted(codes)
    assert ('delete_group', 1841) in fake_service.calls


def test_rebuild_detects_missing_stocks(fake_service):
    """重建后必须能补齐所有缺失股票"""
    codes = ['NEW1', 'NEW2']
    fake_service.groups[1841] = ['OLD1']
    new_gid = sync_top10_v9._rebuild_group(fake_service, '20261104', codes, 1841, ['OLD1'])
    assert sorted(fake_service.groups[new_gid]) == sorted(codes)


def test_rebuild_aborts_when_new_group_dead(fake_service):
    """
    新组不存活 (gid 不存在) → 必须中止, 不能假装成功。

    11-04 实测: 退役后 groups.json 缓存仍存死 gid → 返回死组 →
    add_stocks 全部 state=-119 失败, 但脚本仍 print "添加=N" 假装成功。
    """
    codes = ['NEW1']
    fake_service.groups[1841] = ['OLD1']

    def dead_get_or_create(name):
        return 8888          # 8888 不在 groups → 不存活

    fake_service.get_or_create_group = dead_get_or_create
    new_gid = sync_top10_v9._rebuild_group(fake_service, '20261104', codes, 1841, ['OLD1'])
    assert new_gid is None, '新组不存活必须中止'


def test_group_codes_extraction(fake_service):
    """_group_codes 必须从 security 字段正确提取 6 位代码"""
    fake_service.groups[7] = ['600000', '000001']
    assert sorted(sync_top10_v9._group_codes(fake_service, 7)) == ['000001', '600000']
