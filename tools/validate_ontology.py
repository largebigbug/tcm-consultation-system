#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中医问诊系统 本体模型跨文件一致性校验器（阶段二）

用法：
    D:/hermes/workspace/docx-venv/Scripts/python.exe validate_ontology.py [yaml目录]

字段名以 ontology_modeling_framework_v9.md 与 reference-example/ 为准：
  M1 aggregates[].id / data_dictionaries / aggregate_associations
  M2 behaviors[].id|ownerEntity|behaviorType|triggerType|appliedRules|requiredPermissions|syncTriggers[].behaviorRef|queryReportRef
  M3 rules[].id|reusedBy
  M5 actors|roles|permissions[].permissionId|targetType|targetRef
  M6 flows[].id|activities[].activityId|roleRef|behaviorRef|subFlowRef|branches[].ruleRef|approvalOutcome
  M7 query_reports[].id|objectType|behaviorRef|sourceObjects[].primary|reportOptions
  MU application.menus|screens[].screenId|layout|elements[].dataBinding|actions[].behaviorRef|permissionRef
"""
import io
import json
import os
import re
import sys

import yaml

FILES = ["m1-object-model.yaml", "m2-behavior-model.yaml", "m3-rule-model.yaml",
         "m5-actor-model.yaml", "m6-flow-model.yaml", "m7-report-model.yaml",
         "mu-ui-model.yaml"]

PROBLEMS = []
NOTES = []


def bad(msg):
    PROBLEMS.append(msg)


def note(msg):
    NOTES.append(msg)


def ok(msg):
    print("  [OK] " + msg)


def as_list(v):
    """permissionRef / behaviorRef 允许标量或列表（与 reference-example 一致）。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def load(path):
    if not os.path.exists(path):
        return None
    try:
        return yaml.safe_load(io.open(path, encoding="utf-8").read())
    except Exception as exc:  # noqa: BLE001
        bad("%s 解析失败：%s" % (os.path.basename(path), exc))
        return None


