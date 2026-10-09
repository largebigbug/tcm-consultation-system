# -*- coding: utf-8 -*-
"""打印 M1 Visit 关键属性/不变性 与 M2 相关行为的规则（口径裁决用）。"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m1 = yaml.safe_load(io.open(os.path.join(D, "m1-object-model.yaml"), encoding="utf-8").read())
for a in m1["aggregates"]:
    if a["id"] in ("AGG-VISIT-001", "AGG-PRESCRIPTION-001"):
        print("===== M1 %s %s" % (a["id"], a.get("name")))
        for at in a["attributes"]:
            if at["name"] in ("chiefComplaint", "visitStatus", "registerTime", "receiveTime", "remark",
                              "prescriptionStatus", "submitTime"):
                print("  %-20s req=%-5s %s" % (at["name"], at.get("required"), str(at.get("description"))[:70]))
        for inv in a.get("invariants", []) or []:
            print("  INV %-14s %s" % (inv.get("id"), str(inv.get("expression"))[:110]))

m2 = yaml.safe_load(io.open(os.path.join(D, "m2-behavior-model.yaml"), encoding="utf-8").read())
print("\n键名：", list(m2["behaviors"][0].keys()))
for b in m2["behaviors"]:
    if b["id"] in ("Visit_Register", "Visit_Receive", "Prescription_Save", "Prescription_Cancel",
                   "Prescription_Submit", "Prescription_Review"):
        print("\n== %s | %s" % (b["id"], b.get("name")))
        for key in ("preconditions", "postconditions", "triggeredRules", "rules", "invariants"):
            if b.get(key):
                print("  [%s]" % key)
                for p in b[key]:
                    print("     - %s" % (p if isinstance(p, str) else str(p)[:160]))
