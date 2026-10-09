"""M3 规则 R-01～R-06 的落地判定（services 层，供处方 / 调剂 / 随访服务调用）。

契约：`docs/批次2-实现契约.md` §8.1（逐条判定与中文提示，文案逐字使用）；
      字段表 REF-08 / REF-14 / INV-03 / INV-04；批次 1 §8 的 R-06 复用文案。
模型：`models/m3-rule-model.yaml` —— RULE-PRESCRIPTION-DOSE-LIMIT-CHECK(R-01)、
      RULE-HERB-STOCK-SUFFICIENT(R-02)、RULE-HERB-TOXIC-TOTAL-LIMIT-CHECK(R-03)、
      RULE-PRESCRIPTION-VOID-DISPATCH(R-04)、RULE-FOLLOWUP-DATE-ORDER(R-05)、
      RULE-HERB-STOCK-RECONCILE(R-06)。

落地说明：M3 规则表达式是伪代码（IF/THEN/RETURN、FOR EACH …），不能直接交 simpleeval 求值
（R-06 的纯算术表达式除外）。本模块把每条表达式逐行等价翻译为 Python 判定函数，判定结论取值
（PASS / NEED_REASON / BLOCK / VOID_ONLY / VOID_WITH_ROLLBACK）与规则输出类型一致，并在结果里
回带 `rule_ref` 便于追溯。**规则要么给出判定结论，要么抛中文业务异常，绝不静默放行。**
"""
import datetime

import db
from utils.rules import evaluate

# ---------------------------------------------------------------- 规则 id（M3）

RULE_DOSE_LIMIT = "RULE-PRESCRIPTION-DOSE-LIMIT-CHECK"          # R-01
RULE_STOCK_SUFFICIENT = "RULE-HERB-STOCK-SUFFICIENT"            # R-02
RULE_TOXIC_TOTAL = "RULE-HERB-TOXIC-TOTAL-LIMIT-CHECK"          # R-03
RULE_VOID_DISPATCH = "RULE-PRESCRIPTION-VOID-DISPATCH"          # R-04
RULE_FOLLOWUP_DATE_ORDER = "RULE-FOLLOWUP-DATE-ORDER"           # R-05
RULE_STOCK_RECONCILE = "RULE-HERB-STOCK-RECONCILE"              # R-06

# R-01 三态（M3 outputType=String）
PASS = "PASS"
NEED_REASON = "NEED_REASON"
BLOCK = "BLOCK"

# R-04 三分派（M3 outputType=String）
VOID_ONLY = "VOID_ONLY"
VOID_WITH_ROLLBACK = "VOID_WITH_ROLLBACK"
VOID_BLOCK = "BLOCK"

# 调剂发药记录状态（M1 DICT-DISPENSE.DISPENSE_STATUS）
REC_PENDING = "PENDING"
REC_DISPENSED = "DISPENSED"
REC_ISSUED = "ISSUED"

MSG_VOID_BLOCK = "处方已发药，不可作废"
MSG_FOLLOWUP_ORDER = "实际随访日期不得早于上次就诊挂号日期"

_EPS = 1e-6


# ---------------------------------------------------------------- 工具

def num(value):
    """数值展示：整数去掉小数尾零（40.0 → 40），否则保留 3 位。"""
    if value is None:
        return None
    f = float(value)
    if abs(f - round(f)) < _EPS:
        return int(round(f))
    return round(f, 3)


