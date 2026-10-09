"""种子数据：角色 / 权限 / 资源（菜单）/ 用户 / 角色授权 / 流程定义。

设计原则（《本体模型业务功能开发指导书》§3.7）：模型是唯一语义来源 ——
本文件不硬编码任何角色、权限或菜单，一律从 ontology.registry（七模型）读取后落库；
只有两处「模型未定义、属平台落地补充」的内容需要显式声明：
    ① 屏幕的路由 path 与图标 icon（MU 未定义，见 MENU_META / SCREEN_META）；
    ② 平台自身的管理菜单（系统管理 / 审批中心 / 流程管理）与平台权限授予。
"""
import json

import db
from utils.security import hash_password

# ---------------------------------------------------------------- 规则与工具


def snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def kebab(name: str) -> str:
    return snake(name).replace("_", "-")


def permission_code(target_ref: str) -> str:
    """M5 permissionId 的 targetRef（= M2 行为 id `{EntityAlias}_{ActionName}`）→ 权限码 `{对象}:{动作}`。

    例：Herb_QueryStockAndAlert → herb:query-stock-alert；Patient_Save → patient:save。
    """
    alias, _, action = (target_ref or "").partition("_")
    if not alias or not action:
        return ""
    return "%s:%s" % (snake(alias), kebab(action))


# ---------------------------------------------------------------- 平台落地补充

# MU 一级菜单 → 图标（MU 未定义 icon）
DIRECTORY_ICON = {
    "menu-outpatient": "Stethoscope",
    "menu-pharmacy": "Pill",
    "menu-stock": "Boxes",
    "menu-followup": "CalendarClock",
    "menu-report": "BarChart3",
    "menu-masterdata": "Database",
}

# 已实现屏幕 → (路由, 图标, 菜单可见性权限码)；未列出的屏幕属后续批次，暂不落菜单
SCREEN_META = {
    "frmPatientCreate": ("/outpatient/patient", "UserPlus", "patient:save"),
    "frmHerbMaintain": ("/stock/herb", "Package", "herb:save"),
    "frmHerbStock": ("/stock/alert", "AlertTriangle", "herb:query-stock-and-alert"),
    "frmSyndromeMaintain": ("/basic/syndrome", "ListTree", "syndrome:save"),
    "frmFormulaMaintain": ("/basic/formula", "FlaskConical", "formula:save"),
    # 批次 2：门诊业务流
    "frmVisitRegister": ("/outpatient/register", "ClipboardPlus", "visit:register"),
    "frmVisitReceive": ("/outpatient/receive", "UserCheck", "visit:receive"),
    "frmFourDiagnosis": ("/outpatient/four-diagnosis", "NotebookPen", "visit:save-four-diagnosis"),
    "frmDiagnosisJudge": ("/outpatient/diagnosis", "Microscope", "diagnosis:save"),
    "frmPrescription": ("/outpatient/prescription", "FileSignature", "prescription:save"),
    "frmPrescriptionReview": ("/pharmacy/review", "FileCheck", "prescription:review"),
    "frmDispense": ("/pharmacy/dispense", "PackageCheck", "dispense:confirm"),
    # 批次 3：随访管理 + 统计报表（一级菜单 随访管理/统计报表 已在 MU application.menus 中）
    "frmFollowUp": ("/followup/register", "CalendarClock", "follow_up:query-completion"),
    "frmVisitStats": ("/report/visit-stats", "BarChart3", "visit:query-stats"),
    "frmSyndromeDist": ("/report/syndrome-dist", "PieChart", "diagnosis:query-syndrome-distribution"),
    "frmHerbUsageStats": ("/report/herb-usage", "Leaf", "prescription:query-herb-usage"),
    "frmVisitPrescriptionQuery": ("/report/visit-prescription", "Search", "visit:query-visit-and-prescription"),
    "frmOverdoseLedger": ("/report/overdose-ledger", "ShieldAlert", "prescription:query-overdose-review"),
    "frmFollowUpAnalysis": ("/report/followup-analysis", "TrendingUp", "follow_up:query-completion"),
}

