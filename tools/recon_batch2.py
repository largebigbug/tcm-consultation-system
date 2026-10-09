# -*- coding: utf-8 -*-
"""批次 2 侦察：抽出门诊业务流涉及的 M1/M2/M3/M7/MU 规格。"""
import io
import json
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m1 = yaml.safe_load(io.open(os.path.join(D, "m1-object-model.yaml"), encoding="utf-8").read())
m2 = yaml.safe_load(io.open(os.path.join(D, "m2-behavior-model.yaml"), encoding="utf-8").read())
m3 = yaml.safe_load(io.open(os.path.join(D, "m3-rule-model.yaml"), encoding="utf-8").read())
m7 = yaml.safe_load(io.open(os.path.join(D, "m7-report-model.yaml"), encoding="utf-8").read())
mu = yaml.safe_load(io.open(os.path.join(D, "mu-ui-model.yaml"), encoding="utf-8").read())

BATCH1 = {"AGG-PATIENT-001", "AGG-SYNDROME-001", "AGG-FORMULA-001", "AGG-HERB-001"}

print("=== M1 全部聚合（★=批次1已实现） ===")
for a in m1["aggregates"]:
    star = "★" if a["id"] in BATCH1 else " "
    ents = ", ".join(e["alias"] for e in a.get("entities", []) or [])
    print("%s %-22s %-16s 属性 %-4d 关联表取数" % (star, a["id"], a["alias"], len(a["attributes"])))
    if ents:
        print("      子实体：%s" % ents)
    print("      关联：%s" % ", ".join(
        "%s(%s)" % (r.get("targetAggregate", r.get("target", "?")), r.get("type", "")) for r in a.get("associations", []) or []))

print("\n=== M2 行为（按聚合） ===")
for a in m1["aggregates"]:
    bs = [b for b in m2["behaviors"] if b.get("ownerEntity") == a["id"]]
    if not bs:
        continue
    print("%s %s（%d）" % ("★" if a["id"] in BATCH1 else " ", a["alias"], len(bs)))
    for b in bs:
        print("   %-32s %-12s %s" % (b["id"], b.get("triggerType"), b.get("name")))
        pre = b.get("preconditions") or []
        post = b.get("postconditions") or []
        if pre:
            print("      前置：%s" % " / ".join(str(x)[:70] for x in pre))
        if post:
            print("      后置：%s" % " / ".join(str(x)[:70] for x in post))
        if b.get("syncTriggers"):
            print("      联动：%s" % json.dumps(b["syncTriggers"], ensure_ascii=False)[:220])
        if b.get("queryReportRef"):
            print("      报表：%s" % b["queryReportRef"])

print("\n=== M3 规则全文 ===")
for r in m3["rules"]:
    print("--- %s %s（%s）" % (r["id"], r.get("name"), r.get("ruleType")))
    print("    表达式：%s" % (r.get("expression") or "").replace("\n", " ")[:400])
    print("    输入：%s" % json.dumps(r.get("inputParams"), ensure_ascii=False)[:200])
    print("    违反提示：%s" % r.get("violationMessage"))

print("\n=== M7 对象 ===")
for q in m7["query_reports"]:
    srcs = [s.get("aggregateRef") or s.get("sourceObject") for s in q.get("sources", []) or []]
    print("%-28s %-12s %-22s 参数 %d 列 %d 来源 %s" % (
        q["id"], q.get("objectType"), q.get("name", "")[:22],
        len(q.get("parameters", []) or []), len(q.get("resultColumns", []) or []), srcs))
    print("      behaviorRef=%s" % q.get("behaviorRef"))

print("\n=== MU 屏幕清单（批次 1 已实现 5 屏） ===")
done = {"frmPatientCreate", "frmSyndromeMaintain", "frmFormulaMaintain", "frmHerbMaintain", "frmHerbStock"}
for m in mu["application"]["menus"]:
    print("%s（%s）" % (m.get("name"), m.get("menuId")))
    for c in m.get("children", []) or []:
        sid = c.get("screenRef")
        scr = [s for s in mu["screens"] if s["screenId"] == sid]
        st = scr[0].get("screenType") if scr else "?"
        print("   [%s] %-24s %-16s %s" % ("已做" if sid in done else "待做", c.get("name"), sid, st))
