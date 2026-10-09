"""AGG-HERB-001 中药饮片（+ HerbStockFlow 出入库流水）。

行为：Herb_Save / Herb_Inbound / Herb_ChangeStatus / Herb_Stocktake / Herb_QueryStockAndAlert。
契约：§2.3 主从单事务、§3 AGG-HERB-001、§4.4 API、§8 规则落地。
规则：REF-07 常用量区间（max ≥ min）、REF-06 最小量 > 0、REF-08 库存非负、
      REF-13 数量不得为 0、INV-03 库存与流水净和一致、R-06 RULE-HERB-STOCK-RECONCILE。
说明：字典字段存 code；biz_type 存 DICT-STOCK-FLOW.FLOW_BIZ_TYPE 的 code（入库 INBOUND、
      盘点调整 STOCKTAKE_ADJUST），对外同时给出 label。Herb_DeductStock / Herb_ReturnStock 属批次 2。
"""
import datetime

import db
from ontology.registry import get_dictionary_items
from utils.codegen import next_code
from utils.rules import evaluate

TABLE = "herb"
FLOW_TABLE = "herb_stock_flow"
STATUS_CODES = ("ENABLED", "DISABLED")
BIZ_INBOUND = "INBOUND"
BIZ_STOCKTAKE = "STOCKTAKE_ADJUST"
RECONCILE_RULE_ID = "RULE-HERB-STOCK-RECONCILE"


def _codes(dict_id, type_code):
    return {i["code"] for i in get_dictionary_items(dict_id, type_code)}


def _biz_labels():
    return {i["code"]: i["label"] for i in get_dictionary_items("DICT-STOCK-FLOW", "FLOW_BIZ_TYPE")}


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value)


def _to_decimal(value, label, required=True):
    if value in (None, ""):
        if required:
            raise ValueError("%s必填" % label)
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("%s必须为数字" % label)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_date(value):
    if value in (None, ""):
        return _now()
    return _text(value)


# ------------------------------------------------------------------ 建档维护

def _validate(data, exclude_id=None):
    name = _text(data.get("herb_name"))
    if not name:
        raise ValueError("饮片名称必填")
    dup = db.query_one(
        "SELECT id FROM herb WHERE flag = 1 AND herb_name = ? AND id <> ?", (name, exclude_id or -1)
    )
    if dup:
        raise ValueError("饮片名称已存在")

    min_dose = _to_decimal(data.get("min_common_dose"), "常用最小量")
    if min_dose <= 0:
        raise ValueError("常用最小量必须大于 0")
    max_dose = _to_decimal(data.get("max_common_dose"), "常用最大量")
    if max_dose < min_dose:
        raise ValueError("常用最大量不得小于常用最小量")  # REF-07

    toxicity = _text(data.get("toxicity_level")) or "NONE"
    if toxicity not in _codes("DICT-HERB", "TOXICITY_LEVEL"):
        raise ValueError("毒性分级取值不在字典范围内")

    category = _text(data.get("herb_category")) or None
    if category and category not in _codes("DICT-HERB", "HERB_CATEGORY"):
        raise ValueError("药材类别取值不在字典范围内")

    threshold = _to_decimal(data.get("low_stock_threshold"), "低库存预警值", required=False)
    if threshold is not None and threshold < 0:
        raise ValueError("低库存预警值不得为负数")  # REF-09

    # 毒性单张处方总量上限（M1 Herb.toxicDoseLimit，供 M3 规则 R-03 判定）
    toxic_limit = _to_decimal(data.get("toxic_dose_limit"), "毒性单张处方总量上限", required=False)
    if toxic_limit is not None and toxic_limit <= 0:
        raise ValueError("毒性单张处方总量上限必须大于 0")
    if toxicity == "NONE":
        toxic_limit = None  # 无毒饮片不设毒性上限（R-03 仅对毒性分级非「无毒」判定）

    status = _text(data.get("herb_status")) or "ENABLED"
    if status not in STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")

    return {
        "herb_name": name,
        "alias_name": _text(data.get("alias_name")) or None,
        "herb_category": category,
        "nature_meridian": _text(data.get("nature_meridian")) or None,
        "efficacy": _text(data.get("efficacy")) or None,
        "min_common_dose": min_dose,
        "max_common_dose": max_dose,
        "toxicity_level": toxicity,
        "toxic_dose_limit": toxic_limit,
        "special_managed": 1 if data.get("special_managed") in (1, True, "1", "true", "True") else 0,
        "low_stock_threshold": threshold,
        "origin": _text(data.get("origin")) or None,
        "spec": _text(data.get("spec")) or None,
        "herb_status": status,
    }