# 平台自身功能菜单（不在 MU 业务菜单内）
PLATFORM_MENUS = [
    (None, "审批中心", "menu-workbench", None, "DIRECTORY", None, "ClipboardList", 90),
    ("menu-workbench", "我的待办", "menu-workbench-todo", None, "MENU", "/workbench/todo", "Inbox", 91),
    ("menu-workbench", "我的已办", "menu-workbench-done", None, "MENU", "/workbench/done", "CheckSquare", 92),
    ("menu-workbench", "我的申请", "menu-workbench-requested", None, "MENU", "/workbench/requested", "FileText", 93),
    (None, "流程管理", "menu-flow", None, "DIRECTORY", None, "GitBranch", 94),
    ("menu-flow", "流程定义", "menu-flow-definition", "flow:manage", "MENU", "/flow/definitions", "Workflow", 95),
    ("menu-flow", "流程实例", "menu-flow-instance", "flow:manage", "MENU", "/flow/instances", "List", 96),
    ("menu-flow", "任务管理", "menu-flow-task", "flow:manage", "MENU", "/flow/tasks", "ListChecks", 97),
    (None, "系统管理", "menu-system", None, "DIRECTORY", None, "Settings", 98),
    ("menu-system", "用户管理", "menu-system-user", "system:manage", "MENU", "/system/users", "User", 99),
    ("menu-system", "角色管理", "menu-system-role", "system:manage", "MENU", "/system/roles", "Shield", 100),
    ("menu-system", "权限管理", "menu-system-permission", "system:manage", "MENU", "/system/permissions", "Key", 101),
    ("menu-system", "资源管理", "menu-system-resource", "system:manage", "MENU", "/system/resources", "Menu", 102),
]

# 平台权限（系统管理 / 流程管理），授予 ROLE-06 系统管理员 与 admin；
# M5 只定义业务行为权限，平台权限不属 M5 管辖，故在此显式声明。
PLATFORM_PERMISSIONS = [
    ("system:manage", "系统管理", "RESOURCE", "system"),
    ("flow:manage", "流程管理", "RESOURCE", "flow"),
]

# 演示账号 → M5 角色（密码：admin 为 admin123，其余 123456）
DEMO_USERS = [
    ("admin", "admin123", "系统管理员", "admin"),
    ("daozhen", "123456", "王导诊", "ROLE-01"),
    ("yishi", "123456", "李中医师", "ROLE-02"),
    ("yaoshi", "123456", "赵中药师", "ROLE-03"),
    ("kufang", "123456", "孙库管", "ROLE-04"),
    ("keshi", "123456", "周科长", "ROLE-05"),
]

# ---------------------------------------------------------------- 流程定义（M6 → node_graph）

_NODE_TYPE = {
    "START": "start",
    "END": "end",
    "USER_TASK": "user_task",
    "APPROVAL_TASK": "approval_task",
    "SYSTEM_TASK": "system_task",
    "BEHAVIOR_CALL": "behavior_call",
    "SUB_FLOW_CALL": "sub_flow_call",
    "GATEWAY": "gateway",
}


def _end_result(name: str) -> str:
    return "REJECTED" if any(k in (name or "") for k in ("驳回", "终止", "不通过", "作废")) else "APPROVED"


def build_node_graph(flow: dict) -> dict:
    """把 M6 流程模型转换为流程引擎的 node_graph（nodes + edges）。"""
    nodes, edges = [], []
    for a in flow.get("activities", []) or []:
        node = {
            "id": a["activityId"],
            "type": _NODE_TYPE.get(a.get("activityType"), "user_task"),
            "name": a.get("name"),
            "role_ref": a.get("roleRef"),
            "behavior_ref": a.get("behaviorRef"),
        }
        if node["type"] == "end":
            node["result"] = _end_result(a.get("name"))
        if node["type"] == "gateway":
            node["branches"] = [
                {
                    "branch_name": b.get("branchName"),
                    "target": b.get("targetActivity"),
                    "is_default": bool(b.get("isDefault")),
                    "approval_outcome": b.get("approvalOutcome"),
                    "condition": b.get("conditionExpression"),
                    "rule_ref": b.get("ruleRef"),
                }
                for b in a.get("branches", []) or []
            ]
            for b in a.get("branches", []) or []:
                if b.get("targetActivity"):
                    edges.append({"source": a["activityId"], "target": b["targetActivity"]})
        for nxt in a.get("nextActivities", []) or []:
            edges.append({"source": a["activityId"], "target": nxt})
        nodes.append(node)
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- 种子主体


