"""AGG-FORMULA-001 方剂模板（+ FormulaItem 组成明细）—— Formula_Save / Formula_ChangeStatus。

契约：§2.3 主从单事务、§3 AGG-FORMULA-001、§4.3 API、§8 规则落地。
校验：名称唯一、类型必填、明细 ≥1 行且药味不重复、herb_id 必须存在且 flag=1、常用剂量 > 0。
注意：主表「功用」列名是 SQLite 关键字 function，SQL 中一律写成 "function"。
"""
import uuid

import db
from ontology.registry import get_dictionary_items
from utils.codegen import next_code

TABLE = "formula_template"
_STATUS_CODES = ("ENABLED", "DISABLED")


def _codes(dict_id, type_code):
    return {i["code"] for i in get_dictionary_items(dict_id, type_code)}


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _to_int(value, label):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("%s必须为整数" % label)


def _validate_master(data, exclude_id=None):
    name = _text(data.get("formula_name"))
    if not name:
        raise ValueError("方剂名称必填")
    dup = db.query_one(
        "SELECT id FROM formula_template WHERE flag = 1 AND formula_name = ? AND id <> ?",
        (name, exclude_id or -1),
    )
    if dup:
        raise ValueError("方剂名称已存在")

    ftype = _text(data.get("formula_type"))
    if not ftype:
        raise ValueError("方剂类型必填")
    if ftype not in _codes("DICT-FORMULA", "FORMULA_TYPE"):
        raise ValueError("方剂类型取值不在字典范围内")

    status = _text(data.get("formula_status")) or "ENABLED"
    if status not in _STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")

    doses = _to_int(data.get("default_doses"), "常用剂数")
    if doses is not None and (doses < 1 or doses > 30):
        raise ValueError("常用剂数应在 1 到 30 之间")

    return {
        "formula_name": name,
        "formula_type": ftype,
        "formula_status": status,
        "source": _text(data.get("source")) or None,
        "function": _text(data.get("function")) or None,
        "indication": _text(data.get("indication")) or None,
        "default_doses": doses,
    }


def _validate_items(items, conn):
    """明细校验：≥1 行、药味不重复、herb_id 存在且启用未删除、常用剂量 > 0。"""
    if not isinstance(items, list) or not items:
        raise ValueError("组成明细至少一味药味")
    seen = set()
    rows = []
    for i, item in enumerate(items, start=1):
        herb_id = item.get("herb_id")
        if herb_id in (None, ""):
            raise ValueError("第 %d 行药味必选" % i)
        try:
            herb_id = int(herb_id)
        except (TypeError, ValueError):
            raise ValueError("第 %d 行药味标识无效" % i)
        if herb_id in seen:
            raise ValueError("同一方剂模板内药味不得重复")
        seen.add(herb_id)
        herb = db.query_one("SELECT id FROM herb WHERE id = ? AND flag = 1", (herb_id,), conn)
        if not herb:
            raise ValueError("第 %d 行药味不存在或已删除" % i)
        if item.get("common_dose") in (None, ""):
            raise ValueError("第 %d 行常用剂量必填" % i)
        try:
            dose = float(item["common_dose"])
        except (TypeError, ValueError):
            raise ValueError("第 %d 行常用剂量必须为数字" % i)
        if dose <= 0:
            raise ValueError("常用剂量必须大于 0")
        seq_no = item.get("seq_no")
        try:
            seq_no = int(seq_no) if seq_no not in (None, "") else i
        except (TypeError, ValueError):
            seq_no = i
        rows.append({
            "seq_no": seq_no,
            "herb_id": herb_id,
            "common_dose": dose,
            "decoction_method": _text(item.get("decoction_method")) or None,
        })
    return rows


