# -*- coding: utf-8 -*-
"""工作台服务（批次 6 块①②④）：我的待办 / 已办 / 我的申请 + 审批闭环 + 转办催办。

设计口径（`docs/批次6-实现契约.md`）：

- **单一实现路径（§3）**：工作台审批**不写自己的业务回写**——由任务反查业务单据
  （`flow_instance.business_object_refs` 中 `aggregateId=='AGG-PRESCRIPTION-001'` 的 `businessId`），
  一律转发 `prescription_service.review_prescription()`（批次 2 已交付的完整实现）。
- **越权（§3.2）**：按任务 `behavior_ref` 经 `seed.permission_code` 派生 M5 权限码后校验
  （禁手写权限码；不只看「登录 + 任务归属」）。
- **转办/催办（§4.2）**：工作台侧接口按自身口径鉴权（登录 + 任务归属，非平台权限码），
  内部复用 `flow_service.transfer_task` / `flow_service.urge_task`。
- **筛选（§6）**：三页支持 `flowName` / `activityName` / `dateFrom` / `dateTo` / `status`，
  一律在 SQL 层生效（列表与 `total` 共用同一 WHERE，保证自洽）。
- **兼容**：既有返回结构（`list` / `total` / `page` / `size`）不变；新增字段为追加。
"""
import json

import db
from engine.flow_engine import FlowEngine
from seed import permission_code
from services import auth_service, flow_service, prescription_service

#: 处方聚合 id（M1 聚合）；工作台审批据此定位业务单据
PRESCRIPTION_AGGREGATE = "AGG-PRESCRIPTION-001"

#: 调剂聚合 id（M2）。注意：`business_object_refs` 里该项的 `businessId` 恒为 null
#: （处方通过时才由 `Dispense_CreatePending` 生成调剂记录，实例引用不回收更新），
#: 故本服务按同实例处方聚合的 `businessId` 回落关联调剂记录，保证前端拿得到可跳转的 `id`/`dispense_no`。
DISPENSE_AGGREGATE = "AGG-DISPENSE-001"

#: 流程实例状态中文标签（我的申请状态徽标；含 §9.7 新增取值 TERMINATED）
INSTANCE_STATUS_LABELS = {
    "RUNNING": "审批中",
    "APPROVED": "已通过",
    "REJECTED": "已驳回",
    "TERMINATED": "已终止",
}


class PermissionDenied(Exception):
    """越权（HTTP 403）——与业务规则错误（`ValueError`）区分，便于 API 层给 403。"""


# ---------------------------------------------------------------- 通用工具


def _user_role_codes(user_id, conn=None):
    return [r["code"] for r in auth_service.get_user_roles(user_id, conn)]


def _role_in_clause(role_codes):
    if not role_codes:
        return "NULL"
    return ",".join("?" for _ in role_codes)


def _is_admin_id(user_id):
    return "*" in auth_service.get_permission_codes(user_id)


def is_admin(user):
    if not user:
        return False
    codes = auth_service.get_permission_codes(user["id"])
    return "*" in codes


def _json_list(raw):
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _like(value):
    return "%%%s%%" % value


def _in_clause(values):
    return ",".join("?" for _ in values)


def _prescription_ref_id(refs):
    """从引用列表取处方聚合的 `businessId`（无则 None）。"""
    for ref in refs:
        if isinstance(ref, dict) and ref.get("aggregateId") == PRESCRIPTION_AGGREGATE and ref.get("businessId"):
            return ref["businessId"]
    return None


def _business_object(ref, prescription_id, rx_status, dispense_by_id, dispense_by_prescription):
    """单个业务对象引用 → `{aggregateId, businessId, businessNo, status}`（形状固定）。

    `status` 取对应业务对象的**当前状态 code**：
    `AGG-PRESCRIPTION-001` → `prescription.prescription_status`；
    `AGG-DISPENSE-001` → `dispense_record.record_status`（无记录 → null）。
    未识别的聚合保留引用原值、`status` 为 null。
    """
    if not isinstance(ref, dict):
        return {"aggregateId": None, "businessId": None, "businessNo": None, "status": None}
    aggregate_id = ref.get("aggregateId")
    business_id = ref.get("businessId")
    business_no = ref.get("businessNo")
    status = None
    if aggregate_id == PRESCRIPTION_AGGREGATE:
        status = rx_status.get(business_id) if business_id else None
    elif aggregate_id == DISPENSE_AGGREGATE:
        record = dispense_by_id.get(business_id) if business_id else dispense_by_prescription.get(prescription_id)
        if record:
            business_id = record["id"]
            business_no = record["dispense_no"]
            status = record["record_status"]
    return {"aggregateId": aggregate_id, "businessId": business_id, "businessNo": business_no, "status": status}