def ensure_seed(conn):
    """种子落库（幂等：重复执行或并发执行都不会因唯一约束失败）。

    幂等由三处保证：① 各 _seed_* 内部用 `INSERT OR IGNORE` 或先查后插；
    ② 资源按 code 判存；③ 流程定义按 code 判存。
    """
    if db.query_one("SELECT COUNT(*) AS c FROM sys_user", (), conn)["c"] > 0:
        _ensure_flow_definition(conn)
        return
    _seed_roles(conn)
    _seed_permissions(conn)
    _seed_resources(conn)
    _seed_users(conn)
    _seed_role_permissions(conn)
    _ensure_flow_definition(conn)


def _seed_roles(conn):
    """角色来自 M5 roles（+ 平台超级管理员 admin）。"""
    from ontology.registry import registry

    db.execute(
        "INSERT OR IGNORE INTO sys_role (name, code, parent_id, description, status) VALUES (?, ?, 0, ?, 1)",
        ("超级管理员", "admin", "平台内置超级管理员（拥有全部权限）"),
        conn,
    )
    for rid, role in registry["roles"].items():
        db.execute(
            "INSERT OR IGNORE INTO sys_role (name, code, parent_id, description, status) VALUES (?, ?, 0, ?, 1)",
            (role.get("name", rid), rid, role.get("description")),
            conn,
        )


def _seed_permissions(conn):
    """权限来自 M5 permissions（业务行为级）+ 平台权限；权限码由 targetRef 确定性派生。"""
    from ontology.registry import registry

    for pid, p in registry["permissions"].items():
        code = permission_code(p.get("targetRef"))
        if not code:
            continue
        db.execute(
            "INSERT OR IGNORE INTO sys_permission (code, name, target_type, target_ref, data_scope, abac_condition, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (code, p.get("name", pid), p.get("targetType", "BEHAVIOR"), p.get("targetRef", ""),
             p.get("dataScope", "ALL"), p.get("abacCondition")),
            conn,
        )
    for code, name, tt, ref in PLATFORM_PERMISSIONS:
        db.execute(
            "INSERT OR IGNORE INTO sys_permission (code, name, target_type, target_ref, data_scope, status) "
            "VALUES (?, ?, ?, ?, 'ALL', 1)",
            (code, name, tt, ref),
            conn,
        )


def _seed_resources(conn):
    """菜单 = MU application.menus（批次 1 已实现屏幕）+ 平台功能菜单。"""
    from ontology.registry import registry

    id_map = {}
    sort = 10
    for menu in registry["menus"]:
        children = []
        for child in menu.get("children", []) or []:
            meta = SCREEN_META.get(child.get("screenRef"))
            if meta:
                children.append((child.get("name"), child.get("menuId"), meta[2], "MENU", meta[0], meta[1]))
        if not children:
            continue  # 该一级菜单下暂无已实现屏幕（批次 2/3 追加）
        sort += 1
        existing = db.query_one("SELECT id FROM sys_resource WHERE code = ?", (menu.get("menuId"),), conn)
        pid = existing["id"] if existing else db.execute(
            "INSERT INTO sys_resource (parent_id, name, code, permission_code, type, path, component, icon, sort_order, status) "
            "VALUES (0, ?, ?, NULL, 'DIRECTORY', NULL, NULL, ?, ?, 1)",
            (menu.get("name"), menu.get("menuId"), DIRECTORY_ICON.get(menu.get("menuId"), "Folder"),
             sort * 100),
            conn,
        )[0]
        id_map[menu.get("menuId")] = pid
        for idx, (name, code, perm, rtype, path, icon) in enumerate(children, start=1):
            if db.query_one("SELECT id FROM sys_resource WHERE code = ?", (code,), conn):
                continue
            rid = db.execute(
                "INSERT INTO sys_resource (parent_id, name, code, permission_code, type, path, component, icon, sort_order, status) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)",
                (pid, name, code, perm, rtype, path, icon, sort * 100 + idx),
                conn,
            )[0]
            id_map[code] = rid
    # 平台菜单按固定 parent_code 结构落库
    for parent_code, name, code, pc, rtype, path, icon, so in PLATFORM_MENUS:
        if db.query_one("SELECT id FROM sys_resource WHERE code = ?", (code,), conn):
            continue
        parent_id = id_map.get(parent_code, 0) if parent_code else 0
        rid = db.execute(
            "INSERT INTO sys_resource (parent_id, name, code, permission_code, type, path, component, icon, sort_order, status) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)",
            (parent_id, name, code, pc, rtype, path, icon, so * 100),
            conn,
        )[0]
        id_map[code] = rid