def get_herb(herb_id, conn=None, flow_limit=20):
    row = db.query_one("SELECT * FROM herb WHERE id = ? AND flag = 1", (herb_id,), conn)
    if not row:
        return None
    row["stock_flows"] = list_flows(herb_id, flow_limit, conn)
    return row


def list_flows(herb_id, limit=20, conn=None):
    rows = db.query(
        "SELECT * FROM herb_stock_flow WHERE herb_id = ? AND flag = 1 "
        "ORDER BY biz_date DESC, id DESC LIMIT ?",
        (herb_id, limit),
        conn,
    )
    labels = _biz_labels()
    for r in rows:
        r["biz_type_label"] = labels.get(r["biz_type"])
        r["operator_name"] = r["operator_id"]
    return rows


def list_herbs(page=1, size=10, filters=None):
    filters = filters or {}
    where = "WHERE flag = 1"
    params = []
    if filters.get("herb_name"):
        where += " AND (herb_name LIKE ? OR alias_name LIKE ?)"
        params += [f"%{filters['herb_name']}%", f"%{filters['herb_name']}%"]
    if filters.get("herb_code"):
        where += " AND herb_code LIKE ?"
        params.append(f"%{filters['herb_code']}%")
    if filters.get("herb_category"):
        where += " AND herb_category = ?"
        params.append(filters["herb_category"])
    if filters.get("herb_status"):
        where += " AND herb_status = ?"
        params.append(filters["herb_status"])
    total = db.query_one(f"SELECT COUNT(*) AS c FROM {TABLE} {where}", params)["c"]
    rows = db.query(
        f"SELECT * FROM {TABLE} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    return {"list": rows, "total": total, "page": page, "size": size}


def create_herb(data, user):
    f = _validate(data)

    def _do(conn):
        code = next_code("herb", TABLE, "herb_code", conn)
        return db.execute(
            """
            INSERT INTO herb (herb_code, herb_name, alias_name, herb_category, nature_meridian, efficacy,
                min_common_dose, max_common_dose, toxicity_level, toxic_dose_limit, special_managed, stock_quantity,
                low_stock_threshold, origin, spec, herb_status, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (code, f["herb_name"], f["alias_name"], f["herb_category"], f["nature_meridian"],
             f["efficacy"], f["min_common_dose"], f["max_common_dose"], f["toxicity_level"],
             f["toxic_dose_limit"], f["special_managed"], f["low_stock_threshold"], f["origin"], f["spec"],
             f["herb_status"], user["id"], user["id"]),
            conn,
        )[0]

    return get_herb(db.transaction(_do))


def update_herb(herb_id, data, user):
    if not get_herb(herb_id):
        raise ValueError("饮片不存在或已删除")
    f = _validate(data, exclude_id=herb_id)
    # stock_quantity 不由建档/修改写入，仅由入库/盘点流水驱动
    db.execute(
        """
        UPDATE herb SET herb_name = ?, alias_name = ?, herb_category = ?, nature_meridian = ?,
            efficacy = ?, min_common_dose = ?, max_common_dose = ?, toxicity_level = ?, toxic_dose_limit = ?,
            special_managed = ?, low_stock_threshold = ?, origin = ?, spec = ?, herb_status = ?,
            updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND flag = 1
        """,
        (f["herb_name"], f["alias_name"], f["herb_category"], f["nature_meridian"], f["efficacy"],
         f["min_common_dose"], f["max_common_dose"], f["toxicity_level"], f["toxic_dose_limit"],
         f["special_managed"], f["low_stock_threshold"], f["origin"], f["spec"], f["herb_status"],
         user["id"], herb_id),
    )
    return get_herb(herb_id)


def change_status(herb_id, status, user):
    row = get_herb(herb_id)
    if not row:
        raise ValueError("饮片不存在或已删除")
    status = _text(status)
    if status not in STATUS_CODES:
        raise ValueError("状态取值不在字典范围内")
    if status == row["herb_status"]:
        raise ValueError("饮片当前已是%s状态" % ("启用" if status == "ENABLED" else "停用"))
    db.execute(
        "UPDATE herb SET herb_status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND flag = 1",
        (status, user["id"], herb_id),
    )
    return get_herb(herb_id)


def options(keyword=""):
    where = "WHERE flag = 1 AND herb_status = 'ENABLED'"
    params = []
    if keyword:
        where += " AND (herb_name LIKE ? OR herb_code LIKE ? OR alias_name LIKE ?)"
        params += [f"%{keyword}%"] * 3
    return db.query(
        f"SELECT id, herb_code, herb_name FROM herb {where} ORDER BY herb_code LIMIT 200", params
    )


# ------------------------------------------------------------------ 库存：入库 / 盘点 / 对账

def flow_net_quantity(herb_id, conn=None):
    row = db.query_one(
        "SELECT COALESCE(SUM(quantity), 0) AS net FROM herb_stock_flow WHERE herb_id = ? AND flag = 1",
        (herb_id,),
        conn,
    )
    return float(row["net"] or 0)


def reconcile_difference(herb_id, conn=None):
    """R-06 / INV-03 对账差异 = stock_quantity − SUM(flow.quantity)（M3 规则表达式求值）。"""
    herb = db.query_one("SELECT stock_quantity FROM herb WHERE id = ? AND flag = 1", (herb_id,), conn)
    if not herb:
        raise ValueError("饮片不存在或已删除")
    net = flow_net_quantity(herb_id, conn)
    stock = float(herb["stock_quantity"] or 0)
    from ontology.registry import registry
    rule = registry["rules"].get(RECONCILE_RULE_ID)
    if rule and rule.get("expression"):
        diff = float(evaluate(rule["expression"], {"stockQuantity": stock, "flowNetQuantity": net}))
    else:
        diff = stock - net
    return round(diff, 3)


def reconcile(herb_id):
    """btnReconcile：返回库存、流水净和与差异（不阻断业务）。"""
    herb = db.query_one("SELECT id, herb_code, herb_name, stock_quantity FROM herb WHERE id = ? AND flag = 1",
                        (herb_id,))
    if not herb:
        raise ValueError("饮片不存在或已删除")
    net = flow_net_quantity(herb_id)
    diff = reconcile_difference(herb_id)
    return {
        "herb_id": herb_id,
        "herb_code": herb["herb_code"],
        "herb_name": herb["herb_name"],
        "stock_quantity": float(herb["stock_quantity"] or 0),
        "flow_net_quantity": net,
        "difference": diff,
        "consistent": abs(diff) < 1e-6,
    }


def _add_flow(conn, herb_id, biz_type, quantity, biz_date, user, inbound_no=None,
              prescription_id=None, remark=None):
    flow_no = next_code("herb_stock_flow", FLOW_TABLE, "flow_no", conn)
    db.execute(
        """
        INSERT INTO herb_stock_flow (herb_id, flow_no, biz_type, quantity, biz_date, operator_id,
            prescription_id, inbound_no, remark, created_by, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (herb_id, flow_no, biz_type, quantity, biz_date, str(user["id"]), prescription_id,
         inbound_no, remark, user["id"], user["id"]),
        conn,
    )
    return flow_no


def _assert_inv03(conn, herb_id):
    """INV-03：库存数量必须等于该饮片全部出入库记录的数量净和。"""
    herb = db.query_one("SELECT stock_quantity FROM herb WHERE id = ?", (herb_id,), conn)
    net = flow_net_quantity(herb_id, conn)
    stock = round(float(herb["stock_quantity"] or 0), 3)
    if abs(stock - round(net, 3)) > 1e-6:
        raise ValueError("库存数量必须等于该饮片全部出入库记录的数量净和（差异 %.3f g）" % (stock - net))


def inbound(herb_id, data, user):
    """Herb_Inbound：同一事务内追加「入库」流水 + 增加库存。"""
    herb = db.query_one("SELECT * FROM herb WHERE id = ? AND flag = 1", (herb_id,))
    if not herb:
        raise ValueError("饮片不存在或已删除")
    if herb["herb_status"] != "ENABLED":
        raise ValueError("饮片已停用，不可登记入库")
    quantity = _to_decimal(data.get("quantity"), "入库数量")
    if quantity <= 0:
        raise ValueError("入库数量必须大于 0")
    inbound_no = _text(data.get("inbound_no"))
    if not inbound_no:
        raise ValueError("入库单号必填")
    biz_date = _norm_date(data.get("biz_date"))
    remark = _text(data.get("remark")) or None

    def _do(conn):
        _add_flow(conn, herb_id, BIZ_INBOUND, round(quantity, 3), biz_date, user,
                  inbound_no=inbound_no, remark=remark)
        db.execute(
            "UPDATE herb SET stock_quantity = ROUND(stock_quantity + ?, 3), updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (round(quantity, 3), user["id"], herb_id),
            conn,
        )
        _assert_inv03(conn, herb_id)
        return herb_id

    db.transaction(_do)
    return get_herb(herb_id)


def stocktake(herb_id, data, user):
    """Herb_Stocktake：差异 = 实盘 − 账面；生成「盘点调整」流水并把库存置为实盘数。"""
    herb = db.query_one("SELECT * FROM herb WHERE id = ? AND flag = 1", (herb_id,))
    if not herb:
        raise ValueError("饮片不存在或已删除")
    actual = _to_decimal(data.get("actual_quantity"), "实盘数量")
    if actual < 0:
        raise ValueError("实盘数量不得为负数")  # REF-08
    remark = _text(data.get("remark"))
    if not remark:
        raise ValueError("盘点调整原因必填")
    biz_date = _norm_date(data.get("biz_date"))
    book = round(float(herb["stock_quantity"] or 0), 3)
    actual = round(actual, 3)
    difference = round(actual - book, 3)
    if abs(difference) < 1e-6:
        raise ValueError("账实相符，无需调整")  # REF-13：调整数量不得为 0

    def _do(conn):
        reconcile_difference(herb_id, conn)  # R-06 对账（账实一致时差异为 0）
        _add_flow(conn, herb_id, BIZ_STOCKTAKE, difference, biz_date, user, remark=remark)
        db.execute(
            "UPDATE herb SET stock_quantity = ROUND(?, 3), updated_by = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (actual, user["id"], herb_id),
            conn,
        )
        _assert_inv03(conn, herb_id)
        return herb_id

    db.transaction(_do)
    result = get_herb(herb_id)
    result["stocktake"] = {"book_quantity": book, "actual_quantity": actual, "adjust_quantity": difference}
    return result


# ------------------------------------------------------------------ 库存查询与预警（QR-HERB-STOCK-001）

def _stock_where(filters):
    where = "WHERE h.flag = 1"
    params = []
    if filters.get("herb_name"):
        where += " AND (h.herb_name LIKE ? OR h.alias_name LIKE ?)"
        params += [f"%{filters['herb_name']}%", f"%{filters['herb_name']}%"]
    if filters.get("herb_code"):
        where += " AND h.herb_code LIKE ?"
        params.append(f"%{filters['herb_code']}%")
    if filters.get("herb_category"):
        where += " AND h.herb_category = ?"
        params.append(filters["herb_category"])
    if filters.get("toxicity_level"):
        where += " AND h.toxicity_level = ?"
        params.append(filters["toxicity_level"])
    if filters.get("herb_status"):
        where += " AND h.herb_status = ?"
        params.append(filters["herb_status"])
    if filters.get("stock_from") not in (None, ""):
        where += " AND h.stock_quantity >= ?"
        params.append(float(filters["stock_from"]))
    if filters.get("stock_to") not in (None, ""):
        where += " AND h.stock_quantity <= ?"
        params.append(float(filters["stock_to"]))
    alert = str(filters.get("alert_only") or "").lower() in ("1", "true", "yes")
    if alert:
        where += " AND h.low_stock_threshold IS NOT NULL AND h.stock_quantity < h.low_stock_threshold"
    return where, params


_STOCK_SELECT = """
SELECT h.*,
       (SELECT MAX(f.biz_date) FROM herb_stock_flow f
         WHERE f.herb_id = h.id AND f.flag = 1 AND f.quantity > 0) AS latest_inbound_date,
       (SELECT MAX(f.biz_date) FROM herb_stock_flow f
         WHERE f.herb_id = h.id AND f.flag = 1 AND f.quantity < 0) AS latest_outbound_date
FROM herb h
"""

_STOCK_ORDER = """
ORDER BY CASE WHEN (h.low_stock_threshold IS NOT NULL AND h.stock_quantity < h.low_stock_threshold)
              THEN 0 ELSE 1 END, h.stock_quantity, h.herb_code
"""


def _decorate_stock(rows):
    for r in rows:
        threshold = r.get("low_stock_threshold")
        alert = threshold is not None and float(r["stock_quantity"] or 0) < float(threshold)
        r["alert_flag"] = alert
        r["alert_status"] = "预警" if alert else "正常"
        r["alert_gap"] = round(float(threshold) - float(r["stock_quantity"] or 0), 3) if alert else None
    return rows


def stock_rows(filters=None):
    where, params = _stock_where(filters or {})
    return _decorate_stock(db.query(f"{_STOCK_SELECT} {where} {_STOCK_ORDER}", params))


def list_stock(page=1, size=20, filters=None):
    where, params = _stock_where(filters or {})
    total = db.query_one(f"SELECT COUNT(*) AS c FROM herb h {where}", params)["c"]
    rows = db.query(
        f"{_STOCK_SELECT} {where} {_STOCK_ORDER} LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size],
    )
    return {"list": _decorate_stock(rows), "total": total, "page": page, "size": size}
