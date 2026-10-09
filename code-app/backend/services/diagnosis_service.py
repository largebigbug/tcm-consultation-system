# -*- coding: utf-8 -*-
"""AGG-DIAGNOSIS-001 辨证结论（SyndromeDiagnosis）。

行为：Diagnosis_Save（保存草稿）/ Diagnosis_Confirm（确认结论）。
契约：docs/批次2-实现契约.md §4.2 API、§8.6 就诊与辨证规则（保存前置四诊、依据 ≥10 字、
      确认前置「就诊 IN_CONSULT + 治法已填 + INV-02 主证唯一」）。
规则来源：M1 AGG-DIAGNOSIS-001 字段表（必填/唯一/字典）+ 不变性 INV-02 +
      属性级规则 SyndromeDiagnosis.diagnosisBasis 长度不少于 10 字。

说明：conclusion_status 存字典 DICT-SYNDROME.CONCLUSION_STATUS 的 code（DRAFT/CONFIRMED）；
      编号 BZ+6 由 utils/codegen 生成；INV-02 由唯一索引 ux_diagnosis_primary 兜底，
      服务层预检 + IntegrityError → 中文提示（不透出英文异常）。
"""
import sqlite3

import db
from ontology.registry import get_dictionary_items
from services import visit_service
from utils.codegen import next_code

TABLE = "syndrome_diagnosis"

STATUS_DRAFT = "DRAFT"
STATUS_CONFIRMED = "CONFIRMED"
NATURE_PRIMARY = "PRIMARY"
NATURE_SECONDARY = "SECONDARY"
MIN_BASIS = 10  # 属性级规则：辨证依据长度不少于 10 字


def _dict_items(dict_id, type_code):
    return get_dictionary_items(dict_id, type_code)


def _codes(dict_id, type_code):
    return {i["code"] for i in _dict_items(dict_id, type_code)}


def _labels(dict_id, type_code):
    return {i["code"]: i["label"] for i in _dict_items(dict_id, type_code)}


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _clip(value, label, max_len):
    text = _text(value)
    if len(text) > max_len:
        raise ValueError("%s不能超过 %d 字" % (label, max_len))
    return text


_SELECT = """
SELECT d.*, s.syndrome_code, s.syndrome_name, s.syndrome_status,
       v.visit_no, v.visit_status, v.patient_id, v.doctor_id, p.patient_name
FROM syndrome_diagnosis d
LEFT JOIN syndrome_type s ON s.id = d.syndrome_id
LEFT JOIN visit v ON v.id = d.visit_id
LEFT JOIN patient p ON p.id = v.patient_id
"""


def _decorate(row):
    if not row:
        return row
    row["conclusion_status_label"] = _labels("DICT-SYNDROME", "CONCLUSION_STATUS").get(
        row.get("conclusion_status"), row.get("conclusion_status"))
    row["syndrome_nature_label"] = _labels("DICT-SYNDROME", "SYNDROME_NATURE").get(
        row.get("syndrome_nature"), row.get("syndrome_nature"))
    row["diagnosis_method_label"] = _labels("DICT-SYNDROME", "DIAG_METHOD").get(
        row.get("diagnosis_method"), row.get("diagnosis_method"))
    if row.get("visit_status"):
        row["visit_status_label"] = visit_service.status_label(row["visit_status"])
    row["is_editable"] = row.get("conclusion_status") == STATUS_DRAFT
    return row


def get_diagnosis(diagnosis_id, conn=None):
    try:
        diagnosis_id = int(diagnosis_id)
    except (TypeError, ValueError):
        return None
    row = db.query_one(_SELECT + " WHERE d.id = ? AND d.flag = 1", (diagnosis_id,), conn)
    return _decorate(row)


def list_diagnoses(visit_id, conn=None):
    """该就诊下全部辨证结论（UI-05 从表 / §4.2 GET /api/diagnosis?visit_id=）。"""
    rows = db.query(
        _SELECT + " WHERE d.visit_id = ? AND d.flag = 1 ORDER BY d.id", (int(visit_id),), conn
    )
    return [_decorate(r) for r in rows]


