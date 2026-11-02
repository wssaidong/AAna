"""回归测试: sina 行业名解析不能把"备注：此为申万行业分类"当成行业名

背景 (2026-11-02):
    data_sources._sina_industry_concept 用正则 `<td[^>]*>([^<]+)</td>` 抓单元格。
    该正则要求 1+ 个非 '<' 字符, 所以"行业名单元格为空"的 <td></td> 被整格跳过 →
    tds 变成 ['所属行业板块', '备注：此为申万行业分类'] → 取 tds[1] 当行业名 →
    拿到那句表尾备注。

    实际 sina HTML (悍高集团 001221 原始片段):
        <td class="ct" align="center"></td>          <- 行业名单元格, 空
        <td class="ct" align="center">点击查看</td>
        <td colspan="2" class="ct" align="center">备注：此为申万行业分类</td>

    污染链: 垃圾值 → recommendations.csv/rec_feedback.csv 的 sector 列
           → rec_optimizer._lookup_sector → rec_tuning.sector_stats 垃圾 key
           → _cn_sector_to_enum 匹配不到 → 那几只股票逃过所有板块黑名单。
    实测 16 只股票被污染 (state/industry_cache.json), 4 行进了 rec_tuning。

修法: 行业名只取第一个非空且非 "备注" 开头的单元格; 取不到 → None 继续走降级链。

注: requests 是在 _sina_industry_concept 内部 import 的 (函数级导入),
    所以必须打 requests.get 这个模块属性, 不能给 data_sources 模块挂属性。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib

import requests

from scripts.data_sources import _sina_industry_concept

# sina 行业名单元格为空时的真实 HTML (001221 悍高集团 原始片段)
EMPTY_CELL_HTML = """
<table class="comInfo1" width="60%" align="center">
  <tr>
    <td class="ct" align="center" colspan="2" bgcolor="EEF5FF">所属行业板块</td>
  </tr>
  <tr>
    <th class="ct" align="center">所属行业板块</th>
    <th class="ct" align="center">同行业个股</th>
  </tr>
  <tr>
    <td class="ct" align="center"></td>
    <td class="ct" align="center"><a target="_blank" href="/corp/view/vCI_CorpInfoLink.php?page=1&amp;stockid=001221&amp;Type=">点击查看</a></td>
  </tr>
  <tr><td colspan="2" class="ct" align="center">备注：此为申万行业分类</td></tr>
</table>
"""

# 正常有行业名的 HTML (600031 三一重工)
NORMAL_HTML = """
<table class="comInfo1" width="60%" align="center">
  <tr>
    <td class="ct" align="center" colspan="2" bgcolor="EEF5FF">所属行业板块</td>
  </tr>
  <tr>
    <td class="ct" align="center">工程机械</td>
    <td class="ct" align="center"><a target="_blank" href="/x">点击查看</a></td>
  </tr>
  <tr><td colspan="2" class="ct" align="center">备注：此为申万行业分类</td></tr>
</table>
"""

GARBAGE = "备注：此为申万行业分类"


@contextlib.contextmanager
def _fake_sina_html(html):
    """把 requests.get 换成返回固定 HTML (离线跑测试)。"""
    class _Resp:
        encoding = "gbk"
        text = html

    orig_get = requests.get

    def _get(url, headers=None, timeout=None, **kw):
        return _Resp()

    requests.get = _get
    try:
        yield
    finally:
        requests.get = orig_get


def test_empty_industry_cell_does_not_return_remark():
    """行业名单元格为空 → 绝不能返回 '备注：此为申万行业分类'"""
    with _fake_sina_html(EMPTY_CELL_HTML):
        industry, _concepts, _err = _sina_industry_concept("001221")
    assert industry != GARBAGE, (
        "行业名单元格为空时不能把表尾备注当成行业名 (2026-11-02 数据污染根因)"
    )
    assert industry is None or industry == "unknown", (
        f"行业名应回落到 None/unknown 交给降级链, 实际得到 {industry!r}"
    )


def test_normal_industry_still_parsed():
    """正常情况不能被修复搞坏 —— 行业名仍要正确解析出来"""
    with _fake_sina_html(NORMAL_HTML):
        industry, _concepts, _err = _sina_industry_concept("600031")
    assert industry == "工程机械", f"正常行业名解析被破坏, 得到 {industry!r}"


def test_remark_cell_never_leaks_into_concepts():
    """概念列表也不能混进备注句"""
    with _fake_sina_html(EMPTY_CELL_HTML):
        _industry, concepts, _err = _sina_industry_concept("001221")
    assert not any(c.startswith("备注") for c in concepts), f"概念列表混入备注: {concepts}"


def test_industry_for_code_never_returns_remark():
    """端到端守卫: industry_for_code 的任何返回路径都不能是那句备注"""
    import scripts.data_sources as ds

    orig_cache = ds._load_industry_cache
    orig_save = ds._save_industry_cache
    ds._load_industry_cache = lambda: {}
    ds._save_industry_cache = lambda c: None
    try:
        with _fake_sina_html(EMPTY_CELL_HTML):
            result = ds.industry_for_code("001221")
    finally:
        ds._load_industry_cache = orig_cache
        ds._save_industry_cache = orig_save

    assert result != GARBAGE, f"industry_for_code 返回了垃圾行业名: {result!r}"


def test_industry_cache_has_no_poisoned_entries():
    """本地行业缓存里不能残留被污染的条目"""
    import scripts.data_sources as ds

    cache = ds._load_industry_cache()
    poisoned = {k: v for k, v in cache.items() if str(v).startswith("备注")}
    assert not poisoned, (
        f"行业缓存仍残留 {len(poisoned)} 条污染值: {list(poisoned.items())[:5]}"
    )
