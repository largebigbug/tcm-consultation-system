"""AGG-FOLLOWUP-001 复诊随访记录 —— 计划生成（系统行为）/ 复诊登记 / 标记失访。

契约：`docs/批次2-实现契约.md` §4.5 API、§8.3 处方提交链（FollowUp_CreatePlan，幂等）、§8.1 R-05、§9 验收。
模型：M2 FollowUp_CreatePlan（计划随访日期 = 就诊日期 + 剂数 × 1 天，D-17）、FollowUp_Complete、FollowUp_MarkLost。
规则：R-05 `RULE-FOLLOWUP-DATE-ORDER`（实际随访日期 ≥ 上次就诊挂号日期）。
说明：状态码取 M1 字典 `DICT-FOLLOWUP.FOLLOWUP_STATUS`（PENDING/COMPLETED/LOST）；
      编号 `SF+4`。`create_plan` 在调用方事务内执行（不新开事务），保证「一个行为一个事务」。
"""
import datetime

import db
from ontology.registry import get_dictionary_items
from services import domain_rules
from utils.codegen import next_code

TABLE = "follow_up"

# 随访记录状态（M1 DICT-FOLLOWUP.FOLLOWUP_STATUS）
PENDING = "PENDING"
COMPLETED = "COMPLETED"
LOST = "LOST"


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _codes(dict_id, type_code):
    return {i["code"] for i in get_dictionary_items(dict_id, type_code)}


def _label(dict_id, type_code, code):
    for item in get_dictionary_items(dict_id, type_code):
        if item["code"] == code:
            return item["label"]
    return None


def _norm_bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "是"):
        return 1
    if text in ("0", "false", "no", "n", "否"):
        return 0
    raise ValueError("是否继续用药取值不正确")


# ---------------------------------------------------------------- 读取

def get_followup(followup_id, conn=None):
    row = db.query_one("SELECT * FROM follow_up WHERE id = ? AND flag = 1", (followup_id,), conn)
    if not row:
        return None
    row = dict(row)
    row["record_status_label"] = _label("DICT-FOLLOWUP", "FOLLOWUP_STATUS", row["record_status"])
    row["efficacy_level_label"] = _label("DICT-FOLLOWUP", "EFFICACY_LEVEL", row["efficacy_level"])
    patient = db.query_one("SELECT patient_no, patient_name FROM patient WHERE id = ?",
                           (row["patient_id"],), conn)
    if patient:
        row["patient_no"] = patient["patient_no"]
        row["patient_name"] = patient["patient_name"]
    visit = db.query_one("SELECT visit_no, register_time FROM visit WHERE id = ?",
                         (row["source_visit_id"],), conn)
    if visit:
        row["visit_no"] = visit["visit_no"]
        row["source_visit_register_time"] = visit["register_time"]
    return row


def list_followups(page=1, size=10, filters=None):
    """随访列表（契约 §4.5）：结果含 `patient_name / visit_no / planned_follow_up_date`。"""
    filters = filters or {}
    where = "WHERE f.flag = 1"
    params = []
    if filters.get("patient_name"):
        where += " AND pa.patient_name LIKE ?"
        params.append("%%%s%%" % filters["patient_name"])
    if filters.get("record_status"):
        where += " AND f.record_status = ?"
        params.append(filters["record_status"])
    if filters.get("scheduled_from"):
        where += " AND f.planned_follow_up_date >= ?"
        params.append(domain_rules.as_date(filters["scheduled_from"]).strftime("%Y-%m-%d"))
    if filters.get("scheduled_to"):
        where += " AND f.planned_follow_up_date <= ?"
        params.append(domain_rules.as_date(filters["scheduled_to"]).strftime("%Y-%m-%d"))
    base = """
        FROM follow_up f
        LEFT JOIN patient pa ON pa.id = f.patient_id
        LEFT JOIN visit v ON v.id = f.source_visit_id
        %s
    """ % where
    total = db.query_one("SELECT COUNT(*) AS c " + base, params)["c"]
    rows = db.query(
        """
        SELECT f.*, pa.patient_no, pa.patient_name, v.visit_no, v.register_time AS source_visit_register_time
        """ + base + " ORDER BY f.planned_follow_up_date, f.id LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    for r in rows:
        r["record_status_label"] = _label("DICT-FOLLOWUP", "FOLLOWUP_STATUS", r["record_status"])
        r["efficacy_level_label"] = _label("DICT-FOLLOWUP", "EFFICACY_LEVEL", r["efficacy_level"])
    return {"list": rows, "total": total, "page": page, "size": size}


# ---------------------------------------------------------------- 系统行为：FollowUp_CreatePlan

def create_plan(patient_id, source_visit_id, planned_date, conn=None, created_by=None):
    """FollowUp_CreatePlan（B-03，系统行为）：生成「待随访」记录，计划随访日期 = 就诊日期 + 剂数天（D-17）。

    **幂等**：同一 `source_visit_id` 已存在随访记录则直接返回既有记录（不重复生成）。
    必须在调用方事务内执行（`conn` 由处方提交链传入），保证与处方提交、就诊收尾强一致。
    """
    existing = db.query_one(
        "SELECT * FROM follow_up WHERE source_visit_id = ? AND flag = 1", (source_visit_id,), conn)
    if existing:
        return existing

    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (source_visit_id,), conn)
    if not visit:
        raise ValueError("随访来源就诊不存在或已删除")
    patient = db.query_one("SELECT * FROM patient WHERE id = ? AND flag = 1", (patient_id,), conn)
    if not patient:
        raise ValueError("患者不存在或已删除")
    planned = domain_rules.as_date(planned_date)
    if planned is None:
        raise ValueError("计划随访日期必填")

    follow_up_no = next_code("follow_up", TABLE, "follow_up_no", conn)
    new_id = db.execute(
        """
        INSERT INTO follow_up (follow_up_no, patient_id, source_visit_id, actual_visit_id,
            planned_follow_up_date, actual_follow_up_date, efficacy_level, symptom_change,
            continue_medication, record_status, remark, created_by, updated_by)
        VALUES (?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?, NULL, ?, ?)
        """,
        (follow_up_no, patient_id, source_visit_id, planned.strftime("%Y-%m-%d"), PENDING,
         created_by, created_by),
        conn,
    )[0]
    return db.query_one("SELECT * FROM follow_up WHERE id = ?", (new_id,), conn)


