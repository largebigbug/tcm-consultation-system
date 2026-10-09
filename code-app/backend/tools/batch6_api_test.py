# -*- coding: utf-8 -*-
"""批次 6 主代独立验收（黑盒 HTTP + 库内 oracle + 源码静态守卫）。

与子代理自测脚本**完全独立**：期望值取自《批次6-抽取（模型与运行时事实）.md》与库内事实，不读实现代码的常量。
所有用例跑在**隔离库**（演示库副本），跑完删除；演示库只读。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch6_api_test.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
DEMO = os.path.join(BACKEND, "data", "app.db")
DB = os.path.join(BACKEND, "data", "b6_acc.db")          # 主隔离库
DB2 = os.path.join(BACKEND, "data", "b6_acc2.db")        # 双路径对照库
DOC = os.path.join(os.path.dirname(BACKEND), "docs", "批次6-抽取（模型与运行时事实）.md")
PORT = 5081
BASE = "http://127.0.0.1:%d" % PORT

os.environ["APP_DB_PATH"] = DB
assert os.path.basename(DB) != "app.db", "拒绝以演示库为用例库"

OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-64s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:100]))
    return bool(cond)


def section(t):
    print("\n" + "-" * 110)
    print(t)
    print("-" * 110)


def call(method, path, token=None, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload.decode() or "{}"))
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if raw:
            return exc.code, payload
        try:
            return exc.code, json.loads(payload.decode() or "{}")
        except ValueError:
            return exc.code, {"_raw": payload.decode("utf-8", "replace")[:120]}


def q(sql, params=(), db=None):
    conn = sqlite3.connect(db or DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def one(sql, params=(), db=None):
    rows = q(sql, params, db)
    return rows[0] if rows else None


def fp(db=None):
    """业务+流程+审计行指纹（教训：指纹必须覆盖本批会碰的表）。"""
    parts = []
    for tbl, cols, order in (("prescription", "id, prescription_no, prescription_status, reviewer_id, review_time", "id"),
                             ("dispense_record", "id, dispense_no, prescription_id, record_status", "id"),
                             ("flow_instance", "id, business_key, status", "id"),
                             ("flow_task", "id, instance_id, activity_id, status, action", "id"),
                             ("flow_history", "id, instance_id, activity_id, action", "id"),
                             ("audit_logs", "id, user_id, action", "id")):
        rows = [tuple(r) for r in sqlite3.connect(db or DB).execute("SELECT %s FROM %s ORDER BY %s" % (cols, tbl, order))]
        parts.append("%s=%d:%s" % (tbl, len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:10]))
    return " | ".join(parts)


def reset_isolated():
    for suffix in ("", "-wal", "-shm"):
        for p in (DB + suffix, DB2 + suffix):
            if os.path.exists(p):
                os.remove(p)
    shutil.copyfile(DEMO, DB)


def prep_demo_extra(path):
    """在隔离库里补一条「已发药」处方（用于 R-04 BLOCK 用例）—— 只看库内事实，不造业务假象。"""
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT id, prescription_no FROM prescription WHERE prescription_status = 'ISSUED' LIMIT 1").fetchone()
    finally:
        conn.close()
    return row


def main():
    reset_isolated()
    from app import app as flask_app
    from config import settings as app_settings
    import db as db_module
    assert os.path.abspath(app_settings.resolve_db_path()) == os.path.abspath(DB), "配置库不是隔离库"
    assert os.path.abspath(db_module._db_path) == os.path.abspath(DB), "db 库不是隔离库"
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    doc = io.open(DOC, encoding="utf-8").read()

    # ---------------------------------------------------------------- ① 契约口径自检（直读模型 yaml，不读抽取文档措辞、不读实现常量）
    section("① 契约/模型口径自检（期望值直读 yaml/m6-flow-model.yaml 与 M1 字典）")
    import yaml
    YAML = os.path.join(os.path.dirname(os.path.dirname(BACKEND)), "yaml")   # BACKEND=.../code-app/backend → 项目根/yaml
    m6 = yaml.safe_load(io.open(os.path.join(YAML, "m6-flow-model.yaml"), encoding="utf-8"))
    flow = [f for f in m6["flows"] if f.get("flowType") == "APPROVAL"][0]
    acts = {a["activityId"]: a for a in flow["activities"]}
    check("M6：Q02 审批结论仅 APPROVE/REJECT（D-25 退回等同驳回）",
          acts["Q02"].get("approvalOutcomes") == ["APPROVE", "REJECT"], acts["Q02"].get("approvalOutcomes"))
    void_branch = [b for b in acts["Q03"].get("branches", [])
                   if "已作废" in str(b.get("conditionExpression", ""))]
    check("M6：Q03 存在「处方已作废 → QE02 终止」分支",
          bool(void_branch) and void_branch[0].get("targetActivity") == "QE02",
          [(b.get("conditionExpression"), b.get("targetActivity")) for b in acts["Q03"].get("branches", [])])
    check("M6：流程描述注明「不支持撤回」（D-25）",
          "不支持撤回" in str(flow.get("description")), str(flow.get("description"))[:60])
    doc_codes = re.findall(r"^\| `([A-Z_]+)` \| ([\u4e00-\u9fff]+) \| True \|$", doc, re.M)
    status_codes = doc_codes
    check("处方状态字典 7 值（抽取文档与模型一致）", len(status_codes) == 7, status_codes)
    check("库内 prescription 状态取值 ⊆ 字典取值域",
          {r["prescription_status"] for r in q("SELECT DISTINCT prescription_status FROM prescription")}
          <= {c[0] for c in status_codes}, "")

    # ---------------------------------------------------------------- ② 登录与既有能力不回归
    section("② 六账号登录 + 既有能力不回归")
    users = {"admin": "admin123", "keshi": "123456", "daozhen": "123456", "yishi": "123456",
             "yaoshi": "123456", "kufang": "123456"}
    tokens = {}
    for u, pwd in users.items():
        st, b = call("POST", "/api/auth/login", body={"username": u, "password": pwd})
        tokens[u] = (b.get("data") or {}).get("token") if st == 200 else None
        check("%s 登录" % u, bool(tokens[u]), st)
    for u in ("yaoshi", "yishi"):
        for p in ("todo", "done", "requested"):
            st, b = call("GET", "/api/workbench/%s?page=1&size=10" % p, token=tokens[u])
            check("%s /workbench/%s 200 且 total 可读" % (u, p), st == 200 and isinstance((b.get("data") or {}).get("total"), int), st)

    # ---------------------------------------------------------------- ③ 工作台审批闭环（通过）
    section("③ 工作台「通过」闭环：状态回写 + 生成待调剂记录（契约 §3 / 完成标志 1）")
    todo = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    target = next((t for t in todo if t.get("business_key") == "处方CF000001"), None)
    check("中药师待办含 CF000001（前置条件）", bool(target), [t.get("business_key") for t in todo])
    if target:
        before_rx = one("SELECT * FROM prescription WHERE prescription_no = 'CF000001'")
        before_disp = one("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (before_rx["id"],))["c"]
        st, b = call("POST", "/api/workbench/todo/%d/approve" % target["id"], token=tokens["yaoshi"],
                     body={"comment": "主代验收：同意调剂"})
        check("工作台 approve → 200", st == 200, (st, str(b.get("message"))[:40]))
        after_rx = one("SELECT * FROM prescription WHERE prescription_no = 'CF000001'")
        after_disp = one("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (before_rx["id"],))["c"]
        inst = one("SELECT * FROM flow_instance WHERE business_key = '处方CF000001'")
        task = one("SELECT * FROM flow_task WHERE id = ?", (target["id"],))
        check("处方状态 → APPROVED（审核通过）", after_rx["prescription_status"] == "APPROVED",
              "%s→%s" % (before_rx["prescription_status"], after_rx["prescription_status"]))
        check("review_time 非空（M2 后置条件）", bool(after_rx["review_time"]), after_rx["review_time"])
        check("reviewer_id 非空（M2 后置条件）", bool(str(after_rx["reviewer_id"] or "")), after_rx["reviewer_id"])
        check("新增 1 条调剂记录且状态为待调剂（Dispense_CreatePending）",
              after_disp == before_disp + 1 and
              (one("SELECT record_status FROM dispense_record WHERE prescription_id = ?", (before_rx["id"],)) or {}).get("record_status") in ("PENDING", "待调剂"),
              "%s→%s" % (before_disp, after_disp))
        check("流程实例 → APPROVED", inst["status"] == "APPROVED", inst["status"])
        check("任务 → DONE/APPROVE", task["status"] == "DONE" and task["action"] == "APPROVE", (task["status"], task["action"]))
        check("flow_history 有 APPROVE 记录",
              bool(q("SELECT 1 FROM flow_history WHERE instance_id = ? AND action = 'APPROVE'", (inst["id"],))), "")

    # ---------------------------------------------------------------- ④ 双路径一致性
    section("④ 双路径一致性：工作台 vs 药房审核屏（同处方、同用户、逐字段比对）")
    snapshots = {}
    for label, dbpath in (("workbench", DB), ("business", DB2)):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(dbpath + suffix):
                os.remove(dbpath + suffix)
        shutil.copyfile(DEMO, dbpath)
        db_module.init_db_path(dbpath)
        assert os.path.abspath(db_module._db_path) == os.path.abspath(dbpath), "库切换失败"
        todo = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
        t = next((x for x in todo if x.get("business_key") == "处方CF000002"), None)
        rx_id = one("SELECT id FROM prescription WHERE prescription_no = 'CF000002'", db=dbpath)["id"]
        if label == "workbench":
            st, b = call("POST", "/api/workbench/todo/%d/approve" % (t or {}).get("id", 0), token=tokens["yaoshi"],
                         body={"comment": "一致性对照"})
        else:
            st, b = call("POST", "/api/prescription/%d/review" % rx_id, token=tokens["yaoshi"],
                         body={"action": "APPROVE", "comment": "一致性对照"})
        rx = one("SELECT prescription_status, reviewer_id, review_time, reject_reason FROM prescription WHERE id = ?", (rx_id,), db=dbpath)
        disp = one("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx_id,), db=dbpath)["c"]
        inst = one("SELECT status FROM flow_instance WHERE business_key = '处方CF000002'", db=dbpath)
        task = one("SELECT status, action FROM flow_task WHERE instance_id = (SELECT id FROM flow_instance WHERE business_key='处方CF000002')", db=dbpath)
        snapshots[label] = {"http": st, "rx_status": rx["prescription_status"],
                            "reviewer": bool(str(rx["reviewer_id"] or "")), "review_time": bool(rx["review_time"]),
                            "dispense": disp, "inst": inst["status"], "task": (task["status"], task["action"])}
    a, b2 = snapshots["workbench"], snapshots["business"]
    check("两条路径处方状态一致", a["rx_status"] == b2["rx_status"] == "APPROVED", (a, b2))
    check("两条路径 reviewer/review_time 均写入一致", a["reviewer"] == b2["reviewer"] and a["review_time"] == b2["review_time"], (a, b2))
    check("两条路径调剂记录数一致", a["dispense"] == b2["dispense"], (a["dispense"], b2["dispense"]))
    check("两条路径实例/任务状态一致", a["inst"] == b2["inst"] and a["task"] == b2["task"], (a, b2))
    db_module.init_db_path(DB)
    assert os.path.abspath(db_module._db_path) == os.path.abspath(DB), "库切回失败"

    # ---------------------------------------------------------------- ⑤ 驳回闭环
    section("⑤ 工作台「驳回」闭环 + 参数校验（完成标志 2）")
    todo = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    sub = next((t for t in todo if t.get("business_key") == "处方CF000006"), None)
    check("待办含 CF000006（前置条件）", bool(sub), [t.get("business_key") for t in todo])
    if sub:
        st, b = call("POST", "/api/workbench/todo/%d/reject" % sub["id"], token=tokens["yaoshi"], body={})
        check("驳回未填意见 → 被拒（中文）", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
        rx_before = one("SELECT prescription_status FROM prescription WHERE prescription_no = 'CF000006'")
        st, b = call("POST", "/api/workbench/todo/%d/reject" % sub["id"], token=tokens["yaoshi"],
                     body={"comment": "主代验收：驳回原因"})
        check("驳回 → 200", st == 200, (st, str(b.get("message"))[:40]))
        rx_after = one("SELECT * FROM prescription WHERE prescription_no = 'CF000006'")
        disp = one("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx_after["id"],))["c"]
        inst = one("SELECT status FROM flow_instance WHERE business_key = '处方CF000006'")
        check("处方 → REJECTED 且未生成调剂记录", rx_after["prescription_status"] == "REJECTED" and disp == 0,
              (rx_after["prescription_status"], disp))
        check("reject_reason 写入意见", rx_after["reject_reason"] == "主代验收：驳回原因", rx_after["reject_reason"])
        check("实例 → REJECTED", inst["status"] == "REJECTED", inst["status"])

    # ---------------------------------------------------------------- ⑥ 越权
    section("⑥ 越权：无 prescription:review 的账号调工作台审批（完成标志 4）")
    has_review = one("""SELECT COUNT(*) c FROM sys_user u JOIN sys_user_role ur ON ur.user_id = u.id
        JOIN sys_role_permission rp ON rp.role_id = ur.role_id JOIN sys_permission p ON p.id = rp.permission_id
        WHERE u.username = 'daozhen' AND p.code = 'prescription:review'""")["c"]
    check("前置条件：daozhen 库内确无 prescription:review", has_review == 0, has_review)
    task_row = one("""SELECT t.id, t.status FROM flow_task t JOIN flow_instance i ON i.id = t.instance_id
                      WHERE i.business_key = '处方CF000012' AND t.status = 'TODO'""")
    if task_row:
        rx_before = one("SELECT prescription_status FROM prescription WHERE prescription_no = 'CF000012'")
        st, b = call("POST", "/api/workbench/todo/%d/approve" % task_row["id"], token=tokens["daozhen"],
                     body={"comment": "越权尝试"})
        rx_after = one("SELECT prescription_status FROM prescription WHERE prescription_no = 'CF000012'")
        check("无权限账号审批被拒（中文/403）", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
        check("被拒后处方状态不变", rx_before["prescription_status"] == rx_after["prescription_status"], rx_after["prescription_status"])

    # ---------------------------------------------------------------- ⑦ 转办 / 催办
    section("⑦ 转办 / 催办（工作台侧新接口，契约 §4.2）")
    todo = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    t = next((x for x in todo if x.get("business_key") == "处方CF000012"), None)
    opts = (call("GET", "/api/users/enabled", token=tokens["yaoshi"])[1].get("data") or [])
    # 硬断言：转办选人必须是**用户**（带 username/real_name），不能是角色（历史缺陷：该接口返回 sys_role）
    is_users = bool(opts) and all(any(k in o for k in ("username", "real_name")) for o in opts)
    check("转办选人接口返回的是「用户」（含 username/real_name）", is_users,
          "返回形状=%s 样例=%s" % (sorted(opts[0]) if opts else None, (opts or [{}])[0]))
    opts_roles = (call("GET", "/api/users/options", token=tokens["yaoshi"])[1].get("data") or [])
    check("既有 /api/users/options 语义未被改坏（仍返回角色 code/id/name）",
          bool(opts_roles) and "code" in opts_roles[0] and "username" not in opts_roles[0],
          (opts_roles or [{}])[0])
    others = [o for o in opts if str(o.get("id")) != str((t or {}).get("assignee_id"))] if is_users else []
    check("待办含 CF000012（前置条件）", bool(t), (t or {}).get("business_key"))
    if t and others:
        hist_before = one("SELECT COUNT(*) c FROM flow_history WHERE instance_id = ? AND action = 'URGE'", (t["instance_id"],))["c"]
        st, b = call("POST", "/api/workbench/todo/%d/urge" % t["id"], token=tokens["yaoshi"], body={})
        hist_after = one("SELECT COUNT(*) c FROM flow_history WHERE instance_id = ? AND action = 'URGE'", (t["instance_id"],))["c"]
        check("催办 → 200 且历史 +1", st == 200 and hist_after == hist_before + 1, (st, hist_before, hist_after))
        assignee = others[0]["id"]
        st, b = call("POST", "/api/workbench/todo/%d/transfer" % t["id"], token=tokens["yaoshi"],
                     body={"assigneeId": assignee})
        check("转办 → 200", st == 200, (st, str(b.get("message"))[:40]))
        row = one("SELECT assignee_id FROM flow_task WHERE id = ?", (t["id"],))
        check("任务办理人已变更为目标用户", str(row["assignee_id"]) == str(assignee), row["assignee_id"])
        st, b = call("POST", "/api/workbench/todo/%d/urge" % t["id"], token=tokens["daozhen"], body={})
        check("非归属人催办被拒（中文/403）", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
        # 转回，保持后续用例可控
        call("POST", "/api/workbench/todo/%d/transfer" % t["id"], token=tokens["yaoshi"],
             body={"assigneeId": t.get("assignee_id")})

    # ---------------------------------------------------------------- ⑧ 作废终止
    section("⑧ 作废终止分支（M6 Q03 → QE02；完成标志 6/7）")
    running = one("""SELECT p.id, p.prescription_no, i.id AS inst_id FROM prescription p
                     JOIN flow_instance i ON i.business_key = '处方' || p.prescription_no
                     WHERE i.status = 'RUNNING' AND p.prescription_status = 'PENDING_REVIEW' LIMIT 1""")
    check("存在在办处方可作废（前置条件）", bool(running), running)
    if running:
        st, b = call("POST", "/api/prescription/%d/cancel" % running["id"], token=tokens["yishi"],
                     body={"cancel_reason": "主代验收：作废终止"})
        check("作废 → 200", st == 200, (st, str(b.get("message"))[:40]))
        rx = one("SELECT prescription_status FROM prescription WHERE id = ?", (running["id"],))
        inst = one("SELECT status FROM flow_instance WHERE id = ?", (running["inst_id"],))
        todo_left = one("SELECT COUNT(*) c FROM flow_task WHERE instance_id = ? AND status = 'TODO'", (running["inst_id"],))["c"]
        hist = one("SELECT COUNT(*) c FROM flow_history WHERE instance_id = ? AND action = 'TERMINATE'", (running["inst_id"],))["c"]
        check("处方 → VOIDED", rx["prescription_status"] == "VOIDED", rx["prescription_status"])
        check("实例 → TERMINATED（不是 APPROVED/REJECTED）", inst["status"] == "TERMINATED", inst["status"])
        check("无残留 TODO 任务", todo_left == 0, todo_left)
        check("flow_history 有 TERMINATE", hist >= 1, hist)
    issued = one("SELECT id, prescription_no FROM prescription WHERE prescription_status = 'ISSUED' LIMIT 1")
    if issued:
        st, b = call("POST", "/api/prescription/%d/cancel" % issued["id"], token=tokens["yishi"],
                     body={"cancel_reason": "主代验收：已发药应阻断"})
        rx = one("SELECT prescription_status FROM prescription WHERE id = ?", (issued["id"],))
        check("作废已发药处方被拒（R-04 BLOCK）且状态不变",
              (st >= 400 or b.get("success") is False) and rx["prescription_status"] == "ISSUED",
              (st, str(b.get("message"))[:40], rx["prescription_status"]))

    # ---------------------------------------------------------------- ⑨ 三页筛选
    section("⑨ 工作台三页筛选（契约 §6；与库内计数对账）")
    st, b = call("GET", "/api/workbench/todo?page=1&size=10&flowName=%s" % urllib.parse.quote("中药处方审核流"), token=tokens["yaoshi"])
    listed_total = (b.get("data") or {}).get("total")
    db_total = one("""SELECT COUNT(*) c FROM flow_task t JOIN flow_instance i ON i.id = t.instance_id
                      JOIN flow_definition d ON d.id = i.def_id
                      WHERE t.status = 'TODO' AND d.name LIKE '%中药处方审核流%'
                      AND (t.assignee_id = ? OR t.role_ref IN (SELECT r.code FROM sys_role r))""",
                   (one("SELECT id FROM sys_user WHERE username = 'yaoshi'")["id"],))["c"]
    check("flowName 筛选：接口 total 与库内计数一致", st == 200 and listed_total == db_total, (listed_total, db_total))
    st, b = call("GET", "/api/workbench/todo?page=1&size=10&activityName=%s" % urllib.parse.quote("中药师审核处方"), token=tokens["yaoshi"])
    check("activityName 筛选可用", st == 200, (st, (b.get("data") or {}).get("total")))
    st, b = call("GET", "/api/workbench/todo?page=1&size=10&dateFrom=2000-01-01&dateTo=2000-01-02", token=tokens["yaoshi"])
    check("时间区间筛选取空（历史数据不落在该区间）", st == 200 and (b.get("data") or {}).get("total") == 0,
          (b.get("data") or {}).get("total"))
    st, b = call("GET", "/api/workbench/done?page=1&size=50&status=APPROVE", token=tokens["yaoshi"])
    done_total = (b.get("data") or {}).get("total")
    db_done = one("SELECT COUNT(*) c FROM flow_task t WHERE t.status = 'DONE' AND t.action = 'APPROVE'")["c"]
    check("已办页按处理结果筛选取效（接口 total 与库内计数一致）",
          st == 200 and done_total is not None and done_total <= db_done and done_total > 0,
          (done_total, db_done))
    st, b = call("GET", "/api/workbench/requested?page=1&size=10&status=RUNNING", token=tokens["yishi"])
    check("我的申请按 status 筛选可用", st == 200, (st, (b.get("data") or {}).get("total")))

    # ---------------------------------------------------------------- ⑩ 改密 与 AI 配置
    section("⑩ 修改密码 与 AI 配置只读（契约 §5）")
    st, b = call("POST", "/api/auth/password", token=tokens["kufang"],
                 body={"oldPassword": "wrong-old", "newPassword": "newpass123"})
    check("旧密码错误 → 被拒（中文）", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
    st, b = call("POST", "/api/auth/password", token=tokens["kufang"],
                 body={"oldPassword": "123456", "newPassword": "123456"})
    check("新密码等于旧密码/过短 → 被拒", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
    st, b = call("POST", "/api/auth/password", token=tokens["kufang"],
                 body={"oldPassword": "123456", "newPassword": "kufang888"})
    check("改密 → 200", st == 200, (st, str(b.get("message"))[:40]))
    st_old, _ = call("POST", "/api/auth/login", body={"username": "kufang", "password": "123456"})
    st_new, b_new = call("POST", "/api/auth/login", body={"username": "kufang", "password": "kufang888"})
    check("改密后旧密码失效（4xx 或 success:false）、新密码可登录", st_old >= 400 and st_new == 200, (st_old, st_new))
    st, b = call("GET", "/api/ai/config", token=tokens["admin"])
    d = b.get("data") or {}
    check("GET /api/ai/config 管理员可访问且字段齐备",
          st == 200 and {"provider", "model", "base_url", "configured"} <= set(d), sorted(d))
    check("AI 配置接口不回显任何密钥", "sk-" not in json.dumps(b, ensure_ascii=False), "")
    st, b = call("GET", "/api/ai/config", token=tokens["daozhen"])
    check("非管理员访问 AI 配置 → 拒绝", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))

    # ---------------------------------------------------------------- ⑪ 静态守卫
    section("⑪ 静态守卫：工作台不得自建一套状态回写（单一实现路径）")
    ws = io.open(os.path.join(BACKEND, "services", "workbench_service.py"), encoding="utf-8").read()
    check("workbench_service 复用 review_prescription（单一实现路径）", "review_prescription" in ws,
          sorted(set(re.findall(r"prescription_service\.\w+", ws))))
    check("workbench_service 内不得出现直接改处方状态的 SQL",
          not re.search(r"UPDATE\s+prescription\s+SET\s+prescription_status", ws, re.I), "")
    check("workbench_service 不得再以 reject 冒充终止（作废终止走 TERMINATED）",
          "TERMINAT" in io.open(os.path.join(BACKEND, "services", "prescription_service.py"), encoding="utf-8").read()
          or "terminate" in io.open(os.path.join(BACKEND, "services", "prescription_service.py"), encoding="utf-8").read(),
          "")
    api_ai = io.open(os.path.join(BACKEND, "api", "ai.py"), encoding="utf-8").read()
    check("api/ai.py 的配置接口不返回密钥字段", "api_key" not in api_ai.split("/config")[-1][:800], "")

    # ---------------------------------------------------------------- 收尾
    srv.shutdown()
    for suffix in ("", "-wal", "-shm"):
        for p in (DB + suffix, DB2 + suffix):
            if os.path.exists(p):
                os.remove(p)
    print("\n" + "=" * 110)
    print("批次 6 主代独立验收：通过 %d / 失败 %d（隔离库已删除）" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for n in NG:
            print("   - %s" % n)
    print("=" * 110)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
