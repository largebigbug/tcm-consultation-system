"""AGG-PRESCRIPTION-001 处方（+ PrescriptionItem）—— 开具 / 提交送审 / 审核 / 作废。

契约：`docs/批次2-实现契约.md` §4.3 API、§8.2 事务边界、§8.3 处方提交链、§8.4 审核与作废链、
      §8.1 R-01/R-03/R-04、§9 验收；字段表 REF-10/REF-11/REF-12、INV-04、明细饮片不重复。
行为：Prescription_Save / Prescription_Submit / Prescription_Review / Prescription_Cancel，
      并编排系统行为 Visit_Complete、FollowUp_CreatePlan、Dispense_CreatePending、
      Dispense_CancelPending、Herb_ReturnStock。
状态码：M1 字典 `DICT-PRESCRIPTION.PRESCRIPTION_STATUS` 的 code
      （DRAFT → PENDING_REVIEW → APPROVED / REJECTED → DISPENSING → ISSUED；另有 VOIDED）。
      契约文本里写的 SUBMITTED / DISPENSED 是同一语义的别名，仅在入参/过滤条件上做兼容归一。
事务：一个行为一个事务（`db.transaction`）；提交链、审核链、作废链的跨聚合联动都在这一个事务里完成。
"""
import datetime

import db
from engine.flow_engine import FlowEngine
from ontology.registry import get_dictionary_items
from services import dispense_service, domain_rules, flow_service, followup_service
from utils.codegen import next_code

TABLE = "prescription"
ITEM_TABLE = "prescription_item"
FLOW_CODE = "FLOW-PRESCRIPTION-APPROVAL-001"

# 处方状态（M1 DICT-PRESCRIPTION.PRESCRIPTION_STATUS）
DRAFT = "DRAFT"
PENDING_REVIEW = "PENDING_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
DISPENSING = "DISPENSING"
ISSUED = "ISSUED"
VOIDED = "VOIDED"

# 契约 §2.3 文本别名 → M1 字典 code（仅用于入参兼容，落库一律用 M1 code）
STATUS_ALIASES = {
    "SUBMITTED": PENDING_REVIEW,
    "DISPENSED": DISPENSING,
    "PENDING_REVIEW": PENDING_REVIEW,
    "DISPENSING": DISPENSING,
}

# 就诊「接诊中」：M1 字典 code 为 IN_PROGRESS，契约文本写作 IN_CONSULT（跨模块读取两者都接受）
VISIT_IN_CONSULT = ("IN_PROGRESS", "IN_CONSULT")
VISIT_REGISTERED = "REGISTERED"
VISIT_COMPLETED = "COMPLETED"
VISIT_CANCELLED = "CANCELLED"

MAX_DOSES = 30
MIN_DOSES = 1


# ---------------------------------------------------------------- 工具

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _to_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("%s必须为整数" % label)


def _to_decimal(value, label, required=True):
    if value in (None, ""):
        if required:
            raise ValueError("%s必填" % label)
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        raise ValueError("%s必须为数字" % label)


def _labels(dict_id, type_code):
    return {i["code"]: i["label"] for i in get_dictionary_items(dict_id, type_code)}


def _codes(dict_id, type_code):
    return set(_labels(dict_id, type_code))


def _status_label(code):
    return _labels("DICT-PRESCRIPTION", "PRESCRIPTION_STATUS").get(code)


def normalize_status(value):
    """处方状态入参归一：契约别名 → M1 字典 code。"""
    text = _text(value).upper()
    if not text:
        return None
    if text in _codes("DICT-PRESCRIPTION", "PRESCRIPTION_STATUS"):
        return text
    return STATUS_ALIASES.get(text, text)


def _herb_map(herb_ids, conn=None):
    ids = []
    for raw in herb_ids or []:
        if raw in (None, ""):
            continue
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = db.query("SELECT * FROM herb WHERE id IN (%s) AND flag = 1" % placeholders, ids, conn)
    return {r["id"]: r for r in rows}