def _seed_users(conn):
    for username, pwd, real_name, role_code in DEMO_USERS:
        existing = db.query_one("SELECT id FROM sys_user WHERE username = ?", (username,), conn)
        if existing:
            uid = existing["id"]
        else:
            uid = db.execute(
                "INSERT INTO sys_user (username, password, real_name, actor_type, status) VALUES (?, ?, ?, 'HUMAN', 1)",
                (username, hash_password(pwd), real_name),
                conn,
            )[0]
        role = db.query_one("SELECT id FROM sys_role WHERE code = ?", (role_code,), conn)
        db.execute("INSERT OR IGNORE INTO sys_user_role (user_id, role_id) VALUES (?, ?)", (uid, role["id"]), conn)


def _seed_role_permissions(conn):
    """角色授权来自 M5 roles[].permissions；平台权限授予 ROLE-06 与 admin。"""
    from ontology.registry import registry

    for rid, role in registry["roles"].items():
        row = db.query_one("SELECT id FROM sys_role WHERE code = ?", (rid,), conn)
        for pid in role.get("permissions", []) or []:
            p = registry["permissions"].get(pid)
            if not p:
                continue
            code = permission_code(p.get("targetRef"))
            perm = db.query_one("SELECT id FROM sys_permission WHERE code = ?", (code,), conn)
            if perm:
                db.execute(
                    "INSERT OR IGNORE INTO sys_role_permission (role_id, permission_id) VALUES (?, ?)",
                    (row["id"], perm["id"]),
                    conn,
                )
    for role_code in ("ROLE-06", "admin"):
        row = db.query_one("SELECT id FROM sys_role WHERE code = ?", (role_code,), conn)
        if not row:
            continue
        for code, _name, _tt, _ref in PLATFORM_PERMISSIONS:
            perm = db.query_one("SELECT id FROM sys_permission WHERE code = ?", (code,), conn)
            if perm:
                db.execute(
                    "INSERT OR IGNORE INTO sys_role_permission (role_id, permission_id) VALUES (?, ?)",
                    (row["id"], perm["id"]),
                    conn,
                )


def _ensure_flow_definition(conn):
    """流程定义来自 M6（审批型流程进入流程引擎；协同流为业务协同说明，不落流程定义）。"""
    from ontology.registry import registry

    for code, flow in registry.get("flows", {}).items():
        if db.query_one("SELECT id FROM flow_definition WHERE code = ?", (code,), conn):
            continue
        if flow.get("flowType") != "APPROVAL":
            continue
        trigger = flow.get("trigger", {}) or {}
        db.execute(
            "INSERT INTO flow_definition (code, name, flow_type, trigger_type, trigger_behavior, description, node_graph, version, status, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1)",
            (code, flow.get("name", code), flow.get("flowType", "APPROVAL"),
             trigger.get("triggerType", "MANUAL"), trigger.get("behaviorRef"),
             flow.get("description"), json.dumps(build_node_graph(flow), ensure_ascii=False)),
            conn,
        )
