# -*- coding: utf-8 -*-
"""批次 6（工作台补齐）契约用事实抽取：从 M1/M2/M5/M6/MU + 运行库 + url_map 机械生成。

产出：code-app/docs/批次6-抽取（模型与运行时事实）.md（**禁止手改**，重跑即刷新）
用法：code-app/backend/.venv/Scripts/python.exe tools/gen_batch6_spec.py
"""
import io
import json
import os
import shutil
import sqlite3
import tempfile
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BACKEND))
YAML = os.path.join(PROJECT, "yaml")
OUT = os.path.join(PROJECT, "code-app", "docs", "批次6-抽取（模型与运行时事实）.md")
COPY = os.path.join(BACKEND, "data", "b6_spec.db")

sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ["APP_DB_PATH"] = COPY
assert os.path.basename(os.environ["APP_DB_PATH"]) != "app.db", "拒绝以演示库为抽取库"

L = []
def add(t=""): L.append(t)

try:
    import yaml  # noqa: F811
except ImportError:  # docx-venv 有 pyyaml；后端 venv 亦有
    raise

def load(name):
    return yaml.safe_load(io.open(os.path.join(YAML, name), encoding="utf-8"))

m1, m2, m3, m5, m6, mu = (load(f) for f in ("m1-object-model.yaml", "m2-behavior-model.yaml", "m3-rule-model.yaml",
                                            "m5-actor-model.yaml", "m6-flow-model.yaml", "mu-ui-model.yaml"))

add("# 批次 6 契约用事实抽取（模型 + 运行时）")
add()
add("> 由 `code-app/backend/tools/gen_batch6_spec.py` 机械生成，**禁止手改**；与契约同等效力。")
add()

# ---------- 1. M6 审批流 ----------
add("## 1. M6 审批流（FLOW-PRESCRIPTION-APPROVAL-001）")
add()
flow = [f for f in m6["flows"] if f.get("flowType") == "APPROVAL"][0]
add("| 键 | 值 |")
add("|---|---|")
for k in ("id", "name", "flowType", "startActivity", "endActivities", "roleRefs", "businessObjectRefs"):
    add("| %s | `%s` |" % (k, json.dumps(flow.get(k), ensure_ascii=False)))
add("| trigger | `%s` |" % json.dumps(flow.get("trigger"), ensure_ascii=False))
add("| preconditions | %s |" % "；".join(flow.get("preconditions") or []))
add("| postconditions | %s |" % "；".join(flow.get("postconditions") or []))
add()
add("**描述（含 D-24/D-25 决策）**：%s" % (flow.get("description") or "").replace("\n", " "))
add()
add("| 活动 id | 类型 | 名称 | 角色 | 行为 | 审批结论 | nextActivities |")
add("|---|---|---|---|---|---|---|")
for a in flow["activities"]:
    add("| `%s` | %s | %s | %s | %s | %s | %s |" % (
        a["activityId"], a.get("activityType"), a.get("name"), a.get("roleRef") or "-",
        a.get("behaviorRef") or "-", ",".join(a.get("approvalOutcomes") or []) or "-",
        ",".join(a.get("nextActivities") or []) or "-"))
add()
for a in flow["activities"]:
    if a.get("activityType") == "GATEWAY":
        add("**网关 `%s`（%s）分支**：" % (a["activityId"], a.get("name")))
        add()
        add("| 分支 | 判定 | 目标 | 默认 |")
        add("|---|---|---|---|")
        for b in a.get("branches") or []:
            cond = b.get("conditionExpression") or ("approvalOutcome=%s" % b.get("approvalOutcome"))
            add("| %s | `%s` | `%s` | %s |" % (b.get("branchName"), cond, b.get("targetActivity"), b.get("isDefault")))
        add()

# ---------- 2. M2 相关行为 ----------
add("## 2. M2 相关行为（审批链涉及）")
add()
want = ("Prescription_Submit", "Prescription_Review", "Prescription_Cancel", "Dispense_CreatePending",
        "Dispense_CancelPending", "Herb_ReturnStock")
for b in m2["behaviors"]:
    if b["id"] not in want:
        continue
    add("### `%s` %s" % (b["id"], b.get("name")))
    add()
    add("- ownerEntity：`%s`｜behaviorType：%s｜triggerType：%s" % (b["ownerEntity"], b["behaviorType"], b["triggerType"]))
    add("- preconditions：%s" % ("；".join(b.get("preconditions") or []) or "-"))
    add("- postconditions：%s" % ("；".join(json.dumps(x, ensure_ascii=False) for x in (b.get("postconditions") or [])) or "-"))
    add("- appliedRules：%s" % (", ".join(b.get("appliedRules") or []) or "-"))
    add("- requiredPermissions：%s" % (", ".join(b.get("requiredPermissions") or []) or "-"))
    add()