def _patient_name(patient_id, conn=None):
    row = db.query_one("SELECT patient_name FROM patient WHERE id = ?", (patient_id,), conn)
    return row["patient_name"] if row else None


# ---------------------------------------------------------------- 跨模块：就诊

def _visit_service():
    """后端 A 的 visit_service（并行开发，可能尚未到位）。"""
    try:
        from services import visit_service  # noqa: WPS433
        return visit_service
    except Exception:
        return None


def get_visit(visit_id, conn=None):
    """优先调用 `visit_service.get_visit`；模块未到位时按同口径直接读取（保证本批可独立验收）。"""
    module = _visit_service()
    if module and hasattr(module, "get_visit"):
        try:
            return module.get_visit(visit_id, conn)
        except TypeError:
            return module.get_visit(visit_id)
    return db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (visit_id,), conn)


def _complete_visit(conn, visit_id):
    """Visit_Complete（B-04）：处方提交送审成功后把就诊置「已完成」。

    优先调用 `visit_service.complete_visit(visit_id, conn)`（契约要求的跨模块入口）；
    模块未到位时按同口径兜底（仅 IN_PROGRESS/IN_CONSULT → COMPLETED，已完成视为幂等）。
    返回 (就诊状态, 调用来源)。
    """
    module = _visit_service()
    if module and hasattr(module, "complete_visit"):
        try:
            # 幂等语义：就诊已完成时不报错（同一就诊多张处方先后提交）
            visit = module.complete_visit(visit_id, conn, allow_idempotent=True)
        except TypeError:
            visit = module.complete_visit(visit_id, conn)
        return (visit or {}).get("visit_status"), "visit_service.complete_visit"

    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (visit_id,), conn)
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    status = visit["visit_status"]
    if status in VISIT_IN_CONSULT:
        status = VISIT_COMPLETED
        db.execute(
            "UPDATE visit SET visit_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (status, visit_id), conn)
    elif status == VISIT_COMPLETED:
        pass  # 幂等：已完成的就诊不重复收尾
    elif status == VISIT_CANCELLED:
        raise ValueError("就诊已取消，不能收尾")
    else:
        raise ValueError("就诊尚未接诊，不能收尾")
    return status, "fallback:prescription_service"


def _require_visit_in_consult(visit_id, conn):
    visit = get_visit(visit_id, conn)
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    if visit["visit_status"] not in VISIT_IN_CONSULT:
        raise ValueError("就诊当前状态不可开具处方（仅「接诊中」可开方）")
    return visit


def _require_confirmed_diagnosis(visit_id, conn):
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM syndrome_diagnosis WHERE visit_id = ? AND flag = 1 "
        "AND conclusion_status = 'CONFIRMED'", (visit_id,), conn)
    if not row or row["c"] <= 0:
        raise ValueError("所属就诊不存在「已确认」的辨证结论，不可开具处方")


# ---------------------------------------------------------------- 校验

def _validate_items(raw_items, herb_map):
    """明细校验：非空、饮片存在、饮片不重复、单剂剂量 > 0（REF-12）。"""
    if not raw_items:
        raise ValueError("处方明细不得为空（INV-04）")
    seen = set()
    items = []
    for idx, raw in enumerate(raw_items, start=1):
        herb_id = raw.get("herb_id")
        if herb_id in (None, ""):
            raise ValueError("第 %d 行处方明细未选择饮片" % idx)
        herb_id = _to_int(herb_id, "饮片")
        if herb_id not in herb_map:
            raise ValueError("饮片不存在或已删除（第 %d 行）" % idx)
        if herb_id in seen:
            raise ValueError("同一处方内饮片不得重复：%s" % herb_map[herb_id]["herb_name"])
        seen.add(herb_id)
        single_dose = _to_decimal(raw.get("single_dose"), "第 %d 行单剂剂量" % idx)
        if single_dose <= 0:
            raise ValueError("单剂剂量必须大于 0（REF-12）")  # REF-12
        method = _text(raw.get("decoction_method")) or None
        if method and method not in _codes("DICT-PRESCRIPTION", "DECOCTION_METHOD"):
            raise ValueError("特殊煎法取值不在字典范围内")
        items.append({
            "seq_no": idx,
            "herb_id": herb_id,
            "single_dose": single_dose,
            "decoction_method": method,
            "remark": _text(raw.get("remark")) or None,
            "over_dose_reason": _text(raw.get("over_dose_reason")) or None,
        })
    return items