def _load_visit(visit_id):
    if visit_id in (None, ""):
        raise ValueError("就诊记录必填")
    try:
        visit_id = int(visit_id)
    except (TypeError, ValueError):
        raise ValueError("就诊记录标识非法")
    visit = db.query_one("SELECT * FROM visit WHERE id = ? AND flag = 1", (visit_id,))
    if not visit:
        raise ValueError("就诊记录不存在或已删除")
    return visit


def _assert_four_diagnosis_exists(visit_id):
    """§8.6 Diagnosis_Save：所属就诊必须已有四诊信息。"""
    row = db.query_one("SELECT id FROM four_diagnosis WHERE visit_id = ? AND flag = 1", (int(visit_id),))
    if not row:
        raise ValueError("该就诊尚未录入四诊信息，不能保存辨证结论")


def _assert_inv02(visit_id, exclude_id=None):
    """INV-02：同一就诊下「主证」只能有一条（仅约束未删除记录）。"""
    row = db.query_one(
        "SELECT id, diagnosis_no FROM syndrome_diagnosis WHERE visit_id = ? AND syndrome_nature = ? "
        "AND flag = 1 AND id <> ?",
        (int(visit_id), NATURE_PRIMARY, exclude_id or -1),
    )
    if row:
        raise ValueError("同一就诊下「主证」只能有一条，已存在主证 %s（INV-02）"
                         % (row["diagnosis_no"] or row["id"]))


def _validate(data, visit_id):
    visit = _load_visit(visit_id)
    _assert_four_diagnosis_exists(visit["id"])  # 前置：已有四诊信息

    method = _text(data.get("diagnosis_method"))
    if not method:
        raise ValueError("辨证方法必填")
    if method not in _codes("DICT-SYNDROME", "DIAG_METHOD"):
        raise ValueError("辨证方法取值不在字典范围内")

    syndrome_id = data.get("syndrome_id")
    if syndrome_id in (None, ""):
        raise ValueError("证型必填")
    try:
        syndrome_id = int(syndrome_id)
    except (TypeError, ValueError):
        raise ValueError("证型标识非法")
    syndrome = db.query_one("SELECT * FROM syndrome_type WHERE id = ? AND flag = 1", (syndrome_id,))
    if not syndrome:
        raise ValueError("证型不存在或已删除")

    nature = _text(data.get("syndrome_nature"))
    if not nature:
        raise ValueError("证型性质必填")
    if nature not in _codes("DICT-SYNDROME", "SYNDROME_NATURE"):
        raise ValueError("证型性质取值不在字典范围内")

    basis = _text(data.get("diagnosis_basis"))
    if not basis:
        raise ValueError("辨证依据必填")
    if len(basis) < MIN_BASIS:
        raise ValueError("辨证依据不少于 %d 字（当前 %d 字）" % (MIN_BASIS, len(basis)))

    principle = _text(data.get("treatment_principle"))
    if not principle:
        raise ValueError("治法必填")

    return visit, {
        "visit_id": visit["id"],
        "diagnosis_method": method,
        "syndrome_id": syndrome_id,
        "syndrome_nature": nature,
        "diagnosis_basis": _clip(basis, "辨证依据", 500),
        "treatment_principle": _clip(principle, "治法", 200),
    }


