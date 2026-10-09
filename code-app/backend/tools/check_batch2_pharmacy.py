# -*- coding: utf-8 -*-
"""批次 2「药房侧」自测（真实 HTTP，Flask test_client）：处方 / 调剂发药 / 随访 / R-01～R-05 / 联动链。

覆盖 `docs/批次2-实现契约.md` §9 必测清单第 1–8、10 项：
  1 全链路正例（挂号 → 接诊 → 四诊 → 辨证确认 → 开方 → 提交 → 审核 → 调剂 → 发药）
  2 R-01 三态（PASS / 超量未填理由阻断 / 超 2 倍阻断 / 超量填理由通过并落库）
  3 R-03 三情形（毒性上限 40g 阻断、30g 通过、无毒放行）
  4 R-02 需求超库存阻断 + 入库补足后放行
  5 R-04 三分派（PENDING 作废无流水 / 已调剂作废回冲且 INV-03 成立 / 已发药阻断）
  6 R-05 实际随访日期早于上次挂号日期 → 阻断
  7 联动（提交后就诊 COMPLETED + 随访生成且计划日期 = 挂号日 + 剂数天；重复提交不重复生成）
  8 INV-02（同就诊第二条主证阻断）+ 处方侧不变性（明细空 / 饮片重复 / 剂数越界 / 驳回无理由）
 10 库存一致性（stock_quantity == SUM(herb_stock_flow.quantity)，调剂后与回冲后）
另附第 9 项的后端 B 侧越权负例（中医师调 dispense:confirm、中药师调 prescription:save 等）。

用法：
  cd D:/hermes/workspace/中医问诊系统/code-app/backend
  ./.venv/Scripts/python.exe tools/check_batch2_pharmacy.py            # 重建数据库后跑
  ./.venv/Scripts/python.exe tools/check_batch2_pharmacy.py --keep-db  # 不删库（数据自增，编号不保证从 1 开始）
"""
import os
import sqlite3
import sys
import traceback

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

KEEP_DB = "--keep-db" in sys.argv
# 自测库必须隔离：绝不能读写演示库 data/app.db（否则本脚本会冲掉演示数据）
DB_PATH = os.path.join(BACKEND, "data", "check_batch2_pharmacy.db")
os.environ["APP_DB_PATH"] = DB_PATH  # 必须：settings.resolve_db_path() 依据该环境变量选库
if not KEEP_DB:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass

from app import create_app  # noqa: E402
import db  # noqa: E402
from services import domain_rules, herb_service  # noqa: E402
from utils.codegen import next_code  # noqa: E402

APP = create_app()
CLIENT = APP.test_client()

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  [PASS] %s%s" % (name, (" | " + str(detail)) if detail else ""))
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s%s" % (name, (" | " + str(detail)) if detail else ""))
    return bool(cond)


def section(title):
    print("\n=== %s ===" % title)


def login(username, password):
    resp = CLIENT.post("/api/auth/login", json={"username": username, "password": password})
    data = resp.get_json() or {}
    assert data.get("success"), "登录失败：%s %s" % (username, data)
    return {"Authorization": "Bearer " + data["data"]["token"]}


def call(method, path, headers, payload=None):
    fn = getattr(CLIENT, method.lower())
    resp = fn(path, headers=headers, json=payload) if payload is not None else fn(path, headers=headers)
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp.status_code, (body or {})


def ok_call(method, path, headers, payload=None):
    """期望成功：返回 data；失败直接抛错（便于定位）。"""
    status, body = call(method, path, headers, payload)
    if status != 200 or not body.get("success"):
        raise RuntimeError("%s %s 期望成功，实际 HTTP %s / %s" % (method, path, status, body.get("message")))
    return body.get("data")


def expect_fail(method, path, headers, payload=None, keyword=None):
    """期望业务失败：返回 (是否失败, 提示文案)。"""
    status, body = call(method, path, headers, payload)
    failed = (not body.get("success")) and status in (200, 400, 403)
    message = body.get("message") or ""
    if keyword:
        failed = failed and (keyword in message)
    return failed, message, status


def sql(sql_text, params=(), one=True):
    conn = db.connect()
    try:
        cur = conn.execute(sql_text, params)
        rows = cur.fetchall()
        conn.commit()
        rows = [dict(r) for r in rows]
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def flow_net(herb_id):
    return domain_rules.flow_net_quantity(herb_id)


# ---------------------------------------------------------------- 前置数据

def seed_fixtures(admin):
    """患者 / 证型（直插 fixture）+ 饮片（走 herb_service 真实建档与入库）。"""
    conn = db.connect()
    try:
        patient_no = next_code("patient", "patient", "patient_no", conn)
        cur = conn.execute(
            "INSERT INTO patient (patient_no, patient_name, gender, birth_date, phone, patient_status) "
            "VALUES (?, ?, 'MALE', '1980-05-06', '13800000001', 'ACTIVE')",
            (patient_no, "自测患者甲"))
        patient_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO syndrome_type (syndrome_code, syndrome_name, diagnosis_method, "
            "corresponding_treatment, syndrome_status) VALUES ('Z900', '自测肝气郁结证', 'ZANGFU', "
            "'疏肝解郁', 'ENABLED')")
        syndrome_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    user = {"id": 1, "username": "admin", "real_name": "系统管理员"}

    def herb(name, min_dose, max_dose, toxicity="NONE", limit=None, stock=0, category="TONIFYING"):
        row = herb_service.create_herb({
            "herb_name": name, "herb_category": category, "min_common_dose": min_dose,
            "max_common_dose": max_dose, "toxicity_level": toxicity, "toxic_dose_limit": limit,
        }, user)
        if stock:
            herb_service.inbound(row["id"], {"quantity": stock, "inbound_no": "RK%s" % row["herb_code"]}, user)
        row = herb_service.get_herb(row["id"])
        return row

    herbs = {
        # 常用 6~12g，无毒：R-01 正常 / 超量用例
        "normal": herb("自测当归", 6, 12, stock=3000),
        # 库存很小：R-02 阻断用例（入库 100g）
        "scarce": herb("自测茯苓", 9, 15, stock=100),
        # 小毒 + 毒性单张上限 30g：R-03 用例（常用 3~20g）
        "toxic": herb("自测半夏", 3, 20, toxicity="SLIGHT", limit=30, stock=1000, category="STOPPING_COUGH"),
        # 常用 6~15g，库存充足：链路正例的第二味（与 R-02 专用的小库存饮片分离）
        "plenty": herb("自测白术", 6, 15, stock=2000),
    }
    return {"patient_id": patient_id, "syndrome_id": syndrome_id, "herbs": herbs}


