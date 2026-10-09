# -*- coding: utf-8 -*-
"""生成批次 1 实现契约的「模型字段表」段落（直接从 M1 抽取，保证与本体逐字一致）。

用法：D:/hermes/tools/docx-venv/Scripts/python.exe tools/gen_batch1_fields.py
输出：D:/hermes/.hermes/cache/scratch/batch1_fields.md
"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统"
OUT = r"D:\hermes\.hermes\cache\scratch\batch1_fields.md"
WANT = ["AGG-PATIENT-001", "AGG-SYNDROME-001", "AGG-FORMULA-001", "AGG-HERB-001"]
DT = {"String": "VARCHAR", "Integer": "INTEGER", "Decimal": "NUMERIC", "Money": "NUMERIC",
      "Date": "DATE", "DateTime": "DATETIME", "Boolean": "TINYINT", "DictionaryRef": "VARCHAR",
      "AggregateRootRef": "INTEGER", "Enum": "VARCHAR", "Text": "TEXT"}


def snake(name):
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def note(x):
    bits = []
    if x.get("dictionaryRef"):
        dr = x["dictionaryRef"]
        bits.append("字典 `%s.%s`" % (dr.get("dictionaryId"), dr.get("typeCode")))
    if x.get("enumValues"):
        bits.append("枚举：" + "/".join(map(str, x["enumValues"])))
    if x.get("maxLength"):
        bits.append("长度 %s" % x["maxLength"])
    if x.get("description"):
        bits.append(x["description"].replace("|", "/").replace("\n", " "))
    return "；".join(bits)[:130]


def main():
    m1 = yaml.safe_load(io.open(os.path.join(D, "yaml/m1-object-model.yaml"), encoding="utf-8").read())
    out = []
    for a in m1["aggregates"]:
        if a["id"] not in WANT:
            continue
        out.append("#### %s %s（alias `%s` → 表 `%s`）" % (a["id"], a["name"], a["alias"], snake(a["alias"])))
        out.append("")
        out.append("| 属性 | 标签 | 类型 | SQLite | 必填 | 唯一 | 默认 | 说明 / 字典 |")
        out.append("|---|---|---|---|---|---|---|---|")
        for x in a["attributes"]:
            out.append("| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
                x["name"], x.get("label", ""), x.get("type"), DT.get(x.get("type"), "VARCHAR"),
                "是" if x.get("required") else "否", "是" if x.get("unique") else "否",
                x.get("defaultValue", ""), note(x)))
        out.append("")
        for iv in a.get("invariants", []) or []:
            head = (iv.get("name") or "").split(" ")[0]
            out.append("- 聚合不变性 **%s**：%s（违反提示：%s）" % (
                head, (iv.get("expression") or "").replace("\n", " ")[:180],
                iv.get("violationMessage") or ""))
        for at in a.get("attributes", []):
            for rr in at.get("refRules", []) or []:
                out.append("- 属性级规则 `%s.%s`：%s" % (
                    a["alias"], at["name"], (rr.get("description") or rr.get("expression") or str(rr)).replace("\n", " ")[:180]))
        for e in a.get("entities", []) or []:
            tname = "%s_%s" % (snake(a["alias"]), snake(e["alias"]))
            out.append("")
            out.append("#### 从表：%s.%s（alias `%s` → 表 `%s`，外键 `%s_id`，基数 %s，localId `%s`）" % (
                a["alias"], e["name"], e["alias"], tname, snake(a["alias"]), e.get("cardinality"), e.get("localId")))
            out.append("")
            out.append("| 属性 | 标签 | 类型 | SQLite | 必填 | 唯一 | 说明 / 字典 |")
            out.append("|---|---|---|---|---|---|---|")
            for x in e["attributes"]:
                out.append("| `%s` | %s | %s | %s | %s | %s | %s |" % (
                    x["name"], x.get("label", ""), x.get("type"), DT.get(x.get("type"), "VARCHAR"),
                    "是" if x.get("required") else "否", "是" if x.get("unique") else "否", note(x)))
        out.append("")
    text = "\n".join(out)
    io.open(OUT, "w", encoding="utf-8").write(text)
    print("生成完成：%d 字符 → %s" % (len(text), OUT))
    for line in text.splitlines():
        if line.startswith("#### "):
            print("  " + line)


if __name__ == "__main__":
    main()