def create_diagnosis(data, user):
    """Diagnosis_Save：新增辨证结论草稿（BZ+6、conclusion_status=DRAFT）。"""
    visit, fields = _validate(data, data.get("visit_id"))
    if fields["syndrome_nature"] == NATURE_PRIMARY:
        _assert_inv02(visit["id"])
    _assert_visit_usable_for_create(visit)

    def _do(conn):
        no = next_code("syndrome_diagnosis", TABLE, "diagnosis_no", conn)
        return db.execute(
            """
            INSERT INTO syndrome_diagnosis (diagnosis_no, visit_id, diagnosis_method, syndrome_id,
                syndrome_nature, diagnosis_basis, treatment_principle, conclusion_status,
                created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (no, fields["visit_id"], fields["diagnosis_method"], fields["syndrome_id"],
             fields["syndrome_nature"], fields["diagnosis_basis"], fields["treatment_principle"],
             STATUS_DRAFT, user["id"] if user else None, user["id"] if user else None),
            conn,
        )[0]

    try:
        diagnosis_id = db.transaction(_do)
    except sqlite3.IntegrityError:
        raise ValueError("同一就诊下「主证」只能有一条（INV-02）")
    return get_diagnosis(diagnosis_id)


def _assert_visit_usable_for_create(visit):
    """已取消的就诊不得再录入辨证结论（契约 §8.6 未给状态前置，故仅拦「已取消」）。"""
    if visit["visit_status"] == visit_service.STATUS_CANCELLED:
        raise ValueError("该就诊已取消，不能保存辨证结论")


def update_diagnosis(diagnosis_id, data, user):
    """Diagnosis_Save（修改）：仅 DRAFT 可改（PUT /api/diagnosis/{id}）。"""
    existing = get_diagnosis(diagnosis_id)
    if not existing:
        raise ValueError("辨证结论不存在或已删除")
    if existing["conclusion_status"] != STATUS_DRAFT:
        raise ValueError("仅「草稿」状态的辨证结论可修改（当前状态：%s）"
                         % existing.get("conclusion_status_label"))

    visit, fields = _validate(data, existing["visit_id"])
    if fields["syndrome_nature"] == NATURE_PRIMARY:
        _assert_inv02(visit["id"], exclude_id=existing["id"])

    try:
        db.execute(
            """
            UPDATE syndrome_diagnosis SET diagnosis_method = ?, syndrome_id = ?, syndrome_nature = ?,
                diagnosis_basis = ?, treatment_principle = ?, updated_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND flag = 1 AND conclusion_status = ?
            """,
            (fields["diagnosis_method"], fields["syndrome_id"], fields["syndrome_nature"],
             fields["diagnosis_basis"], fields["treatment_principle"],
             user["id"] if user else None, int(diagnosis_id), STATUS_DRAFT),
        )
    except sqlite3.IntegrityError:
        raise ValueError("同一就诊下「主证」只能有一条（INV-02）")
    return get_diagnosis(diagnosis_id)


def confirm_diagnosis(diagnosis_id, user):
    """Diagnosis_Confirm：就诊 IN_CONSULT + 治法已填 + INV-02 → CONFIRMED。"""
    existing = db.query_one("SELECT * FROM syndrome_diagnosis WHERE id = ? AND flag = 1",
                            (int(diagnosis_id),))
    if not existing:
        raise ValueError("辨证结论不存在或已删除")
    if existing["conclusion_status"] == STATUS_CONFIRMED:
        raise ValueError("辨证结论已确认，不可重复确认")
    if existing["conclusion_status"] != STATUS_DRAFT:
        raise ValueError("仅「草稿」状态的辨证结论可确认（当前状态：%s）"
                         % existing["conclusion_status"])

    visit = _load_visit(existing["visit_id"])
    if visit["visit_status"] != visit_service.STATUS_IN_CONSULT:
        raise ValueError("仅「接诊中」状态的就诊可确认辨证结论（当前状态：%s）"
                         % visit_service.status_label(visit["visit_status"]))
    if not _text(existing["treatment_principle"]):
        raise ValueError("确认辨证结论前必须填写治法")
    if existing["syndrome_nature"] == NATURE_PRIMARY:
        _assert_inv02(visit["id"], exclude_id=existing["id"])

    try:
        db.execute(
            "UPDATE syndrome_diagnosis SET conclusion_status = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1 AND conclusion_status = ?",
            (STATUS_CONFIRMED, user["id"] if user else None, int(diagnosis_id), STATUS_DRAFT),
        )
    except sqlite3.IntegrityError:
        raise ValueError("同一就诊下「主证」只能有一条（INV-02）")
    return get_diagnosis(diagnosis_id)


def has_confirmed(visit_id, conn=None):
    """供处方链路查询：该就诊是否存在已确认的辨证结论（§8.6 Prescription_Save 前置）。"""
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM syndrome_diagnosis WHERE visit_id = ? AND flag = 1 "
        "AND conclusion_status = ?",
        (int(visit_id), STATUS_CONFIRMED),
        conn,
    )
    return bool(row and row["c"])
