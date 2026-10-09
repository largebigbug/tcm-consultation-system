# -*- coding: utf-8 -*-
"""批次 3 侦察（二）：打印 M7 报表与 MU 屏幕的真实结构，确定抽取口径。"""
import io
import json
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
load = lambda f: yaml.safe_load(io.open(os.path.join(D, f), encoding="utf-8").read())

m7 = load("m7-report-model.yaml")
r = [x for x in m7["query_reports"] if x["id"] == "RPT-VISIT-STATS-001"][0]
print("== M7 报表顶层键：", list(r.keys()))
print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])

print("\n" + "=" * 100)
mu = load("mu-ui-model.yaml")
s = [x for x in mu["screens"] if x.get("name") == "门诊量统计"][0]
print("== MU 屏幕顶层键：", list(s.keys()))
print(json.dumps({k: v for k, v in s.items() if k != "elements"}, ensure_ascii=False, indent=1)[:1200])
print("-- 前 4 个元素：")
print(json.dumps(s["elements"][:4], ensure_ascii=False, indent=1)[:1500])

print("\n" + "=" * 100)
m5 = load("m5-actor-model.yaml")
print("== M5 roles 第 1 项键：", list(m5["roles"][0].keys()))
print(json.dumps(m5["roles"][0], ensure_ascii=False, indent=1)[:1200])
print("-- permissions 第 1 项：")
print(json.dumps(m5["permissions"][0], ensure_ascii=False, indent=1)[:600])