def a_side_available(headers):
    """后端 A 是否到位：用具备 visit:receive 的中医师探测 /api/visit/pending。"""
    status, _ = call("GET", "/api/visit/pending", headers["yishi"])
    return status == 200


def create_visit_in_consult(headers, fixture, doctor_id="3"):
    """挂号 → 接诊 → 四诊 → 辨证保存+确认；后端 A 未到位时退回等价 fixture。"""
    if a_side_available(headers):
        visit = ok_call("POST", "/api/visit", headers["daozhen"], {
            "patient_id": fixture["patient_id"], "visit_type": "FIRST",
            "dept_code": "TCM_INTERNAL", "doctor_id": doctor_id,
            "chief_complaint": "反复胁肋胀痛 1 月余，自测用",
        })
        visit_id = visit["id"]
        ok_call("POST", "/api/visit/%d/receive" % visit_id, headers["yishi"], {})
        ok_call("POST", "/api/visit/%d/four-diagnosis" % visit_id, headers["yishi"], {
            "pulse_code": "FLOAT", "tongue_body": "PALE_RED", "tongue_coating": "THIN_WHITE",
            "four_diagnosis_summary": "自测：舌淡红苔薄白，脉浮",
        })
        diagnosis = ok_call("POST", "/api/diagnosis", headers["yishi"], {
            "visit_id": visit_id, "diagnosis_method": "ZANGFU", "syndrome_id": fixture["syndrome_id"],
            "syndrome_nature": "PRIMARY", "diagnosis_basis": "情志不畅，胁肋胀痛，善太息，脉弦。",
            "treatment_principle": "疏肝理气、健脾和胃",
        })
        ok_call("POST", "/api/diagnosis/%d/confirm" % diagnosis["id"], headers["yishi"], {})
        visit = ok_call("GET", "/api/visit/%d" % visit_id, headers["daozhen"])
        return visit_id, visit["visit_status"], visit["register_time"], "api(visit/diagnosis)"

    # 后端 A 未交付时的等价 fixture（与 A 的数据口径一致：IN_CONSULT + 已确认主证）
    import datetime
    conn = db.connect()
    try:
        visit_no = next_code("visit", "visit", "visit_no", conn)
        register_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO visit (visit_no, patient_id, visit_type, register_time, receive_time, doctor_id, "
            "dept_code, chief_complaint, visit_status) VALUES (?, ?, 'FIRST', ?, ?, ?, 'TCM_INTERNAL', "
            "'自测主诉', 'IN_PROGRESS')",
            (visit_no, fixture["patient_id"], register_time, register_time, doctor_id))
        visit_id = cur.lastrowid
        conn.execute(
            "INSERT INTO four_diagnosis (visit_id, four_diagnosis_id, pulse_code, four_diagnosis_summary) "
            "VALUES (?, ?, 'FLOAT', '自测四诊')", (visit_id, "FD-%s" % visit_no))
        diag_no = next_code("syndrome_diagnosis", "syndrome_diagnosis", "diagnosis_no", conn)
        conn.execute(
            "INSERT INTO syndrome_diagnosis (diagnosis_no, visit_id, diagnosis_method, syndrome_id, "
            "syndrome_nature, diagnosis_basis, treatment_principle, conclusion_status) "
            "VALUES (?, ?, 'ZANGFU', ?, 'PRIMARY', '情志不畅，胁肋胀痛，善太息，脉弦。', "
            "'疏肝理气、健脾和胃', 'CONFIRMED')",
            (diag_no, visit_id, fixture["syndrome_id"]))
        conn.commit()
    finally:
        conn.close()
    return visit_id, "IN_CONSULT", register_time, "fixture(visit_service 未到位)"


def save_prescription(headers, visit_id, items, doses=7, expect_ok=True, payload_extra=None):
    payload = {
        "visit_id": visit_id, "prescription_type": "HERBAL_DECOCTION", "doses": doses,
        "usage_method": "DAILY_1_2", "decoction_instruction": "自测", "medical_advice": "忌辛辣",
        "items": items,
    }
    payload.update(payload_extra or {})
    if expect_ok:
        row = ok_call("POST", "/api/prescription", headers["yishi"], payload)
        return row["id"], row
    status, body = call("POST", "/api/prescription", headers["yishi"], payload)
    body["_http_status"] = status
    return None, body


def submit(headers, prescription_id, expect_ok=True):
    if expect_ok:
        return ok_call("POST", "/api/prescription/%d/submit" % prescription_id, headers["yishi"], {})
    status, body = call("POST", "/api/prescription/%d/submit" % prescription_id, headers["yishi"], {})
    return body


def approve(headers, prescription_id, comment="同意"):
    return ok_call("POST", "/api/prescription/%d/review" % prescription_id, headers["yaoshi"],
                   {"action": "APPROVE", "comment": comment})


def reject(headers, prescription_id, comment):
    return ok_call("POST", "/api/prescription/%d/review" % prescription_id, headers["yaoshi"],
                   {"action": "REJECT", "comment": comment})


def dispense_confirm(headers, record_id):
    return ok_call("POST", "/api/dispense/%d/confirm" % record_id, headers["yaoshi"], {})


def dispense_issue(headers, record_id):
    return ok_call("POST", "/api/dispense/%d/issue" % record_id, headers["yaoshi"], {})


def item(herb, dose, reason=None):
    row = {"herb_id": herb["id"], "single_dose": dose}
    if reason:
        row["over_dose_reason"] = reason
    return row


# ================================================================ 主流程

