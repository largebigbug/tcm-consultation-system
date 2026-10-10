#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把「中医问诊系统」的 7 个本体模型（YAML）转成 OWL/Turtle，供 WebProtégé 导入浏览与编辑。

用法：
    python tools/yaml2owl.py [yaml目录=yaml] [输出=tcm-ontology.ttl]

映射口径（概念层为主，规则/流程语义 OWL 无法完整表达，按个体+注记保留）：
    M1 聚合根          → owl:Class（subClassOf tcm:Aggregate）
    M1 标量字段        → owl:DatatypeProperty（domain=所属类，range=xsd:*）
    M1 DictionaryRef   → owl:ObjectProperty（range=对应枚举类）
    M1 AggregateRootRef→ owl:ObjectProperty（range=目标聚合类）
    M1 数据字典        → 每个字典类型一个 owl:Class（tcm:Enumeration）+ 每个取值一个个体
    M1 聚合关联        → owl:ObjectProperty（domain/range = 两端聚合类）
    M5 角色            → owl:Class（subClassOf tcm:Role）；角色→权限 用对象属性连接
    M5 权限/人员       → 个体（tcm:Permission / 角色的实例）
    M2 行为            → 个体（tcm:Behavior）＋注记（类型/触发/前后置/规则）
    M3 规则            → 个体（tcm:Rule）＋注记（表达式/输入输出）＋指向行为
    M6 流程            → 个体（tcm:Flow）+ 活动个体（tcm:FlowActivity）＋ hasActivity
    M7 报表            → 个体（tcm:Report）＋注记（来源对象/参数/列/排序）
    MU 屏幕            → 个体（tcm:Screen）＋注记（类型/元素数/动作数）

