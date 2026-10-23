#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 groups.json: 20261016ZZ 条目写入深度分析 Top1 002270 (8/24 双 SOP: 备份+位置参数+写后校验)"""
import json, os, shutil, sys

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
from eastmoney_portfolio import api_call, mkurl

PATH = os.path.expanduser(
    "/Users/cai/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")
BAK = PATH + ".bak"
GID = "1676"
ENTRY = "20261016ZZ"

# 1. 从服务端取真实 codes (8/24 SOP: 用 gstkinfos 真实 codes)
r, _ = api_call(mkurl('gstkinfos', g=int(GID)), max_retries=3)
stks = r.get('data', {}).get('stkinfolist', []) or []
real_codes = []
for s in stks:
    sec = s.get('security', '')
    code = sec.split('$')[1] if '$' in sec else sec
    if code:
        real_codes.append(code)
print("服务端真实 codes:", real_codes)
assert real_codes == ["002270"], f"服务端不是恰好 1 只 002270: {real_codes}"

# 2. 备份
shutil.copy2(PATH, BAK)
print("backup:", BAK)

# 3. 读 + 改 + 写 (位置参数, 禁 fp=)
with open(PATH) as f:
    groups = json.load(f)
groups[ENTRY]["stocks"] = real_codes
groups[ENTRY]["note"] = ("深度分析精选 Top1 华明装备 (002270, 深度评分 77.0 买入, "
                        "目标 19.73 止损 17.47) — replace-all from 冰点日空组合; "
                        "候选池 尾盘 Top5 剔除 ST (*ST数源)")
groups[ENTRY]["ts"] = "2026-10-16T14:53:00+08:00"
with open(PATH, "w") as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

# 4. 写后校验
with open(PATH) as f:
    check = json.load(f)
assert check[ENTRY]["stocks"] == ["002270"], "写后校验失败"
print("✅ groups.json 更新并校验通过:", ENTRY, check[ENTRY]["stocks"])