def main(root):
    docs = {}
    print("=== 模型文件 ===")
    for f in FILES:
        p = os.path.join(root, f)
        docs[f] = load(p)
        print("  %-24s %s  %d bytes" % (f, "OK" if docs[f] is not None else "缺失",
                                        os.path.getsize(p) if os.path.exists(p) else 0))
    mp = os.path.join(root, "manifest.json")
    if os.path.exists(mp):
        man = json.load(io.open(mp, encoding="utf-8"))
        missing = [f for f in man.get("model_files", []) if not os.path.exists(os.path.join(root, f))]
        print("  manifest.json            OK  缺失文件：%s" % (missing or "无"))
        if missing:
            bad("manifest.model_files 指向不存在的文件：%s" % missing)
    else:
        note("缺少 manifest.json（框架约定为可选）")

    m1, m2, m3, m5, m6, m7, mu = (docs[f] for f in FILES)

    # ---------- M1 ----------
    attrs = {}
    agg_ids = {}
    if m1:
        print("\n=== M1 对象模型 ===")
        for a in m1.get("aggregates", []):
            aid, alias = a.get("id"), a.get("alias")
            if aid in agg_ids:
                bad("M1 聚合 id 重复：%s" % aid)
            agg_ids[aid] = a
            names = [x.get("name") for x in a.get("attributes", [])]
            if len(names) != len(set(names)):
                bad("M1 %s 属性名重复" % aid)
            for key in (aid, alias):
                if key:
                    attrs[key] = set(names)
            for ent in a.get("entities", []) or []:
                en = [x.get("name") for x in ent.get("attributes", [])]
                for key in (aid, alias):
                    if not key:
                        continue
                    attrs["%s.%s" % (key, ent.get("name"))] = set(en)
                    if ent.get("alias"):
                        attrs["%s.%s" % (key, ent.get("alias"))] = set(en)
        dicts = m1.get("data_dictionaries", []) or []
        assocs = m1.get("aggregate_associations", []) or []
        ok("聚合 %d / 字典 %d / 关联 %d" % (len(m1.get("aggregates", [])), len(dicts), len(assocs)))
        for x in assocs:
            for k in ("sourceAggregate", "targetAggregate"):
                if x.get(k) and x[k] not in agg_ids and x[k] not in attrs:
                    bad("M1 关联 %s %s 悬空：%s" % (x.get("id"), k, x[k]))
        for a in m1.get("aggregates", []):
            for at in a.get("attributes", []):
                for rr in at.get("refRules", []) or []:
                    tgt = rr.get("targetField") if isinstance(rr, dict) else None
                    if tgt and "." in tgt and tgt.split(".")[0] not in attrs:
                        note("M1 %s.%s refRules 目标 %s 不在本模型（可能为字典/平台用户）"
                             % (a.get("id"), at.get("name"), tgt))

    # ---------- M2 ----------
    beh = {}
    if m2:
        print("\n=== M2 行为模型 ===")
        for b in m2.get("behaviors", []):
            if b["id"] in beh:
                bad("M2 行为 id 重复：%s" % b["id"])
            beh[b["id"]] = b
        kinds = {}
        for b in beh.values():
            k = (b.get("behaviorType"), b.get("triggerType"))
            kinds[k] = kinds.get(k, 0) + 1
        ok("行为 %d 个 · %s" % (len(beh), kinds))
        for b in beh.values():
            owner = b.get("ownerEntity")
            if owner and owner not in agg_ids:
                bad("M2 %s ownerEntity 悬空：%s" % (b["id"], owner))
            for st in b.get("syncTriggers", []) or []:
                t = st.get("behaviorRef") if isinstance(st, dict) else st
                if t and t not in beh:
                    bad("M2 %s syncTriggers 目标悬空：%s" % (b["id"], t))
                if t == b["id"]:
                    bad("M2 %s syncTriggers 自引用" % b["id"])
            for p in b.get("requiredPermissions", []) or []:
                if m5 and p not in {x["permissionId"] for x in m5.get("permissions", [])}:
                    bad("M2 %s requiredPermissions 悬空：%s" % (b["id"], p))

    # ---------- M3 ----------
    rules = {}
    if m3:
        print("\n=== M3 规则模型 ===")
        for r in m3.get("rules", []):
            if r["id"] in rules:
                bad("M3 规则 id 重复：%s" % r["id"])
            rules[r["id"]] = r
        ok("规则 %d 条：%s" % (len(rules), ", ".join(rules)))
        used_by_m2 = set()
        for b in beh.values():
            for rid in b.get("appliedRules", []) or []:
                rid = rid.get("ruleId") if isinstance(rid, dict) else rid
                if rid and rid not in rules:
                    note("M2 %s appliedRules %s 不在 M3（应为 M1 属性级/聚合级规则）" % (b["id"], rid))
                used_by_m2.add(rid)
        used_by_m6 = set()
        if m6:
            for fl in m6.get("flows", []):
                for a in fl.get("activities", []):
                    if a.get("ruleRef"):
                        used_by_m6.add(a["ruleRef"])
                    for br in a.get("branches", []) or []:
                        if br.get("ruleRef"):
                            used_by_m6.add(br["ruleRef"])
        orphan = [r for r in rules if r not in used_by_m2 and r not in used_by_m6]
        if orphan:
            bad("M3 存在既不被 M2 也不被 M6 引用的孤立规则：%s" % orphan)
        for rid in sorted(used_by_m6):
            if rid not in rules:
                bad("M6 网关 ruleRef 悬空：%s" % rid)

    # ---------- M5 ----------
    roles, perm = {}, {}
    if m5:
        print("\n=== M5 角色模型 ===")
        for r in m5.get("roles", []):
            if r["roleId"] in roles:
                bad("M5 角色 id 重复：%s" % r["roleId"])
            roles[r["roleId"]] = r
        for x in m5.get("permissions", []):
            if x["permissionId"] in perm:
                bad("M5 权限 id 重复：%s" % x["permissionId"])
            perm[x["permissionId"]] = x
        ok("角色 %d 个 / 权限 %d 条 / 角色主体 %d 个"
           % (len(roles), len(perm), len(m5.get("actors", []) or [])))
        for x in perm.values():
            tt, tr = x.get("targetType"), x.get("targetRef")
            if tt in ("BEHAVIOR", "COMMAND", "QUERY") and m2 and tr not in beh:
                bad("M5 %s targetRef 悬空：%s" % (x["permissionId"], tr))
            if tt == "REPORT" and m7:
                if tr not in {o.get("id") for o in m7.get("query_reports", [])}:
                    bad("M5 %s REPORT targetRef 悬空：%s" % (x["permissionId"], tr))
        assigned = set()
        for r in roles.values():
            for p in r.get("permissions", []) or []:
                if p not in perm:
                    bad("M5 %s permissions 悬空：%s" % (r["roleId"], p))
                assigned.add(p)
        if set(perm) - assigned:
            bad("M5 未被任何角色引用的权限：%s" % sorted(set(perm) - assigned))
        for a in m5.get("actors", []) or []:
            for r in a.get("roles", []) or []:
                if r not in roles:
                    bad("M5 主体 %s roles 悬空：%s" % (a.get("actorId"), r))

    # ---------- M6 ----------
    if m6:
        print("\n=== M6 流程模型 ===")
        flows = {f["id"]: f for f in m6.get("flows", [])}
        for fid, fl in flows.items():
            acts = {a["activityId"]: a for a in fl["activities"]}
            errs = []
            for a in fl["activities"]:
                if a.get("roleRef") and a["roleRef"] not in roles:
                    errs.append("角色悬空 %s@%s" % (a["roleRef"], a["activityId"]))
                if a.get("behaviorRef") and a["behaviorRef"] not in beh:
                    errs.append("行为悬空 %s@%s" % (a["behaviorRef"], a["activityId"]))
                if a.get("subFlowRef") and a["subFlowRef"] not in flows:
                    errs.append("子流悬空 %s@%s" % (a["subFlowRef"], a["activityId"]))
                if a.get("subFlowRef") == fid:
                    errs.append("子流自引用 %s" % fid)
                for n in a.get("nextActivities", []) or []:
                    if n not in acts:
                        errs.append("后继悬空 %s->%s" % (a["activityId"], n))
                if a["activityType"] in ("USER_TASK", "APPROVAL_TASK") and not a.get("roleRef"):
                    errs.append("人工活动缺 roleRef %s" % a["activityId"])
                if a["activityType"] == "GATEWAY":
                    br = a.get("branches", []) or []
                    if len(br) < 2:
                        errs.append("网关分支 <2 %s" % a["activityId"])
                    if len([b for b in br if b.get("isDefault")]) > 1:
                        errs.append("网关多个默认分支 %s" % a["activityId"])
                    for b in br:
                        if b.get("targetActivity") not in acts:
                            errs.append("网关目标悬空 %s" % b.get("targetActivity"))
                        if not (b.get("ruleRef") or b.get("conditionExpression") or b.get("approvalOutcome") or b.get("isDefault")):
                            errs.append("网关分支缺判定条件 %s" % a["activityId"])
            ends = {a["activityId"] for a in fl["activities"] if a["activityType"] == "END"}
            if not fl.get("endActivities") or not set(fl["endActivities"]) <= ends:
                errs.append("endActivities 不合法")
            seen, stack = set(), [fl.get("startActivity")]
            while stack:
                cur = stack.pop()
                if cur in seen or cur not in acts:
                    continue
                seen.add(cur)
                a = acts[cur]
                stack += list(a.get("nextActivities", []) or [])
                if a["activityType"] == "GATEWAY":
                    stack += [b["targetActivity"] for b in a.get("branches", []) or []]
            if set(acts) - seen:
                errs.append("不可达活动 %s" % sorted(set(acts) - seen))
            if fl.get("flowType") == "APPROVAL":
                if not any(a["activityType"] == "APPROVAL_TASK" for a in fl["activities"]):
                    errs.append("审批流缺 APPROVAL_TASK")
                tb = (fl.get("trigger") or {}).get("behaviorRef")
                if not tb:
                    errs.append("审批流缺 trigger.behaviorRef")
                elif tb not in beh:
                    errs.append("trigger.behaviorRef 悬空 %s" % tb)
                outs = set()
                for a in fl["activities"]:
                    outs |= set(a.get("approvalOutcomes", []) or [])
                if not {"APPROVE", "REJECT"} <= outs:
                    errs.append("审批结论未覆盖通过/驳回：%s" % outs)
            print("  [%s] %s · 活动 %d · %s" % (fid, fl.get("flowType"), len(acts), errs or "通过"))
            for e in errs:
                bad("M6 %s：%s" % (fid, e))

    # ---------- M7 ----------
    if m7:
        print("\n=== M7 报表模型 ===")
        objs = m7.get("query_reports", []) or []
        seen = set()
        for o in objs:
            oid = o.get("id")
            if oid in seen:
                bad("M7 id 重复：%s" % oid)
            seen.add(oid)
            br = o.get("behaviorRef")
            if br not in beh:
                bad("M7 %s behaviorRef 悬空：%s" % (oid, br))
            elif beh[br].get("queryReportRef") != oid:
                bad("M7 一对一断裂：%s.behaviorRef=%s 而 M2.queryReportRef=%s"
                    % (oid, br, beh[br].get("queryReportRef")))
            srcs = o.get("sourceObjects", []) or []
            if sum(1 for s in srcs if s.get("primary")) != 1:
                bad("M7 %s primary 来源数 != 1" % oid)
            for k in ("ruleRefs", "requiredPermissions", "roleRefs", "flowRefs"):
                if k in o:
                    bad("M7 %s 出现禁止字段 %s" % (oid, k))
            if o.get("objectType") == "REPORT" and not o.get("reportOptions"):
                bad("M7 %s REPORT 缺 reportOptions" % oid)
            if o.get("objectType") != "REPORT" and o.get("reportOptions"):
                bad("M7 %s 非 REPORT 却含 reportOptions" % oid)
            # 约定 13：非 BASE 条件组必须显式声明机读开关（switchParameterRef 等），
            # 且开关参数存在、非必填；显式 switchActivateValue 须与参数类型相符（否则无法定位开关、
            # 引擎会静默按「整组恒参与」容错 —— QR-HERB-STOCK-001 曾因此忽略 onlyAlert）。
            # M7 参数容器键为 `parameters`（沿用批次 3 抽取口径；queryParameters 仅作兼容兜底）
            params = {pp.get("name"): pp for pp in (o.get("parameters") or o.get("queryParameters") or [])}
            groups = {}
            for cond in (o.get("conditions") or []):
                groups.setdefault(cond.get("group") or "BASE", []).append(cond)
            for gname, members in groups.items():
                if gname == "BASE":
                    continue
                refs = {c.get("switchParameterRef") for c in members if c.get("switchParameterRef")}
                if len(refs) != 1:
                    bad("M7 %s 条件组 %s 未显式声明 switchParameterRef（约定 13：%d 个成员、%d 种开关）"
                        % (oid, gname, len(members), len(refs)))
                    continue
                ref = next(iter(refs))
                spec = params.get(ref)
                if not spec:
                    bad("M7 %s 条件组 %s 的开关参数 %s 不在 queryParameters 中（约定 13）" % (oid, gname, ref))
                    continue
                if spec.get("required"):
                    bad("M7 %s 条件组 %s 的开关参数 %s 不得为必填（约定 13）" % (oid, gname, ref))
                acts = [c.get("switchActivateValue") for c in members if c.get("switchParameterRef") == ref]
                acts = [a for a in acts if a is not None]
                if acts:
                    if len({json.dumps(a, ensure_ascii=False, sort_keys=True) for a in acts}) != 1:
                        bad("M7 %s 条件组 %s 各成员的 switchActivateValue 不一致" % (oid, gname))
                    act = acts[0]
                    if spec.get("dataType") == "Boolean" and not isinstance(act, bool):
                        bad("M7 %s 条件组 %s 开关 %s 为 Boolean，switchActivateValue 必须是布尔值：%r"
                            % (oid, gname, ref, act))
                    if spec.get("dataType") == "Enum":
                        ev = [str(x).upper() for x in (spec.get("enumValues") or [])]
                        if str(act).upper() not in ev:
                            bad("M7 %s 条件组 %s 开关 %s 的 switchActivateValue=%s 不在 enumValues %s 内"
                                % (oid, gname, ref, act, ev))
                else:
                    ev = [str(x).upper() for x in (spec.get("enumValues") or [])]
                    if "BOTH" not in ev:
                        bad("M7 %s 条件组 %s 用 Enum 开关 %s，但 enumValues %s 缺 BOTH（约定 13）"
                            % (oid, gname, ref, ev))
                    for c in members:
                        kind = str(c.get("triggerKind") or "").upper()
                        if not kind:
                            bad("M7 %s 条件组 %s 成员 %s 缺 triggerKind（Enum 开关模式，约定 13）"
                                % (oid, gname, c.get("conditionId")))
                        elif kind not in ev:
                            bad("M7 %s 条件组 %s 成员 triggerKind=%s 不在开关 enumValues %s 内"
                                % (oid, gname, kind, ev))
        ok("条件组开关（约定 13）：%d 个非 BASE 组已显式声明"
           % sum(1 for o in objs for c in (o.get("conditions") or [])
                 if (c.get("group") or "BASE") != "BASE" and c.get("switchParameterRef")))
        qbeh = {b["id"] for b in beh.values() if b.get("behaviorType") == "QUERY"}
        miss = sorted(x for x in qbeh if not beh[x].get("queryReportRef"))
        if miss:
            bad("M2 查询行为未声明 queryReportRef：%s" % miss)
        ok("查询报表对象 %d 个（覆盖查询行为 %d/%d）" % (len(objs), len(qbeh) - len(miss), len(qbeh)))

    # ---------- MU ----------
    if mu:
        print("\n=== MU 界面模型 ===")
        screens = {}
        for s in mu.get("screens", []):
            if s["screenId"] in screens:
                bad("MU screenId 重复：%s" % s["screenId"])
            screens[s["screenId"]] = s
        menus = (mu.get("application") or {}).get("menus", []) or []
        for m in menus:
            kids = m.get("children", []) or []
            if not kids:
                bad("MU 一级菜单无子菜单：%s" % (m.get("menuId") or m.get("name")))
            for k in kids:
                if k.get("screenRef") and k["screenRef"] not in screens:
                    bad("MU 二级菜单 screenRef 悬空：%s -> %s" % (k.get("menuId") or k.get("name"), k["screenRef"]))
                if k.get("children"):
                    bad("MU 菜单层级超过两级：%s" % (k.get("menuId") or k.get("name")))
        used_beh, used_perm, tot_el, tot_ac = set(), set(), 0, 0
        for sid, s in screens.items():
            els = s.get("elements", []) or []
            eids = [e["id"] for e in els]
            if len(eids) != len(set(eids)):
                bad("MU %s elementId 重复" % sid)
            tot_el += len(eids)
            layout = s.get("layout", "") or ""
            tokens = set(mm.group(1) for mm in re.finditer(r"[\[\(\{@]([A-Za-z][A-Za-z0-9_]*)", layout))
            unknown = sorted(t for t in tokens if t not in set(eids))
            if unknown:
                bad("MU %s 布局中的未定义标识符：%s" % (sid, unknown))
            for a in s.get("actions", []) or []:
                tot_ac += 1
                for bref in as_list(a.get("behaviorRef")):
                    used_beh.add(bref)
                    if bref not in beh:
                        bad("MU %s behaviorRef 悬空：%s" % (sid, bref))
                for pref in as_list(a.get("permissionRef")):
                    used_perm.add(pref)
                    if m5 and pref not in perm:
                        bad("MU %s permissionRef 悬空：%s" % (sid, pref))
            for e in els:
                db = e.get("dataBinding")
                if not db or "." not in db or not m1:
                    continue
                parts = db.split(".")
                pre = parts[0]
                if pre not in attrs:
                    continue
                if len(parts) == 2:
                    if parts[1] not in attrs[pre] and "%s.%s" % (pre, parts[1]) not in attrs:
                        note("MU %s.%s dataBinding 未在 M1 找到：%s" % (sid, e["id"], db))
                else:
                    ent_key = "%s.%s" % (parts[0], parts[1])
                    if ent_key in attrs:
                        if parts[2] not in attrs[ent_key]:
                            note("MU %s.%s 子实体属性未在 M1 找到：%s" % (sid, e["id"], db))
                    elif parts[1] not in attrs[pre]:
                        note("MU %s.%s dataBinding 未在 M1 找到：%s" % (sid, e["id"], db))
        manual = {b["id"] for b in beh.values() if b.get("triggerType") == "USER_ACTION"}
        uncovered = sorted(x for x in manual if x not in used_beh)
        print("  屏幕 %d / 元素 %d / 操作功能点 %d" % (len(screens), tot_el, tot_ac))
        print("  人工行为覆盖：%d/%d" % (len(manual) - len(uncovered), len(manual)))
        if uncovered:
            bad("MU 未覆盖的人工行为：%s" % uncovered)
        auto_used = sorted(x for x in used_beh if x not in manual)
        if auto_used:
            bad("MU 引用了系统自动行为（不应有界面入口）：%s" % auto_used)

    # ---------- 框架 §10.2 模型评审检查清单（可自动判定项）----------
    print("\n=== 框架 §10.2 评审检查清单（自动判定项）===")

    def chk(cond, label, detail=""):
        if cond:
            print("  [OK] " + label)
        else:
            bad("%s → %s" % (label, detail))

    m1_types = {}
    if m1:
        for a in m1.get("aggregates", []):
            for key in (a.get("id"), a.get("alias")):
                if not key:
                    continue
                for x in a.get("attributes", []):
                    m1_types["%s.%s" % (key, x.get("name"))] = x.get("type")
                for ent in a.get("entities", []) or []:
                    for ek in (ent.get("name"), ent.get("alias")):
                        if not ek:
                            continue
                        for x in ent.get("attributes", []):
                            m1_types["%s.%s.%s" % (key, ek, x.get("name"))] = x.get("type")
        n_ref = sum(1 for k, v in m1_types.items() if v == "AggregateRootRef")
        n_inv = sum(len(a.get("invariants", []) or []) for a in m1.get("aggregates", []))
        n_refrule = sum(len(x.get("refRules", []) or [])
                        for a in m1.get("aggregates", []) for x in a.get("attributes", []))
        chk(n_ref >= 1, "M1 聚合间以 ID 引用（AggregateRootRef %d 个，无对象内嵌）" % n_ref)
        chk(n_inv >= 1, "M1 聚合不变性约束落位（invariants %d 条 / 属性级 refRules %d 条）" % (n_inv, n_refrule))

    if m2:
        owner = {b["id"]: b.get("ownerEntity") for b in beh.values()}
        same, cond_ref = [], []
        for b in beh.values():
            for st in b.get("syncTriggers", []) or []:
                t = st.get("behaviorRef")
                if owner.get(t) and owner.get(t) == owner.get(b["id"]):
                    same.append("%s→%s" % (b["id"], t))
                if st.get("condition") and not st.get("ruleRef"):
                    cond_ref.append(b["id"])
        chk(not same, "M2 syncTriggers 仅表达跨聚合联动", str(same))
        chk(not cond_ref, "M2 syncTriggers 条件均引用 M3 规则", str(cond_ref))
        qbad = [b["id"] for b in beh.values() if b.get("queryReportRef") and b.get("behaviorType") != "QUERY"]
        chk(not qbad, "M2 queryReportRef 仅出现在 behaviorType=QUERY", str(qbad))
        nopre = [b["id"] for b in beh.values() if b.get("behaviorType") == "COMMAND" and not b.get("preconditions")]
        chk(not nopre, "M2 命令行为均有前置条件", str(nopre))
        nopost = [b["id"] for b in beh.values()
                  if b.get("behaviorType") == "COMMAND" and not b.get("postconditions")]
        chk(not nopost, "M2 命令行为均有后置状态变更", str(nopost))

    if m5:
        ext = [k for k in m5 if k not in ("model_type", "version", "domain", "actors", "roles", "permissions")]
        chk(not ext, "M5 无外部实体/接口契约残留", str(ext))
        abac = [x["permissionId"] for x in perm.values()
                if x.get("dataScope") not in (None, "ALL") and not x.get("abacCondition")]
        chk(not abac, "M5 非 ALL 数据范围均有 ABAC 条件（本期全为 ALL，见 D-32）", str(abac))

    if m6:
        allowed = {"START", "END", "USER_TASK", "APPROVAL_TASK", "SYSTEM_TASK", "BEHAVIOR_CALL",
                   "SUB_FLOW_CALL", "GATEWAY"}
        for fid, fl in flows.items():
            acts = {a["activityId"]: a for a in fl["activities"]}
            outs = {a.get("roleRef") for a in fl["activities"] if a.get("roleRef")}
            chk(outs <= set(fl.get("roleRefs", []) or []), "M6 %s 活动 roleRef ⊆ 流程 roleRefs" % fid,
                str(sorted(outs - set(fl.get("roleRefs", []) or []))))
            chk({a["activityType"] for a in fl["activities"]} <= allowed,
                "M6 %s 仅使用框架允许的活动类型" % fid,
                str({a["activityType"] for a in fl["activities"]} - allowed))
            chk(sum(1 for a in fl["activities"] if a["activityType"] == "START") == 1,
                "M6 %s 有且仅有一个 START" % fid)
            # 子流程调用无环
            g = {a["activityId"]: a.get("subFlowRef") for a in fl["activities"] if a.get("subFlowRef")}
            cyc = []
            for start_f in g:
                seen_f, cur = set(), fl["id"]
                while cur in g and cur not in seen_f:
                    seen_f.add(cur)
                    cur = g[cur]
                if cur in seen_f:
                    cyc.append(cur)
            chk(not cyc, "M6 子流程调用图无环", str(sorted(set(cyc))))

    if m7:
        assoc_ids = {x.get("id") for x in (m1.get("aggregate_associations", []) or [])} if m1 else set()
        for o in objs:
            srcs = o.get("sourceObjects", []) or []
            aliases = [s.get("alias") for s in srcs]
            chk(len(aliases) == len(set(aliases)), "M7 %s 来源别名唯一" % o["id"])
            bads = [s.get("objectRef") for s in srcs if agg_ids and s.get("objectRef") not in agg_ids]
            chk(not bads, "M7 %s sourceObjects.objectRef 均为 M1 已存在聚合根" % o["id"], str(bads))
            detail = [s for s in srcs if s.get("preAggregation") or s.get("entityPath")]
            has_agg = any(c.get("aggregateFunction") not in (None, "NONE")
                          for c in (o.get("resultColumns") or []))
            if len(detail) >= 2 and has_agg:
                miss = [s.get("alias") for s in detail if not s.get("preAggregation")]
                chk(not miss, "M7 %s 多个一对多来源参与聚合时已预聚合" % o["id"], str(miss))
            jbad = []
            for j in o.get("joins", []) or []:
                for k in ("leftSource", "rightSource"):
                    if j.get(k) not in aliases:
                        jbad.append("%s.%s=%s" % (j.get("joinId"), k, j.get(k)))
                if j.get("relationRef") and j["relationRef"] not in assoc_ids:
                    jbad.append("relationRef=%s" % j["relationRef"])
            chk(not jbad, "M7 %s Join 左右来源与关系引用有效" % o["id"], str(jbad))
            # 约定 12：预聚合（preAggregation）来源不得作主来源（主来源即 FROM 表，须为普通表）
            prim = [s2 for s2 in srcs if s2.get("primary")]
            chk(len(prim) == 1, "M7 %s 主来源唯一" % o["id"], str([x.get("alias") for x in prim]))
            bad_prim = [s2.get("alias") for s2 in prim if s2.get("preAggregation") or s2.get("entityPath")]
            chk(not bad_prim, "M7 %s 主来源为普通表（非预聚合/子实体，约定 12）" % o["id"], str(bad_prim))
        chk(True, "M7 未定义权限/角色/规则/流程引用（已逐对象校验禁止字段）")

    if mu:
        mis = []
        for sid, s in screens.items():
            for e in s.get("elements", []):
                t = m1_types.get(e.get("dataBinding") or "")
                if not t:
                    continue
                exp = {"Date": "DATEPICKER", "DateTime": "DATEPICKER", "DictionaryRef": "COMBO",
                       "AggregateRootRef": "POPUP_SELECT", "Boolean": "CHECKBOX"}.get(t)
                if exp and e.get("type") != exp:
                    mis.append("%s.%s(%s=%s≠%s)" % (sid, e["id"], t, e.get("type"), exp))
        chk(not mis, "MU 控件类型遵循 §8.3 强制映射", str(mis[:6]))
        trig = {fl["trigger"]["behaviorRef"] for fl in (m6.get("flows", []) if m6 else [])
                if fl.get("flowType") == "APPROVAL" and fl.get("trigger", {}).get("behaviorRef")}
        for sid, s in screens.items():
            acts = s.get("actions", []) or []
            if any(a.get("behaviorRef") in trig for a in acts):
                kinds = {a.get("actionType") for a in acts}
                chk({"DRAFT", "SUBMIT"} <= kinds,
                    "MU %s 带审批流，含「保存草稿 + 提交」双功能点" % sid, str(kinds))
        nform = {}
        for sid, s in screens.items():
            nform[s.get("screenType")] = nform.get(s.get("screenType"), 0) + 1
        chk(True, "MU 界面类型分布：%s（共 %d 屏）" % (nform, len(screens)))

    # ---------- M2 后置条件字段必须可在 M1 解析（字段级一致性）----------
    if m2 and m1:
        print("\n=== M2 后置条件 ↔ M1 字段一致性 ===")
        idx = {}
        collections = set()
        for a in m1.get("aggregates", []):
            for key in (a.get("id"), a.get("alias")):
                if not key:
                    continue
                idx.setdefault(key.lower(), set()).update(x.get("name") for x in a.get("attributes", []))
                for ent in a.get("entities", []) or []:
                    for ek in (ent.get("name"), ent.get("alias")):
                        if not ek:
                            continue
                        full = "%s.%s" % (key, ek)
                        collections.add(full.lower())
                        collections.add(ek.lower())
                        idx.setdefault(full.lower(), set()).update(
                            x.get("name") for x in ent.get("attributes", []))
        field_bad = []
        for b in beh.values():
            for pc in b.get("postconditions", []) or []:
                f = pc.get("field") if isinstance(pc, dict) else None
                if not f or "." not in f:
                    continue
                fl = f.lower()
                if fl in collections or fl.split(".")[-1] in collections:
                    continue
                if len(f.split(".")) >= 3:
                    parent = ".".join(f.split(".")[:2]).lower()
                    attr = f.split(".")[-1]
                    if parent not in idx or attr not in idx[parent]:
                        field_bad.append("%s → %s" % (b["id"], f))
                else:
                    pre, attr = f.split(".", 1)
                    if pre.lower() not in idx or attr not in idx[pre.lower()]:
                        field_bad.append("%s → %s" % (b["id"], f))
        chk(not field_bad, "M2 后置条件字段全部可解析到 M1", str(field_bad))

    print("\n=== 结论 ===")
    if NOTES:
        print("提示（%d 条）：" % len(NOTES))
        for n in NOTES:
            print("  - " + n)
    if PROBLEMS:
        print("阻断问题 %d 条：" % len(PROBLEMS))
        for x in PROBLEMS:
            print("  [X] " + x)
        return 1
    print("全部跨模型一致性门禁通过。")
    return 0


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else r"D:\hermes\workspace\中医问诊系统\yaml"
    sys.exit(main(root))
