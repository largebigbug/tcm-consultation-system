# -*- coding: utf-8 -*-
"""生成批次 3 的三份机器抽取规格（与实现契约同等效力）。

产出：
  code-app/docs/批次3-报表规格（M7抽取）.md
  code-app/docs/批次3-屏幕规格（MU抽取）.md
  code-app/docs/批次3-权限与菜单（M5+MU抽取）.md

用法：D:/hermes/workspace/docx-venv/Scripts/python.exe tools/gen_batch3_spec.py
"""
import io
import os
import re

import yaml

R = r"D:\hermes\workspace\中医问诊系统"
D = os.path.join(R, "yaml")
OUT = os.path.join(R, "code-app", "docs")
load = lambda f: yaml.safe_load(io.open(os.path.join(D, f), encoding="utf-8").read())

m1 = load("m1-object-model.yaml")
m5 = load("m5-actor-model.yaml")
m7 = load("m7-report-model.yaml")
mu = load("mu-ui-model.yaml")
DOC = io.open(os.path.join(R, "中医问诊系统-需求规格说明书-V9.md"), encoding="utf-8").read()


def snake(name):
    """与 seed.py 完全一致（逐字复制，保证派生口径唯一）。"""
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def kebab(name):
    return snake(name).replace("_", "-")


def permission_code(target_ref):
    """与 seed.py::permission_code 同一实现：targetRef（{EntityAlias}_{ActionName}）→ {对象}:{动作}。

    注意 FollowUp → follow_up（snake），不是 followup。
    """
    alias, _, action = (target_ref or "").partition("_")
    if not alias or not action:
        return ""
    return "%s:%s" % (snake(alias), kebab(action))


def code_of_permission(perm_id):
    for p in m5["permissions"]:
        if p["permissionId"] == perm_id:
            return permission_code(p["targetRef"]), p
    return None, None


BATCH3_SCREENS = ["复诊随访登记", "门诊量统计", "证型分布统计", "方剂与饮片使用统计",
                  "就诊与处方记录查询", "超量·毒性处方审核台账", "随访完成与失访分析"]
BATCH3_REPORTS = ["RPT-VISIT-STATS-001", "RPT-SYNDROME-DIST-001", "RPT-HERB-USAGE-001",
                  "QR-VISIT-PRESCRIPTION-001", "QR-PRESCRIPTION-OVERDOSE-001", "RPT-FOLLOWUP-COMPLETION-001"]

AGG_TABLE = {}
for a in m1["aggregates"]:
    AGG_TABLE[a["id"]] = (a.get("alias"), a.get("name"))


def agg_table_hint(object_ref):
    """M1 聚合 → 物理表名（按本应用 schema.sql 的命名约定：聚合别名 snake_case）。"""
    a = AGG_TABLE.get(object_ref)
    if not a:
        return object_ref, ""
    alias = a[0]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", alias).lower(), a[1]


# ---------------------------------------------------------------- 报表规格
lines = ["# 批次 3 · 报表规格（由 M7 机械抽取）", "",
         "> 本文件与 `批次3-实现契约.md` 同等效力；由 `tools/gen_batch3_spec.py` 从 `yaml/m7-report-model.yaml` 直接生成，**不得手改**。",
         "> 命名映射：M7 的 `sourceObjects[].alias` 是逻辑别名，物理表见「数据来源」表的 `物理表` 列（由 M1 聚合名 snake_case 推导）；",
         "> 列表达式一律形如 `别名.属性名`，属性名 → 物理列名同样为 snake_case（如 `visit.registerTime` → `visit.register_time`）。", ""]
doc_lines = DOC.splitlines()


def req_excerpt(keyword, max_lines=14):
    """从需求文档抓该报表的口径段落（表格行）。"""
    out = []
    for i, l in enumerate(doc_lines):
        if re.match(r"^### 5\.\d+ .*" + re.escape(keyword), l):
            for l2 in doc_lines[i:i + 30]:
                if l2.startswith("### ") and l2 != l:
                    break
                if l2.strip().startswith("|") or l2.strip().startswith(">"):
                    out.append(l2.strip())
            break
    return out[:max_lines]


REQ_NAME = {"RPT-VISIT-STATS-001": "门诊量统计", "RPT-SYNDROME-DIST-001": "证型分布统计",
            "RPT-HERB-USAGE-001": "方剂与饮片使用统计", "QR-VISIT-PRESCRIPTION-001": "就诊与处方记录查询",
            "QR-PRESCRIPTION-OVERDOSE-001": "超量", "RPT-FOLLOWUP-COMPLETION-001": "随访完成与失访分析"}

