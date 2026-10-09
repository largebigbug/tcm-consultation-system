# -*- coding: utf-8 -*-
"""批次 3 侦察（三）：报表列结构、参考 SQL 与规模。"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m7 = yaml.safe_load(io.open(os.path.join(D, "m7-report-model.yaml"), encoding="utf-8").read())

for r in m7["query_reports"]:
    sql = r.get("referenceSql") or ""
    print("== %-30s %-16s 来源 %d Join %d 参数 %d 条件 %d 列 %d 分组 %d 排序 %d 参考SQL %d 行" % (
        r["id"], r.get("alias"), len(r.get("sourceObjects") or []), len(r.get("joins") or []),
        len(r.get("parameters") or []), len(r.get("conditions") or []), len(r.get("resultColumns") or []),
        len(r.get("groupBy") or []), len(r.get("orderBy") or []), len(sql.splitlines())))

r = [x for x in m7["query_reports"] if x["id"] == "QR-VISIT-PRESCRIPTION-001"][0]
print("\n== 就诊与处方记录查询 · 列定义（前 6） ==")
for c in (r.get("resultColumns") or [])[:6]:
    print("   %s" % c)
print("\n== 参数（全部） ==")
for p in r.get("parameters") or []:
    print("   %-22s %-10s %-12s required=%-5s default=%-14s op=%s ← %s" % (
        p.get("name"), p.get("dataType"), p.get("label"), p.get("required"), p.get("defaultValue"),
        p.get("allowedOperators"), p.get("sourceField")))
print("\n== reportOptions ==")
print(r.get("reportOptions"))
print("\n== 参考 SQL（前 40 行） ==")
print("\n".join((r.get("referenceSql") or "").splitlines()[:40]))
print("\n== 列名去重后的聚合函数使用情况 ==")
import re
exprs = [str(c.get("expression") or c.get("sourceExpression") or "") for c in (r.get("resultColumns") or [])]
print("  ", [e for e in exprs if re.search(r"COUNT|SUM|AVG|MAX|MIN", e, re.I)][:8])
