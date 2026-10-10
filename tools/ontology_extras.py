#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本体配套产物生成器（不改主生成器 yaml2owl.py，只消费 YAML 与已生成的主文件）：

    python tools/ontology_extras.py shards   # 按模型拆成 7 个分片 → ontology/shards/*.ttl
    python tools/ontology_extras.py skos     # SKOS 值域词表        → ontology/tcm-vocabulary-skos.ttl
    python tools/ontology_extras.py shacl    # SHACL 结构校验形状    → ontology/tcm-shapes.ttl
    python tools/ontology_extras.py all      # 以上全部

依赖：PyYAML（本机 docx-venv：D:\\hermes\\workspace\\docx-venv\\Scripts\\python.exe）
"""
import io
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：用 D:/hermes/workspace/docx-venv/Scripts/python.exe 运行")

BASE = "http://hermes.local/tcm-ontology#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SCALAR_RANGE = {"String": "xsd:string", "Integer": "xsd:integer", "Decimal": "xsd:decimal",
                "Date": "xsd:date", "DateTime": "xsd:dateTime", "Boolean": "xsd:boolean"}
HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)                      # 中医问诊系统/
YDIR = os.path.join(PRJ, "yaml")
ODIR = os.path.join(PRJ, "ontology")
PREFIXES = """@prefix tcm:  <http://hermes.local/tcm-ontology#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> ."""


def esc(s):
    s = "" if s is None else str(s)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def local(name):
    s = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
    s = re.sub(r"_+", "_", s).strip("_") or "x"
    return ("n" + s) if s[0].isdigit() else s


def load():
    m = json.load(io.open(os.path.join(YDIR, "manifest.json"), encoding="utf-8"))
    d = {}
    for f in m.get("model_files", []):
        d[f] = yaml.safe_load(io.open(os.path.join(YDIR, f), encoding="utf-8"))
    return d


# ---------------------------------------------------------------- 分片
def do_shards(docs):
    m1 = docs.get("m1-object-model.yaml", {})
    master = io.open(os.path.join(ODIR, "tcm-ontology.ttl"), encoding="utf-8").read()
    text = "\n".join(l for l in master.splitlines() if not l.startswith("#"))
    header, _, body = text.partition("tcm:ontology")
    body = "tcm:ontology" + body
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]

    # 各模型实体名集合（精确计算，不靠猜）
    own = {k: set() for k in ("m1", "m2", "m3", "m5", "m6", "m7", "mu")}
    for a in m1.get("aggregates", []):
        cls = local(a.get("alias") or a["id"])
        own["m1"].add(cls)
        for at in a.get("attributes", []):
            own["m1"].add("%s_%s" % (cls, local(at["name"])))
    for dct in m1.get("data_dictionaries", []):
        for t in dct.get("types", []):
            own["m1"].add("Enum_" + local(t["typeCode"]))
            for it in t.get("items", []) or []:
                own["m1"].add("%s_%s" % (local(t["typeCode"]), local(it.get("code"))))
    for a in m1.get("aggregate_associations", []):
        own["m1"].add("assoc_" + local(a["id"]))
    texts = {}
    for f, k in (("m2-behavior-model.yaml", "m2"), ("m3-rule-model.yaml", "m3"),
                 ("m5-actor-model.yaml", "m5"), ("m6-flow-model.yaml", "m6"),
                 ("m7-report-model.yaml", "m7"), ("mu-ui-model.yaml", "mu")):
        dd = docs.get(f, {})
        for key in ("behaviors", "rules", "roles", "actors", "permissions", "flows", "query_reports", "screens"):
            for x in dd.get(key, []) or []:
                nm = x.get("id") or x.get("roleId") or x.get("actorId") or x.get("permissionId") or x.get("screenId")
                if nm:
                    own[k].add(("Role_" if key == "roles" else "Actor_" if key == "actors"
                                else "Permission_" if key == "permissions" else "Behavior_" if key == "behaviors"
                                else "Rule_" if key == "rules" else "Flow_" if key == "flows"
                                else "Report_" if key == "query_reports" else "Screen_") + local(nm))
        for fl in dd.get("flows", []) or []:
            for act in fl.get("activities", []) or []:
                aid = act.get("id") or act.get("activityId") or act.get("name")
                if aid:
                    own["m6"].add("Activity_%s_%s" % (local(fl["id"]), local(aid)))

    structural = [b for b in blocks if not any(b.startswith("tcm:" + x) for k in own for x in own[k])]
    unclassified = [b.split("\n")[0] for b in structural]
    outdir = os.path.join(ODIR, "shards")
    os.makedirs(outdir, exist_ok=True)
    title = {"m1": "M1 对象模型", "m2": "M2 行为模型", "m3": "M3 规则模型", "m5": "M5 角色权限模型",
             "m6": "M6 流程模型", "m7": "M7 报表模型", "mu": "MU 界面模型"}
    stats = {}
    for k in own:
        keep = structural + [b for b in blocks if any(b.startswith("tcm:" + x) for x in own[k])]
        txt = ("# 中医问诊系统本体 · %s 分片（由 tools/ontology_extras.py 从主文件拆分）\n"
               "# 用途：分工维护与评审。完整导入 WebProtégé 请用上级目录的 tcm-ontology.ttl\n\n"
               % title[k]) + PREFIXES + "\n\n" + "\n\n".join(keep) + "\n"
        p = os.path.join(outdir, k + ".ttl")
        io.open(p, "w", encoding="utf-8", newline="\n").write(txt)
        stats[k] = (len(keep), os.path.getsize(p) / 1024)
        print("  分片 %-4s %-12s 三元组块 %3d ｜ %6.1f KB" % (k, title[k], stats[k][0], stats[k][1]))
    print("  共 %d 个分片；未分类（进入每个分片的公共部分）%d 块: %s"
          % (len(own), len(structural), ", ".join(u.replace("tcm:", "")[:24] for u in unclassified[:6])))