add("**R-04（作废三分派）表达式**：")
add()
add("```")
add(([r for r in m3.get("rules", []) if r.get("id") == "RULE-PRESCRIPTION-VOID-DISPATCH"] or [{}])[0].get("expression", "（未找到）"))
add("```")
add()

# ---------- 3. M1 处方聚合生命周期（状态机） ----------
add("## 3. M1 处方聚合（状态机与字典）")
add()
for a in m1["aggregates"]:
    if "Prescription" in str(a.get("alias", "")):
        add("- 聚合：`%s`（%s）" % (a["id"], a.get("name")))
        add("- lifecycle：")
        add()
        add("```json")
        add(json.dumps(a.get("lifecycle"), ensure_ascii=False, indent=1))
        add("```")
        add()
        add("| 属性 | 标签 | 类型 | 字典 |")
        add("|---|---|---|---|")
        for at in a.get("attributes", []):
            if any(k in str(at.get("name", "")) for k in ("status", "Status", "review", "Review", "submit", "Submit", "cancel", "Cancel")):
                ref = at.get("dictionaryRef") or {}
                add("| `%s` | %s | %s | %s |" % (at.get("name"), at.get("label"), at.get("dataType"),
                                                 json.dumps(ref, ensure_ascii=False)))
add()
d = [x for x in m1["data_dictionaries"] if x["id"] == "DICT-PRESCRIPTION"][0]
for t in d["types"]:
    if t["typeCode"] == "PRESCRIPTION_STATUS":
        add("**处方状态字典（%s）**：" % t["typeCode"])
        add()
        add("| code | label | enabled |")
        add("|---|---|---|")
        for it in t["items"]:
            add("| `%s` | %s | %s |" % (it["code"], it["label"], it.get("enabled")))
        add()

# ---------- 4. M5 权限与角色 ----------
add("## 4. M5 角色与权限（派生规则：`{targetRef}` → `{对象}:{动作}`）")
add()
add("| 权限 id | 名称 | targetRef | 派生权限码 |")
add("|---|---|---|---|")
def perm_code(target_ref):
    from seed import permission_code  # 与运行时种子同源，避免手推
    return permission_code(target_ref)
for p in m5["permissions"]:
    if any(k in str(p.get("targetRef")) for k in ("Prescription", "Dispense", "Visit_Complete", "Herb_")):
        add("| `%s` | %s | `%s` | `%s` |" % (p.get("id"), p.get("name"), p.get("targetRef"),
                                            perm_code(p.get("targetRef"))))
add()
add("| 角色 | 名称 | 权限数 | 相关权限 |")
add("|---|---|---|---|")
for r in m5["roles"]:
    rel = [x for x in (r.get("permissions") or []) if any(k in x for k in ("Prescription", "Dispense"))]
    rn = r.get("name") or r.get("id") or r.get("code")
    rid = r.get("id") or r.get("code")
    add("| `%s` | %s | %d | %s |" % (rid, rn, len(r.get("permissions") or []), ", ".join(rel) or "-"))
add()

# ---------- 5. MU 屏幕与路由 ----------
add("## 5. MU 屏幕 ↔ 路由 ↔ 权限（业务单跳转用；路由取自 `seed.SCREEN_META`）")
add()
from seed import SCREEN_META  # noqa: E402
add("| screenId | 屏幕名 | 路由 path | 权限码 |")
add("|---|---|---|---|")
for s in mu["screens"]:
    # SCREEN_META 的取值是三元组 (path, icon, permission_code)（实测，勿猜）
    meta = SCREEN_META.get(s["screenId"])
    path, icon, pcode = (meta if isinstance(meta, tuple) and len(meta) == 3 else ("（未实现/无路由）", "-", "-"))
    add("| `%s` | %s | `%s` | `%s` |" % (s["screenId"], s.get("name"), path, pcode))
add()

# ---------- 6. 运行时：node_graph 与表结构 ----------
if os.path.exists(COPY):
    os.remove(COPY)