def _attach_business_objects(rows):
    """三页列表统一收尾：为每条记录追加 `business_objects`（含业务对象**当前状态**）。

    - 原 `business_object_refs` 字段**原样保留**（兼容）。
    - 批量查询（处方一条、调剂两条 IN），避免逐行 N+1。
    """
    refs_by_row = [_json_list(row.get("business_object_refs")) for row in rows]
    rx_id_by_row, rx_ids, dispense_ids = [], set(), set()
    for refs in refs_by_row:
        rx_id = _prescription_ref_id(refs)
        rx_id_by_row.append(rx_id)
        if rx_id:
            rx_ids.add(rx_id)
        for ref in refs:
            if isinstance(ref, dict) and ref.get("aggregateId") == DISPENSE_AGGREGATE and ref.get("businessId"):
                dispense_ids.add(ref["businessId"])

    rx_status = {}
    if rx_ids:
        ids = sorted(rx_ids)
        for row in db.query("SELECT id, prescription_status FROM prescription WHERE id IN (%s)"
                            % _in_clause(ids), ids):
            rx_status[row["id"]] = row["prescription_status"]

    dispense_by_id = {}
    if dispense_ids:
        ids = sorted(dispense_ids)
        for row in db.query("SELECT id, dispense_no, prescription_id, record_status FROM dispense_record "
                            "WHERE id IN (%s) AND flag = 1" % _in_clause(ids), ids):
            dispense_by_id[row["id"]] = row

    dispense_by_prescription = {}
    if rx_ids:
        ids = sorted(rx_ids)
        for row in db.query("SELECT id, dispense_no, prescription_id, record_status FROM dispense_record "
                            "WHERE prescription_id IN (%s) AND flag = 1 ORDER BY id" % _in_clause(ids), ids):
            dispense_by_prescription.setdefault(row["prescription_id"], row)

    for row, refs, rx_id in zip(rows, refs_by_row, rx_id_by_row):
        row["business_objects"] = [
            _business_object(ref, rx_id, rx_status, dispense_by_id, dispense_by_prescription) for ref in refs]
    return rows


def _apply_filters(where, params, filters, date_column, status_column=None):
    """通用筛选（§6）：名称模糊 / 时间区间 / 状态；返回 (where, params)。"""
    filters = filters or {}
    if filters.get("flowName"):
        where += " AND d.name LIKE ?"
        params.append(_like(filters["flowName"]))
    if filters.get("activityName"):
        where += " AND t.activity_name LIKE ?"
        params.append(_like(filters["activityName"]))
    if status_column and filters.get("status"):
        where += " AND %s = ?" % status_column
        params.append(filters["status"])
    if filters.get("dateFrom"):
        where += " AND date(%s) >= date(?)" % date_column
        params.append(filters["dateFrom"])
    if filters.get("dateTo"):
        where += " AND date(%s) <= date(?)" % date_column
        params.append(filters["dateTo"])
    return where, params


TASK_JOINS = """
    FROM flow_task t
    JOIN flow_instance i ON i.id = t.instance_id
    LEFT JOIN flow_definition d ON d.id = i.def_id
"""


