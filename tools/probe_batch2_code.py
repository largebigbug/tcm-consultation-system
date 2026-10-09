# -*- coding: utf-8 -*-
"""探针：M2 随访行为前置 + schema.visit DDL + 代码内的状态码/主诉校验位置。"""
import io
import os
import re

import yaml

ROOT = r"D:\hermes\workspace\中医问诊系统"
m2 = yaml.safe_load(io.open(os.path.join(ROOT, "yaml", "m2-behavior-model.yaml"), encoding="utf-8").read())
print("===== M2 随访/系统行为")
for b in m2["behaviors"]:
    if "Follow" in b["id"] or b.get("behaviorType") == "SYSTEM":
        print("\n== %s | %s (%s)" % (b["id"], b.get("name"), b.get("behaviorType")))
        for key in ("preconditions", "postconditions", "syncTriggers"):
            for p in b.get(key) or []:
                print("   [%s] %s" % (key, p if isinstance(p, str) else str(p)[:120]))

print("\n===== schema.sql visit 表 DDL")
sql = io.open(os.path.join(ROOT, "code-app", "backend", "schema.sql"), encoding="utf-8").read()
m = re.search(r"CREATE TABLE IF NOT EXISTS visit \(.*?\);", sql, re.S)
print(m.group(0) if m else "未找到")

print("\n===== visit_service 内涉及 REF-05 / 主诉 / 字典校验的代码行")
vs = io.open(os.path.join(ROOT, "code-app", "backend", "services", "visit_service.py"), encoding="utf-8").read().splitlines()
pat = re.compile(r"chief_complaint|register_time|receive_time|REF-05|主诉|_ALIAS|visit_type|dept_code|IN_CONSULT|IN_PROGRESS")
for i, line in enumerate(vs, 1):
    if pat.search(line):
        print("%4d| %s" % (i, line.rstrip()[:150]))