依赖：PyYAML（本机 docx-venv 已装）。
"""
import hashlib
import io
import json
import os
import re
import sys
import datetime

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：用 D:/hermes/workspace/docx-venv/Scripts/python.exe 运行本脚本")

BASE = "http://hermes.local/tcm-ontology#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SCALAR_RANGE = {"String": "xsd:string", "Integer": "xsd:integer", "Decimal": "xsd:decimal",
                "Date": "xsd:date", "DateTime": "xsd:dateTime", "Boolean": "xsd:boolean"}


def esc(s):
    """Turtle 字面量转义"""
    s = "" if s is None else str(s)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "").replace("\t", "\\t")


def local(name):
    """生成合法的 Turtle 本地名"""
    s = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "x"
    if s[0].isdigit():
        s = "n" + s
    return s


class Out:
    def __init__(self):
        self.lines = []
        self.n = {"class": 0, "objprop": 0, "dataprop": 0, "individual": 0, "annotation": 0}

    def w(self, s=""):
        self.lines.append(s)

    def triple(self, subj, pairs, note=None):
        """输出一个带多组谓宾的三元组块"""
        body = []
        for p, o in pairs:
            body.append("    %s %s" % (p, o))
        self.w("%s\n%s%s .\n" % (subj, " ;\n".join(body), ("  # " + note) if note else ""))

    def count(self, k, n=1):
        self.n[k] += n


def lit(label_zh, comment=None):
    """rdfs:label@zh [+ @en 由调用方补] + 可选 rdfs:comment"""
    pairs = [("rdfs:label", '"%s"@zh' % esc(label_zh))]
    if comment:
        pairs.append(("rdfs:comment", '"%s"@zh' % esc(comment)))
    return pairs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    ydir = os.path.abspath(args[0] if args else "yaml")
    outpath = os.path.abspath(args[1] if len(args) > 1 else "tcm-ontology.ttl")
    if not os.path.isdir(ydir):
        sys.exit("找不到 yaml 目录：%s" % ydir)

    man = json.load(io.open(os.path.join(ydir, "manifest.json"), encoding="utf-8"))
    files = man.get("model_files", [])
    docs, md5s = {}, []
    for f in files:
        p = os.path.join(ydir, f)
        raw = open(p, "rb").read()
        md5s.append((f, hashlib.md5(raw).hexdigest()[:16]))
        docs[f] = yaml.safe_load(raw.decode("utf-8"))
    m1 = docs.get("m1-object-model.yaml", {})
    m2 = docs.get("m2-behavior-model.yaml", {})
    m3 = docs.get("m3-rule-model.yaml", {})
    m5 = docs.get("m5-actor-model.yaml", {})
    m6 = docs.get("m6-flow-model.yaml", {})
    m7 = docs.get("m7-report-model.yaml", {})
    mu = docs.get("mu-ui-model.yaml", {})

    # 索引：聚合 id → alias/类名；字典 (dictionaryId,typeCode) → 枚举类名
    agg_class, agg_name = {}, {}
    for a in m1.get("aggregates", []):
        cls = local(a.get("alias") or a["id"])
        agg_class[a["id"]] = cls
        agg_name[a["id"]] = a.get("name", a["id"])
    enum_class, enum_meta = {}, {}
    for d in m1.get("data_dictionaries", []):
        for t in d.get("types", []):
            key = (d["id"], t["typeCode"])
            cls = "Enum_" + local(t["typeCode"])
            enum_class[key] = cls
            enum_meta[key] = (d["id"], t)

    o = Out()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    o.w("# -*- coding: utf-8 -*-")
    o.w("# 中医问诊系统 · OWL 本体（由 tools/yaml2owl.py 从本体模型 YAML 机械生成，请勿手改）")
    o.w("# 生成时间：%s" % now)
    for f, h in md5s:
        o.w("#   源文件 %s  md5[:16]=%s" % (f, h))
    o.w("")
    o.w("@prefix tcm:  <%s> ." % BASE)
    o.w("@prefix owl:  <http://www.w3.org/2002/07/owl#> .")
    o.w("@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .")
    o.w("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
    o.w("@prefix skos: <http://www.w3.org/2004/02/skos/core#> .")
    o.w("@prefix xsd:  <%s> ." % XSD)
    o.w("@prefix dcterms: <http://purl.org/dc/terms/> .")
    o.w("")
    o.triple("tcm:ontology", [
        ("a", "owl:Ontology"),
        ("rdfs:label", '"中医问诊系统本体"@zh'),
        ("rdfs:comment", '"由 7 个本体模型（M1/M2/M3/M5/M6/M7/MU）机械生成；领域：中医问诊"@zh'),
        ("dcterms:source", '"中医问诊系统-需求规格说明书-V9"'),
        ("owl:versionInfo", '"%s"' % esc(m1.get("version", "?"))),
    ])
    # ---------- 结构类 ----------
    for name, label, comment in (
        ("Aggregate", "聚合根", "可独立存在的业务对象（M1 聚合根）"),
        ("Enumeration", "枚举字典", "M1 数据字典中的取值类型"),
        ("Role", "角色", "M5 角色（权限集合）"),
        ("Actor", "人员/主体", "M5 参与者（人）"),
        ("Behavior", "行为", "M2 行为（命令/查询等）"),
        ("Permission", "权限", "M5 权限项（行为级 + 数据范围）"),
        ("Rule", "业务规则", "M3 规则（校验/计算/分派）"),
        ("Flow", "流程", "M6 流程定义"),
        ("FlowActivity", "流程活动", "M6 流程内的活动节点"),
        ("Report", "报表", "M7 查询与报表"),
        ("Screen", "界面", "MU 屏幕"),
    ):
        o.triple("tcm:" + name, [("a", "owl:Class"), ("rdfs:label", '"%s"@zh' % label),
                                ("rdfs:comment", '"%s"@zh' % comment)])
        o.count("class")
    o.w("")

    # ---------- 自定义属性声明（保证 OWL 语义清晰）----------
    o.w("# ---------- 自定义对象属性（个体/类之间的连接）----------")
    for name, dom, rng, label in (
        ("grantsPermission", "tcm:Role", "tcm:Permission", "角色授予权限"),
        ("hasRole", "tcm:Actor", "tcm:Role", "人员具有角色"),
        ("appliesRule", "tcm:Behavior", "tcm:Rule", "行为适用规则"),
        ("hasActivity", "tcm:Flow", "tcm:FlowActivity", "流程包含活动"),
    ):
        o.triple("tcm:" + name, [("a", "owl:ObjectProperty"), ("rdfs:domain", dom), ("rdfs:range", rng),
                                 ("rdfs:label", '"%s"@zh' % label)])
        o.count("objprop")
    o.w("")
    o.w("# ---------- 自定义注记属性 ----------")
    for name, label in (
        ("lifecycle", "生命周期"), ("required", "是否必填"), ("unique", "是否唯一"),
        ("defaultValue", "默认值"), ("dictionaryId", "所属字典"), ("sortOrder", "排序"),
        ("inverseLabel", "反向角色名"), ("cardinality", "基数"), ("referenceField", "引用字段"),
        ("targetType", "目标类型"), ("dataScope", "数据范围"), ("actorType", "主体类型"),
        ("behaviorType", "行为类型"), ("triggerType", "触发方式"), ("ownerEntity", "所属实体ID"),
        ("ownerEntityName", "所属实体"), ("precondition", "前置条件"), ("postcondition", "后置条件"),
        ("appliedRule", "适用规则ID"), ("ruleType", "规则类型"), ("outputType", "输出类型"),
        ("expression", "规则表达式"), ("inputParam", "输入参数"), ("reusedByBehavior", "被行为引用"),
        ("flowType", "流程类型"), ("businessObject", "涉及业务对象"), ("involvedRole", "涉及角色"),
        ("startActivity", "起始活动"), ("endActivity", "结束活动"), ("performer", "执行角色"),
        ("activityType", "活动类型"), ("behaviorRef", "对应行为"), ("sourceObject", "来源对象"),
        ("resultColumn", "结果列"), ("parameter", "参数"), ("groupBy", "分组字段"),
        ("screenType", "屏幕类型"), ("elementCount", "元素数"), ("actionCount", "动作数"),
    ):
        o.triple("tcm:" + name, [("a", "owl:AnnotationProperty"), ("rdfs:label", '"%s"@zh' % label)])
        o.count("annotation")
    o.w("")

    # ---------- M1 聚合根 → 类；字段 → 属性 ----------
    fields_done = set()
    for a in m1.get("aggregates", []):
        cls = agg_class[a["id"]]
        o.w("# ---------- %s %s ----------" % (a["id"], a.get("name")))
        o.triple("tcm:" + cls, [
            ("a", "owl:Class"),
            ("rdfs:subClassOf", "tcm:Aggregate"),
            ("rdfs:label", '"%s"@zh' % esc(a.get("name"))),
            ("rdfs:label", '"%s"@en' % esc(a.get("alias"))),
            ("skos:notation", '"%s"' % esc(a["id"])),
            ("rdfs:comment", '"%s"@zh' % esc(a.get("description"))),
        ] + ([("tcm:lifecycle", '"%s"@zh' % esc(" → ".join(a["lifecycle"])))] if a.get("lifecycle") else []))
        o.count("class")
        for at in a.get("attributes", []):
            pname = "%s_%s" % (cls, local(at["name"]))
            if pname in fields_done:
                continue
            fields_done.add(pname)
            ann = [("rdfs:label", '"%s"@zh' % esc(at.get("label"))),
                   ("skos:notation", '"%s"' % esc(at["name"]))]
            if at.get("description"):
                ann.append(("rdfs:comment", '"%s"@zh' % esc(at["description"])))
            ann.append(("tcm:required", '"%s"' % ("true" if at.get("required") else "false")))
            if at.get("unique"):
                ann.append(("tcm:unique", '"true"'))
            if at.get("defaultValue") not in (None, ""):
                ann.append(("tcm:defaultValue", '"%s"' % esc(at["defaultValue"])))
            t = at.get("type")
            if t == "DictionaryRef" and at.get("dictionaryRef"):
                dr = at["dictionaryRef"]
                rng = enum_class.get((dr.get("dictionaryId"), dr.get("typeCode")))
                o.triple("tcm:" + pname, [("a", "owl:ObjectProperty"), ("rdfs:domain", "tcm:" + cls),
                                          ("rdfs:range", "tcm:" + (rng or "Enumeration"))] + ann)
                o.count("objprop")
            elif t == "AggregateRootRef":
                tgt = agg_class.get(at.get("targetAggregate"), "Aggregate")
                o.triple("tcm:" + pname, [("a", "owl:ObjectProperty"), ("rdfs:domain", "tcm:" + cls),
                                          ("rdfs:range", "tcm:" + tgt)] + ann)
                o.count("objprop")
            else:
                o.triple("tcm:" + pname, [("a", "owl:DatatypeProperty"), ("rdfs:domain", "tcm:" + cls),
                                          ("rdfs:range", SCALAR_RANGE.get(t, "xsd:string"))] + ann)
                o.count("dataprop")
            for rr in (at.get("refRules") or []):
                o.count("annotation")
    o.w("")

    # ---------- M1 数据字典 → 枚举类 + 个体 ----------
    o.w("# ---------- M1 数据字典（枚举）----------")
    for d in m1.get("data_dictionaries", []):
        for t in d.get("types", []):
            cls = enum_class[(d["id"], t["typeCode"])]
            o.triple("tcm:" + cls, [
                ("a", "owl:Class"), ("rdfs:subClassOf", "tcm:Enumeration"),
                ("rdfs:label", '"%s"@zh' % esc(t.get("typeName"))),
                ("skos:notation", '"%s"' % esc(t["typeCode"])),
                ("rdfs:comment", '"%s"@zh' % esc(t.get("description"))),
                ("tcm:dictionaryId", '"%s"' % esc(d["id"])),
            ])
            o.count("class")
            for it in t.get("items", []) or []:
                ind = "%s_%s" % (local(t["typeCode"]), local(it.get("code")))
                o.triple("tcm:" + ind, [
                    ("a", "owl:NamedIndividual"), ("a", "tcm:" + cls),
                    ("rdfs:label", '"%s"@zh' % esc(it.get("label"))),
                    ("skos:notation", '"%s"' % esc(it.get("code"))),
                ] + ([("tcm:sortOrder", '"%s"' % esc(it.get("sortOrder")))] if it.get("sortOrder") is not None else []))
                o.count("individual")
    o.w("")

    # ---------- M1 聚合关联 → 对象属性 ----------
    o.w("# ---------- M1 聚合关联 ----------")
    for asso in m1.get("aggregate_associations", []):
        pname = "assoc_" + local(asso["id"])
        ann = [("rdfs:label", '"%s"@zh' % esc(asso.get("sourceRole") or asso["id"])),
               ("skos:notation", '"%s"' % esc(asso["id"]))]
        if asso.get("targetRole"):
            ann.append(("tcm:inverseLabel", '"%s"@zh' % esc(asso["targetRole"])))
        if asso.get("cardinality"):
            ann.append(("tcm:cardinality", '"%s"' % esc(asso["cardinality"])))
        if asso.get("referenceField"):
            ann.append(("tcm:referenceField", '"%s"' % esc(asso["referenceField"])))
        o.triple("tcm:" + pname, [("a", "owl:ObjectProperty"),
                                  ("rdfs:domain", "tcm:" + agg_class.get(asso.get("sourceAggregate"), "Aggregate")),
                                  ("rdfs:range", "tcm:" + agg_class.get(asso.get("targetAggregate"), "Aggregate"))] + ann)
        o.count("objprop")
    o.w("")

    # ---------- M5 角色 / 权限 / 人员 ----------
    o.w("# ---------- M5 角色与权限 ----------")
    perm_ind = {}
    for perm in m5.get("permissions", []):
        ind = "Permission_" + local(perm["permissionId"])
        perm_ind[perm["permissionId"]] = ind
        o.triple("tcm:" + ind, [
            ("a", "owl:NamedIndividual"), ("a", "tcm:Permission"),
            ("rdfs:label", '"%s"@zh' % esc(perm.get("name"))),
            ("skos:notation", '"%s"' % esc(perm["permissionId"])),
            ("tcm:targetType", '"%s"' % esc(perm.get("targetType"))),
            ("tcm:dataScope", '"%s"' % esc(perm.get("dataScope"))),
        ] + ([("rdfs:comment", '"%s"@zh' % esc(perm.get("description")))] if perm.get("description") else []))
        o.count("individual")
    role_cls = {}
    for role in m5.get("roles", []):
        ind = "Role_" + local(role["roleId"])
        role_cls[role["roleId"]] = ind
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Role"),
                 ("rdfs:label", '"%s"@zh' % esc(role.get("name"))),
                 ("skos:notation", '"%s"' % esc(role["roleId"]))]
        if role.get("description"):
            pairs.append(("rdfs:comment", '"%s"@zh' % esc(role["description"])))
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
        for pid in role.get("permissions") or []:
            if pid in perm_ind:
                o.triple("tcm:" + ind, [("tcm:grantsPermission", "tcm:" + perm_ind[pid])])
                o.count("annotation")
    for actor in m5.get("actors", []):
        ind = "Actor_" + local(actor["actorId"])
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Actor"),
                 ("rdfs:label", '"%s"@zh' % esc(actor.get("name"))),
                 ("skos:notation", '"%s"' % esc(actor["actorId"])),
                 ("tcm:actorType", '"%s"' % esc(actor.get("actorType")))]
        for rid in actor.get("roles") or []:
            if rid in role_cls:
                pairs.append(("tcm:hasRole", "tcm:" + role_cls[rid]))
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
    o.w("")

    # ---------- M2 行为 ----------
    o.w("# ---------- M2 行为 ----------")
    for b in m2.get("behaviors", []):
        ind = "Behavior_" + local(b["id"])
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Behavior"),
                 ("rdfs:label", '"%s"@zh' % esc(b.get("name"))),
                 ("skos:notation", '"%s"' % esc(b["id"])),
                 ("tcm:behaviorType", '"%s"' % esc(b.get("behaviorType"))),
                 ("tcm:triggerType", '"%s"' % esc(b.get("triggerType"))),
                 ("tcm:ownerEntity", '"%s"' % esc(b.get("ownerEntity"))),
                 ("tcm:ownerEntityName", '"%s"@zh' % esc(agg_name.get(b.get("ownerEntity"), "")))]
        if b.get("description"):
            pairs.append(("rdfs:comment", '"%s"@zh' % esc(b["description"])))
        for pre in b.get("preconditions") or []:
            pairs.append(("tcm:precondition", '"%s"@zh' % esc(pre)))
        for post in b.get("postconditions") or []:
            if isinstance(post, dict):
                pairs.append(("tcm:postcondition", '"%s"' % esc(json.dumps(post, ensure_ascii=False))))
            else:
                pairs.append(("tcm:postcondition", '"%s"@zh' % esc(post)))
        for r in b.get("appliedRules") or []:
            pairs.append(("tcm:appliedRule", '"%s"' % esc(r)))
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
        o.count("annotation", len(pairs))
    o.w("")

    # ---------- M3 规则 ----------
    o.w("# ---------- M3 规则 ----------")
    rule_ind = {}
    for r in m3.get("rules", []):
        ind = "Rule_" + local(r["id"])
        rule_ind[r["id"]] = ind
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Rule"),
                 ("rdfs:label", '"%s"@zh' % esc(r.get("name"))),
                 ("skos:notation", '"%s"' % esc(r["id"])),
                 ("tcm:ruleType", '"%s"' % esc(r.get("ruleType"))),
                 ("tcm:outputType", '"%s"' % esc(r.get("outputType")))]
        if r.get("description"):
            pairs.append(("rdfs:comment", '"%s"@zh' % esc(r["description"])))
        if r.get("expression"):
            pairs.append(("tcm:expression", '"%s"' % esc(json.dumps(r["expression"], ensure_ascii=False))))
        for ip in r.get("inputParams") or []:
            pairs.append(("tcm:inputParam", '"%s"' % esc(json.dumps(ip, ensure_ascii=False))))
        for rb in r.get("reusedBy") or []:
            pairs.append(("tcm:reusedByBehavior", '"%s"' % esc(rb)))
            o.triple("tcm:Behavior_" + local(rb), [("tcm:appliesRule", "tcm:" + ind)])
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
    o.w("")

    # ---------- M6 流程 ----------
    o.w("# ---------- M6 流程 ----------")
    for fl in m6.get("flows", []):
        find = "Flow_" + local(fl["id"])
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Flow"),
                 ("rdfs:label", '"%s"@zh' % esc(fl.get("name"))),
                 ("skos:notation", '"%s"' % esc(fl["id"])),
                 ("tcm:flowType", '"%s"' % esc(fl.get("flowType")))]
        if fl.get("description"):
            pairs.append(("rdfs:comment", '"%s"@zh' % esc(fl["description"])))
        for ref in fl.get("businessObjectRefs") or []:
            pairs.append(("tcm:businessObject", '"%s"' % esc(ref)))
        for rr in fl.get("roleRefs") or []:
            pairs.append(("tcm:involvedRole", '"%s"' % esc(rr)))
        if fl.get("startActivity"):
            pairs.append(("tcm:startActivity", '"%s"' % esc(fl["startActivity"])))
        for ea in fl.get("endActivities") or []:
            pairs.append(("tcm:endActivity", '"%s"' % esc(ea)))
        o.triple("tcm:" + find, pairs)
        o.count("individual")
        for act in fl.get("activities", []) or []:
            aid = act.get("id") or act.get("activityId") or act.get("name")
            aind = "Activity_%s_%s" % (local(fl["id"]), local(aid))
            ap = [("a", "owl:NamedIndividual"), ("a", "tcm:FlowActivity"),
                  ("rdfs:label", '"%s"@zh' % esc(act.get("name") or aid)),
                  ("skos:notation", '"%s"' % esc(aid)),
                  ("tcm:activityType", '"%s"' % esc(act.get("activityType") or act.get("type")))]
            if act.get("performer") or act.get("roleRef"):
                ap.append(("tcm:performer", '"%s"' % esc(act.get("performer") or act.get("roleRef"))))
            if act.get("description"):
                ap.append(("rdfs:comment", '"%s"@zh' % esc(act["description"])))
            o.triple("tcm:" + aind, ap)
            o.count("individual")
            o.triple("tcm:" + find, [("tcm:hasActivity", "tcm:" + aind)])
    o.w("")

    # ---------- M7 报表 ----------
    o.w("# ---------- M7 报表 ----------")
    for rp in m7.get("query_reports", []):
        ind = "Report_" + local(rp["id"])
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Report"),
                 ("rdfs:label", '"%s"@zh' % esc(rp.get("name"))),
                 ("skos:notation", '"%s"' % esc(rp["id"]))]
        if rp.get("alias"):
            pairs.append(("rdfs:label", '"%s"@en' % esc(rp["alias"])))
        if rp.get("description"):
            pairs.append(("rdfs:comment", '"%s"@zh' % esc(rp["description"])))
        if rp.get("behaviorRef"):
            pairs.append(("tcm:behaviorRef", '"%s"' % esc(rp["behaviorRef"])))
        for so in rp.get("sourceObjects") or []:
            if isinstance(so, dict):
                pairs.append(("tcm:sourceObject", '"%s%s"' % (esc(so.get("objectRef")),
                                                             " (主表)" if so.get("primary") else "")))
        for col in rp.get("resultColumns") or []:
            if isinstance(col, dict):
                pairs.append(("tcm:resultColumn", '"%s"' % esc(json.dumps(col, ensure_ascii=False))))
        for p_ in rp.get("parameters") or []:
            pairs.append(("tcm:parameter", '"%s"' % esc(json.dumps(p_, ensure_ascii=False))))
        for g in rp.get("groupBy") or []:
            pairs.append(("tcm:groupBy", '"%s"' % esc(g if isinstance(g, str) else json.dumps(g, ensure_ascii=False))))
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
    o.w("")

    # ---------- MU 屏幕 ----------
    o.w("# ---------- MU 界面 ----------")
    for sc in mu.get("screens", []):
        ind = "Screen_" + local(sc["screenId"])
        pairs = [("a", "owl:NamedIndividual"), ("a", "tcm:Screen"),
                 ("rdfs:label", '"%s"@zh' % esc(sc.get("name"))),
                 ("skos:notation", '"%s"' % esc(sc["screenId"])),
                 ("tcm:screenType", '"%s"' % esc(sc.get("screenType")))]
        if sc.get("elements") is not None:
            pairs.append(("tcm:elementCount", '"%s"' % len(sc.get("elements") or [])))
        if sc.get("actions") is not None:
            pairs.append(("tcm:actionCount", '"%s"' % len(sc.get("actions") or [])))
        o.triple("tcm:" + ind, pairs)
        o.count("individual")
    o.w("")

    head = "# 统计：类 %d | 对象属性 %d | 数据属性 %d | 个体 %d | 注记三元组 ≈%d\n" % (
        o.n["class"], o.n["objprop"], o.n["dataprop"], o.n["individual"], o.n["annotation"])
    txt = head.join([o.lines[0] + "\n", "\n" + "\n".join(o.lines[1:])])
    io.open(outpath, "w", encoding="utf-8", newline="\n").write(txt)
    print("已生成 %s（%.1f KB）" % (outpath, os.path.getsize(outpath) / 1024))
    print("统计：类 %d ｜ 对象属性 %d ｜ 数据属性 %d ｜ 个体 %d" % (
        o.n["class"], o.n["objprop"], o.n["dataprop"], o.n["individual"]))
    print("源模型：%s" % ", ".join("%s(%s)" % (f, h) for f, h in md5s))


if __name__ == "__main__":
    main()