for rid in BATCH3_REPORTS:
    r = [x for x in m7["query_reports"] if x["id"] == rid][0]
    code = permission_code(r.get("behaviorRef"))
    lines += ["", "---", "", "## %s　%s" % (r["id"], r["name"]), "",
              "- **别名（前端/接口用）**：`%s`" % r.get("alias"),
              "- **objectType**：%s" % r.get("objectType"),
              "- **绑定行为（M2）**：`%s` → **权限码 `%s`**" % (r.get("behaviorRef"), code),
              "- **业务说明**：%s" % r.get("description"), ""]
    lines += ["### 数据来源", "", "| 别名 | M1 聚合 | 对象名 | 物理表 | 主来源 |", "|---|---|---|---|---|"]
    for s in r.get("sourceObjects") or []:
        t, nm = agg_table_hint(s.get("objectRef"))
        lines.append("| `%s` | %s | %s | `%s` | %s |" % (s.get("alias"), s.get("objectRef"), nm, t,
                                                         "是" if s.get("primary") else ""))
    if r.get("joins"):
        lines += ["", "### Join（连接条件）", "", "| Join | 类型 | 左 | 右 | 条件（逻辑表达式） |", "|---|---|---|---|---|"]
        for j in r["joins"]:
            lines.append("| %s | %s | `%s` | `%s` | `%s` |" % (j.get("joinId"), j.get("joinType"),
                                                                 j.get("leftSource"), j.get("rightSource"),
                                                                 j.get("conditionExpression")))
    lines += ["", "### 查询参数（%d 个）" % len(r.get("parameters") or []), "",
              "| 参数名 | 标签 | 类型 | 必填 | 默认值 | 允许算子 | 来源字段 |", "|---|---|---|---|---|---|---|"]
    for p in r.get("parameters") or []:
        lines.append("| `%s` | %s | %s | %s | %s | %s | `%s` |" % (
            p.get("name"), p.get("label"), p.get("dataType"), "是" if p.get("required") else "",
            p.get("defaultValue") or "", ",".join(p.get("allowedOperators") or []), p.get("sourceField")))
    lines += ["", "### 查询条件（%d 条）" % len(r.get("conditions") or []), "",
              "| 条件 | 左表达式 | 算子 | 参数 | 常量值(fixedValue) | 连接 | 组 | 触发类型(triggerKind) | 参数为空则跳过 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in r.get("conditions") or []:
        fixed = c.get("fixedValue")
        fixed = ("`%s`" % fixed) if fixed not in (None, "") else ""
        lines.append("| %s | `%s` | %s | `%s` | %s | %s | %s | %s | %s |" % (
            c.get("conditionId"), c.get("leftExpression"), c.get("operator"),
            c.get("parameterRef") or "", fixed,
            c.get("logicalConnector"), c.get("group"), c.get("triggerKind") or "",
            "是" if c.get("skipWhenParameterEmpty") else ""))
    lines += ["", "### 结果列（%d 列）" % len(r.get("resultColumns") or []), "",
              "| 序号 | 列名 | 列标签 | 类型 | 表达式 | 聚合 | 格式 | 可排序 | 可见 |", "|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(r.get("resultColumns") or [], 1):
        lines.append("| %d | `%s` | %s | %s | `%s` | %s | %s | %s | %s |" % (
            i, c.get("name"), c.get("label"), c.get("dataType"), c.get("sourceExpression"),
            c.get("aggregateFunction") or "NONE", c.get("format") or "", "是" if c.get("sortable") else "",
            "是" if c.get("visible") is not False else "否"))
    for key, label in (("groupBy", "分组"), ("having", "分组过滤"), ("orderBy", "排序"), ("pagination", "分页")):
        v = r.get(key)
        if v:
            lines += ["", "### %s" % label, "", "```json", __import__("json").dumps(v, ensure_ascii=False, indent=1), "```"]
    for key, label in (("reportOptions", "呈现选项"),):
        if r.get(key):
            lines += ["", "### %s" % label, "", "```json", __import__("json").dumps(r[key], ensure_ascii=False, indent=1), "```"]
    ex = req_excerpt(REQ_NAME[rid])
    if ex:
        lines += ["", "### 需求文档口径摘录（REP-%s 段）" % REQ_NAME[rid][:2], ""] + ["> " + e for e in ex]
io.open(os.path.join(OUT, "批次3-报表规格（M7抽取）.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("① 报表规格已生成：%d 行" % len(lines))

# ---------------------------------------------------------------- 屏幕规格
lines = ["# 批次 3 · 屏幕规格（由 MU 机械抽取）", "",
         "> 与 `批次3-实现契约.md` 同等效力；由 `tools/gen_batch3_spec.py` 从 `yaml/mu-ui-model.yaml` 生成，**不得手改**。",
         "> 元素 `dataBinding` 的 `对象.属性` 需按下划线的 snake_case 落到表单/查询条件字段；`type` 与 MU 一致。", ""]
for name in BATCH3_SCREENS:
    s = [x for x in mu["screens"] if x.get("name") == name][0]
    lines += ["", "---", "", "## %s　%s（%s）" % (s.get("screenId"), s.get("name"), s.get("screenType")), ""]
    lines += ["### 动作（%d 个）" % len(s.get("actions") or []), "", "| 动作 | 名称 | 类型 | 绑定行为 | 权限 | 权限码 |", "|---|---|---|---|---|---|"]
    for a in s.get("actions") or []:
        codes = []
        for pr in a.get("permissionRef") or []:
            c, _p = code_of_permission(pr)
            codes.append("%s（%s）" % (c, pr) if c else pr)
        lines.append("| `%s` | %s | %s | `%s` | %s | %s |" % (a.get("actionId"), a.get("name"), a.get("actionType"),
                                                            a.get("behaviorRef"), ",".join(a.get("permissionRef") or []),
                                                            "；".join(codes)))
    lines += ["", "### 元素（%d 个）" % len(s.get("elements") or []), "",
              "| 序号 | 元素 id | 类型 | 标签 | io | dataBinding | 其它 |", "|---|---|---|---|---|---|---|"]
    for i, e in enumerate(s.get("elements") or [], 1):
        extra = {k: v for k, v in e.items() if k not in ("id", "type", "label", "io", "dataBinding")}
        lines.append("| %d | `%s` | %s | %s | %s | `%s` | %s |" % (
            i, e.get("id"), e.get("type"), e.get("label"), e.get("io"), e.get("dataBinding") or "",
            __import__("json").dumps(extra, ensure_ascii=False) if extra else ""))
    if s.get("layout"):
        lines += ["", "### 布局（MU ASCII 原型）", "", "```", str(s["layout"]).rstrip(), "```"]
io.open(os.path.join(OUT, "批次3-屏幕规格（MU抽取）.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("② 屏幕规格已生成：%d 行" % len(lines))

# ---------------------------------------------------------------- 权限与菜单
lines = ["# 批次 3 · 权限与菜单（由 M5+MU 机械抽取）", "",
         "> 与 `批次3-实现契约.md` 同等效力；由 `tools/gen_batch3_spec.py` 生成，**不得手改**。",
         "> 权限码由 M5 `targetRef`（= M2 行为 id）按 `seed.py::permission_code` 同一规则派生（`{对象}:{动作-kebab}`）。", ""]
behaviors = []
for name in BATCH3_SCREENS:
    s = [x for x in mu["screens"] if x.get("name") == name][0]
    for a in s.get("actions") or []:
        behaviors.append((s.get("screenId"), a.get("actionId"), a.get("behaviorRef"),
                          (a.get("permissionRef") or [None])[0]))
uniq = {}
for scr, act, beh, pid in behaviors:
    u = uniq.setdefault(beh, {"perm": pid, "code": permission_code(beh), "screens": []})
    if scr not in u["screens"]:
        u["screens"].append(scr)
lines += ["## 一、批次 3 行为 → 权限码", "", "| 行为 | 权限项 | 权限码 | 出现屏幕 |", "|---|---|---|---|"]
for beh, u in uniq.items():
    lines.append("| `%s` | %s | **`%s`** | %s |" % (beh, u["perm"], u["code"], ", ".join(u["screens"])))
lines += ["", "## 二、角色授权（M5）", "", "| 角色 | 名称 | 是否持有本批权限 | 本批权限码 |", "|---|---|---|---|"]
for role in m5["roles"]:
    granted = []
    for pid in role.get("permissions") or []:
        c, p = code_of_permission(pid)
        if c in {u["code"] for u in uniq.values()} or (p and p.get("targetRef") == "Prescription_Cancel"):
            granted.append(c)
    lines.append("| %s | %s | %s | %s |" % (role["roleId"], role["name"], "是" if granted else "否",
                                            ", ".join(sorted(set(granted))) or "——"))
lines += ["", "## 三、菜单树（需求文档附录 D.3：一级菜单 7 个，仅二级关联界面）", "",
          "| 一级菜单 | 二级菜单 | 界面 | screenId | 屏幕类型 |", "|---|---|---|---|---|"]
tree = [("门诊管理", ["患者建档", "门诊挂号（含撤销就诊）", "接诊开单", "四诊录入", "辨证判定", "开具处方"]),
        ("药房管理", ["处方审核", "调剂发药"]),
        ("库存管理", ["饮片建档与入库", "饮片库存与预警（含盘点）"]),
        ("随访管理", ["复诊随访登记"]),
        ("统计报表", ["门诊量统计", "证型分布统计", "方剂与饮片使用统计", "就诊与处方记录查询",
                      "超量·毒性处方审核台账", "随访完成与失访分析"]),
        ("基础数据", ["证型字典维护", "方剂模板维护"]),
        ("系统管理", ["用户管理", "角色与权限配置", "菜单管理"])]
mu_names = {x.get("name"): x for x in mu["screens"]}
for top, children in tree:
    for ch in children:
        hit = [k for k in mu_names if ch.startswith(k) or k.startswith(ch[:6])]
        s = mu_names.get(hit[0]) if hit else None
        lines.append("| %s | %s | %s | %s | %s |" % (top, ch, "", s.get("screenId") if s else "",
                                                     s.get("screenType") if s else ""))
io.open(os.path.join(OUT, "批次3-权限与菜单（M5+MU抽取）.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("③ 权限与菜单已生成：%d 行" % len(lines))
