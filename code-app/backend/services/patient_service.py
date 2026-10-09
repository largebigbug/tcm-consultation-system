"""AGG-PATIENT-001 患者 —— 建档与状态变更（Patient_Save / Patient_ChangeStatus）。

契约：docs/批次1-实现契约.md §2 全局约定、§3 AGG-PATIENT-001、§4.1 API、§8 规则落地。
规则：M1 Patient.refRules（姓名/出生日期/年龄/电话/地址/备注）、invariants（INV-01 证件联合唯一、
      REF-03 身份证格式、出生日期与年龄至少一项）。
"""
import re

import datetime

import db
from ontology.registry import get_dictionary_items
from utils.codegen import next_code

TABLE = "patient"

# REF-04 联系电话格式：11 位手机号 或 含区号固话
_PHONE_RE = re.compile(r"^(1[3-9]\d{9}|0\d{2,3}-?\d{7,8})$")
# REF-03 身份证：18 位 + 校验位（GB 11643-1999）
_ID_CARD_RE = re.compile(r"^\d{17}[0-9Xx]$")
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CHARS = "10X98765432"

_STATUS_CODES = ("ACTIVE", "INACTIVE")


def _codes(dict_id, type_code):
    return {i["code"] for i in get_dictionary_items(dict_id, type_code)}


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def check_id_card(id_no: str) -> bool:
    """身份证 18 位格式 + 校验位。"""
    if not _ID_CARD_RE.match(id_no or ""):
        return False
    total = sum(int(id_no[i]) * _ID_WEIGHTS[i] for i in range(17))
    return id_no[17].upper() == _ID_CHECK_CHARS[total % 11]


def _validate(data, conn, exclude_id=None):
    """逐条落地 M1 refRules / invariants，返回规范化后的字段字典。"""
    out = {}

    # 患者姓名：必填、2～20 字
    name = _text(data.get("patient_name"))
    if not name:
        raise ValueError("患者姓名必填")
    if len(name) < 2 or len(name) > 20:
        raise ValueError("患者姓名长度应在 2 到 20 字之间")
    out["patient_name"] = name

    # 性别：必填、须为字典 DICT-PATIENT.GENDER 取值
    gender = _text(data.get("gender"))
    if not gender:
        raise ValueError("性别必填")
    if gender not in _codes("DICT-PATIENT", "GENDER"):
        raise ValueError("性别取值不在字典范围内")
    out["gender"] = gender

    # 出生日期 / 年龄：至少一项；范围校验
    birth_date = _text(data.get("birth_date")) or None
    if birth_date:
        import datetime
        try:
            d = datetime.date.fromisoformat(birth_date[:10])
        except ValueError:
            raise ValueError("出生日期格式应为 yyyy-MM-dd")
        if d > datetime.date.today():
            raise ValueError("出生日期不得晚于当前日期")
        birth_date = d.isoformat()
    age = data.get("age")
    age = None if age in (None, "") else age
    if age is not None:
        try:
            age = int(age)
        except (TypeError, ValueError):
            raise ValueError("年龄必须为整数")
        if age < 0 or age > 150:
            raise ValueError("年龄应在 0 到 150 岁之间")
    if not birth_date and age is None:
        raise ValueError("出生日期与年龄至少填写一项")
    # M2 Patient_Save 后置条件：有出生日期时按出生日期自动计算年龄
    if birth_date:
        today = datetime.date.today()
        age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
        if age < 0 or age > 150:
            raise ValueError("年龄应在 0 到 150 岁之间")
    out["birth_date"] = birth_date
    out["age"] = age

    # 证件类型 + 证件号码
    id_type = _text(data.get("id_type")) or None
    id_no = _text(data.get("id_no")) or None
    if id_type and id_type not in _codes("DICT-PATIENT", "ID_TYPE"):
        raise ValueError("证件类型取值不在字典范围内")
    if id_no:
        if not id_type:
            raise ValueError("填写了证件号码时必须选择证件类型")
        if id_type == "ID_CARD" and not check_id_card(id_no):
            raise ValueError("证件类型为居民身份证时，证件号码须为 18 位且校验位正确")
        # INV-01 证件联合唯一（仅约束未删除记录、排除自身）
        dup = db.query_one(
            "SELECT id FROM patient WHERE flag = 1 AND id_type IS ? AND id_no = ? AND id <> ?",
            (id_type, id_no, exclude_id or -1),
            conn,
        )
        if dup:
            raise ValueError("同一「证件类型 + 证件号码」不得重复建档")
    out["id_type"] = id_type
    out["id_no"] = id_no

    # 联系电话：必填 + 格式
    phone = _text(data.get("phone"))
    if not phone:
        raise ValueError("联系电话必填")
    if not _PHONE_RE.match(phone):
        raise ValueError("联系电话须为 11 位手机号或含区号的固话格式")
    out["phone"] = phone

    # 联系地址 ≤100 字
    address = _text(data.get("address")) or None
    if address and len(address) > 100:
        raise ValueError("联系地址不能超过 100 字")
    out["address"] = address

    out["occupation"] = _text(data.get("occupation")) or None
    out["allergy_history"] = _text(data.get("allergy_history")) or None

    # 患者状态：默认 ACTIVE
    status = _text(data.get("patient_status")) or "ACTIVE"
    if status not in _STATUS_CODES:
        raise ValueError("患者状态取值不在字典范围内")
    out["patient_status"] = status

    # 备注 ≤200 字
    remark = _text(data.get("remark")) or None
    if remark and len(remark) > 200:
        raise ValueError("备注不能超过 200 字")
    out["remark"] = remark
    return out