shutil.copyfile(os.path.join(BACKEND, "data", "app.db"), COPY)
conn = sqlite3.connect(COPY)
conn.row_factory = sqlite3.Row
add("## 6. 运行时事实（演示库副本）")
add()
defn = conn.execute("SELECT * FROM flow_definition WHERE code = 'FLOW-PRESCRIPTION-APPROVAL-001'").fetchone()
if defn:
    graph = json.loads(defn["node_graph"] or "{}")
    add("**已落库 node_graph 节点**（%d 个）：" % len(graph.get("nodes", [])))
    add()
    add("| id | type | name | roleRef | behaviorRef |")
    add("|---|---|---|---|---|")
    for n in graph.get("nodes", []):
        add("| `%s` | %s | %s | %s | %s |" % (n.get("id"), n.get("type"), n.get("name"),
                                             n.get("roleRef") or "-", n.get("behaviorRef") or "-"))
    add()
    add("**边**：%s" % "，".join("`%s→%s`%s" % (e.get("source"), e.get("target"),
                                              ("（%s）" % e.get("condition") if e.get("condition") else ""))
                                for e in graph.get("edges", [])))
    add()
add("| 表 | 列 |")
add("|---|---|")
for t in ("flow_instance", "flow_task", "flow_history", "audit_logs", "prescription", "dispense_record"):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)]
    add("| `%s` | %s |" % (t, ", ".join("`%s`" % c for c in cols)))
add()
add("**演示库基线（只读体检用）**：")
add()
base = {
    "flow_task TODO": "SELECT COUNT(*) FROM flow_task WHERE status='TODO'",
    "flow_task DONE": "SELECT COUNT(*) FROM flow_task WHERE status='DONE'",
    "flow_instance RUNNING": "SELECT COUNT(*) FROM flow_instance WHERE status='RUNNING'",
    "flow_instance APPROVED": "SELECT COUNT(*) FROM flow_instance WHERE status='APPROVED'",
    "flow_history": "SELECT COUNT(*) FROM flow_history",
    "audit_logs": "SELECT COUNT(*) FROM audit_logs",
    "dispense_record": "SELECT COUNT(*) FROM dispense_record",
    "prescription": "SELECT COUNT(*) FROM prescription",
}
add("| 指标 | 值 |")
add("|---|---|")
for k, q in base.items():
    add("| %s | %d |" % (k, conn.execute(q).fetchone()[0]))
add("| 实例现有状态取值 | %s |" % ", ".join(
    "%s=%d" % (r[0], r[1]) for r in conn.execute("SELECT status, COUNT(*) FROM flow_instance GROUP BY status")))
add("| 任务现有状态取值 | %s |" % ", ".join(
    "%s/%s=%d" % (r[0], r[1], r[2]) for r in conn.execute(
        "SELECT status, COALESCE(action,'-'), COUNT(*) FROM flow_task GROUP BY status, action")))
add()
conn.close()
os.remove(COPY)

# ---------- 7. 接口清单（url_map 为准） ----------
add("## 7. 现有接口清单（以 `app.url_map` 为准，不以源码正则为准）")
add()
add("| rule | methods |")
add("|---|---|")
# 注意：import app 会按 APP_DB_PATH 幂等初始化数据库 —— 必须先把路径挪出 data/，
# 否则会把刚删掉的副本重新建回来（本批实测踩到）。
_SCRATCH_DB = os.path.join(tempfile.gettempdir(), "b6_spec_probe.db")
os.environ["APP_DB_PATH"] = _SCRATCH_DB
from app import app as flask_app  # noqa: E402
for r in sorted(flask_app.url_map.iter_rules(), key=lambda x: str(x.rule)):
    u = str(r.rule)
    if u.startswith(("/api/workbench", "/api/flow", "/api/prescription", "/api/dispense", "/api/auth", "/api/ai")):
        add("| `%s` | %s |" % (u, ",".join(sorted(r.methods - {"HEAD", "OPTIONS"}))))
add()

io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print("已生成 %s（%d 行）" % (OUT, len(L)))
print("抽取要点：审批流活动 %d 个｜相关 M2 行为 %d 个｜处方状态字典 7 值｜MU 屏 %d 个" % (
    len(flow["activities"]), len([b for b in m2["behaviors"] if b["id"] in want]), len(mu["screens"])))

# ---------- 收尾：清理所有临时库（副本 + import app 用的临时库） ----------
for _p in (COPY, _SCRATCH_DB):
    for _suf in ("", "-wal", "-shm"):
        if os.path.exists(_p + _suf):
            os.remove(_p + _suf)
print("[gen_batch6_spec] 临时库已清理：%s / %s" % (COPY, _SCRATCH_DB))
