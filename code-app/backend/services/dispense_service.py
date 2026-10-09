"""AGG-DISPENSE-001 调剂发药记录 —— 确认调剂 / 发药确认（含库存联动）。

契约：`docs/批次2-实现契约.md` §4.4 API、§8.2 事务边界、§8.4 审核与作废链、§8.5 调剂链、§9 验收。
行为：Dispense_CreatePending / Dispense_CancelPending（系统行为，被审核通过链与作废链调用）、
      Dispense_Confirm（+ 联动 Herb_DeductStock）、Dispense_Issue、Herb_ReturnStock（作废回冲）。
规则：R-02 库存充足（调剂前置）、R-06/INV-03 库存与流水净和一致、REF-08 库存非负、REF-14 发药时间不早于调剂时间。
说明：状态码取 M1 字典 `DICT-DISPENSE.DISPENSE_STATUS` 的 code（PENDING/DISPENSED/ISSUED/CANCELLED）；
      处方状态取 `DICT-PRESCRIPTION.PRESCRIPTION_STATUS` 的 code（APPROVED/DISPENSING/ISSUED）。
      `dispenser_id` 为 M1 必填：创建待调剂记录时写创建者（审核药师），确认调剂时覆盖为实际调剂人。
      所有库存动作与调剂记录状态在同一事务（同一 conn）内完成，不「先提交再异步补写」。
"""
import datetime

import db
from ontology.registry import get_dictionary_items
from services import domain_rules
from utils.codegen import next_code

TABLE = "dispense_record"
FLOW_TABLE = "herb_stock_flow"

# 调剂发药记录状态（M1 DICT-DISPENSE.DISPENSE_STATUS）
PENDING = "PENDING"
DISPENSED = "DISPENSED"
ISSUED = "ISSUED"
CANCELLED = "CANCELLED"

# 处方状态（M1 DICT-PRESCRIPTION.PRESCRIPTION_STATUS）
P_APPROVED = "APPROVED"
P_DISPENSING = "DISPENSING"
P_ISSUED = "ISSUED"

# 饮片流水业务类型（M1 DICT-STOCK-FLOW.FLOW_BIZ_TYPE）
BIZ_DISPENSE_OUT = "DISPENSE_OUT"
BIZ_VOID_ROLLBACK = "VOID_ROLLBACK"


# ---------------------------------------------------------------- 工具


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _norm_datetime(value, label, default=None):
    text = _text(value)
    if not text:
        return default if default is not None else _now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("%s格式不正确（应为 YYYY-MM-DD HH:MM:SS）" % label)


def _label(dict_id, type_code, code):
    for item in get_dictionary_items(dict_id, type_code):
        if item["code"] == code:
            return item["label"]
    return None


def _user_id(user):
    return str((user or {}).get("id") or "")


# ---------------------------------------------------------------- 读取


def get_record(record_id, conn=None):
    return db.query_one(
        "SELECT * FROM dispense_record WHERE id = ? AND flag = 1", (record_id,), conn
    )


def get_by_prescription(prescription_id, conn=None):
    """一张处方至多一条调剂发药记录（`ux_dispense_prescription`）。"""
    return db.query_one(
        "SELECT * FROM dispense_record WHERE prescription_id = ? AND flag = 1",
        (prescription_id,),
        conn,
    )


def _prescription(prescription_id, conn=None):
    return db.query_one(
        "SELECT * FROM prescription WHERE id = ? AND flag = 1", (prescription_id,), conn
    )


def _items(prescription_id, conn=None):
    return db.query(
        "SELECT * FROM prescription_item WHERE prescription_id = ? AND flag = 1 ORDER BY seq_no, id",
        (prescription_id,),
        conn,
    )


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
    rows = db.query(
        "SELECT * FROM herb WHERE id IN (%s) AND flag = 1" % placeholders, ids, conn
    )
    return {r["id"]: r for r in rows}


def _decorate(row, conn=None):
    if not row:
        return None
    row = dict(row)
    row["record_status_label"] = _label("DICT-DISPENSE", "DISPENSE_STATUS", row["record_status"])
    p = _prescription(row["prescription_id"], conn)
    if p:
        row["prescription_no"] = p["prescription_no"]
        row["prescription_status"] = p["prescription_status"]
        row["doses"] = p["doses"]
        row["patient_id"] = p["patient_id"]
        row["visit_id"] = p["visit_id"]
        patient = db.query_one("SELECT patient_name FROM patient WHERE id = ?", (p["patient_id"],), conn)
        row["patient_name"] = patient["patient_name"] if patient else None
    return row


