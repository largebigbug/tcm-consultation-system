# -*- coding: utf-8 -*-
"""抽取批次 2 七屏的 MU 规格（元素 + 动作 + 布局摘要），写入 scratch 供写契约时引用。"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
OUT = r"D:\hermes\.hermes\cache\scratch\batch2_screens.md"
mu = yaml.safe_load(io.open(os.path.join(D, "mu-ui-model.yaml"), encoding="utf-8").read())

IDS = ["frmVisitRegister", "frmVisitReceive", "frmFourDiagnosis", "frmDiagnosisJudge",
       "frmPrescription", "frmPrescriptionReview", "frmDispense"]

out = []
for sid in IDS:
    s = [x for x in mu["screens"] if x["screenId"] == sid]
    if not s:
        out.append("### %s —— 未找到\n" % sid)
        continue
    s = s[0]
    out.append("### %s %s（%s）" % (sid, s.get("name"), s.get("screenType")))
    out.append("")
    out.append("| 元素 id | 类型 | io | 字典/来源 | dataBinding | 标签 |")
    out.append("|---|---|---|---|---|---|")
    for e in s.get("elements", []) or []:
        bits = []
        if e.get("dictionaryRef"):
            dr = e["dictionaryRef"]
            bits.append("字典 %s.%s" % (dr.get("dictionaryId"), dr.get("typeCode")))
        elif e.get("dataSource"):
            bits.append("来源 %s" % e["dataSource"])
        elif e.get("aggregateRef"):
            bits.append("聚合 %s" % e["aggregateRef"])
        out.append("| `%s` | %s | %s | %s | `%s` | %s |" % (
            e.get("id"), e.get("type"), e.get("io"), "；".join(bits),
            e.get("dataBinding") or "", (e.get("label") or "")[:28]))
    out.append("")
    out.append("动作：")
    for a in s.get("actions", []) or []:
        out.append("- `%s` %s → 行为 `%s` 权限 `%s`%s" % (
            a.get("actionId"), a.get("actionType"), a.get("behaviorRef"),
            a.get("permissionRef"), ("　备注：" + str(a.get("description"))) if a.get("description") else ""))
    out.append("")
    if s.get("layout"):
        out.append("布局（ASCII）：")
        out.append("```text")
        out.append(str(s["layout"]).strip())
        out.append("```")
    out.append("")

io.open(OUT, "w", encoding="utf-8").write("\n".join(out))
text = "\n".join(out)
print("已写入 %s（%d 字符 / %d 行）" % (OUT, len(text), len(text.splitlines())))
print(text[:5200])