def _validate_master(data):
    prescription_type = _text(data.get("prescription_type"))
    if prescription_type not in _codes("DICT-PRESCRIPTION", "PRESCRIPTION_TYPE"):
        raise ValueError("处方类型取值不在字典范围内")
    usage_method = _text(data.get("usage_method"))
    if usage_method not in _codes("DICT-PRESCRIPTION", "USAGE_METHOD"):
        raise ValueError("用法取值不在字典范围内")
    doses = _to_int(data.get("doses"), "剂数")
    if doses < MIN_DOSES or doses > MAX_DOSES:
        raise ValueError("剂数必须在 %d 到 %d 之间（REF-10）" % (MIN_DOSES, MAX_DOSES))  # REF-10
    return {
        "prescription_type": prescription_type,
        "usage_method": usage_method,
        "doses": doses,
        "formula_template_id": data.get("formula_template_id") or None,
        "decoction_instruction": _text(data.get("decoction_instruction")) or None,
        "medical_advice": _text(data.get("medical_advice")) or None,
    }


def _prescription_row(prescription_id, conn=None):
    return db.query_one("SELECT * FROM prescription WHERE id = ? AND flag = 1",
                        (prescription_id,), conn)


def _items(prescription_id, conn=None):
    return db.query(
        "SELECT * FROM prescription_item WHERE prescription_id = ? AND flag = 1 ORDER BY seq_no, id",
        (prescription_id,), conn)


# ---------------------------------------------------------------- 查询

_LIST_SELECT = """
SELECT p.*, pa.patient_name, pa.patient_no, v.visit_no, u.real_name AS doctor_name,
       (SELECT COUNT(*) FROM prescription_item i WHERE i.prescription_id = p.id AND i.flag = 1) AS item_count
FROM prescription p
LEFT JOIN patient pa ON pa.id = p.patient_id
LEFT JOIN visit v ON v.id = p.visit_id
LEFT JOIN sys_user u ON u.id = CAST(p.doctor_id AS INTEGER)
"""


def _decorate(row, conn=None):
    if not row:
        return None
    row = dict(row)
    row["prescription_status_label"] = _status_label(row["prescription_status"])
    record = dispense_service.get_by_prescription(row["id"], conn)
    row["dispense_record"] = dict(record) if record else None
    return row


def list_prescriptions(page=1, size=10, filters=None):
    """处方列表（契约 §4.3）。"""
    filters = filters or {}
    where = "WHERE p.flag = 1"
    params = []
    if filters.get("prescription_no"):
        where += " AND p.prescription_no LIKE ?"
        params.append("%%%s%%" % filters["prescription_no"])
    if filters.get("visit_id"):
        where += " AND p.visit_id = ?"
        params.append(_to_int(filters["visit_id"], "就诊"))
    if filters.get("patient_name"):
        where += " AND pa.patient_name LIKE ?"
        params.append("%%%s%%" % filters["patient_name"])
    status = normalize_status(filters.get("prescription_status"))
    if status:
        where += " AND p.prescription_status = ?"
        params.append(status)
    total = db.query_one("SELECT COUNT(*) AS c FROM prescription p "
                         "LEFT JOIN patient pa ON pa.id = p.patient_id " + where, params)["c"]
    rows = db.query(_LIST_SELECT + where + " ORDER BY p.id DESC LIMIT ? OFFSET ?",
                    params + [size, (page - 1) * size])
    for r in rows:
        r["prescription_status_label"] = _status_label(r["prescription_status"])
    return {"list": rows, "total": total, "page": page, "size": size}


