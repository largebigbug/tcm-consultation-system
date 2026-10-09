# -*- coding: utf-8 -*-
"""批次 3 侦察（七）：抽取 6 张报表用到的全部别名与派生别名，供契约定义别名→物理表映射。"""
import io
import os
import re
from collections import OrderedDict

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m7 = yaml.safe_load(io.open(os.path.join(D, "m7-report-model.yaml"), encoding="utf-8").read())
REPORTS = ["RPT-VISIT-STATS-001", "RPT-SYNDROME-DIST-001", "RPT-HERB-USAGE-001",
           "QR-VISIT-PRESCRIPTION-001", "QR-PRESCRIPTION-OVERDOSE-001", "RPT-FOLLOWUP-COMPLETION-001"]

all_derived = set()
for rid in REPORTS:
    r = [x for x in m7["query_reports"] if x["id"] == rid][0]
    declared = {s["alias"] for s in r.get("sourceObjects") or []}
    exprs = [c.get("sourceExpression") for c in r.get("resultColumns") or []]
    exprs += [c.get("leftExpression") for c in r.get("conditions") or []]
    exprs += [j.get("conditionExpression") for j in r.get("joins") or []]
    exprs += [g if isinstance(g, str) else str(g) for g in (r.get("groupBy") or [])]
    exprs += [str(o) for o in (r.get("orderBy") or [])]
    exprs += [str(h) for h in (r.get("having") or [])]
    prefixes = set()
    for e in exprs:
        for m in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.", e or ""):
            prefixes.add(m)
    derived = prefixes - declared
    all_derived |= derived
    print("== %-30s 声明别名 %s" % (rid, sorted(declared)))
    print("   派生别名（需子查询/CTE 或聚合）: %s" % (sorted(derived) or "无"))
    print("   聚合函数:", sorted({c.get("aggregateFunction") for c in r.get("resultColumns") or []
                                 if c.get("aggregateFunction") not in (None, "NONE")}))
    print("   分组:", r.get("groupBy"))
    print("   having:", r.get("having"))
    print("   排序:", r.get("orderBy"))
    print("   分页:", r.get("pagination"))
    print("   呈现选项:", r.get("reportOptions"))
print("\n全部派生别名：", sorted(all_derived))