def get_patient(patient_id, conn=None):
    return db.query_one("SELECT * FROM patient WHERE id = ? AND flag = 1", (patient_id,), conn)


def list_patients(page=1, size=10, filters=None):
    filters = filters or {}
    where = "WHERE flag = 1"
    params = []
    if filters.get("patient_no"):
        where += " AND patient_no LIKE ?"
        params.append(f"%{filters['patient_no']}%")
    if filters.get("patient_name"):
        where += " AND patient_name LIKE ?"
        params.append(f"%{filters['patient_name']}%")
    if filters.get("phone"):
        where += " AND phone LIKE ?"
        params.append(f"%{filters['phone']}%")
    if filters.get("patient_status"):
        where += " AND patient_status = ?"
        params.append(filters["patient_status"])
    total = db.query_one(f"SELECT COUNT(*) AS c FROM {TABLE} {where}", params)["c"]
    rows = db.query(
        f"SELECT * FROM {TABLE} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    return {"list": rows, "total": total, "page": page, "size": size}


def create_patient(data, user):
    fields = _validate(data, None)

    def _do(conn):
        no = next_code("patient", TABLE, "patient_no", conn)
        pid = db.execute(
            """
            INSERT INTO patient (patient_no, patient_name, gender, birth_date, age, id_type, id_no,
                phone, address, occupation, allergy_history, patient_status, remark, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (no, fields["patient_name"], fields["gender"], fields["birth_date"], fields["age"],
             fields["id_type"], fields["id_no"], fields["phone"], fields["address"],
             fields["occupation"], fields["allergy_history"], fields["patient_status"],
             fields["remark"], user["id"], user["id"]),
            conn,
        )[0]
        return pid

    pid = db.transaction(_do)
    return get_patient(pid)


def update_patient(patient_id, data, user):
    existing = get_patient(patient_id)
    if not existing:
        raise ValueError("患者不存在或已删除")
    fields = _validate(data, None, exclude_id=patient_id)

    def _do(conn):
        db.execute(
            """
            UPDATE patient SET patient_name = ?, gender = ?, birth_date = ?, age = ?, id_type = ?,
                id_no = ?, phone = ?, address = ?, occupation = ?, allergy_history = ?,
                patient_status = ?, remark = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND flag = 1
            """,
            (fields["patient_name"], fields["gender"], fields["birth_date"], fields["age"],
             fields["id_type"], fields["id_no"], fields["phone"], fields["address"],
             fields["occupation"], fields["allergy_history"], fields["patient_status"],
             fields["remark"], user["id"], patient_id),
            conn,
        )

    db.transaction(_do)
    return get_patient(patient_id)


def change_status(patient_id, status, user):
    """Patient_ChangeStatus：停用 / 启用（不物理删除，flag 恒为 1）。"""
    patient = get_patient(patient_id)
    if not patient:
        raise ValueError("患者不存在或已删除")
    status = _text(status)
    if status not in _STATUS_CODES:
        raise ValueError("患者状态取值不在字典范围内")
    if status == patient["patient_status"]:
        raise ValueError("患者当前已是%s状态" % ("在用" if status == "ACTIVE" else "停用"))
    db.execute(
        "UPDATE patient SET patient_status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND flag = 1",
        (status, user["id"], patient_id),
    )
    return get_patient(patient_id)