def get_prescription(prescription_id, conn=None):
    """处方详情：主表 + `items[]`（含饮片常用量/毒性/上限）+ `dose_check[]`（R-01）+ 调剂记录。"""
    row = db.query_one(_LIST_SELECT + "WHERE p.id = ? AND p.flag = 1", (prescription_id,), conn)
    if not row:
        return None
    row = _decorate(row, conn)
    items = db.query(
        """
        SELECT i.*, h.herb_code, h.herb_name, h.min_common_dose, h.max_common_dose,
               h.toxicity_level, h.toxic_dose_limit, h.stock_quantity
        FROM prescription_item i
        LEFT JOIN herb h ON h.id = i.herb_id
        WHERE i.prescription_id = ? AND i.flag = 1
        ORDER BY i.seq_no, i.id
        """,
        (prescription_id,), conn)
    herb_map = _herb_map([i["herb_id"] for i in items], conn)
    row["items"] = items
    row["dose_check"] = domain_rules.check_prescription_items(items, herb_map)          # R-01
    row["toxic_check"] = domain_rules.check_toxic_total(items, herb_map)               # R-03
    row["stock_check"] = domain_rules.check_stock_sufficient(items, row["doses"], herb_map)  # R-02
    row["over_dose_flag"] = any(r["verdict"] != domain_rules.PASS for r in row["dose_check"])
    syndromes = db.query(
        """
        SELECT d.*, s.syndrome_name, s.syndrome_code FROM syndrome_diagnosis d
        LEFT JOIN syndrome_type s ON s.id = d.syndrome_id
        WHERE d.visit_id = ? AND d.flag = 1 ORDER BY d.id
        """,
        (row["visit_id"],), conn)
    row["syndromes"] = syndromes
    confirmed = [s for s in syndromes if s["conclusion_status"] == "CONFIRMED"]
    row["diagnosis_summary"] = "；".join(
        "%s（%s）" % (s.get("syndrome_name") or "", s.get("treatment_principle") or "")
        for s in confirmed) or None
    return row


def list_pending_review(page=1, size=10, filters=None):
    """待审核列表（UI-07 载入）：`PENDING_REVIEW` + 患者/开方医师/剂数/提交时间 + 超量标记。"""
    filters = filters or {}
    where = "WHERE p.flag = 1 AND p.prescription_status = ?"
    params = [PENDING_REVIEW]
    if filters.get("prescription_no"):
        where += " AND p.prescription_no LIKE ?"
        params.append("%%%s%%" % filters["prescription_no"])
    if filters.get("patient_name"):
        where += " AND pa.patient_name LIKE ?"
        params.append("%%%s%%" % filters["patient_name"])
    overdose = """
        (SELECT COUNT(*) FROM prescription_item i JOIN herb h ON h.id = i.herb_id
          WHERE i.prescription_id = p.id AND i.flag = 1 AND i.single_dose > h.max_common_dose)
    """
    base = _LIST_SELECT.replace(
        "(SELECT COUNT(*) FROM prescription_item i WHERE i.prescription_id = p.id AND i.flag = 1) AS item_count",
        "(SELECT COUNT(*) FROM prescription_item i WHERE i.prescription_id = p.id AND i.flag = 1) AS item_count, "
        "%s AS over_dose_item_count" % overdose) + where
    total = db.query_one("SELECT COUNT(*) AS c FROM prescription p "
                         "LEFT JOIN patient pa ON pa.id = p.patient_id " + where, params)["c"]
    rows = db.query(base + " ORDER BY p.submit_time, p.id LIMIT ? OFFSET ?",
                    params + [size, (page - 1) * size])
    for r in rows:
        r["prescription_status_label"] = _status_label(r["prescription_status"])
        r["has_over_dose"] = bool(r.get("over_dose_item_count"))
    return {"list": rows, "total": total, "page": page, "size": size}


def list_pending_dispense(page=1, size=10, filters=None):
    """待调剂列表（UI-08 载入）。"""
    return dispense_service.list_pending_dispense(page, size, filters)


# ---------------------------------------------------------------- 行为：开具 / 修改


