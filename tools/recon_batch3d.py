# -*- coding: utf-8 -*-
"""批次 3 侦察（四）：需求文档口径 + M1 聚合→物理表 + 现有菜单表。"""
import io
import os
import re

import yaml

R = r"D:\hermes\workspace\中医问诊系统"
D = os.path.join(R, "yaml")
load = lambda f: yaml.safe_load(io.open(os.path.join(D, f), encoding="utf-8").read())

m1 = load("m1-object-model.yaml")
print("== M1 聚合 → 物理表（按别名登记） ==")
for a in m1["aggregates"]:
    print("  %-24s %-16s name=%s" % (a["id"], a.get("alias") or a.get("tableName"), a.get("name")))
    for sub in a.get("childEntities") or a.get("subEntities") or []:
        print("      └ %-20s %s" % (sub.get("alias"), sub.get("name")))

print("\n== 需求文档中与批次 3 相关的表述（AI/智能/对话/导出/报表口径） ==")
doc = io.open(os.path.join(R, "中医问诊系统-需求规格说明书-V9.md"), encoding="utf-8").read()
lines = doc.splitlines()
keys = ("AI", "智能", "对话", "导出", "Excel", "CSV", "报表", "台账", "合计", "粒度")
hits = [(i + 1, l.strip()) for i, l in enumerate(lines) if any(k in l for k in keys)]
print("命中 %d 行，取前 45 行：" % len(hits))
for i, l in hits[:45]:
    print("%5d| %s" % (i, l[:150]))