def get_dispense(record_id, conn=None):
    """调剂发药详情 + 处方明细（UI-08 grdStockCheck）+ 逐味库存校验（R-02）。"""
    row = _decorate(get_record(record_id, conn), conn)
    if not row:
        return None
    row["items"] = stock_check(record_id, conn)
    row["stock_enough"] = all(i["enough"] for i in row["items"])
    return row


def stock_check(record_id, conn=None):
    """R-02 逐味库存校验：`[{herb_id, herb_name, required_quantity, stock_quantity, enough}]`。"""
    record = get_record(record_id, conn)
    if not record:
        raise ValueError("调剂发药记录不存在或已删除")
    return stock_check_by_prescription(record["prescription_id"], conn)


def stock_check_by_prescription(prescription_id, conn=None):
    p = _prescription(prescription_id, conn)
    if not p:
        raise ValueError("处方不存在或已删除")
    items = _items(prescription_id, conn)
    herb_map = _herb_map([i["herb_id"] for i in items], conn)
    return domain_rules.check_stock_sufficient(items, p["doses"], herb_map)


def list_pending_dispense(page=1, size=10, filters=None):
    """待调剂列表（UI-08 载入）：处方 `APPROVED` 且无调剂记录或记录为 `PENDING`。"""
    filters = filters or {}
    where = ("WHERE p.flag = 1 AND p.prescription_status = ? AND (d.id IS NULL OR d.record_status = ?)")
    params = [P_APPROVED, PENDING]
    if filters.get("prescription_no"):
        where += " AND p.prescription_no LIKE ?"
        params.append("%%%s%%" % filters["prescription_no"])
    if filters.get("patient_name"):
        where += " AND pa.patient_name LIKE ?"
        params.append("%%%s%%" % filters["patient_name"])
    base = """
        FROM prescription p
        LEFT JOIN dispense_record d ON d.prescription_id = p.id AND d.flag = 1
        LEFT JOIN patient pa ON pa.id = p.patient_id
        LEFT JOIN visit v ON v.id = p.visit_id
        %s
    """ % where
    total = db.query_one("SELECT COUNT(*) AS c " + base, params)["c"]
    rows = db.query(
        """
        SELECT p.id AS prescription_id, p.prescription_no, p.doses, p.usage_method, p.visit_id,
               p.patient_id, p.prescription_status, p.submit_time, p.review_time,
               pa.patient_name, v.visit_no,
               d.id AS dispense_id, d.dispense_no, d.record_status, d.dispense_time
        """ + base + " ORDER BY p.submit_time DESC, p.id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    for r in rows:
        r["record_status_label"] = _label("DICT-DISPENSE", "DISPENSE_STATUS", r["record_status"])
        r["prescription_status_label"] = _label(
            "DICT-PRESCRIPTION", "PRESCRIPTION_STATUS", r["prescription_status"])
    return {"list": rows, "total": total, "page": page, "size": size}


# ---------------------------------------------------------------- 系统行为：创建 / 取消待调剂记录


def create_pending(conn, prescription, user=None):
    """Dispense_CreatePending（B-05）：审核通过后生成待调剂记录（幂等）。

    契约 §8.4：`dispense_no = FY+6`、`record_status=PENDING`、`dispense_time` 先置为创建时间、
    `dispenser_id` 创建时写入当前审核用户 id（M1 必填，占位空串不允许），调剂确认时覆盖为实际调剂人。
    """
    existing = get_by_prescription(prescription["id"], conn)
    if existing:
        return existing
    if prescription["prescription_status"] != P_APPROVED:
        raise ValueError("处方状态不是「审核通过」，不可创建待调剂记录")
    now = _now()
    operator = _user_id(user) or None
    dispense_no = next_code("dispense_record", TABLE, "dispense_no", conn)
    new_id = db.execute(
        """
        INSERT INTO dispense_record (dispense_no, prescription_id, dispenser_id, checker_id,
            dispense_time, issue_time, record_status, remark, created_by, updated_by)
        VALUES (?, ?, ?, NULL, ?, NULL, ?, NULL, ?, ?)
        """,
        (dispense_no, prescription["id"], operator, now, PENDING,
         (user or {}).get("id"), (user or {}).get("id")),
        conn,
    )[0]
    return get_record(new_id, conn)


def cancel_pending(conn, prescription_id, user=None, remark=None):
    """Dispense_CancelPending（B-06）：取消该处方的调剂记录（已调剂 / 待调剂可取消，已发药不可）。"""
    record = get_by_prescription(prescription_id, conn)
    if not record:
        return None
    if record["record_status"] == ISSUED:
        raise ValueError("处方已发药，不可取消调剂发药记录")
    if record["record_status"] == CANCELLED:
        return record
    db.execute(
        "UPDATE dispense_record SET record_status = ?, remark = COALESCE(?, remark), "
        "updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
        (CANCELLED, remark, (user or {}).get("id"), record["id"]),
        conn,
    )
    return get_record(record["id"], conn)


# ---------------------------------------------------------------- 库存联动：扣减 / 回冲


def _add_flow(conn, herb_id, biz_type, quantity, biz_date, user, prescription_id, remark=None):
    """写饮片出入库流水（`herb_stock_flow`）；编号 `LS+6`，在业务事务内生成。"""
    flow_no = next_code("herb_stock_flow", FLOW_TABLE, "flow_no", conn)
    return db.execute(
        """
        INSERT INTO herb_stock_flow (herb_id, flow_no, biz_type, quantity, biz_date, operator_id,
            prescription_id, inbound_no, remark, created_by, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (herb_id, flow_no, biz_type, round(quantity, 3), biz_date, _user_id(user),
         prescription_id, remark, (user or {}).get("id"), (user or {}).get("id")),
        conn,
    )[0]


def _apply_stock(conn, herb_id, delta, user):
    db.execute(
        "UPDATE herb SET stock_quantity = ROUND(stock_quantity + ?, 3), updated_by = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (round(delta, 3), (user or {}).get("id"), herb_id),
        conn,
    )


def deduct_stock(conn, prescription, items, user):
    """Herb_DeductStock（B-01）：逐味 `stock_quantity -= singleDose × doses`，
    写 `biz_type=DISPENSE_OUT` 负数量流水（`prescription_id` 必填）；扣减后库存不得为负（REF-08），
    并断言 INV-03（库存 == 流水净和）。
    """
    doses = float(prescription["doses"] or 0)
    now = _now()
    detail = []
    for item in items:
        required = round(float(item["single_dose"] or 0) * doses, 3)
        herb = db.query_one("SELECT * FROM herb WHERE id = ? AND flag = 1", (item["herb_id"],), conn)
        if not herb:
            raise ValueError("饮片不存在或已删除")
        stock = round(float(herb["stock_quantity"] or 0), 3)
        if round(stock - required, 3) < 0:
            raise ValueError("%s 需求 %sg 超过库存 %sg，无法调剂"
                             % (herb["herb_name"], domain_rules.num(required), domain_rules.num(stock)))
        _add_flow(conn, item["herb_id"], BIZ_DISPENSE_OUT, -required, now, user,
                  prescription["id"], remark="处方 %s 调剂出库" % prescription["prescription_no"])
        _apply_stock(conn, item["herb_id"], -required, user)
        domain_rules.assert_inv03(conn, item["herb_id"])
        detail.append({
            "herb_id": item["herb_id"], "herb_name": herb["herb_name"],
            "quantity": domain_rules.num(required),
            "stock_quantity": domain_rules.num(round(stock - required, 3)),
        })
    return detail


def return_stock(conn, prescription, user):
    """Herb_ReturnStock（B-02）：按原调剂出库流水逐味回冲（`biz_type=VOID_ROLLBACK` 正数量 +
    `stock_quantity +=` 原出库量），并断言 INV-03。已回冲过的处方不重复回冲。
    """
    flows = db.query(
        "SELECT * FROM herb_stock_flow WHERE prescription_id = ? AND biz_type = ? AND flag = 1",
        (prescription["id"], BIZ_DISPENSE_OUT),
        conn,
    )
    if not flows:
        raise ValueError("未找到该处方的调剂出库流水，无法回冲库存")
    rolled = db.query_one(
        "SELECT COUNT(*) AS c FROM herb_stock_flow WHERE prescription_id = ? AND biz_type = ? AND flag = 1",
        (prescription["id"], BIZ_VOID_ROLLBACK),
        conn,
    )["c"]
    if rolled:
        raise ValueError("该处方库存已回冲，不可重复回冲")

    now = _now()
    totals = {}
    for flow in flows:
        totals[flow["herb_id"]] = round(totals.get(flow["herb_id"], 0.0) - float(flow["quantity"] or 0), 3)

    total_quantity = 0.0
    detail = []
    for herb_id, quantity in totals.items():
        if quantity <= 0:
            continue
        herb = db.query_one("SELECT * FROM herb WHERE id = ? AND flag = 1", (herb_id,), conn)
        if not herb:
            raise ValueError("饮片不存在或已删除")
        _add_flow(conn, herb_id, BIZ_VOID_ROLLBACK, quantity, now, user, prescription["id"],
                  remark="处方 %s 作废回冲" % prescription["prescription_no"])
        _apply_stock(conn, herb_id, quantity, user)
        domain_rules.assert_inv03(conn, herb_id)
        total_quantity = round(total_quantity + quantity, 3)
        detail.append({"herb_id": herb_id, "herb_name": herb["herb_name"],
                       "quantity": domain_rules.num(quantity)})
    return {"total_quantity": domain_rules.num(total_quantity), "items": detail}


# ---------------------------------------------------------------- 行为：确认调剂 / 发药确认


def confirm_dispense(record_id, data, user):
    """Dispense_Confirm：`PENDING` + 处方 `APPROVED` + R-02 全部充足 → `DISPENSED` + 处方 `DISPENSING`，
    联动 Herb_DeductStock（同一事务）。
    """
    data = data or {}

    def _do(conn):
        record = get_record(record_id, conn)
        if not record:
            raise ValueError("调剂发药记录不存在或已删除")
        if record["record_status"] != PENDING:
            raise ValueError("调剂发药记录当前状态不可确认调剂")
        prescription = _prescription(record["prescription_id"], conn)
        if not prescription:
            raise ValueError("处方不存在或已删除")
        if prescription["prescription_status"] != P_APPROVED:
            raise ValueError("处方状态不是「审核通过」，不可确认调剂")

        items = _items(prescription["id"], conn)
        if not items:
            raise ValueError("处方明细不得为空（INV-04）")
        herb_map = _herb_map([i["herb_id"] for i in items], conn)
        domain_rules.assert_stock_sufficient(
            domain_rules.check_stock_sufficient(items, prescription["doses"], herb_map))  # R-02

        dispense_time = _norm_datetime(data.get("dispense_time"), "调剂时间", _now())
        db.execute(
            "UPDATE dispense_record SET record_status = ?, dispense_time = ?, dispenser_id = ?, "
            "checker_id = ?, remark = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND flag = 1",
            (DISPENSED, dispense_time, _user_id(user), _text(data.get("checker_id")) or None,
             _text(data.get("remark")) or None, (user or {}).get("id"), record_id),
            conn,
        )
        db.execute(
            "UPDATE prescription SET prescription_status = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (P_DISPENSING, (user or {}).get("id"), prescription["id"]),
            conn,
        )
        deducted = deduct_stock(conn, prescription, items, user)  # Herb_DeductStock（联动）
        return record_id, dispense_time, deducted

    record_id, dispense_time, deducted = db.transaction(_do)
    row = get_dispense(record_id)
    row["stock_flows"] = deducted
    return row


def issue_dispense(record_id, data, user):
    """Dispense_Issue：记录 `DISPENSED` → `ISSUED` + 处方 `ISSUED`（REF-14 发药时间不早于调剂时间）。"""
    data = data or {}

    def _do(conn):
        record = get_record(record_id, conn)
        if not record:
            raise ValueError("调剂发药记录不存在或已删除")
        if record["record_status"] != DISPENSED:
            raise ValueError("调剂发药记录当前状态不可发药确认")
        prescription = _prescription(record["prescription_id"], conn)
        if not prescription:
            raise ValueError("处方不存在或已删除")
        if prescription["prescription_status"] != P_DISPENSING:
            raise ValueError("处方状态不是「已调剂」，不可发药确认")
        issue_time = _norm_datetime(data.get("issue_time"), "发药时间", _now())
        if record["dispense_time"] and issue_time < str(record["dispense_time"]):
            raise ValueError("发药时间不得早于调剂时间（REF-14）")  # REF-14
        db.execute(
            "UPDATE dispense_record SET record_status = ?, issue_time = ?, remark = COALESCE(?, remark), "
            "updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (ISSUED, issue_time, _text(data.get("remark")) or None, (user or {}).get("id"), record_id),
            conn,
        )
        db.execute(
            "UPDATE prescription SET prescription_status = ?, updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND flag = 1",
            (P_ISSUED, (user or {}).get("id"), prescription["id"]),
            conn,
        )
        return record_id

    return get_dispense(db.transaction(_do))