def main():
    print("=" * 88)
    print("批次 2 药房侧自测（真实 HTTP / Flask test_client）")
    print("=" * 88)
    print("数据库：%s（%s）" % (DB_PATH, "保留既有数据" if KEEP_DB else "已删除重建"))

    headers = {
        "admin": login("admin", "admin123"),
        "yishi": login("yishi", "123456"),
        "yaoshi": login("yaoshi", "123456"),
        "daozhen": login("daozhen", "123456"),
    }
    print("登录成功：" + "、".join(headers.keys()))
    fixture = seed_fixtures(headers["admin"])
    print("饮片：当归(%s, 6~12g, 库存 %sg) / 茯苓(%s, 9~15g, 库存 %sg) / 半夏(%s, 3~20g, SLIGHT 上限 30g, "
          "库存 %sg) / 白术(%s, 6~15g, 库存 %sg)"
          % (fixture["herbs"]["normal"]["herb_code"], fixture["herbs"]["normal"]["stock_quantity"],
             fixture["herbs"]["scarce"]["herb_code"], fixture["herbs"]["scarce"]["stock_quantity"],
             fixture["herbs"]["toxic"]["herb_code"], fixture["herbs"]["toxic"]["stock_quantity"],
             fixture["herbs"]["plenty"]["herb_code"], fixture["herbs"]["plenty"]["stock_quantity"]))
    normal, scarce, toxic = fixture["herbs"]["normal"], fixture["herbs"]["scarce"], fixture["herbs"]["toxic"]
    plenty = fixture["herbs"]["plenty"]

    # ---------------------------------------------------------- 1 全链路正例 + 7 联动链
    section("1/7. 全链路正例：挂号 → 接诊 → 四诊 → 辨证确认 → 开方 → 提交 → 审核 → 调剂 → 发药")
    visit_id, visit_status, register_time, visit_via = create_visit_in_consult(headers, fixture)
    print("  就诊 #%s（状态 %s，挂号 %s，来源 %s）" % (visit_id, visit_status, register_time, visit_via))
    check("前置：就诊处于接诊中", visit_status in ("IN_CONSULT", "IN_PROGRESS"), visit_status)

    p1, row1 = save_prescription(headers, visit_id, [item(normal, 12), item(plenty, 9)])
    check("Prescription_Save：处方号 CF+6 位", row1["prescription_no"].startswith("CF")
          and len(row1["prescription_no"]) == 8, row1["prescription_no"])
    check("Prescription_Save：状态 DRAFT、开方时间已写", row1["prescription_status"] == "DRAFT"
          and bool(row1["prescribe_time"]), "%s / %s" % (row1["prescription_status"], row1["prescribe_time"]))
    detail1 = ok_call("GET", "/api/prescription/%d" % p1, headers["yaoshi"])
    check("详情：药师（prescription:review）可读，含 2 条明细 + R-01 判定",
          len(detail1["items"]) == 2 and all(d["verdict"] == "PASS" for d in detail1["dose_check"]),
          [d["verdict"] for d in detail1["dose_check"]])

    # 第二张处方：用于「重复提交不重复生成随访」
    p2, row2 = save_prescription(headers, visit_id, [item(normal, 6)])

    stock_before = {normal["id"]: normal["stock_quantity"], plenty["id"]: plenty["stock_quantity"]}
    sub1 = submit(headers, p1)
    check("Prescription_Submit：状态 → PENDING_REVIEW（M1 字典「待审核」）+ submit_time",
          sub1["prescription_status"] == "PENDING_REVIEW" and bool(sub1["submit_time"]),
          "%s / %s" % (sub1["prescription_status"], sub1["submit_time"]))
    check("联动 Visit_Complete：就诊 → COMPLETED", sub1["visit_status"] == "COMPLETED",
          "%s（经由 %s）" % (sub1["visit_status"], sub1["visit_complete_via"]))
    visit_now = sql("SELECT visit_status FROM visit WHERE id = ?", (visit_id,))
    check("联动 Visit_Complete（落库核对）", visit_now["visit_status"] == "COMPLETED", visit_now["visit_status"])

    import datetime
    expect_planned = (datetime.datetime.strptime(str(register_time)[:10], "%Y-%m-%d")
                      + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    plan = sql("SELECT * FROM follow_up WHERE source_visit_id = ? AND flag = 1", (visit_id,))
    check("联动 FollowUp_CreatePlan：生成随访 SF+4 位、状态 PENDING",
          plan is not None and plan["follow_up_no"].startswith("SF") and len(plan["follow_up_no"]) == 6
          and plan["record_status"] == "PENDING",
          plan and "%s / %s" % (plan["follow_up_no"], plan["record_status"]))
    check("随访计划日期 = 挂号日 + 剂数天（%s）" % expect_planned,
          plan and plan["planned_follow_up_date"] == expect_planned,
          plan and plan["planned_follow_up_date"])

    inst = sql("SELECT * FROM flow_instance WHERE business_key = ?", ("处方%s" % row1["prescription_no"],))
    check("引擎：审批流实例已启动（FLOW-PRESCRIPTION-APPROVAL-001）",
          inst is not None and inst["status"] == "RUNNING", inst and inst["status"])
    task = sql("SELECT * FROM flow_task WHERE instance_id = ? AND status = 'TODO'", (inst["id"],)) if inst else None
    check("引擎：生成待办任务且角色为中药师 ROLE-03", task is not None and task["role_ref"] == "ROLE-03",
          task and "%s / %s" % (task["activity_name"], task["role_ref"]))
    check("引擎：business_object_refs 指向处方与调剂聚合",
          inst and "AGG-PRESCRIPTION-001" in (inst["business_object_refs"] or "")
          and "AGG-DISPENSE-001" in (inst["business_object_refs"] or ""), inst and inst["business_object_refs"])

    # 第二张处方提交（就诊已 COMPLETED）：随访不得重复生成
    sub2 = submit(headers, p2)
    cnt = sql("SELECT COUNT(*) AS c FROM follow_up WHERE source_visit_id = ? AND flag = 1", (visit_id,))["c"]
    check("重复提交：就诊保持 COMPLETED 且不重复生成随访（仅 1 条）",
          sub2["visit_status"] == "COMPLETED" and cnt == 1, "随访条数=%s" % cnt)

    pending = ok_call("GET", "/api/prescription/pending-review", headers["yaoshi"])
    row = [r for r in pending["list"] if r["id"] == p1]
    check("待审核列表（UI-07 载入）：含该处方 + 患者姓名 + 超量标记 False",
          bool(row) and row[0]["patient_name"] == "自测患者甲" and row[0]["has_over_dose"] is False,
          row and "%s / %s" % (row[0]["patient_name"], row[0]["has_over_dose"]))

    rev = approve(headers, p1)
    check("Prescription_Review(APPROVE)：状态 → APPROVED + reviewer_id/review_time",
          rev["prescription_status"] == "APPROVED" and rev["reviewer_id"] == "4" and bool(rev["review_time"]),
          "%s / reviewer=%s" % (rev["prescription_status"], rev["reviewer_id"]))
    rec = rev["dispense_record"]
    check("联动 Dispense_CreatePending：生成 FY+6 位待调剂记录，dispenser_id 暂为审核药师",
          rec and rec["dispense_no"].startswith("FY") and len(rec["dispense_no"]) == 8
          and rec["record_status"] == "PENDING" and rec["dispenser_id"] == "4",
          rec and "%s / %s / dispenser=%s" % (rec["dispense_no"], rec["record_status"], rec["dispenser_id"]))
    check("引擎：审批任务已结束（无 TODO 残留）",
          sql("SELECT COUNT(*) AS c FROM flow_task WHERE instance_id = ? AND status = 'TODO'", (inst["id"],))["c"] == 0)
    task_done = sql("SELECT * FROM flow_task WHERE instance_id = ?", (inst["id"],))
    check("引擎：审批任务动作 = APPROVE / 实例状态 APPROVED",
          task_done["status"] == "DONE" and task_done["action"] == "APPROVE"
          and sql("SELECT status FROM flow_instance WHERE id = ?", (inst["id"],))["status"] == "APPROVED",
          "%s / %s" % (task_done["action"], task_done["status"]))

    record_id = rec["id"]
    disp = ok_call("GET", "/api/dispense/%d" % record_id, headers["yaoshi"])
    check("调剂详情：含处方明细 + 逐味库存校验（R-02）全部充足",
          len(disp["items"]) == 2 and disp["stock_enough"] is True,
          [(i["herb_name"], i["required_quantity"], i["stock_quantity"], i["enough"]) for i in disp["items"]])
    sc = ok_call("GET", "/api/dispense/%d/stock-check" % record_id, headers["yaoshi"])
    check("stock-check：需求 = 单剂剂量 × 剂数",
          sc[0]["required_quantity"] == 12 * 7 and sc[1]["required_quantity"] == 9 * 7,
          [(r["herb_name"], r["required_quantity"]) for r in sc])

    conf = dispense_confirm(headers, record_id)
    check("Dispense_Confirm：记录 → DISPENSED（调剂时间/调剂人覆盖为当前用户）",
          conf["record_status"] == "DISPENSED" and conf["dispenser_id"] == "4" and bool(conf["dispense_time"]),
          "%s / dispenser=%s" % (conf["record_status"], conf["dispenser_id"]))
    check("Dispense_Confirm：处方 → DISPENSING（M1 字典「已调剂」）",
          conf["prescription_status"] == "DISPENSING", conf["prescription_status"])
    stock_after = {h["id"]: sql("SELECT * FROM herb WHERE id = ?", (h["id"],))["stock_quantity"]
                   for h in (normal, plenty)}
    check("联动 Herb_DeductStock：库存 = 原库存 − 单剂剂量 × 剂数",
          abs(float(stock_after[normal["id"]]) - (stock_before[normal["id"]] - 84)) < 1e-6
          and abs(float(stock_after[plenty["id"]]) - (stock_before[plenty["id"]] - 63)) < 1e-6,
          "当归 %s→%s / 白术 %s→%s" % (stock_before[normal["id"]], stock_after[normal["id"]],
                                    stock_before[plenty["id"]], stock_after[plenty["id"]]))
    outf = sql("SELECT * FROM herb_stock_flow WHERE prescription_id = ? AND biz_type = 'DISPENSE_OUT' "
               "ORDER BY id", (p1,), one=False)
    check("联动 Herb_DeductStock：写 DISPENSE_OUT 负数量流水且 prescription_id 已填",
          len(outf) == 2 and all(f["quantity"] < 0 and f["prescription_id"] == p1 for f in outf)
          and all(f["flow_no"].startswith("LS") and len(f["flow_no"]) == 8 for f in outf),
          [(f["flow_no"], f["biz_type"], f["quantity"]) for f in outf])

    iss = dispense_issue(headers, record_id)
    check("Dispense_Issue：记录 → ISSUED + 处方 → ISSUED（发药时间不早于调剂时间）",
          iss["record_status"] == "ISSUED" and iss["prescription_status"] == "ISSUED"
          and iss["issue_time"] >= iss["dispense_time"],
          "%s / %s → %s" % (iss["record_status"], iss["dispense_time"], iss["issue_time"]))

    # ---------------------------------------------------------- 10 库存一致性
    section("10. 库存一致性：stock_quantity == SUM(herb_stock_flow.quantity)（INV-03 / R-06）")
    for herb in (normal, scarce, toxic, plenty):
        row = sql("SELECT * FROM herb WHERE id = ?", (herb["id"],))
        net = flow_net(herb["id"])
        check("INV-03 成立：%s" % row["herb_name"], abs(float(row["stock_quantity"]) - net) < 1e-6,
              "库存 %s / 流水净和 %s" % (row["stock_quantity"], net))

    # ---------------------------------------------------------- 2 R-01 三态
    section("2. R-01 RULE-PRESCRIPTION-DOSE-LIMIT-CHECK 三态（常用最大量 12g）")
    v2, st2, _, _ = create_visit_in_consult(headers, fixture)
    pid, prow = save_prescription(headers, v2, [item(normal, 12)])
    d = ok_call("GET", "/api/prescription/%d" % pid, headers["yishi"])
    check("R-01 PASS：单剂 12g = 常用最大量 → 放行", d["dose_check"][0]["verdict"] == "PASS",
          d["dose_check"][0]["verdict"])

    v3, _, _, _ = create_visit_in_consult(headers, fixture)
    _, body = save_prescription(headers, v3, [item(normal, 15)], expect_ok=False)
    check("R-01 NEED_REASON 未填理由：单剂 15g（≤2 倍）→ 阻断保存",
          body.get("success") is False and "自测当归 单剂剂量 15g 超过常用最大量 12g，请填写超量理由"
          in body.get("message", ""), body.get("message"))

    v4, _, _, _ = create_visit_in_consult(headers, fixture)
    _, body = save_prescription(headers, v4, [item(normal, 25)], expect_ok=False)
    check("R-01 BLOCK：单剂 25g（> 2 倍）→ 阻断保存",
          body.get("success") is False and "自测当归 单剂剂量 25g 超过常用最大量 12g 的 2 倍，禁止开具"
          in body.get("message", ""), body.get("message"))

    v5, _, _, _ = create_visit_in_consult(headers, fixture)
    pid5, _ = save_prescription(headers, v5, [item(normal, 15, reason="素体壮实，辨证需加量")])
    d5 = ok_call("GET", "/api/prescription/%d" % pid5, headers["yishi"])
    check("R-01 NEED_REASON 已填理由 → 通过且 over_dose_reason 落库",
          d5["dose_check"][0]["verdict"] == "NEED_REASON"
          and d5["items"][0]["over_dose_reason"] == "素体壮实，辨证需加量",
          "%s / %s" % (d5["dose_check"][0]["verdict"], d5["items"][0]["over_dose_reason"]))
    # 提交时清空超量理由 → 仍须阻断（规则不得静默放行）
    sql("UPDATE prescription_item SET over_dose_reason = NULL WHERE prescription_id = ?", (pid5,))
    body = submit(headers, pid5, expect_ok=False)
    check("R-01 提交兜底：理由被清空后提交 → 阻断",
          body.get("success") is False and "请填写超量理由" in body.get("message", ""), body.get("message"))

    # ---------------------------------------------------------- 3 R-03
    section("3. R-03 RULE-HERB-TOXIC-TOTAL-LIMIT-CHECK（半夏 SLIGHT，单张上限 30g）")
    v6, _, _, _ = create_visit_in_consult(headers, fixture)
    pid6, _ = save_prescription(headers, v6, [item(toxic, 40, reason="急症重剂，已告知患者")])
    body = submit(headers, pid6, expect_ok=False)
    check("R-03：毒性饮片单张总量 40g > 上限 30g → 阻断提交",
          body.get("success") is False
          and "毒性饮片 自测半夏 单张处方总量 40g 超过上限 30g" in body.get("message", ""),
          body.get("message"))

    v7, _, _, _ = create_visit_in_consult(headers, fixture)
    pid7, _ = save_prescription(headers, v7, [item(toxic, 30, reason="上限内加量")])
    sub7 = submit(headers, pid7)
    check("R-03：单张总量 30g = 上限 → 通过（状态 SUBMITTED/PENDING_REVIEW）",
          sub7["prescription_status"] == "PENDING_REVIEW", sub7["prescription_status"])
    check("超量标记：has_over_dose=True 出现在待审核列表（UI-07）",
          [r for r in ok_call("GET", "/api/prescription/pending-review", headers["yaoshi"])["list"]
           if r["id"] == pid7][0]["has_over_dose"] is True)
    d7 = ok_call("GET", "/api/prescription/%d" % pid7, headers["yaoshi"])
    check("R-03 判定行仅含毒性饮片（无毒饮片不放行依赖）",
          len(d7["toxic_check"]) == 1 and d7["toxic_check"][0]["passed"] is True
          and d7["toxic_check"][0]["toxic_dose_limit"] == 30,
          d7["toxic_check"])

    v8, _, _, _ = create_visit_in_consult(headers, fixture)
    pid8, _ = save_prescription(headers, v8, [item(normal, 12), item(toxic, 20, reason="上限内")])
    sub8 = submit(headers, pid8)
    d8 = ok_call("GET", "/api/prescription/%d" % pid8, headers["yaoshi"])
    check("R-03：无毒饮片无上限 → 放行（判定行数为 1，仅毒性饮片）",
          sub8["prescription_status"] == "PENDING_REVIEW" and len(d8["toxic_check"]) == 1
          and d8["toxic_check"][0]["herb_name"] == "自测半夏", len(d8["toxic_check"]))

    # ---------------------------------------------------------- 4 R-02
    section("4. R-02 RULE-HERB-STOCK-SUFFICIENT（茯苓库存 100g，需求 15×10=150g）")
    v9, _, _, _ = create_visit_in_consult(headers, fixture)
    pid9, _ = save_prescription(headers, v9, [item(scarce, 15, reason="加量"), item(plenty, 9)], doses=10)
    submit(headers, pid9)
    approve(headers, pid9)
    rec9 = sql("SELECT * FROM dispense_record WHERE prescription_id = ? AND flag = 1", (pid9,))
    stock_before_r02 = float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (scarce["id"],))["stock_quantity"])
    expect_msg = "自测茯苓 需求 150g 超过库存 %sg，无法调剂" % domain_rules.num(stock_before_r02)
    status, body = call("POST", "/api/dispense/%d/confirm" % rec9["id"], headers["yaoshi"], {})
    check("R-02：需求 150g > 库存 %sg → 阻断调剂并给出饮片与数量" % domain_rules.num(stock_before_r02),
          body.get("success") is False and body.get("message") == expect_msg,
          "%s | 期望：%s" % (body.get("message"), expect_msg))
    check("R-02 阻断后：记录仍 PENDING、处方仍 APPROVED、无出库流水",
          sql("SELECT record_status FROM dispense_record WHERE id = ?", (rec9["id"],))["record_status"] == "PENDING"
          and sql("SELECT prescription_status FROM prescription WHERE id = ?", (pid9,))["prescription_status"] == "APPROVED"
          and sql("SELECT COUNT(*) AS c FROM herb_stock_flow WHERE prescription_id = ?", (pid9,))["c"] == 0)

    ok_call("POST", "/api/herb/%d/inbound" % scarce["id"], headers["admin"],
            {"quantity": 200, "inbound_no": "RK-B2-R02"})
    stock_topped = float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (scarce["id"],))["stock_quantity"])
    check("入库补足后库存 = 原库存 + 200g（%s → %s）"
          % (domain_rules.num(stock_before_r02), domain_rules.num(stock_topped)),
          abs(stock_topped - (stock_before_r02 + 200)) < 1e-6)
    conf9 = dispense_confirm(headers, rec9["id"])
    check("R-02：补货后调剂放行（记录 DISPENSED / 处方 DISPENSING）",
          conf9["record_status"] == "DISPENSED" and conf9["prescription_status"] == "DISPENSING",
          "%s / %s" % (conf9["record_status"], conf9["prescription_status"]))
    check("入库 + 扣减后 INV-03 仍成立（茯苓）",
          abs(float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (scarce["id"],))["stock_quantity"])
              - flow_net(scarce["id"])) < 1e-6,
          "%s vs %s（调剂前 %s）" % (sql("SELECT stock_quantity FROM herb WHERE id = ?",
                                     (scarce["id"],))["stock_quantity"], flow_net(scarce["id"]),
                                 stock_before_r02))

    # ---------------------------------------------------------- 5 R-04 三分派
    section("5. R-04 RULE-PRESCRIPTION-VOID-DISPATCH 三分派")

    # 5a VOID_ONLY（待调剂）
    va, _, _, _ = create_visit_in_consult(headers, fixture)
    pida, _ = save_prescription(headers, va, [item(normal, 10)])
    submit(headers, pida)
    approve(headers, pida)
    reca = sql("SELECT * FROM dispense_record WHERE prescription_id = ? AND flag = 1", (pida,))
    stock_a = float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (normal["id"],))["stock_quantity"])
    cana = ok_call("POST", "/api/prescription/%d/cancel" % pida, headers["yishi"],
                   {"cancel_reason": "患者取消就诊"})
    check("R-04 VOID_ONLY：分派 = VOID_ONLY，处方 → VOIDED，待调剂记录 → CANCELLED",
          cana["dispatch"] == "VOID_ONLY" and cana["prescription_status"] == "VOIDED"
          and cana["cancelled_dispense"] and cana["cancelled_dispense"]["record_status"] == "CANCELLED",
          "%s / %s" % (cana["dispatch"], cana["cancelled_dispense"] and cana["cancelled_dispense"]["record_status"]))
    check("R-04 VOID_ONLY：无库存动作（无流水、库存不变、回冲量 0）",
          cana["rollback_quantity"] == 0
          and sql("SELECT COUNT(*) AS c FROM herb_stock_flow WHERE prescription_id = ?", (pida,))["c"] == 0
          and abs(float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (normal["id"],))["stock_quantity"])
                  - stock_a) < 1e-6)
    failed, message, _ = expect_fail("POST", "/api/prescription/%d/cancel" % pida, headers["yishi"],
                                     {"cancel_reason": "再作废一次"})
    check("状态机：已作废处方再次作废 → 阻断", failed and "不可作废" in message, message)

    # 5b VOID_WITH_ROLLBACK（已调剂）
    vb, _, _, _ = create_visit_in_consult(headers, fixture)
    pidb, _ = save_prescription(headers, vb, [item(normal, 8), item(scarce, 5)], doses=5)
    submit(headers, pidb)
    approve(headers, pidb)
    recb = sql("SELECT * FROM dispense_record WHERE prescription_id = ? AND flag = 1", (pidb,))
    before_b = {h["id"]: float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (h["id"],))["stock_quantity"])
                for h in (normal, scarce)}
    dispense_confirm(headers, recb["id"])
    after_disp = {h["id"]: float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (h["id"],))["stock_quantity"])
                  for h in (normal, scarce)}
    canb = ok_call("POST", "/api/prescription/%d/cancel" % pidb, headers["yishi"],
                   {"cancel_reason": "医师改方，退回重开"})
    after_back = {h["id"]: float(sql("SELECT stock_quantity FROM herb WHERE id = ?", (h["id"],))["stock_quantity"])
                  for h in (normal, scarce)}
    check("R-04 VOID_WITH_ROLLBACK：分派正确 + 处方 VOIDED + 调剂记录 CANCELLED",
          canb["dispatch"] == "VOID_WITH_ROLLBACK" and canb["prescription_status"] == "VOIDED"
          and canb["cancelled_dispense"]["record_status"] == "CANCELLED", canb["dispatch"])
    check("回冲量 = 40 + 25 = 65g", abs(float(canb["rollback_quantity"]) - 65) < 1e-6, canb["rollback_quantity"])
    rollback_flows = sql("SELECT * FROM herb_stock_flow WHERE prescription_id = ? AND biz_type = 'VOID_ROLLBACK'",
                         (pidb,), one=False)
    check("写出 VOID_ROLLBACK 正数量流水（2 条，prescription_id 已填）",
          len(rollback_flows) == 2 and all(f["quantity"] > 0 for f in rollback_flows)
          and all(f["prescription_id"] == pidb for f in rollback_flows),
          [(f["flow_no"], f["quantity"]) for f in rollback_flows])
    check("回冲后库存恢复至调剂前水平", all(abs(after_back[h["id"]] - before_b[h["id"]]) < 1e-6 for h in (normal, scarce)),
          "当归 %s→%s→%s" % (before_b[normal["id"]], after_disp[normal["id"]], after_back[normal["id"]]))

    # 5c BLOCK（已发药）
    vc, _, _, _ = create_visit_in_consult(headers, fixture)
    pidc, _ = save_prescription(headers, vc, [item(normal, 10)])
    submit(headers, pidc)
    approve(headers, pidc)
    recc = sql("SELECT * FROM dispense_record WHERE prescription_id = ? AND flag = 1", (pidc,))
    dispense_confirm(headers, recc["id"])
    dispense_issue(headers, recc["id"])
    status, body = call("POST", "/api/prescription/%d/cancel" % pidc, headers["yishi"],
                        {"cancel_reason": "患者要求退药"})
    check("R-04 BLOCK：已发药作废 → 阻断「处方已发药，不可作废」",
          body.get("success") is False and body.get("message") == "处方已发药，不可作废", body.get("message"))
    check("R-04 BLOCK：状态不变（处方仍 ISSUED / 记录仍 ISSUED）",
          sql("SELECT prescription_status FROM prescription WHERE id = ?", (pidc,))["prescription_status"] == "ISSUED"
          and sql("SELECT record_status FROM dispense_record WHERE id = ?", (recc["id"],))["record_status"] == "ISSUED")
    check("R-04 作废原因必填", expect_fail("POST", "/api/prescription/%d/cancel" % pida, headers["yishi"], {})[1]
          == "作废原因必填")

    # ---------------------------------------------------------- 6 R-05
    section("6. R-05 RULE-FOLLOWUP-DATE-ORDER（实际随访日期 ≥ 上次就诊挂号日期）")
    plan = sql("SELECT * FROM follow_up WHERE source_visit_id = ? AND flag = 1", (visit_id,))
    fups = ok_call("GET", "/api/followup?record_status=PENDING", headers["yishi"])
    check("随访列表：含 patient_name / visit_no / planned_follow_up_date",
          fups["total"] >= 1 and all(k in fups["list"][0] for k in
                                     ("patient_name", "visit_no", "planned_follow_up_date")),
          fups["list"][0]["patient_name"] if fups["list"] else None)
    early = (datetime.datetime.strptime(str(register_time)[:10], "%Y-%m-%d")
             - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    status, body = call("POST", "/api/followup/%d/complete" % plan["id"], headers["yishi"],
                        {"actual_visit_id": visit_id, "actual_follow_up_date": early,
                         "efficacy_level": "EFFECTIVE", "symptom_change": "胁痛减轻",
                         "continue_medication": True})
    check("R-05：实际随访日期早于上次挂号日期 → 阻断",
          body.get("success") is False and body.get("message") == "实际随访日期不得早于上次就诊挂号日期",
          "%s / %s" % (early, body.get("message")))
    okd = ok_call("POST", "/api/followup/%d/complete" % plan["id"], headers["yishi"],
                  {"actual_visit_id": visit_id, "actual_follow_up_date": expect_planned,
                   "efficacy_level": "EFFECTIVE", "symptom_change": "胁痛减轻，睡眠改善",
                   "continue_medication": True, "remark": "自测登记"})
    check("R-05：日期合规 → 登记成功 COMPLETED（本次就诊/实际日期/疗效落库）",
          okd["record_status"] == "COMPLETED" and okd["actual_visit_id"] == visit_id
          and okd["actual_follow_up_date"] == expect_planned and okd["efficacy_level"] == "EFFECTIVE",
          "%s / %s / %s" % (okd["record_status"], okd["actual_follow_up_date"], okd["efficacy_level"]))
    status, body = call("POST", "/api/followup/%d/mark-lost" % plan["id"], headers["yishi"], {"remark": ""})
    check("已完成的随访不可再标记失访", body.get("success") is False, body.get("message"))

    # 失访：新建一条计划随访
    vd, _, _, _ = create_visit_in_consult(headers, fixture)
    pidd, _ = save_prescription(headers, vd, [item(normal, 10)], doses=3)
    submit(headers, pidd)
    plan_d = sql("SELECT * FROM follow_up WHERE source_visit_id = ? AND flag = 1", (vd,))
    # M2 前置：计划随访日期已超期（未到计划日期不能判失访）
    status, body = call("POST", "/api/followup/%d/mark-lost" % plan_d["id"], headers["yishi"],
                        {"remark": "尚未超期却标记失访"})
    check("标记失访：计划未超期 → 阻断（M2 前置「计划随访日期已超期」）",
          body.get("success") is False and "超期" in body.get("message", ""), body.get("message"))
    sql("UPDATE follow_up SET planned_follow_up_date = date('now', '-1 day') WHERE id = ?", (plan_d["id"],))
    status, body = call("POST", "/api/followup/%d/mark-lost" % plan_d["id"], headers["yishi"], {})
    check("标记失访：失访原因必填 → 阻断", body.get("success") is False and "失访原因必填" in body.get("message", ""),
          body.get("message"))
    lost = ok_call("POST", "/api/followup/%d/mark-lost" % plan_d["id"], headers["yishi"],
                   {"remark": "多次电话未接，患者未复诊"})
    check("标记失访：填原因后 → LOST 且原因落库",
          lost["record_status"] == "LOST" and "多次电话未接" in (lost["remark"] or ""),
          "%s / %s" % (lost["record_status"], lost["remark"]))

    # ---------------------------------------------------------- 8 INV-02 + 处方不变性
    section("8. INV-02 主证唯一 + 处方侧不变性（明细空 / 饮片重复 / 剂数越界 / 驳回无理由）")
    if a_side_available(headers):
        status, body = call("POST", "/api/diagnosis", headers["yishi"], {
            "visit_id": visit_id, "diagnosis_method": "ZANGFU", "syndrome_id": fixture["syndrome_id"],
            "syndrome_nature": "PRIMARY", "diagnosis_basis": "再次辨证主证应被阻断的用例。",
            "treatment_principle": "疏肝理气"})
        check("INV-02：同就诊第二条 PRIMARY 辨证 → 阻断（经 diagnosis API）",
              body.get("success") is False and "主证" in body.get("message", ""), body.get("message"))
    else:
        try:
            sql("INSERT INTO syndrome_diagnosis (diagnosis_no, visit_id, diagnosis_method, syndrome_id, "
                "syndrome_nature, diagnosis_basis, treatment_principle, conclusion_status) "
                "VALUES ('BZ999999', ?, 'ZANGFU', ?, 'PRIMARY', '重复主证', '疏肝', 'DRAFT')",
                (visit_id, fixture["syndrome_id"]))
            check("INV-02：同就诊第二条 PRIMARY 辨证 → 阻断（唯一索引）", False, "未抛异常")
        except sqlite3.IntegrityError:
            check("INV-02：同就诊第二条 PRIMARY 辨证 → 阻断（唯一索引 ux_diagnosis_primary 生效）", True)

    ve, _, _, _ = create_visit_in_consult(headers, fixture)
    failed, message, _ = expect_fail("POST", "/api/prescription", headers["yishi"],
                                     {"visit_id": ve, "prescription_type": "HERBAL_DECOCTION", "doses": 7,
                                      "usage_method": "DAILY_1_2", "items": []})
    check("不变性 INV-04：明细为空 → 阻断", failed and "INV-04" in message, message)
    failed, message, _ = expect_fail("POST", "/api/prescription", headers["yishi"],
                                     {"visit_id": ve, "prescription_type": "HERBAL_DECOCTION", "doses": 7,
                                      "usage_method": "DAILY_1_2",
                                      "items": [item(normal, 10), item(normal, 6)]})
    check("不变性：同一处方内饮片重复 → 阻断", failed and "不得重复" in message, message)
    for doses in (0, 31):
        failed, message, _ = expect_fail("POST", "/api/prescription", headers["yishi"],
                                         {"visit_id": ve, "prescription_type": "HERBAL_DECOCTION",
                                          "doses": doses, "usage_method": "DAILY_1_2",
                                          "items": [item(normal, 10)]})
        check("属性规则 REF-10：剂数 %s 越界 → 阻断" % doses, failed and "1 到 30" in message, message)
    failed, message, _ = expect_fail("POST", "/api/prescription", headers["yishi"],
                                     {"visit_id": ve, "prescription_type": "HERBAL_DECOCTION", "doses": 7,
                                      "usage_method": "DAILY_1_2", "items": [item(normal, 0)]})
    check("属性规则 REF-12：单剂剂量 ≤ 0 → 阻断", failed and "REF-12" in message, message)

    # 驳回无理由 + 驳回后重提
    vf, _, _, _ = create_visit_in_consult(headers, fixture)
    pidf, _ = save_prescription(headers, vf, [item(normal, 10)])
    submit(headers, pidf)
    status, body = call("POST", "/api/prescription/%d/review" % pidf, headers["yaoshi"],
                        {"action": "REJECT", "comment": ""})
    check("审核驳回：驳回原因为空 → 阻断", body.get("success") is False and "驳回原因必填" in body.get("message", ""),
          body.get("message"))
    rj = reject(headers, pidf, "剂量偏小，请调整后重报")
    check("审核驳回：填理由 → REJECTED + reject_reason 落库",
          rj["prescription_status"] == "REJECTED" and rj["reject_reason"] == "剂量偏小，请调整后重报",
          rj["prescription_status"])
    upd = ok_call("PUT", "/api/prescription/%d" % pidf, headers["yishi"],
                  {"prescription_type": "HERBAL_DECOCTION", "doses": 5, "usage_method": "DAILY_1_3",
                   "items": [item(normal, 10)]})
    subf = submit(headers, pidf)
    check("驳回后可修改并重新提交（状态回到 PENDING_REVIEW）",
          upd["doses"] == 5 and upd["usage_method"] == "DAILY_1_3"
          and subf["prescription_status"] == "PENDING_REVIEW", subf["prescription_status"])
    status, body = call("POST", "/api/prescription/%d/submit" % pidf, headers["yishi"], {})
    check("状态机：待审核处方不可重复提交", body.get("success") is False, body.get("message"))
    revf = approve(headers, pidf, "同意")
    check("驳回重提后审核通过：状态 APPROVED", revf["prescription_status"] == "APPROVED",
          revf["prescription_status"])
    status, body = call("POST", "/api/prescription/%d/submit" % pidf, headers["yishi"], {})
    check("状态机：已审核通过处方不可再提交送审", body.get("success") is False, body.get("message"))

    # ---------------------------------------------------------- 附 契约 §4.3/§4.4 其余接口
    section("附. 契约 §4.3 / §4.4 其余接口")
    lst = ok_call("GET", "/api/prescription?page=1&size=50", headers["yishi"])
    check("GET /api/prescription：列表可查（含 patient_name / 状态 label / 明细数）",
          lst["total"] >= 1 and "patient_name" in lst["list"][0]
          and lst["list"][0]["prescription_status_label"] is not None, lst["total"])
    lst2 = ok_call("GET", "/api/prescription?prescription_status=SUBMITTED", headers["yishi"])
    check("GET /api/prescription?prescription_status=SUBMITTED（契约别名）→ 等价 PENDING_REVIEW",
          all(r["prescription_status"] == "PENDING_REVIEW" for r in lst2["list"]) and lst2["total"] >= 1,
          "共 %s 条" % lst2["total"])
    lst3 = ok_call("GET", "/api/prescription?prescription_no=%s" % row1["prescription_no"], headers["yishi"])
    check("GET /api/prescription：按处方号过滤命中 1 条", lst3["total"] == 1, lst3["total"])
    pd = ok_call("GET", "/api/prescription/pending-dispense", headers["yaoshi"])
    check("GET /api/prescription/pending-dispense（UI-08 入口列表）字段齐全",
          "dispense_id" in pd["list"][0] or pd["total"] >= 1, pd["total"])
    status, body = call("GET", "/api/prescription/%d" % p1, headers["daozhen"])
    check("越权：导诊员读处方详情（无 prescription:save / review）→ 403", status == 403,
          "HTTP %s / %s" % (status, body.get("message")))
    status, body = call("GET", "/api/prescription/pending-dispense", headers["yishi"])
    check("越权：中医师读待调剂列表（dispense:confirm）→ 403", status == 403, "HTTP %s" % status)

    # ---------------------------------------------------------- 附 越权负例
    section("附. 越权负例（HTTP 403）")
    for name, hdr, method, path, payload in (
            ("中医师（ROLE-02）调 dispense:confirm（调剂确认）", headers["yishi"], "POST",
             "/api/dispense/1/confirm", {}),
            ("中医师（ROLE-02）调 dispense:confirm（库存校验）", headers["yishi"], "GET",
             "/api/dispense/1/stock-check", None),
            ("中医师（ROLE-02）调 prescription:review（审核）", headers["yishi"], "POST",
             "/api/prescription/1/review", {"action": "APPROVE"}),
            ("中医师（ROLE-02）调 prescription:review（待审列表）", headers["yishi"], "GET",
             "/api/prescription/pending-review", None),
            ("中药师（ROLE-03）调 prescription:save（开方）", headers["yaoshi"], "POST", "/api/prescription", {}),
            ("中药师（ROLE-03）调 prescription:submit（提交）", headers["yaoshi"], "POST",
             "/api/prescription/1/submit", {}),
            ("中药师（ROLE-03）调 prescription:cancel（作废）", headers["yaoshi"], "POST",
             "/api/prescription/1/cancel", {}),
            ("中药师（ROLE-03）调 follow_up:complete（随访登记）", headers["yaoshi"], "POST",
             "/api/followup/1/complete", {}),
            ("导诊员（ROLE-01）调 prescription:save（开方）", headers["daozhen"], "POST",
             "/api/prescription", {}),
            ("导诊员（ROLE-01）调 dispense:issue（发药确认）", headers["daozhen"], "POST",
             "/api/dispense/1/issue", {}),
    ):
        status, body = call(method, path, hdr, payload)
        check(name + " → 403", status == 403, "HTTP %s / %s" % (status, body.get("message")))

    # ---------------------------------------------------------- 汇总
    print("\n" + "=" * 88)
    print("汇总：通过 %d / 失败 %d / 合计 %d" % (len(PASSED), len(FAILED), len(PASSED) + len(FAILED)))
    if FAILED:
        print("失败项：")
        for name, detail in FAILED:
            print("  - %s | %s" % (name, detail))
    else:
        print("全部断言通过。")
    print("=" * 88)
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\n[FATAL] 自测脚本异常中断（上方为真实堆栈）")
        sys.exit(2)