def _flt(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_date(value):
    """把 DATE / DATETIME 文本（或 date/datetime）归一为 datetime.date。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("日期格式不正确（应为 YYYY-MM-DD）：%s" % value)


def _herb_name(herb):
    return (herb or {}).get("herb_name") or ("饮片#%s" % (herb or {}).get("id"))


# ---------------------------------------------------------------- R-01 剂量超量


def check_prescription_items(items, herb_map):
    """R-01 `RULE-PRESCRIPTION-DOSE-LIMIT-CHECK` 逐味判定（三态）。

    M3 表达式：singleDose <= maxCommonDose → PASS；singleDose > maxCommonDose*2 → BLOCK；
    否则（超上限但在 2 倍以内）→ NEED_REASON（必须填 overDoseReason）。
    返回逐味判定结果列表（契约 §4.3 的 `dose_check[]`）。
    """
    results = []
    for idx, item in enumerate(items or [], start=1):
        herb = herb_map.get(item.get("herb_id"))
        if not herb:
            # 饮片不存在或已删除：绝不放行（不得静默通过）
            results.append({
                "seq_no": item.get("seq_no") or idx,
                "herb_id": item.get("herb_id"),
                "herb_code": None,
                "herb_name": "饮片#%s" % item.get("herb_id"),
                "single_dose": num(item.get("single_dose")),
                "min_common_dose": None,
                "max_common_dose": None,
                "over_dose_reason": (item.get("over_dose_reason") or "").strip() or None,
                "verdict": BLOCK,
                "message": "处方明细所选饮片不存在或已删除，禁止开具",
                "rule_ref": RULE_DOSE_LIMIT,
            })
            continue
        name = _herb_name(herb)
        single = _flt(item.get("single_dose"), 0.0) or 0.0
        max_dose = _flt(herb.get("max_common_dose"))
        min_dose = _flt(herb.get("min_common_dose"))
        reason = (item.get("over_dose_reason") or "").strip()
        verdict = PASS
        message = "剂量正常"
        if max_dose is not None:
            if single > max_dose * 2:
                verdict = BLOCK
                message = "%s 单剂剂量 %sg 超过常用最大量 %sg 的 2 倍，禁止开具" % (
                    name, num(single), num(max_dose))
            elif single > max_dose:
                verdict = NEED_REASON
                if reason:
                    message = "%s 单剂剂量 %sg 超过常用最大量 %sg，已填写超量理由" % (
                        name, num(single), num(max_dose))
                else:
                    message = "%s 单剂剂量 %sg 超过常用最大量 %sg，请填写超量理由" % (
                        name, num(single), num(max_dose))
        results.append({
            "seq_no": item.get("seq_no") or idx,
            "herb_id": item.get("herb_id"),
            "herb_code": herb.get("herb_code"),
            "herb_name": name,
            "single_dose": num(single),
            "min_common_dose": num(min_dose),
            "max_common_dose": num(max_dose),
            "over_dose_reason": reason or None,
            "verdict": verdict,
            "message": message,
            "rule_ref": RULE_DOSE_LIMIT,
        })
    return results


def assert_dose_limit(items, herb_map):
    """R-01 强制判定：BLOCK 或 NEED_REASON 未填理由 → 抛中文异常（阻断保存 / 提交）。"""
    results = check_prescription_items(items, herb_map)
    for row in results:
        if row["verdict"] == BLOCK:
            raise ValueError(row["message"])
    for row in results:
        if row["verdict"] == NEED_REASON and not row["over_dose_reason"]:
            raise ValueError(row["message"])
    return results


def has_over_dose(results):
    """是否存在需填理由的超量药味（供流程变量 hasOverDose）。"""
    return any(r["verdict"] == NEED_REASON for r in results or [])


# ---------------------------------------------------------------- R-02 库存充足


def check_stock_sufficient(items, doses, herb_map):
    """R-02 `RULE-HERB-STOCK-SUFFICIENT` 逐味判定：requiredQuantity = singleDose × doses。

    M3 表达式：任一味 `item.singleDose * prescription.doses > herb(item.herbId).stockQuantity`
    则返回 false（不足）。
    """
    rows = []
    for idx, item in enumerate(items or [], start=1):
        herb = herb_map.get(item.get("herb_id"))
        if not herb:
            rows.append({
                "seq_no": item.get("seq_no") or idx,
                "herb_id": item.get("herb_id"),
                "herb_code": None,
                "herb_name": "饮片#%s" % item.get("herb_id"),
                "single_dose": num(item.get("single_dose")),
                "doses": num(doses),
                "required_quantity": None,
                "stock_quantity": None,
                "enough": False,
                "message": "处方明细所选饮片不存在或已删除，无法调剂",
                "rule_ref": RULE_STOCK_SUFFICIENT,
            })
            continue
        name = _herb_name(herb)
        required = round((_flt(item.get("single_dose"), 0.0) or 0.0) * (_flt(doses, 0.0) or 0.0), 3)
        stock = round(_flt(herb.get("stock_quantity"), 0.0) or 0.0, 3)
        enough = required <= stock  # 严格大于才不足（相等视为充足）
        rows.append({
            "seq_no": item.get("seq_no") or idx,
            "herb_id": item.get("herb_id"),
            "herb_code": herb.get("herb_code"),
            "herb_name": name,
            "single_dose": num(item.get("single_dose")),
            "doses": num(doses),
            "required_quantity": num(required),
            "stock_quantity": num(stock),
            "enough": enough,
            "message": None if enough else "%s 需求 %sg 超过库存 %sg，无法调剂" % (
                name, num(required), num(stock)),
            "rule_ref": RULE_STOCK_SUFFICIENT,
        })
    return rows


def assert_stock_sufficient(rows):
    """R-02 强制判定：任一味不足 → 抛中文异常（阻断调剂确认）。"""
    for row in rows or []:
        if not row.get("enough"):
            raise ValueError(row.get("message") or ("%s 库存不足，无法调剂" % row.get("herb_name")))
    return rows


# ---------------------------------------------------------------- R-03 毒性总量上限


def check_toxic_total(items, herb_map):
    """R-03 `RULE-HERB-TOXIC-TOTAL-LIMIT-CHECK`：毒性饮片单张处方总量（SUM(singleDose)）。

    M3 表达式：toxicityLevel == 'NONE' → true；toxicDoseLimit IS NULL → true（不单独设限）；
    否则 totalDoseInPrescription <= toxicDoseLimit。
    仅返回毒性分级非「无毒」的饮片判定行。
    """
    totals = {}
    order = []
    for item in items or []:
        herb_id = item.get("herb_id")
        if herb_id not in totals:
            totals[herb_id] = 0.0
            order.append(herb_id)
        totals[herb_id] += _flt(item.get("single_dose"), 0.0) or 0.0

    rows = []
    for herb_id in order:
        herb = herb_map.get(herb_id) or {}
        toxicity = (herb.get("toxicity_level") or "NONE").strip() or "NONE"
        if toxicity == "NONE":
            continue
        total = round(totals[herb_id], 3)
        limit = _flt(herb.get("toxic_dose_limit"))
        passed = True if limit is None else total <= limit + _EPS
        rows.append({
            "herb_id": herb_id,
            "herb_code": herb.get("herb_code"),
            "herb_name": _herb_name(herb),
            "toxicity_level": toxicity,
            "total_dose_in_prescription": num(total),
            "toxic_dose_limit": num(limit),
            "passed": passed,
            "message": None if passed else "毒性饮片 %s 单张处方总量 %sg 超过上限 %sg" % (
                _herb_name(herb), num(total), num(limit)),
            "rule_ref": RULE_TOXIC_TOTAL,
        })
    return rows


def assert_toxic_total(items, herb_map):
    """R-03 强制判定：超上限 → 抛中文异常（阻断提交）。未维护上限（NULL）视为放行。"""
    rows = check_toxic_total(items, herb_map)
    for row in rows:
        if not row["passed"]:
            raise ValueError(row["message"])
    return rows


# ---------------------------------------------------------------- R-04 作废分派


def dispatch_on_cancel(record_status, prescription_status=None):
    """R-04 `RULE-PRESCRIPTION-VOID-DISPATCH`：按调剂发药记录状态三分派。

    M3 表达式：recordStatus IS NULL → VOID_ONLY；'PENDING' → VOID_ONLY；
    'DISPENSED' → VOID_WITH_ROLLBACK；'ISSUED' → BLOCK；其余（如已取消）→ VOID_ONLY。
    """
    status = (record_status or "").strip() or None
    if status in (None, REC_PENDING):
        return VOID_ONLY
    if status == REC_DISPENSED:
        return VOID_WITH_ROLLBACK
    if status == REC_ISSUED:
        return VOID_BLOCK
    return VOID_ONLY


def assert_void_dispatch(record_status, prescription_status=None):
    """R-04 强制判定：BLOCK → 抛中文异常「处方已发药，不可作废」（状态不变）。"""
    dispatch = dispatch_on_cancel(record_status, prescription_status)
    if dispatch == VOID_BLOCK:
        raise ValueError(MSG_VOID_BLOCK)
    return dispatch


# ---------------------------------------------------------------- R-05 随访日期顺序


def check_followup_date_order(actual_follow_up_date, source_visit_register_time):
    """R-05 `RULE-FOLLOWUP-DATE-ORDER`：actualFollowUpDate >= DATE(sourceVisit.registerTime)。"""
    actual = as_date(actual_follow_up_date)
    register = as_date(source_visit_register_time)
    if actual is None or register is None:
        raise ValueError(MSG_FOLLOWUP_ORDER)
    return actual >= register


def assert_followup_date_order(actual_follow_up_date, source_visit_register_time):
    """R-05 强制判定：违反 → 抛中文异常。"""
    if not check_followup_date_order(actual_follow_up_date, source_visit_register_time):
        raise ValueError(MSG_FOLLOWUP_ORDER)
    return True


# ---------------------------------------------------------------- R-06 / INV-03 库存对账


def reconcile_difference(stock_quantity, flow_net_quantity):
    """R-06 `RULE-HERB-STOCK-RECONCILE`：stockQuantity − flowNetQuantity（优先用 M3 表达式求值）。"""
    from ontology.registry import registry
    rule = (registry.get("rules") or {}).get(RULE_STOCK_RECONCILE)
    if rule and rule.get("expression"):
        try:
            return round(float(evaluate(rule["expression"], {
                "stockQuantity": float(stock_quantity or 0),
                "flowNetQuantity": float(flow_net_quantity or 0),
            })), 3)
        except Exception:
            pass
    return round(float(stock_quantity or 0) - float(flow_net_quantity or 0), 3)


def flow_net_quantity(herb_id, conn=None):
    row = db.query_one(
        "SELECT COALESCE(SUM(quantity), 0) AS net FROM herb_stock_flow WHERE herb_id = ? AND flag = 1",
        (herb_id,),
        conn,
    )
    return round(float(row["net"] or 0), 3)


def assert_inv03(conn, herb_id):
    """INV-03 / R-06：入库、盘点、调剂扣减、作废回冲后必须继续成立（文案沿用批次 1）。"""
    herb = db.query_one("SELECT stock_quantity FROM herb WHERE id = ?", (herb_id,), conn)
    if not herb:
        raise ValueError("饮片不存在或已删除")
    stock = round(float(herb["stock_quantity"] or 0), 3)
    net = flow_net_quantity(herb_id, conn)
    diff = reconcile_difference(stock, net)
    if abs(diff) > _EPS:
        raise ValueError("库存数量必须等于该饮片全部出入库记录的数量净和（差异 %.3f g）" % diff)
    return {"herb_id": herb_id, "stock_quantity": stock, "flow_net_quantity": net, "difference": diff}
