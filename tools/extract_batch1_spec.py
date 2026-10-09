# -*- coding: utf-8 -*-
"""抽取批次 1 契约所需的模型数据：M5 角色授权、M3 规则、MU 菜单。"""
import io
import json
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m2 = yaml.safe_load(io.open(os.path.join(D, "m2-behavior-model.yaml"), encoding="utf-8").read())
m3 = yaml.safe_load(io.open(os.path.join(D, "m3-rule-model.yaml"), encoding="utf-8").read())
m5 = yaml.safe_load(io.open(os.path.join(D, "m5-actor-model.yaml"), encoding="utf-8").read())
mu = yaml.safe_load(io.open(os.path.join(D, "mu-ui-model.yaml"), encoding="utf-8").read())

BATCH1_AGG = {"AGG-PATIENT-001", "AGG-SYNDROME-001", "AGG-FORMULA-001", "AGG-HERB-001"}
b1_beh = [b["id"] for b in m2["behaviors"]
          if b.get("ownerEntity") in BATCH1_AGG and b.get("triggerType") == "USER_ACTION"]
print("批次 1 人工行为（%d）：" % len(b1_beh))
print("  " + ", ".join(b1_beh))

b1_set = set(b1_beh) | {"Herb_DeductStock", "Herb_ReturnStock"}
print("\n=== M5 权限（targetRef ∈ 上述行为）===")
perm = {}
for p in m5["permissions"]:
    if p.get("targetRef") in b1_set:
        perm[p["permissionId"]] = p
        print("  %-34s %-12s %-6s %s" % (p["permissionId"], p.get("targetType"), p.get("dataScope"), p.get("name")))

print("\n=== M5 角色 → 本批权限 ===")
for r in m5["roles"]:
    hit = [p for p in r.get("permissions", []) if p in perm]
    print("  %-9s %-10s → %s" % (r["roleId"], r["name"], ", ".join(hit) if hit else "（无）"))

print("\n=== M5 全部角色（角色码/名称）===")
for r in m5["roles"]:
    print("  %-9s %-10s 权限数 %d" % (r["roleId"], r["name"], len(r.get("permissions", []) or [])))

print("\n=== M5 主体（actors）===")
for a in m5.get("actors", []) or []:
    print("  %-16s %-22s roles=%s" % (a.get("actorId"), a.get("name"), a.get("roles")))

print("\n=== M3 规则清单 ===")
for r in m3["rules"]:
    print("  %-16s %-14s %s" % (r["id"], r.get("ruleType"), r.get("name")))
    print("      expr: %s" % (r.get("expression") or "").replace("\n", " ")[:220])
    if r.get("violationMessage"):
        print("      提示: %s" % r["violationMessage"])

print("\n=== MU 菜单树（含屏幕）===")
for m in mu["application"]["menus"]:
    print("  %s %s (%s)" % (m.get("menuId"), m.get("name"), m.get("icon")))
    for c in m.get("children", []) or []:
        scr = [s for s in mu["screens"] if s["screenId"] == c.get("screenRef")]
        st = scr[0].get("screenType") if scr else "?"
        print("     - %-28s %-10s screenRef=%s" % (c.get("name"), st, c.get("screenRef")))

print("\n=== MU 五屏元素（批次 1）===")
for sid in ["frmPatientCreate", "frmSyndromeMaintain", "frmFormulaMaintain", "frmHerbMaintain", "frmHerbStock"]:
    s = [x for x in mu["screens"] if x["screenId"] == sid]
    if not s:
        print("  [缺] " + sid)
        continue
    s = s[0]
    print("  ### %s %s (%s) 元素 %d 动作 %d" % (sid, s.get("name"), s.get("screenType"),
                                              len(s.get("elements", [])), len(s.get("actions", []))))
    for e in s.get("elements", []):
        print("      %-22s %-12s %-4s %s" % (e.get("id"), e.get("type"), e.get("io"),
                                             (str(e.get("dataBinding") or "") + " " + str(e.get("label") or ""))[:60]))
    for a in s.get("actions", []):
        print("      ACT %-22s %-9s %-28s %s" % (a.get("actionId"), a.get("actionType"),
                                                 a.get("behaviorRef"), a.get("permissionRef")))
