#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 groups.json: 20261017ZZ 条目写深度分析两只买入 (双 SOP: 备份+位置参数+写后校验)"""
import json, os, shutil, sys

sys.path.insert(0, '/Users/cai/code/AAna/scripts')
from eastmoney_portfolio import api_call, mkurl

PATH = os.path.expanduser(
    "/Users/cai/.hermes/skills/a-stock/eastmoney-portfolio-api/groups.json")
BAK = PATH + ".bak"
GID = "1681"
ENTRY = "20261017ZZ"
EXPECT = ["002270", "603101"]

# 1. 从服务端取真实 codes (SOP: 用 gstkinfos 真实 codes)
r, _ = api_call(mkurl('gstkinfos', g=int(GID)), max_retries=3)
stks = r.get('data', {}).get('stkinfolist', []) or []
real_codes = []
for s in stks:
    sec = s.get('security', '')
    code = sec.split('$')[1] if '$' in sec else sec
    if code:
        real_codes.append(code)
print("服务端真实 codes:", real_codes)
assert sorted(real_codes) == sorted(EXPECT), f"服务端不是 {EXPECT}: {real_codes}"

# 2. 备份
shutil.copy2(PATH, BAK)
print("backup:", BAK)

# 3. 读 + 改 + 写 (位置参数, 禁 fp=)
with open(PATH) as f:
    groups = json.load(f)
assert ENTRY in groups, f"entry {ENTRY} 不存在: {list(groups)}"
groups[ENTRY]["stocks"] = real_codes
groups[ENTRY]["note"] = ("深度分析买入级 2 只: 华明装备 002270 (Top1, 77.0 买入, "
                         "目标 19.79 止损 17.47, 10-16 +4.09% 正盈利, 连续两日验证) + "
                         "汇嘉时代 603101 (76.8 买入, 前三季预增 68-78%); "
                         "周六非交易日, 基准 10-16 盘后报告, 候选池 11 只非 ST 并集")
groups[ENTRY]["ts"] = "2026-10-17T08:30:00+08:00"
with open(PATH, "w") as f:
    json.dump(groups, f, ensure_ascii=False, indent=2)

# 4. 写后校验
with open(PATH) as f:
    check = json.load(f)
assert sorted(check[ENTRY]["stocks"]) == sorted(EXPECT), "写后校验失败"
print("✅ groups.json 更新并校验通过:", ENTRY, check[ENTRY]["stocks"])
