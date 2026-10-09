# -*- coding: utf-8 -*-
"""批次 3 侦察：MU 剩余屏幕 / M7 报表对象 / M2 查询行为 / M5 权限 / 菜单。"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
load = lambda f: yaml.safe_load(io.open(os.path.join(D, f), encoding="utf-8").read())

mu = load("mu-ui-model.yaml")
m7 = load("m7-report-model.yaml")
m2 = load("m2-behavior-model.yaml")
m5 = load("m5-actor-model.yaml")

print("=" * 100)
print("MU 顶层键：", list(mu.keys()))
print("菜单：")
for m in mu.get("menus", []):
    print("  %s %s" % (m.get("menuId"), m.get("name")))
    for c in m.get("children", []) or []:
        print("     - %s %s → %s" % (c.get("menuId"), c.get("name"), c.get("screenRef") or c.get("path")))

print("=" * 100)
print("MU 屏幕清单（共 %d 屏）：" % len(mu.get("screens", [])))
for s in mu.get("screens", []):
    acts = [(a.get("actionId"), a.get("behaviorRef")) for a in (s.get("actions") or [])]
    print("  %-10s %-22s %-22s 元素 %3d 动作 %s" % (
        s.get("id"), s.get("name"), s.get("protocol") or s.get("formCode"), len(s.get("elements") or []), acts))

print("=" * 100)
print("M7 顶层键：", list(m7.keys()))
for r in m7.get("query_reports", []):
    print("  %-32s %-28s 来源 %2d Join %2d 参数 %2d 列 %3d 权限 %s" % (
        r.get("id"), r.get("name"), len(r.get("dataSources") or r.get("sources") or []),
        len(r.get("joins") or []), len(r.get("parameters") or []), len(r.get("columns") or []),
        r.get("permissionRef") or r.get("requiredPermission")))

print("=" * 100)
print("M2 查询类行为：")
for b in m2["behaviors"]:
    if b.get("behaviorType") == "QUERY":
        print("  %-34s %-20s 返回 %s" % (b["id"], b.get("name"), str(b.get("returns") or b.get("resultType"))[:40]))

print("=" * 100)
print("M2 系统行为：")
for b in m2["behaviors"]:
    if b.get("behaviorType") == "SYSTEM":
        print("  %-34s %s" % (b["id"], b.get("name")))

print("=" * 100)
print("M5 顶层键：", list(m5.keys()))
print("角色：")
for rid, r in (m5.get("roles") or {}).items():
    print("  %-10s %-14s 权限 %d 个" % (rid, r.get("name"), len(r.get("permissions") or r.get("permissionRefs") or [])))
print("报表/查询相关权限码：")
import re as _re
seen = set()
for p in m5.get("permissions", []):
    code = p.get("code") or p.get("id")
    ref = str(p.get("targetRef") or "")
    if _re.search(r"query|report|statistic|VOID|Cancel|FollowUp|Conversation|AI", code + ref, _re.I):
        if code not in seen:
            seen.add(code)
            print("  %-34s %-16s %s" % (code, p.get("targetType"), ref))
