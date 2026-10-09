"""AGG-SYNDROME-001 证型字典 —— 新增/修改与停用启用（Syndrome_Save / Syndrome_ChangeStatus）。

契约：§3 AGG-SYNDROME-001、§4.2 API、§8 规则落地。
规则：编码 Z+3 自动生成（utils/codegen），名称唯一，辨证体系必填。
"""
import db
from ontology.registry import get_dictionary_items
from utils.codegen import next_code

TABLE = "syndrome_type"
_STATUS_CODES = ("ENABLED", "DISABLED")


def _codes(dict_id, type_code):
    return {i["code"] for i in get_dictionary_items(dict_id, type_code)}


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _validate(data, exclude_id=None):
    name = _text(data.get("syndrome_name"))
    if not name:
        raise ValueError("证型名称必填")
    dup = db.query_one(
        "SELECT id FROM syndrome_type WHERE flag = 1 AND syndrome_name = ? AND id <> ?",
        (name, exclude_id or -1),
    )
    if dup:
        raise ValueError("证型名称已存在")

    method = _text(data.get("diagnosis_method"))
    if not method:
        raise ValueError("所属辨证体系必填")
    if method not in _codes("DICT-SYNDROME", "DIAG_METHOD"):
        raise ValueError("所属辨证体系取值不在字典范围内")

    status = _text(data.get("syndrome_status")) or "ENABLED"
    if status not in _STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")

    return {
        "syndrome_name": name,
        "diagnosis_method": method,
        "syndrome_status": status,
        "syndrome_description": _text(data.get("syndrome_description")) or None,
        "common_symptoms": _text(data.get("common_symptoms")) or None,
        "corresponding_treatment": _text(data.get("corresponding_treatment")) or None,
    }


def get_syndrome(syndrome_id, conn=None):
    return db.query_one("SELECT * FROM syndrome_type WHERE id = ? AND flag = 1", (syndrome_id,), conn)


def list_syndromes(page=1, size=10, filters=None):
    filters = filters or {}
    where = "WHERE flag = 1"
    params = []
    if filters.get("syndrome_name"):
        where += " AND syndrome_name LIKE ?"
        params.append(f"%{filters['syndrome_name']}%")
    if filters.get("syndrome_code"):
        where += " AND syndrome_code LIKE ?"
        params.append(f"%{filters['syndrome_code']}%")
    if filters.get("diagnosis_method"):
        where += " AND diagnosis_method = ?"
        params.append(filters["diagnosis_method"])
    if filters.get("syndrome_status"):
        where += " AND syndrome_status = ?"
        params.append(filters["syndrome_status"])
    total = db.query_one(f"SELECT COUNT(*) AS c FROM {TABLE} {where}", params)["c"]
    rows = db.query(
        f"SELECT * FROM {TABLE} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    return {"list": rows, "total": total, "page": page, "size": size}


def create_syndrome(data, user):
    f = _validate(data)

    def _do(conn):
        code = next_code("syndrome", TABLE, "syndrome_code", conn)
        return db.execute(
            """
            INSERT INTO syndrome_type (syndrome_code, syndrome_name, diagnosis_method, syndrome_description,
                common_symptoms, corresponding_treatment, syndrome_status, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code, f["syndrome_name"], f["diagnosis_method"], f["syndrome_description"],
             f["common_symptoms"], f["corresponding_treatment"], f["syndrome_status"],
             user["id"], user["id"]),
            conn,
        )[0]

    return get_syndrome(db.transaction(_do))


def update_syndrome(syndrome_id, data, user):
    if not get_syndrome(syndrome_id):
        raise ValueError("证型不存在或已删除")
    f = _validate(data, exclude_id=syndrome_id)
    db.execute(
        """
        UPDATE syndrome_type SET syndrome_name = ?, diagnosis_method = ?, syndrome_description = ?,
            common_symptoms = ?, corresponding_treatment = ?, syndrome_status = ?,
            updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND flag = 1
        """,
        (f["syndrome_name"], f["diagnosis_method"], f["syndrome_description"], f["common_symptoms"],
         f["corresponding_treatment"], f["syndrome_status"], user["id"], syndrome_id),
    )
    return get_syndrome(syndrome_id)


def change_status(syndrome_id, status, user):
    """Syndrome_ChangeStatus：被引用不可删除，只能停用/启用。"""
    row = get_syndrome(syndrome_id)
    if not row:
        raise ValueError("证型不存在或已删除")
    status = _text(status)
    if status not in _STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")
    if status == row["syndrome_status"]:
        raise ValueError("证型当前已是%s状态" % ("启用" if status == "ENABLED" else "停用"))
    db.execute(
        "UPDATE syndrome_type SET syndrome_status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND flag = 1",
        (status, user["id"], syndrome_id),
    )
    return get_syndrome(syndrome_id)
