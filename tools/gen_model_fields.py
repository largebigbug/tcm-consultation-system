# -*- coding: utf-8 -*-
"""从 M1 抽取指定聚合（含子实体）的字段表，用于批次实现契约。

用法：python tools/gen_model_fields.py AGG-VISIT-001 AGG-DIAGNOSIS-001 ...
输出：D:/hermes/.hermes/cache/scratch/<id 串>.md
"""
import io
import os
import sys

import yaml

D = r"D:\hermes\workspace\中医问诊系统"
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
    return "；".join(bits)[:150]


def row(x):
    return "| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
        x["name"], x.get("label", ""), x.get("type"), DT.get(x.get("type"), "VARCHAR"),
        "是" if x.get("required") else "否", "是" if x.get("unique") else "否",
        x.get("defaultValue", ""), note(x))


def main():
    want = sys.argv[1:]
    m1 = yaml.safe_load(io.open(os.path.join(D, "yaml/m1-object-model.yaml"), encoding="utf-8").read())
    out = []
    for a in m1["aggregates"]:
        if want and a["id"] not in want:
            continue
        out.append("#### %s %s（alias `%s` → 表 `%s`）" % (a["id"], a["name"], a["alias"], snake(a["alias"])))
        out.append("")
        out.append("| 属性 | 标签 | 类型 | SQLite | 必填 | 唯一 | 默认 | 说明 / 字典 |")
        out.append("|---|---|---|---|---|---|---|---|")
        for x in a["attributes"]:
            out.append(row(x))
        out.append("")
        for iv in a.get("invariants", []) or []:
            out.append("- 聚合不变性 **%s**：%s（%s）" % ((iv.get("name") or "").split(" ")[0],
                                                       (iv.get("expression") or "").replace("\n", " ")[:180],
                                                       iv.get("violationMessage") or ""))
        for at in a.get("attributes", []):
            for rr in at.get("refRules", []) or []:
                out.append("- 属性级规则 `%s.%s`：%s" % (a["alias"], at["name"],
                                                     (rr.get("description") or str(rr)).replace("\n", " ")[:180]))
        for e in a.get("entities", []) or []:
            tname = snake(e["alias"])
            out.append("")
            out.append("#### 从表：%s.%s（alias `%s` → 表 `%s`，外键 `%s_id`，基数 %s）" % (
                a["alias"], e["name"], e["alias"], tname, snake(a["alias"]), e.get("cardinality")))
            out.append("")
            out.append("| 属性 | 标签 | 类型 | SQLite | 必填 | 唯一 | 默认 | 说明 / 字典 |")
            out.append("|---|---|---|---|---|---|---|---|")
            for x in e["attributes"]:
                out.append(row(x))
        out.append("")
    text = "\n".join(out)
    fname = "fields_%s.md" % (want[0].replace("AGG-", "").lower() if len(want) == 1 else "batch2")
    p = os.path.join(r"D:\hermes\.hermes\cache\scratch", fname)
    io.open(p, "w", encoding="utf-8").write(text)
    print("已写入 %s（%d 字符 / %d 行）" % (p, len(text), len(text.splitlines())))
    print(text)


if __name__ == "__main__":
    main()