def _write_items(conn, formula_id, item_rows, user):
    """从表全量重建（先逻辑删旧行，再插新行），全部在同一事务的 conn 内执行。"""
    db.execute("UPDATE formula_item SET flag = 0, updated_at = CURRENT_TIMESTAMP "
               "WHERE formula_template_id = ? AND flag = 1", (formula_id,), conn)
    for row in item_rows:
        db.execute(
            """
            INSERT INTO formula_item (formula_template_id, item_id, seq_no, herb_id, common_dose,
                decoction_method, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (formula_id, uuid.uuid4().hex, row["seq_no"], row["herb_id"], row["common_dose"],
             row["decoction_method"], user["id"], user["id"]),
            conn,
        )


def _item_rows(formula_id, conn=None):
    return db.query(
        """
        SELECT i.*, h.herb_code, h.herb_name
        FROM formula_item i
        LEFT JOIN herb h ON h.id = i.herb_id
        WHERE i.formula_template_id = ? AND i.flag = 1
        ORDER BY i.seq_no, i.id
        """,
        (formula_id,),
        conn,
    )


def get_formula(formula_id, conn=None):
    row = db.query_one("SELECT * FROM formula_template WHERE id = ? AND flag = 1", (formula_id,), conn)
    if not row:
        return None
    row["items"] = _item_rows(formula_id, conn)
    return row


def list_formulas(page=1, size=10, filters=None):
    filters = filters or {}
    where = "WHERE flag = 1"
    params = []
    if filters.get("formula_name"):
        where += " AND formula_name LIKE ?"
        params.append(f"%{filters['formula_name']}%")
    if filters.get("formula_code"):
        where += " AND formula_code LIKE ?"
        params.append(f"%{filters['formula_code']}%")
    if filters.get("formula_type"):
        where += " AND formula_type = ?"
        params.append(filters["formula_type"])
    if filters.get("formula_status"):
        where += " AND formula_status = ?"
        params.append(filters["formula_status"])
    total = db.query_one(f"SELECT COUNT(*) AS c FROM {TABLE} {where}", params)["c"]
    rows = db.query(
        f"""
        SELECT f.*, (SELECT COUNT(*) FROM formula_item i
                     WHERE i.formula_template_id = f.id AND i.flag = 1) AS item_count
        FROM {TABLE} f {where} ORDER BY f.id DESC LIMIT ? OFFSET ?
        """,
        params + [size, (page - 1) * size],
    )
    return {"list": rows, "total": total, "page": page, "size": size}


def create_formula(data, user):
    master = _validate_master(data)

    def _do(conn):
        item_rows = _validate_items(data.get("items"), conn)
        code = next_code("formula", TABLE, "formula_code", conn)
        fid = db.execute(
            """
            INSERT INTO formula_template (formula_code, formula_name, formula_type, source, "function",
                indication, default_doses, formula_status, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code, master["formula_name"], master["formula_type"], master["source"],
             master["function"], master["indication"], master["default_doses"],
             master["formula_status"], user["id"], user["id"]),
            conn,
        )[0]
        _write_items(conn, fid, item_rows, user)
        return fid

    return get_formula(db.transaction(_do))


def update_formula(formula_id, data, user):
    if not get_formula(formula_id):
        raise ValueError("方剂模板不存在或已删除")
    master = _validate_master(data, exclude_id=formula_id)

    def _do(conn):
        item_rows = _validate_items(data.get("items"), conn)
        db.execute(
            """
            UPDATE formula_template SET formula_name = ?, formula_type = ?, source = ?, "function" = ?,
                indication = ?, default_doses = ?, formula_status = ?, updated_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND flag = 1
            """,
            (master["formula_name"], master["formula_type"], master["source"], master["function"],
             master["indication"], master["default_doses"], master["formula_status"],
             user["id"], formula_id),
            conn,
        )
        _write_items(conn, formula_id, item_rows, user)
        return formula_id

    return get_formula(db.transaction(_do))


def change_status(formula_id, status, user):
    row = get_formula(formula_id)
    if not row:
        raise ValueError("方剂模板不存在或已删除")
    status = _text(status)
    if status not in _STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")
    if status == row["formula_status"]:
        raise ValueError("方剂模板当前已是%s状态" % ("启用" if status == "ENABLED" else "停用"))
    db.execute(
        "UPDATE formula_template SET formula_status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND flag = 1",
        (status, user["id"], formula_id),
    )
    return get_formula(formula_id)
