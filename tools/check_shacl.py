#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SHACL 形状自检：按 M1 字段元数据机械造两条实例数据，验证 tcm-shapes.ttl 真能拦住不合规数据。

    <owl-venv>/Scripts/python.exe tools/check_shacl.py

预期输出：合规样本 conforms=True；违规样本 conforms=False 且指出缺哪个必填字段 / 类型不符。
依赖：pyshacl、rdflib、pyyaml（本机在 D:\\hermes\\workspace\\owl-venv）
"""
import io
import json
import os
import sys

import yaml
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD

TCM = Namespace("http://hermes.local/tcm-ontology#")
HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
ODIR = os.path.join(PRJ, "ontology")
XSDRANGE = {"String": XSD.string, "Integer": XSD.integer, "Decimal": XSD.decimal,
            "Date": XSD.date, "DateTime": XSD.dateTime, "Boolean": XSD.boolean}
TARGET = "Patient"          # 拿患者聚合做样本
LABEL = "患者姓名"      # 必填字段（患者姓名）
BAD = "年龄"            # 数值字段，用来造类型违规


def local(name):
    import re
    s = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
    return (re.sub(r"_+", "_", s).strip("_") or "x")


def load_m1():
    m = json.load(io.open(os.path.join(PRJ, "yaml", "manifest.json"), encoding="utf-8"))
    return yaml.safe_load(io.open(os.path.join(PRJ, "yaml", "m1-object-model.yaml"), encoding="utf-8"))


def build(skip_field=None, bad_type=None):
    """按字段元数据造一条实例；skip_field=跳过某必填字段（造违规），bad_type=把某字段写成错类型"""
    m1 = load_m1()
    agg = next(a for a in m1["aggregates"] if local(a.get("alias") or a["id"]) == TARGET)
    g = Graph()
    subj = URIRef(TCM["sample_patient_1"])
    g.add((subj, RDF.type, TCM[TARGET]))
    for at in agg["attributes"]:
        name = at["name"]
        pname = TARGET + "_" + local(name)
        if skip_field and (skip_field in (at.get("label") or "") or skip_field == name):
            continue                      # 故意缺必填
        if bad_type and (bad_type in (at.get("label") or "") or bad_type == name):
            g.add((subj, TCM[pname], Literal("不是数字")))   # 故意写错类型
            continue
        t = at.get("type")
        if t == "DictionaryRef" and at.get("dictionaryRef"):
            dr = at["dictionaryRef"]
            dct = next(d for d in m1["data_dictionaries"] if d["id"] == dr["dictionaryId"])
            ty = next(x for x in dct["types"] if x["typeCode"] == dr["typeCode"])
            item = (ty.get("items") or [{}])[0]
            g.add((subj, TCM[pname], URIRef(TCM["%s_%s" % (local(dr["typeCode"]), local(item.get("code")))])))
        elif t == "AggregateRootRef":
            g.add((subj, TCM[pname], URIRef(TCM["sample_" + local(at.get("targetAggregate") or "x")])))
        elif t == "Integer":
            g.add((subj, TCM[pname], Literal(1)))
        elif t == "Decimal":
            g.add((subj, TCM[pname], Literal("1.0", datatype=XSD.decimal)))
        elif t == "Date":
            g.add((subj, TCM[pname], Literal("2026-10-10", datatype=XSD.date)))
        elif t == "DateTime":
            g.add((subj, TCM[pname], Literal("2026-10-10T09:00:00", datatype=XSD.dateTime)))
        elif t == "Boolean":
            g.add((subj, TCM[pname], Literal(True)))
        else:
            g.add((subj, TCM[pname], Literal("示例值")))
    return g


def run(label, data, messy=False):
    shapes = Graph().parse(os.path.join(ODIR, "tcm-shapes.ttl"), format="turtle")
    ont = Graph().parse(os.path.join(ODIR, "tcm-ontology.ttl"), format="turtle")
    ok, results_graph, text = validate(data, shacl_graph=shapes, ont_graph=ont,
                                       inference="rdfs", abort_on_first=False, allow_infos=True)
    print("\n=== %s → conforms=%s" % (label, ok))
    if not ok:
        for line in text.strip().splitlines():
            if line.strip() and not line.startswith("Constraint"):
                print("    " + line[:160])
    return ok


def main():
    good = run("① 合规样本（全部必填齐备、类型正确）", build())
    bad = run("② 违规样本（缺必填「%s」+ 某数值字段写成文本）" % LABEL,
              build(skip_field=LABEL, bad_type=BAD))
    print("\n结论：%s" % ("形状真能拦（合规通过、违规被拒）✓"
                        if good and not bad else "不符合预期 ✗ 需检查形状"))
    return 0 if (good and not bad) else 1


if __name__ == "__main__":
    sys.exit(main())