# ---------------------------------------------------------------- SKOS
def do_skos(docs):
    m1 = docs.get("m1-object-model.yaml", {})
    o = ["# 中医问诊系统 · 值域词表（SKOS）。由 tools/ontology_extras.py 生成，请勿手改。",
         "# 与主本体同命名空间：每个取值同时是本体里对应枚举类的个体。", "", PREFIXES, "",
         "tcm:vocabulary a skos:ConceptScheme ;",
         '    rdfs:label "中医问诊系统 · 值域词表"@zh ;',
         '    rdfs:comment "M1 数据字典的全部取值，按字典类型组织"@zh .', ""]
    n_scheme = n_concept = 0
    for dct in m1.get("data_dictionaries", []):
        for t in dct.get("types", []):
            sch = "scheme_" + local(t["typeCode"])
            o += ["tcm:%s a skos:ConceptScheme ;" % sch,
                  '    skos:prefLabel "%s"@zh ;' % esc(t.get("typeName")),
                  '    skos:notation "%s" ;' % esc(t["typeCode"]),
                  "    skos:inScheme tcm:vocabulary ;",
                  '    tcm:dictionaryId "%s" .' % esc(dct["id"]), ""]
            n_scheme += 1
            for it in t.get("items", []) or []:
                ind = "%s_%s" % (local(t["typeCode"]), local(it.get("code")))
                o += ["tcm:%s a skos:Concept, tcm:Enum_%s ;" % (ind, local(t["typeCode"])),
                      '    skos:prefLabel "%s"@zh ;' % esc(it.get("label")),
                      '    skos:notation "%s" ;' % esc(it.get("code")),
                      "    skos:inScheme tcm:%s ." % sch, ""]
                n_concept += 1
    p = os.path.join(ODIR, "tcm-vocabulary-skos.ttl")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(o))
    print("  SKOS 词表：%d 个概念方案 / %d 个概念 → %s（%.1f KB）"
          % (n_scheme, n_concept, os.path.basename(p), os.path.getsize(p) / 1024))


# ---------------------------------------------------------------- SHACL
def do_shacl(docs):
    m1 = docs.get("m1-object-model.yaml", {})
    enum = {}
    for dct in m1.get("data_dictionaries", []):
        for t in dct.get("types", []):
            enum[(dct["id"], t["typeCode"])] = "Enum_" + local(t["typeCode"])
    o = ["# 中医问诊系统 · SHACL 结构校验形状。由 tools/ontology_extras.py 从 M1 字段元数据机械生成。",
         "# 校验的是「结构契约」：必填、单值、数据类型、引用目标类。业务逻辑不在此（权威口径见 M3 与引擎）。",
         "# 注意：SHACL 无「全局唯一」表达，unique 字段用 sh:maxCount 1 近似（单值），实测见 ontology/README.md。",
         "", PREFIXES, ""]
    n_shape = n_prop = 0
    for a in m1.get("aggregates", []):
        cls = local(a.get("alias") or a["id"])
        rows = []
        for at in a.get("attributes", []):
            pname = "%s_%s" % (cls, local(at["name"]))
            bits = ['sh:path tcm:%s' % pname,
                    "sh:minCount %d" % (1 if at.get("required") else 0)]
            if at.get("unique"):
                bits.append("sh:maxCount 1")
            t = at.get("type")
            if t == "DictionaryRef" and at.get("dictionaryRef"):
                dr = at["dictionaryRef"]
                bits.append("sh:class tcm:%s" % enum.get((dr.get("dictionaryId"), dr.get("typeCode")), "Enumeration"))
            elif t == "AggregateRootRef":
                bits.append("sh:class tcm:%s" % local(at.get("targetAggregate") or "Aggregate"))
            else:
                bits.append("sh:datatype %s" % SCALAR_RANGE.get(t, "xsd:string"))
            bits.append('rdfs:label "%s"@zh' % esc(at.get("label")))
            rows.append("    sh:property [ %s ] ;" % " ;\n                 ".join(bits))
            n_prop += 1
        o.append("tcm:%sShape a sh:NodeShape ;" % cls)
        o.append('    rdfs:label "%s 结构校验"@zh ;' % esc(a.get("name")))
        o.append("    sh:targetClass tcm:%s ;" % cls)
        o.append("    skos:notation \"%s\" ;" % esc(a["id"]))
        o.extend(rows)
        if rows:
            o[-1] = o[-1].rstrip(" ;") + " ."
        else:
            o[-1] = o[-1].rstrip(" ;") + " ."
        o.append("")
        n_shape += 1
    p = os.path.join(ODIR, "tcm-shapes.ttl")
    io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(o))
    print("  SHACL 形状：%d 个节点形状 / %d 条字段约束 → %s（%.1f KB）"
          % (n_shape, n_prop, os.path.basename(p), os.path.getsize(p) / 1024))


def main():
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    docs = load()
    print("源 YAML：%s" % YDIR)
    if what in ("shards", "all"):
        print("① 分片："); do_shards(docs)
    if what in ("skos", "all"):
        print("② SKOS："); do_skos(docs)
    if what in ("shacl", "all"):
        print("③ SHACL："); do_shacl(docs)


if __name__ == "__main__":
    main()