def _task_page(where, params, page, size, order_by):
    total = db.query_one("SELECT COUNT(*) AS c " + TASK_JOINS + " WHERE " + where, params)["c"]
    rows = db.query(
        "SELECT t.*, i.business_key, i.business_object_refs, i.creator_id, i.started_at, "
        "i.status AS instance_status, d.name AS flow_name " + TASK_JOINS + " WHERE " + where +
        " ORDER BY " + order_by + " LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    return {"list": _attach_business_objects(rows), "total": total, "page": page, "size": size}


# ---------------------------------------------------------------- 三页列表


def todo(user_id, page=1, size=10, filters=None):
    """我的待办：`status` 过滤任务状态；`flowName`/`activityName`/`dateFrom`/`dateTo` 见 §6。"""
    filters = filters or {}
    if _is_admin_id(user_id):
        where = "t.status='TODO'"
        params = []
    else:
        role_codes = _user_role_codes(user_id)
        where = "t.status='TODO' AND (t.assignee_id=? OR t.role_ref IN (%s))" % _role_in_clause(role_codes)
        params = [user_id] + role_codes
    where, params = _apply_filters(where, params, filters, "t.created_at", "t.status")
    return _task_page(where, params, page, size, "t.created_at DESC, t.id DESC")


def done(user_id, page=1, size=10, filters=None):
    """我的已办：`status` 过滤审批结论（`flow_task.action`，见 §6）。"""
    filters = filters or {}
    if _is_admin_id(user_id):
        where = "t.status IN ('DONE','CANCEL')"
        params = []
    else:
        role_codes = _user_role_codes(user_id)
        where = "t.status IN ('DONE','CANCEL') AND (t.assignee_id=? OR t.role_ref IN (%s))" % _role_in_clause(role_codes)
        params = [user_id] + role_codes
    where, params = _apply_filters(where, params, filters, "t.done_at", "t.action")
    return _task_page(where, params, page, size, "t.done_at DESC, t.id DESC")


def _graph_names(def_id):
    """流程定义 `activity_id -> 活动名` 映射（我的申请「当前节点」用）。"""
    definition = db.query_one("SELECT node_graph FROM flow_definition WHERE id = ?", (def_id,))
    if not definition:
        return {}
    try:
        graph = json.loads(definition["node_graph"] or "{}")
    except Exception:
        return {}
    return {n.get("id"): n.get("name") for n in graph.get("nodes", []) if n.get("id")}


def requested(user_id, page=1, size=10, filters=None):
    """我的申请：当前用户发起的实例 + 当前节点/状态徽标 + 业务单引用（§6）。"""
    filters = filters or {}
    where = "i.creator_id=?"
    params = [user_id]
    if filters.get("flowName"):
        where += " AND d.name LIKE ?"
        params.append(_like(filters["flowName"]))
    if filters.get("status"):
        where += " AND i.status = ?"
        params.append(filters["status"])
    if filters.get("activityName"):
        where += (" AND EXISTS (SELECT 1 FROM flow_task ft WHERE ft.instance_id = i.id "
                  "AND ft.status = 'TODO' AND ft.activity_name LIKE ?)")
        params.append(_like(filters["activityName"]))
    if filters.get("dateFrom"):
        where += " AND date(i.started_at) >= date(?)"
        params.append(filters["dateFrom"])
    if filters.get("dateTo"):
        where += " AND date(i.started_at) <= date(?)"
        params.append(filters["dateTo"])

    joins = """
        FROM flow_instance i
        LEFT JOIN flow_definition d ON d.id = i.def_id
    """
    total = db.query_one("SELECT COUNT(*) AS c " + joins + " WHERE " + where, params)["c"]
    rows = db.query(
        "SELECT i.*, d.name AS flow_name " + joins + " WHERE " + where +
        " ORDER BY i.id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    cache = {}
    for row in rows:
        row["status_label"] = INSTANCE_STATUS_LABELS.get(row.get("status"), row.get("status"))
        activity_ids = _json_list(row.get("current_activity_ids"))
        names = cache.get(row["def_id"])
        if names is None:
            names = _graph_names(row["def_id"])
            cache[row["def_id"]] = names
        row["current_activity_names"] = [names.get(a, a) for a in activity_ids]
    return {"list": _attach_business_objects(rows), "total": total, "page": page, "size": size}


# ---------------------------------------------------------------- 任务与鉴权


def _load_task_and_check(task_id, user, conn=None):
    task = db.query_one("SELECT * FROM flow_task WHERE id = ?", (task_id,), conn)
    if not task:
        raise ValueError("任务不存在")
    if task["status"] != "TODO":
        raise ValueError("任务已处理，不能重复操作")
    if is_admin(user):
        return task
    if task["assignee_id"] == user["id"]:
        return task
    role_codes = _user_role_codes(user["id"], conn)
    if task["role_ref"] and task["role_ref"] in role_codes:
        return task
    raise ValueError("该任务不属于当前用户")


def _assert_behavior_permission(task, user):
    """§3.2：任务行为 → M5 权限码（由 `seed.permission_code` 派生，禁手写）→ 校验。"""
    behavior_ref = task.get("behavior_ref")
    if not behavior_ref:
        raise PermissionDenied("无权限执行该操作")
    if not auth_service.has_permission((user or {}).get("id"), permission_code(behavior_ref)):
        raise PermissionDenied("无权限执行该操作")


def _business_object_id(task, aggregate_id=PRESCRIPTION_AGGREGATE):
    """§3.1 反查规则：`business_object_refs` 中 `aggregateId` 命中的项取其 `businessId`。"""
    instance = db.query_one("SELECT * FROM flow_instance WHERE id = ?", (task["instance_id"],))
    if not instance:
        raise ValueError("未找到关联的业务单据")
    for ref in _json_list(instance.get("business_object_refs")):
        if isinstance(ref, dict) and ref.get("aggregateId") == aggregate_id and ref.get("businessId"):
            return ref["businessId"]
    raise ValueError("未找到关联的业务单据")


# ---------------------------------------------------------------- 审批（复用业务服务）


def approve(task_id, comment, user):
    """工作台「通过」：校验 M5 权限 → 反查处方 → 转发 `Prescription_Review`（APPROVE）。"""
    task = _load_task_and_check(task_id, user)
    _assert_behavior_permission(task, user)
    business_id = _business_object_id(task)
    # 不另开事务：review_prescription 自身 db.transaction 内完成业务回写 + 引擎推进（§3.1）
    return prescription_service.review_prescription(
        business_id, {"action": "APPROVE", "comment": comment}, user)


def reject(task_id, comment, user):
    """工作台「驳回」：同一实现路径（`review_prescription` 内校验驳回原因必填）。"""
    task = _load_task_and_check(task_id, user)
    _assert_behavior_permission(task, user)
    business_id = _business_object_id(task)
    return prescription_service.review_prescription(
        business_id, {"action": "REJECT", "comment": comment}, user)


def return_task(task_id, target_activity_id, comment, user):
    """退回（底座能力；契约 §0.2：前端不暴露，登记 §9.2）。"""
    def _do(conn):
        task = _load_task_and_check(task_id, user, conn)
        if not target_activity_id:
            target_activity_id = _first_approval_node(conn, task["instance_id"])
        engine = FlowEngine(conn)
        engine.return_to(task_id, target_activity_id, comment, user["id"], user["real_name"])

    db.transaction(_do)
    return True


# ---------------------------------------------------------------- 转办 / 催办（§4.2）


def _to_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("%s必须为有效数字" % label)


def transfer(task_id, assignee_id, user):
    """转办：鉴权 = 登录 + 任务归属（与 approve/reject 同口径，**非平台权限码**）。"""
    assignee_id = _to_int(assignee_id, "目标用户")

    def _do(conn):
        _load_task_and_check(task_id, user, conn)
        return flow_service.transfer_task(task_id, assignee_id, conn=conn, operator=user)

    return db.transaction(_do)


def urge(task_id, user):
    """催办：写一条 `URGE` 历史，任务不变（仅 `TODO` 可催办）。"""
    def _do(conn):
        _load_task_and_check(task_id, user, conn)
        return flow_service.urge_task(task_id, user, conn=conn)

    db.transaction(_do)
    return True


def _first_approval_node(conn, instance_id):
    inst = db.query_one("SELECT * FROM flow_instance WHERE id = ?", (instance_id,), conn)
    definition = db.query_one("SELECT * FROM flow_definition WHERE id = ?", (inst["def_id"],), conn)
    graph = json.loads(definition["node_graph"] or "{}")
    start = next((n for n in graph["nodes"] if n["type"] == "start"), None)
    if not start:
        return None
    out = [e["target"] for e in graph["edges"] if e["source"] == start["id"]]
    return out[0] if out else None