def create_prescription(data, user):
    """Prescription_Save：主表 + 明细（DRAFT）；首次保存写 `prescribe_time`。"""
    data = data or {}
    master = _validate_master(data)
    visit_id = data.get("visit_id")
    if visit_id in (None, ""):
        raise ValueError("就诊记录必填")
    visit_id = _to_int(visit_id, "就诊记录")

    def _do(conn):
        visit = _require_visit_in_consult(visit_id, conn)          # 就诊必须「接诊中」
        _require_confirmed_diagnosis(visit_id, conn)               # 必须存在已确认辨证结论
        patient_id = data.get("patient_id") or visit["patient_id"]
        patient_id = _to_int(patient_id, "患者")
        if not _patient_name(patient_id, conn):
            raise ValueError("患者不存在或已删除")
        doctor_id = _text(data.get("doctor_id")) or _text(visit["doctor_id"])
        if not doctor_id:
            raise ValueError("开方医师必填")

        raw_items = data.get("items") or data.get("prescription_items") or []
        herb_map = _herb_map([(i or {}).get("herb_id") for i in raw_items], conn)
        items = _validate_items(raw_items, herb_map)               # INV-04 / 重复 / REF-12
        domain_rules.assert_dose_limit(items, herb_map)            # R-01（BLOCK / 需理由未填 → 阻断）

        prescribe_time = _text(data.get("prescribe_time")) or _now()
        prescription_no = next_code("prescription", TABLE, "prescription_no", conn)
        new_id = db.execute(
            """
            INSERT INTO prescription (prescription_no, visit_id, patient_id, doctor_id,
                prescription_type, formula_template_id, doses, usage_method, decoction_instruction,
                medical_advice, prescribe_time, submit_time, prescription_status, reviewer_id,
                review_time, reject_reason, cancel_reason, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (prescription_no, visit_id, patient_id, doctor_id, master["prescription_type"],
             master["formula_template_id"], master["doses"], master["usage_method"],
             master["decoction_instruction"], master["medical_advice"], prescribe_time,
             DRAFT, (user or {}).get("id"), (user or {}).get("id")),
            conn,
        )[0]
        _insert_items(conn, new_id, prescription_no, items, user)
        return new_id

    return get_prescription(db.transaction(_do))


def _insert_items(conn, prescription_id, prescription_no, items, user):
    for item in items:
        db.execute(
            """
            INSERT INTO prescription_item (prescription_id, item_id, seq_no, herb_id, single_dose,
                decoction_method, remark, over_dose_reason, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (prescription_id, "%s-%02d" % (prescription_no, item["seq_no"]), item["seq_no"],
             item["herb_id"], item["single_dose"], item["decoction_method"], item["remark"],
             item["over_dose_reason"], (user or {}).get("id"), (user or {}).get("id")),
            conn,
        )


def update_prescription(prescription_id, data, user):
    """Prescription_Save（修改）：仅 `DRAFT`/`REJECTED` 可改；从表全量重建。"""
    data = data or {}
    master = _validate_master(data)

    def _do(conn):
        row = _prescription_row(prescription_id, conn)
        if not row:
            raise ValueError("处方不存在或已删除")
        if row["prescription_status"] not in (DRAFT, REJECTED):
            raise ValueError("仅草稿或已驳回的处方可以修改")
        visit = get_visit(row["visit_id"], conn)
        if not visit:
            raise ValueError("就诊记录不存在或已删除")
        if row["prescription_status"] == REJECTED:
            # 驳回后修改重提：就诊已被提交链收尾为「已完成」（M6 Q04 节点「中医师修改处方并重新提交」），
            # 故仅要求就诊未被取消；草稿仍严格要求就诊处于「接诊中」（M2 前置条件）。
            if visit["visit_status"] == VISIT_CANCELLED:
                raise ValueError("就诊已取消，不可修改处方")
        elif visit["visit_status"] not in VISIT_IN_CONSULT:
            raise ValueError("就诊当前状态不可修改处方（仅「接诊中」可开方）")

        raw_items = data.get("items") or data.get("prescription_items") or []
        herb_map = _herb_map([(i or {}).get("herb_id") for i in raw_items], conn)
        items = _validate_items(raw_items, herb_map)
        domain_rules.assert_dose_limit(items, herb_map)  # R-01

        db.execute(
            """
            UPDATE prescription SET prescription_type = ?, formula_template_id = ?, doses = ?,
                usage_method = ?, decoction_instruction = ?, medical_advice = ?,
                updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1
            """,
            (master["prescription_type"], master["formula_template_id"], master["doses"],
             master["usage_method"], master["decoction_instruction"], master["medical_advice"],
             (user or {}).get("id"), prescription_id),
            conn,
        )
        # 从表全量重建：旧明细逻辑删除（flag=0），按新明细重写
        db.execute("UPDATE prescription_item SET flag = 0, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                   "WHERE prescription_id = ? AND flag = 1", ((user or {}).get("id"), prescription_id), conn)
        _insert_items(conn, prescription_id, row["prescription_no"], items, user)
        return prescription_id

    return get_prescription(db.transaction(_do))


# ---------------------------------------------------------------- 行为：提交送审（联动链）


def submit_prescription(prescription_id, user):
    """Prescription_Submit（单事务，契约 §8.3）：

    ① 处方 → `PENDING_REVIEW` + `submit_time`；
    ② 引擎启动审批流实例（`FLOW-PRESCRIPTION-APPROVAL-001`，待办任务角色为中药师 ROLE-03）；
    ③ 联动 Visit_Complete → 就诊 `COMPLETED`；
    ④ 联动 FollowUp_CreatePlan → 计划随访日期 = 就诊挂号日期 + 剂数天（幂等）。
    前置：状态 ∈ {DRAFT, REJECTED}、明细非空（INV-04）、R-01 非 BLOCK / 超量已填理由、R-03 通过。
    """
    def _do(conn):
        row = _prescription_row(prescription_id, conn)
        if not row:
            raise ValueError("处方不存在或已删除")
        if row["prescription_status"] not in (DRAFT, REJECTED):
            raise ValueError("仅草稿或已驳回的处方可以提交送审")

        items = _items(prescription_id, conn)
        if not items:
            raise ValueError("处方明细不得为空（INV-04）")  # INV-04
        herb_map = _herb_map([i["herb_id"] for i in items], conn)
        dose_check = domain_rules.assert_dose_limit(items, herb_map)       # R-01
        toxic_check = domain_rules.assert_toxic_total(items, herb_map)     # R-03

        submit_time = _now()
        db.execute(
            "UPDATE prescription SET prescription_status = ?, submit_time = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (PENDING_REVIEW, submit_time, (user or {}).get("id"), prescription_id), conn)

        # ② 引擎启动审批流实例
        engine = FlowEngine(conn)
        definition = engine.get_definition_by_code(FLOW_CODE)
        if not definition:
            raise ValueError("流程定义不存在：%s" % FLOW_CODE)
        business_key = "处方%s" % row["prescription_no"]
        instance_id = engine.start(
            definition["id"],
            business_key=business_key,
            business_object_refs=[
                {"aggregateId": "AGG-PRESCRIPTION-001", "businessId": row["id"],
                 "businessNo": row["prescription_no"]},
                {"aggregateId": "AGG-DISPENSE-001", "businessId": None, "businessNo": None},
            ],
            variables={
                "prescriptionId": row["id"],
                "prescriptionNo": row["prescription_no"],
                "patientId": row["patient_id"],
                "doses": row["doses"],
                "hasOverDose": domain_rules.has_over_dose(dose_check),
                "visitId": row["visit_id"],
            },
            creator_id=(user or {}).get("id"),
        )

        # ③ 联动 Visit_Complete
        visit_status, visit_via = _complete_visit(conn, row["visit_id"])

        # ④ 联动 FollowUp_CreatePlan（计划随访日期 = 就诊挂号日期 + 剂数天）
        visit = get_visit(row["visit_id"], conn)
        planned = domain_rules.as_date(visit["register_time"]) + datetime.timedelta(days=int(row["doses"]))
        plan = followup_service.create_plan(row["patient_id"], row["visit_id"], planned, conn,
                                           created_by=(user or {}).get("id"))

        return {
            "prescription_id": prescription_id,
            "prescription_no": row["prescription_no"],
            "prescription_status": PENDING_REVIEW,
            "submit_time": submit_time,
            "flow_instance_id": instance_id,
            "flow_instance_code": FLOW_CODE,
            "business_key": business_key,
            "visit_id": row["visit_id"],
            "visit_status": visit_status,
            "visit_complete_via": visit_via,
            "follow_up_id": plan["id"],
            "follow_up_no": plan["follow_up_no"],
            "planned_follow_up_date": plan["planned_follow_up_date"],
            "dose_check": dose_check,
            "toxic_check": toxic_check,
        }

    result = db.transaction(_do)
    result["prescription"] = get_prescription(prescription_id)
    return result


# ---------------------------------------------------------------- 行为：审核（含 Dispense_CreatePending）


def _todo_task_id(conn, business_key):
    row = db.query_one(
        """
        SELECT t.id FROM flow_task t JOIN flow_instance i ON i.id = t.instance_id
        WHERE i.business_key = ? AND t.status = 'TODO' ORDER BY t.id LIMIT 1
        """,
        (business_key,), conn)
    return row["id"] if row else None


def review_prescription(prescription_id, data, user):
    """Prescription_Review：APPROVE → `APPROVED`（+ 生成待调剂记录 + 结束审批任务）；
    REJECT → `REJECTED` + `reject_reason`（必填）。"""
    data = data or {}
    action = _text(data.get("action")).upper()
    comment = _text(data.get("comment"))
    if action not in ("APPROVE", "REJECT"):
        raise ValueError("审核动作必须为 APPROVE 或 REJECT")
    if action == "REJECT" and not comment:
        raise ValueError("驳回原因必填")

    def _do(conn):
        row = _prescription_row(prescription_id, conn)
        if not row:
            raise ValueError("处方不存在或已删除")
        if row["prescription_status"] != PENDING_REVIEW:
            raise ValueError("处方当前状态不可审核（仅「待审核」可审核）")

        review_time = _now()
        business_key = "处方%s" % row["prescription_no"]
        task_id = _todo_task_id(conn, business_key)
        engine = FlowEngine(conn)
        operator_name = (user or {}).get("real_name") or (user or {}).get("username")

        if action == "REJECT":
            db.execute(
                "UPDATE prescription SET prescription_status = ?, reviewer_id = ?, review_time = ?, "
                "reject_reason = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND flag = 1",
                (REJECTED, str((user or {}).get("id") or ""), review_time, comment,
                 (user or {}).get("id"), prescription_id), conn)
            if task_id:
                engine.reject(task_id, comment, (user or {}).get("id"), operator_name)
            return {"action": "REJECT", "prescription_status": REJECTED, "reject_reason": comment,
                    "review_time": review_time, "flow_task_id": task_id, "dispense_record": None}

        db.execute(
            "UPDATE prescription SET prescription_status = ?, reviewer_id = ?, review_time = ?, "
            "reject_reason = NULL, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND flag = 1",
            (APPROVED, str((user or {}).get("id") or ""), review_time, (user or {}).get("id"),
             prescription_id), conn)
        approved = _prescription_row(prescription_id, conn)
        record = dispense_service.create_pending(conn, approved, user)  # Dispense_CreatePending（幂等）
        if task_id:
            engine.approve(task_id, comment, (user or {}).get("id"), operator_name)
        return {"action": "APPROVE", "prescription_status": APPROVED, "review_time": review_time,
                "reviewer_id": str((user or {}).get("id") or ""), "flow_task_id": task_id,
                "dispense_record": dict(record) if record else None}

    result = db.transaction(_do)
    result["prescription"] = get_prescription(prescription_id)
    return result


# ---------------------------------------------------------------- 行为：作废（R-04 三分派）


def cancel_prescription(prescription_id, data, user):
    """Prescription_Cancel：`cancel_reason` 必填 → R-04 分派：

    - `VOID_ONLY`：处方 → `VOIDED`；存在 `PENDING` 调剂记录 → Dispense_CancelPending（`CANCELLED`）；
    - `VOID_WITH_ROLLBACK`：处方 → `VOIDED`；调剂记录 → `CANCELLED`；Herb_ReturnStock 逐味回冲；
    - `BLOCK`：抛「处方已发药，不可作废」（状态不变）。
    前置：状态 ∈ {DRAFT, PENDING_REVIEW, APPROVED}。
    """
    data = data or {}
    reason = _text(data.get("cancel_reason"))
    if not reason:
        raise ValueError("作废原因必填")

    def _do(conn):
        row = _prescription_row(prescription_id, conn)
        if not row:
            raise ValueError("处方不存在或已删除")
        record = dispense_service.get_by_prescription(prescription_id, conn)
        # R-04 判定（先于状态前置判断，保证「已发药」给出规则文案）
        dispatch = domain_rules.assert_void_dispatch(
            record["record_status"] if record else None, row["prescription_status"])
        # 前置状态：契约 §8.4 写作 {DRAFT, SUBMITTED, APPROVED}，但 §8.4 的 VOID_WITH_ROLLBACK 分支
        # 与本批验收（§9 第 5 项「调剂后作废 → 回冲流水」）要求「已调剂」（M1 code DISPENSING）也可作废，
        # 故此处以 R-04 分派为准：仅「已发药」「已作废」不可作废。
        if row["prescription_status"] in (ISSUED, VOIDED):
            raise ValueError("处方当前状态不可作废")

        cancelled_dispense = None
        rollback = None
        if dispatch == domain_rules.VOID_WITH_ROLLBACK:
            cancelled = dispense_service.cancel_pending(conn, prescription_id, user,
                                                       remark="处方作废取消调剂记录")
            cancelled_dispense = dict(cancelled) if cancelled else None
            rollback = dispense_service.return_stock(conn, row, user)   # Herb_ReturnStock
        elif record and record["record_status"] == dispense_service.PENDING:
            cancelled = dispense_service.cancel_pending(conn, prescription_id, user,
                                                       remark="处方作废取消待调剂记录")
            cancelled_dispense = dict(cancelled) if cancelled else None

        db.execute(
            "UPDATE prescription SET prescription_status = ?, cancel_reason = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (VOIDED, reason, (user or {}).get("id"), prescription_id), conn)

        # 审批中的处方作废（M6 网关 Q03「处方已被作废 → QE02 终止」）：
        # 同一事务内终止流程实例（TERMINATED + 取消 TODO + flow_history(action='TERMINATE')），
        # 不得再以 engine.reject 冒充终止（那会把实例置为 APPROVED，语义错误）。
        flow_task_id = None
        flow_instance_id = None
        flow_instance_status = None
        if row["prescription_status"] == PENDING_REVIEW:
            business_key = "处方%s" % row["prescription_no"]
            instance = db.query_one(
                "SELECT * FROM flow_instance WHERE business_key = ? AND status = 'RUNNING' ORDER BY id LIMIT 1",
                (business_key,), conn)
            if instance:
                flow_instance_id = instance["id"]
                task_row = db.query_one(
                    "SELECT id FROM flow_task WHERE instance_id = ? AND status = 'TODO' ORDER BY id LIMIT 1",
                    (instance["id"],), conn)
                flow_task_id = task_row["id"] if task_row else None
                flow_service.terminate_instance(
                    instance["id"], user, conn=conn,
                    comment="处方作废，审批实例终止（作废原因：%s）" % reason)
                flow_instance_status = "TERMINATED"

        return {
            "dispatch": dispatch,
            "rollback_quantity": (rollback or {}).get("total_quantity", 0),
            "rollback_items": (rollback or {}).get("items", []),
            "cancelled_dispense": cancelled_dispense,
            "prescription_status": VOIDED,
            "cancel_reason": reason,
            "flow_task_id": flow_task_id,
            "flow_instance_id": flow_instance_id,
            "flow_instance_status": flow_instance_status,
        }

    result = db.transaction(_do)
    result["prescription"] = get_prescription(prescription_id)
    return result