# ---------------------------------------------------------------- 行为：复诊登记 / 标记失访

def complete_followup(followup_id, data, user):
    """FollowUp_Complete：回填本次就诊与疗效评价，`PENDING` → `COMPLETED`（R-05 校验日期顺序）。"""
    data = data or {}

    def _do(conn):
        row = db.query_one("SELECT * FROM follow_up WHERE id = ? AND flag = 1", (followup_id,), conn)
        if not row:
            raise ValueError("随访记录不存在或已删除")
        if row["record_status"] != PENDING:
            raise ValueError("随访记录当前状态不可登记复诊")

        actual_visit_id = data.get("actual_visit_id")
        if actual_visit_id in (None, ""):
            raise ValueError("本次就诊记录必填")
        try:
            actual_visit_id = int(actual_visit_id)
        except (TypeError, ValueError):
            raise ValueError("本次就诊记录取值不正确")
        visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (actual_visit_id,), conn)
        if not visit:
            raise ValueError("本次就诊记录不存在或已删除")

        actual_date = data.get("actual_follow_up_date")
        if actual_date in (None, ""):
            raise ValueError("实际随访日期必填")
        source_visit = db.query_one("SELECT * FROM visit WHERE id = ?", (row["source_visit_id"],), conn)
        # R-05：实际随访日期不得早于上次就诊挂号日期
        domain_rules.assert_followup_date_order(
            actual_date, source_visit["register_time"] if source_visit else None)

        efficacy = _text(data.get("efficacy_level")) or None
        if efficacy and efficacy not in _codes("DICT-FOLLOWUP", "EFFICACY_LEVEL"):
            raise ValueError("疗效评价取值不在字典范围内")

        db.execute(
            """
            UPDATE follow_up SET actual_visit_id = ?, actual_follow_up_date = ?, efficacy_level = ?,
                symptom_change = ?, continue_medication = ?, record_status = ?,
                remark = COALESCE(?, remark), updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND flag = 1
            """,
            (actual_visit_id, domain_rules.as_date(actual_date).strftime("%Y-%m-%d"), efficacy,
             _text(data.get("symptom_change")) or None, _norm_bool(data.get("continue_medication")),
             COMPLETED, _text(data.get("remark")) or None, (user or {}).get("id"), followup_id),
            conn,
        )
        return followup_id

    return get_followup(db.transaction(_do))


def mark_lost(followup_id, data, user):
    """FollowUp_MarkLost：`PENDING` → `LOST`。

    前置（M2）：① 记录状态为「待随访」；② **计划随访日期已超期**；③ 失访原因已填写。
    """
    data = data or {}
    reason = _text(data.get("remark"))
    if not reason:
        raise ValueError("失访原因必填")

    def _do(conn):
        row = db.query_one("SELECT * FROM follow_up WHERE id = ? AND flag = 1", (followup_id,), conn)
        if not row:
            raise ValueError("随访记录不存在或已删除")
        if row["record_status"] != PENDING:
            raise ValueError("随访记录当前状态不可标记失访")
        # M2 前置：计划随访日期已超期（未到计划日期不能判为失访，应继续等待随访）
        planned = row.get("planned_follow_up_date")
        if planned:
            planned_date = domain_rules.as_date(planned)
            if planned_date and planned_date >= datetime.date.today():
                raise ValueError("计划随访日期（%s）尚未超期，不可标记失访"
                                 % (planned_date.isoformat(),))
        remark = ("%s；失访原因：%s" % (row["remark"], reason)) if row["remark"] else reason
        db.execute(
            "UPDATE follow_up SET record_status = ?, remark = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (LOST, remark, (user or {}).get("id"), followup_id),
            conn,
        )
        return followup_id

    return get_followup(db.transaction(_do))
