# -*- coding: utf-8 -*-
"""批次 6 后端子代理自测（真实 HTTP / Flask test_client；隔离库）。

覆盖（与《批次6-实现契约》的对应关系写在每个 section 标题里）：
  ① 三页筛选 + 分页自洽（§6 / 完成标志 12）——**在库未被改动时先跑**（筛选结果才非空）
  ② 工作台「通过」闭环（§3 / 完成标志 1）
  ③ 工作台「驳回」闭环 + 意见必填（§3 / 完成标志 2）
  ④ 双路径一致性：工作台 vs `POST /api/prescription/<id>/review`（完成标志 3）
  ⑤ 越权：无 `prescription:review` 账号调工作台审批（§3.2 / 完成标志 4）
  ⑥ 转办 / 催办（§4.2 / 完成标志 8）
  ⑦ 作废终止：在办 → TERMINATED；已发药 → R-04 BLOCK；已调剂 → VOID_WITH_ROLLBACK（§4.1 / 完成标志 6/7）
  ⑧ 改密接口（§5 / 完成标志 10）
  ⑨ `GET /api/ai/config` 只读 + 不含密钥（§5）
  ⑩ 演示库未被写入（血债校验：mtime/size + 8 项基线计数）

纪律（血债）：`APP_DB_PATH` 必须在 `import app` **之前**设置；用例库是**演示库副本**
（basename != app.db），且对配置解析库与运行库都加硬断言；演示库 `data/app.db` 全程只读。

用法：
  cd D:/hermes/workspace/中医问诊系统/code-app/backend
  ./.venv/Scripts/python.exe tools/check_batch6_backend.py
"""
import os
import shutil
import sqlite3
import sys
import traceback
import urllib.parse

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DEMO_DB = os.path.join(BACKEND, "data", "app.db")
DB = os.path.join(BACKEND, "data", "check_batch6_backend.db")      # 主用例库（演示库副本）
DB2 = os.path.join(BACKEND, "data", "check_batch6_backend2.db")    # 双路径对照库

# ---- 隔离库：必须在 import app 之前设置（否则会连到演示库 data/app.db）----
os.environ["APP_DB_PATH"] = DB
assert os.path.basename(DB) != "app.db", "拒绝把演示库当用例库"

for _path in (DB, DB2):
    for _suffix in ("", "-wal", "-shm"):
        if os.path.exists(_path + _suffix):
            os.remove(_path + _suffix)
    shutil.copyfile(DEMO_DB, _path)

from app import create_app          # noqa: E402
import db as db_module              # noqa: E402
from config import settings         # noqa: E402
from seed import permission_code    # noqa: E402

# ---- 硬断言：配置解析库与运行库都必须是隔离库 ----
assert os.path.basename(settings.resolve_db_path()) != "app.db", "配置库是演示库！"
assert os.path.abspath(settings.resolve_db_path()) == os.path.abspath(DB), "配置库不是隔离库"
assert os.path.abspath(db_module._db_path) == os.path.abspath(DB), "db 库不是隔离库"

APP = create_app()
CLIENT = APP.test_client()

OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-68s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:110]))
    return bool(cond)


def section(title):
    print("\n" + "=" * 104)
    print(title)
    print("=" * 104)


def sql(statement, params=(), one=True, path=None):
    conn = sqlite3.connect(path or db_module._db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(statement, params)]
    finally:
        conn.close()
    return (rows[0] if rows else None) if one else rows


def call(method, path, headers=None, payload=None):
    fn = getattr(CLIENT, method.lower())
    resp = fn(path, headers=headers or {}, json=payload) if payload is not None else fn(path, headers=headers or {})
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp.status_code, (body or {})


def login(username, password):
    status, body = call("POST", "/api/auth/login", payload={"username": username, "password": password})
    assert status == 200 and body.get("success"), "登录失败 %s：%s" % (username, body.get("message"))
    return {"Authorization": "Bearer " + body["data"]["token"]}


def switch_db(path):
    db_module.init_db_path(path)
    assert os.path.abspath(db_module._db_path) == os.path.abspath(path), "库切换失败"
    assert os.path.basename(db_module._db_path) != "app.db", "严禁切到演示库"


def task_id_of(no):
    row = sql("""SELECT t.id FROM flow_task t JOIN flow_instance i ON i.id = t.instance_id
                 WHERE i.business_key = ? AND t.status = 'TODO' ORDER BY t.id LIMIT 1""", ("处方%s" % no,))
    return row["id"] if row else None


def uid(username):
    return sql("SELECT id FROM sys_user WHERE username = ?", (username,))["id"]


def demo_fingerprint():
    return (os.path.getmtime(DEMO_DB), os.path.getsize(DEMO_DB))


def main():
    print("批次 6 后端自测（用例库：%s）" % DB)
    print("演示库：%s（只读；用例库为其副本）" % DEMO_DB)
    demo_before = demo_fingerprint()

    headers = {u: login(u, p) for u, p in
               (("admin", "admin123"), ("daozhen", "123456"), ("yishi", "123456"),
                ("yaoshi", "123456"), ("kufang", "123456"), ("keshi", "123456"))}
    print("登录成功：%s" % "、".join(headers))

    yaoshi_uid, yishi_uid = uid("yaoshi"), uid("yishi")

    def sql_todo_total(extra_where="", params=()):
        """独立于实现的对照计数（与 service 同口径：任务状态 + 归属人/角色 + 流程名）。"""
        return sql("""SELECT COUNT(*) c FROM flow_task t JOIN flow_instance i ON i.id=t.instance_id
                      JOIN flow_definition d ON d.id=i.def_id
                      WHERE t.status='TODO' AND (t.assignee_id=? OR t.role_ref IN
                        (SELECT r.code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id
                         WHERE ur.user_id=? AND r.status=1)) %s""" % extra_where,
                   (yaoshi_uid, yaoshi_uid) + tuple(params))["c"]

    # ================================================================ ①
    section("① 三页筛选 + 分页自洽（契约 §6 / 完成标志 12；在未改动库上跑，筛选结果非空）")
    task_date = sql("SELECT date(MAX(created_at)) d FROM flow_task WHERE status='TODO'")["d"]
    q = urllib.parse.quote
    status, body = call("GET", "/api/workbench/todo?page=1&size=50", headers["yaoshi"])
    base_total = body["data"]["total"]
    check("待办基线 total=4（演示库待办）且与库内一致", base_total == 4 == sql_todo_total(),
          (base_total, sql_todo_total()))

    status, body = call("GET", "/api/workbench/todo?page=1&size=10&flowName=%s" % q("中药处方审核流"),
                        headers["yaoshi"])
    expect = sql_todo_total("AND d.name LIKE '%中药处方审核流%'")
    check("flowName 筛选：total 与库内计数一致", status == 200 and body["data"]["total"] == expect == 4,
          (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&flowName=%s" % q("不存在的流程"), headers["yaoshi"])
    check("flowName 不命中 → total=0 且列表为空",
          body["data"]["total"] == 0 and body["data"]["list"] == [], body["data"]["total"])
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&activityName=%s" % q("中药师审核处方"),
                        headers["yaoshi"])
    expect = sql_todo_total("AND t.activity_name LIKE '%中药师审核处方%'")
    check("activityName 筛选：total 与库内计数一致", body["data"]["total"] == expect == 4,
          (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&dateFrom=2000-01-01&dateTo=2000-01-02",
                        headers["yaoshi"])
    check("dateFrom/dateTo 区间外 → total=0", body["data"]["total"] == 0, body["data"]["total"])
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&dateFrom=%s&dateTo=%s" % (task_date, task_date),
                        headers["yaoshi"])
    check("dateFrom/dateTo 命中任务创建日（%s）→ total 与库内一致" % task_date,
          body["data"]["total"] == sql_todo_total("AND date(t.created_at) = date(?)", (task_date,)) == 4,
          body["data"]["total"])
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&status=TODO&flowName=%s"
                        % q("中药处方审核流") + "&activityName=%s" % q("中药师审核处方"), headers["yaoshi"])
    check("组合筛选（status+flowName+activityName）仍自洽",
          body["data"]["total"] == sql_todo_total(
              "AND t.status='TODO' AND d.name LIKE '%中药处方审核流%' AND t.activity_name LIKE '%中药师审核处方%'"),
          body["data"]["total"])
    status, body = call("GET", "/api/workbench/todo?page=1&size=10&status=DONE", headers["yaoshi"])
    check("待办 status=DONE → 0（状态筛选在 SQL 层生效，非前端过滤）", body["data"]["total"] == 0,
          body["data"]["total"])

    status, body = call("GET", "/api/workbench/done?page=1&size=50&status=APPROVE", headers["yaoshi"])
    expect = sql("""SELECT COUNT(*) c FROM flow_task t WHERE t.status IN ('DONE','CANCEL') AND t.action='APPROVE'
                    AND (t.assignee_id=? OR t.role_ref IN (SELECT r.code FROM sys_role r JOIN sys_user_role ur
                    ON ur.role_id=r.id WHERE ur.user_id=? AND r.status=1))""", (yaoshi_uid, yaoshi_uid))["c"]
    check("已办 status 按 action（APPROVE）筛选自洽（=8）", body["data"]["total"] == expect == 8,
          (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/done?page=1&size=50&status=REJECT", headers["yaoshi"])
    expect = sql("""SELECT COUNT(*) c FROM flow_task t WHERE t.status IN ('DONE','CANCEL') AND t.action='REJECT'
                    AND (t.assignee_id=? OR t.role_ref IN (SELECT r.code FROM sys_role r JOIN sys_user_role ur
                    ON ur.role_id=r.id WHERE ur.user_id=? AND r.status=1))""", (yaoshi_uid, yaoshi_uid))["c"]
    check("已办 status 按 action（REJECT）筛选自洽（基线 0）", body["data"]["total"] == expect == 0,
          (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/done?page=1&size=50&dateFrom=2000-01-01&dateTo=2000-01-02",
                        headers["yaoshi"])
    check("已办时间区间外 → total=0", body["data"]["total"] == 0, body["data"]["total"])

    status, body = call("GET", "/api/workbench/requested?page=1&size=50&status=RUNNING", headers["yishi"])
    expect = sql("SELECT COUNT(*) c FROM flow_instance WHERE creator_id=? AND status='RUNNING'", (yishi_uid,))["c"]
    check("我的申请 status=RUNNING 筛选自洽（=4）", status == 200 and body["data"]["total"] == expect == 4,
          (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/requested?page=1&size=50", headers["yishi"])
    rows = body["data"]["list"]
    check("我的申请含「当前节点名 + 状态徽标 + 业务单引用」字段",
          bool(rows) and all(("current_activity_names" in r and "status_label" in r and "business_objects" in r)
                             for r in rows) and rows[0]["current_activity_names"] == ["中药师审核处方"],
          (rows[0]["current_activity_names"], rows[0]["status_label"]) if rows else None)
    status, body = call("GET", "/api/workbench/requested?page=1&size=50&flowName=%s" % q("中药处方审核流"),
                        headers["yishi"])
    expect = sql("""SELECT COUNT(*) c FROM flow_instance i LEFT JOIN flow_definition d ON d.id=i.def_id
                    WHERE i.creator_id=? AND d.name LIKE '%中药处方审核流%'""", (yishi_uid,))["c"]
    check("我的申请 flowName 筛选自洽", body["data"]["total"] == expect == 12, (body["data"]["total"], expect))
    status, body = call("GET", "/api/workbench/requested?page=1&size=50&status=VOIDED", headers["yishi"])
    check("我的申请 status 无匹配 → total=0", body["data"]["total"] == 0, body["data"]["total"])

    status, body = call("GET", "/api/workbench/todo?page=1&size=101", headers["yaoshi"])
    check("size>100 → 400 + 中文", status == 400 and body.get("success") is False and "100" in body.get("message", ""),
          (status, body.get("message")))
    status, body = call("GET", "/api/workbench/todo?page=0&size=10", headers["yaoshi"])
    check("page<1 → 400 + 中文", status == 400 and body.get("success") is False, (status, body.get("message")))
    status, body = call("GET", "/api/workbench/todo?page=1&size=abc", headers["yaoshi"])
    check("size 非数字 → 400 + 中文", status == 400 and body.get("success") is False, (status, body.get("message")))
    status, body = call("GET", "/api/workbench/todo?page=1&size=100", headers["yaoshi"])
    check("size=100（上限内）→ 200 且返回全部 4 条", status == 200 and len(body["data"]["list"]) == 4,
          (status, len(body["data"].get("list", []))))
    status, body = call("GET", "/api/workbench/todo?page=2&size=1", headers["yaoshi"])
    check("分页 page=2&size=1 → total 仍为 4、返回 1 条",
          status == 200 and body["data"]["total"] == 4 and len(body["data"]["list"]) == 1,
          (body["data"]["total"], len(body["data"]["list"])))

    # ================================================================ ②
    section("② 工作台「通过」闭环（契约 §3 / 完成标志 1）")
    rx1 = sql("SELECT * FROM prescription WHERE prescription_no = 'CF000001'")
    disp_before = sql("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx1["id"],))["c"]
    tid = task_id_of("CF000001")
    check("待办存在 CF000001（前置）", bool(tid), tid)
    status, body = call("POST", "/api/workbench/todo/%d/approve" % tid, headers["yaoshi"],
                        {"comment": "自测：同意调剂"})
    check("工作台 approve → 200 且中文提示", status == 200 and body.get("success") is True, body.get("message"))
    rx1_after = sql("SELECT * FROM prescription WHERE id = ?", (rx1["id"],))
    disp_after = sql("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx1["id"],))["c"]
    disp_row = sql("SELECT * FROM dispense_record WHERE prescription_id = ?", (rx1["id"],))
    inst1 = sql("SELECT * FROM flow_instance WHERE business_key = '处方CF000001'")
    task1 = sql("SELECT * FROM flow_task WHERE id = ?", (tid,))
    check("处方 → APPROVED（原 %s）" % rx1["prescription_status"], rx1_after["prescription_status"] == "APPROVED",
          rx1_after["prescription_status"])
    check("reviewer_id / review_time 非空（M2 后置条件）",
          str(rx1_after["reviewer_id"] or "") == str(yaoshi_uid) and bool(rx1_after["review_time"]),
          "%s / %s" % (rx1_after["reviewer_id"], rx1_after["review_time"]))
    check("新增 1 条 dispense_record 且状态 PENDING（Dispense_CreatePending）",
          disp_after == disp_before + 1 and disp_row["record_status"] == "PENDING",
          "%s → %s（%s）" % (disp_before, disp_after, disp_row["record_status"]))
    check("实例 → APPROVED", inst1["status"] == "APPROVED", inst1["status"])
    check("任务 → DONE/APPROVE", task1["status"] == "DONE" and task1["action"] == "APPROVE",
          (task1["status"], task1["action"]))
    check("flow_history 有 APPROVE 记录",
          bool(sql("SELECT 1 FROM flow_history WHERE instance_id = ? AND action = 'APPROVE'", (inst1["id"],))))

    # ================================================================ ③
    section("③ 工作台「驳回」闭环（契约 §3 / 完成标志 2）")
    tid6 = task_id_of("CF000006")
    status, body = call("POST", "/api/workbench/todo/%d/reject" % tid6, headers["yaoshi"], {})
    check("驳回未填意见 → 被拒（中文「驳回原因必填」）",
          body.get("success") is False and "驳回原因必填" in (body.get("message") or ""), body.get("message"))
    check("被拒后处方状态不变（仍 PENDING_REVIEW）",
          sql("SELECT prescription_status FROM prescription WHERE prescription_no='CF000006'")["prescription_status"]
          == "PENDING_REVIEW")
    status, body = call("POST", "/api/workbench/todo/%d/reject" % tid6, headers["yaoshi"],
                        {"comment": "自测：剂量偏小，请调整后重报"})
    check("工作台 reject → 200", status == 200 and body.get("success") is True, body.get("message"))
    rx6 = sql("SELECT * FROM prescription WHERE prescription_no = 'CF000006'")
    inst6 = sql("SELECT * FROM flow_instance WHERE business_key = '处方CF000006'")
    task6 = sql("SELECT * FROM flow_task WHERE id = ?", (tid6,))
    check("处方 → REJECTED + reject_reason = 意见",
          rx6["prescription_status"] == "REJECTED" and rx6["reject_reason"] == "自测：剂量偏小，请调整后重报",
          (rx6["prescription_status"], rx6["reject_reason"]))
    check("未生成调剂记录（Dispense_CreatePending 未触发）",
          sql("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx6["id"],))["c"] == 0)
    check("实例 → REJECTED（不再是 APPROVED）", inst6["status"] == "REJECTED", inst6["status"])
    check("任务 → DONE/REJECT", task6["status"] == "DONE" and task6["action"] == "REJECT",
          (task6["status"], task6["action"]))
    status, body = call("GET", "/api/workbench/done?page=1&size=50&status=REJECT", headers["yaoshi"])
    check("驳回后已办按 action=REJECT 可见（1 条且为该任务）",
          body["data"]["total"] == 1 and body["data"]["list"][0]["id"] == tid6, body["data"]["total"])

    # ================================================================ ④
    section("④ 双路径一致性：工作台 vs 药房审核屏（同一处方 CF000005，逐字段比对）")
    KEYS = ("prescription_status", "reject_reason", "flow_task_action", "flow_task_status", "instance_status",
            "dispense_count", "dispense_status", "history_actions", "reviewer_nonempty", "review_time_nonempty")
    snapshots = {}

    def snapshot(path, rx_id):
        rx = sql("SELECT prescription_status, reject_reason, reviewer_id, review_time FROM prescription "
                 "WHERE id = ?", (rx_id,), path=path)
        inst_id = sql("SELECT id FROM flow_instance WHERE business_key='处方CF000005'", path=path)["id"]
        inst = sql("SELECT status FROM flow_instance WHERE id = ?", (inst_id,), path=path)
        task = sql("SELECT status, action FROM flow_task WHERE instance_id=? ORDER BY id DESC LIMIT 1",
                   (inst_id,), path=path)
        disp = sql("SELECT record_status FROM dispense_record WHERE prescription_id = ?", (rx_id,), path=path)
        hist = sql("SELECT action, COUNT(*) c FROM flow_history WHERE instance_id=? GROUP BY action",
                   (inst_id,), False, path)
        return {
            "prescription_status": rx["prescription_status"],
            "reject_reason": rx["reject_reason"],
            "flow_task_action": task["action"],
            "flow_task_status": task["status"],
            "instance_status": inst["status"],
            "dispense_count": sql("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?",
                                  (rx_id,), path=path)["c"],
            "dispense_status": disp["record_status"] if disp else None,
            "history_actions": {h["action"]: h["c"] for h in hist},
            "reviewer_nonempty": bool(str(rx["reviewer_id"] or "")),
            "review_time_nonempty": bool(rx["review_time"]),
        }

    switch_db(DB)
    rx5_id = sql("SELECT id FROM prescription WHERE prescription_no='CF000005'")["id"]
    tid5 = task_id_of("CF000005")
    status, body = call("POST", "/api/workbench/todo/%d/approve" % tid5, headers["yaoshi"],
                        {"comment": "自测：双路径一致性"})
    check("路径 A（工作台 approve）→ 200", status == 200 and body.get("success") is True, body.get("message"))
    snapshots["workbench"] = snapshot(DB, rx5_id)

    switch_db(DB2)
    rx5_id_b = sql("SELECT id FROM prescription WHERE prescription_no='CF000005'")["id"]
    status, body = call("POST", "/api/prescription/%d/review" % rx5_id_b, headers["yaoshi"],
                        {"action": "APPROVE", "comment": "自测：双路径一致性"})
    check("路径 B（/api/prescription/<id>/review）→ 200", status == 200 and body.get("success") is True,
          body.get("message"))
    snapshots["business"] = snapshot(DB2, rx5_id_b)
    switch_db(DB)
    check("已切回主用例库", os.path.abspath(db_module._db_path) == os.path.abspath(DB))

    a, b = snapshots["workbench"], snapshots["business"]
    for key in KEYS:
        check("双路径逐字段一致：%s" % key, a[key] == b[key], "workbench=%s / business=%s" % (a[key], b[key]))

    # ================================================================ ⑤
    section("⑤ 越权：无 prescription:review 的账号调工作台审批（§3.2 / 完成标志 4）")
    has_review = sql("""SELECT COUNT(*) c FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id
        JOIN sys_role_permission rp ON rp.role_id=ur.role_id JOIN sys_permission p ON p.id=rp.permission_id
        WHERE u.username='daozhen' AND p.code='prescription:review'""")["c"]
    check("前置：库内 daozhen 确无 prescription:review", has_review == 0, has_review)
    check("权限码由 seed.permission_code 派生（Prescription_Review → prescription:review）",
          permission_code("Prescription_Review") == "prescription:review", permission_code("Prescription_Review"))
    tid12 = task_id_of("CF000012")
    rx12_before = sql("SELECT prescription_status FROM prescription WHERE prescription_no='CF000012'")
    status, body = call("POST", "/api/workbench/todo/%d/approve" % tid12, headers["daozhen"],
                        {"comment": "越权尝试"})
    rx12_after = sql("SELECT prescription_status FROM prescription WHERE prescription_no='CF000012'")
    check("工作台审批被拒（HTTP %s / %s）" % (status, body.get("message")),
          status in (200, 403) and body.get("success") is False, body.get("message"))
    check("被拒后处方状态不变", rx12_before["prescription_status"] == rx12_after["prescription_status"],
          rx12_after["prescription_status"])
    check("被拒后任务仍 TODO", sql("SELECT status FROM flow_task WHERE id = ?", (tid12,))["status"] == "TODO")
    # 补充：把任务转给 daozhen 使其「归属满足」，仍须因缺权限码被拒（权限先于归属校验）
    call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["yaoshi"], {"assigneeId": uid("daozhen")})
    status, body = call("POST", "/api/workbench/todo/%d/approve" % tid12, headers["daozhen"], {"comment": "越权2"})
    check("任务已转给他（归属满足）仍因缺 prescription:review 被拒（HTTP %s）" % status,
          body.get("success") is False and status in (200, 403), body.get("message"))
    call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["yaoshi"], {"assigneeId": yaoshi_uid})

    # ================================================================ ⑥
    section("⑥ 转办 / 催办（§4.2 / 完成标志 8）")
    inst12_id = sql("SELECT instance_id FROM flow_task WHERE id = ?", (tid12,))["instance_id"]
    urge_before = sql("SELECT COUNT(*) c FROM flow_history WHERE instance_id=? AND action='URGE'", (inst12_id,))["c"]
    status, body = call("POST", "/api/workbench/todo/%d/urge" % tid12, headers["yaoshi"], {})
    urge_after = sql("SELECT COUNT(*) c FROM flow_history WHERE instance_id=? AND action='URGE'", (inst12_id,))["c"]
    check("催办 → 200 且 URGE 历史 +1", status == 200 and urge_after == urge_before + 1,
          (status, urge_before, urge_after))
    check("催办后任务仍在 TODO", sql("SELECT status FROM flow_task WHERE id=?", (tid12,))["status"] == "TODO")

    status, body = call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["daozhen"],
                        {"assigneeId": yishi_uid})
    check("非归属人转办 → 被拒（中文）", body.get("success") is False, body.get("message"))
    status, body = call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["yaoshi"],
                        {"assigneeId": yishi_uid})
    check("转办 → 200 + 中文提示", status == 200 and body.get("success") is True, body.get("message"))
    check("任务办理人已变更", sql("SELECT assignee_id FROM flow_task WHERE id=?", (tid12,))["assignee_id"] == yishi_uid)
    transfer_rows = sql("SELECT comment FROM flow_history WHERE instance_id=? AND action='TRANSFER' ORDER BY id",
                        (inst12_id,), False)
    check("写 flow_history(action='TRANSFER') 且含原→新办理人",
          len(transfer_rows) >= 1 and "赵中药师 → 李中医师" in (transfer_rows[-1]["comment"] or ""),
          [r["comment"] for r in transfer_rows])
    yaoshi_todo = call("GET", "/api/workbench/todo?page=1&size=50", headers["yaoshi"])[1]["data"]["list"]
    yishi_todo = call("GET", "/api/workbench/todo?page=1&size=50", headers["yishi"])[1]["data"]["list"]
    # 转给「非本流程角色」用户：新办理人按归属可见；原办理人按角色仍可见
    # （底座口径：归属 OR 角色；「从原办理人待办消失」仅在原办理人无 ROLE-03 时成立）
    row12 = sql("SELECT assignee_name FROM flow_task WHERE id=?", (tid12,))
    check("原办理人侧该任务的办理人已改（李中医师，角色可见性口径下仍在列表）",
          row12["assignee_name"] == "李中医师"
          and [t["assignee_name"] for t in yaoshi_todo if t["id"] == tid12] == ["李中医师"],
          (row12["assignee_name"], [t["id"] for t in yaoshi_todo]))
    check("新办理人（yishi）待办出现该任务", any(t["id"] == tid12 for t in yishi_todo),
          [t["id"] for t in yishi_todo])
    status, body = call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["yishi"],
                        {"assigneeId": 999999})
    check("转办给不存在用户（当前办理人发起）→ 中文拒绝（目标用户不存在）",
          body.get("success") is False and "不存在" in (body.get("message") or ""), body.get("message"))
    status, body = call("POST", "/api/workbench/todo/%d/transfer" % tid12, headers["yishi"],
                        {"assigneeId": yaoshi_uid})
    check("转回原办理人（yishi 以「办理人」口径通过鉴权）→ 200",
          status == 200 and body.get("success") is True, body.get("message"))
    check("转回后导诊员待办不出现该任务（归属口径：非归属即不可见）",
          all(t["id"] != tid12 for t in call("GET", "/api/workbench/todo?page=1&size=50",
                                             headers["daozhen"])[1]["data"]["list"]))
    status, body = call("POST", "/api/workbench/todo/%d/urge" % tid12, headers["yishi"], {})
    check("转回后非归属人催办 → 被拒", body.get("success") is False, body.get("message"))

    # ================================================================ ⑦
    section("⑦ 作废终止（§4.1 / 完成标志 6/7）")
    rx12 = sql("SELECT * FROM prescription WHERE prescription_no='CF000012'")
    inst12 = sql("SELECT * FROM flow_instance WHERE business_key='处方CF000012'")
    check("前置：CF000012 在办（处方 PENDING_REVIEW + 实例 RUNNING）",
          rx12["prescription_status"] == "PENDING_REVIEW" and inst12["status"] == "RUNNING",
          (rx12["prescription_status"], inst12["status"]))
    status, body = call("POST", "/api/prescription/%d/cancel" % rx12["id"], headers["yishi"],
                        {"cancel_reason": "自测：作废终止"})
    check("作废 → 200", status == 200 and body.get("success") is True, body.get("message"))
    rx12_after = sql("SELECT * FROM prescription WHERE id = ?", (rx12["id"],))
    inst12_after = sql("SELECT * FROM flow_instance WHERE id = ?", (inst12["id"],))
    check("处方 → VOIDED + cancel_reason 落库",
          rx12_after["prescription_status"] == "VOIDED" and rx12_after["cancel_reason"] == "自测：作废终止",
          (rx12_after["prescription_status"], rx12_after["cancel_reason"]))
    check("实例 → TERMINATED（不是 APPROVED/REJECTED）", inst12_after["status"] == "TERMINATED",
          inst12_after["status"])
    check("实例 ended_at 已写", bool(inst12_after["ended_at"]), inst12_after["ended_at"])
    check("该实例 0 个残留 TODO 任务",
          sql("SELECT COUNT(*) c FROM flow_task WHERE instance_id=? AND status='TODO'", (inst12["id"],))["c"] == 0)
    terminate_comment = sql("SELECT comment FROM flow_history WHERE instance_id=? AND action='TERMINATE'", (inst12["id"],))
    check("flow_history 有 TERMINATE 记录（含作废原因）",
          terminate_comment is not None and "作废" in (terminate_comment["comment"] or ""),
          terminate_comment and terminate_comment["comment"])
    check("响应含终止事实（§4.1 结果字段）",
          (body.get("data") or {}).get("prescription_status") == "VOIDED"
          and (body.get("data") or {}).get("flow_instance_status") == "TERMINATED"
          and (body.get("data") or {}).get("flow_instance_id") == inst12["id"], body.get("data"))

    issued = sql("SELECT * FROM prescription WHERE prescription_status='ISSUED' ORDER BY id LIMIT 1")
    status, body = call("POST", "/api/prescription/%d/cancel" % issued["id"], headers["yishi"],
                        {"cancel_reason": "自测：已发药应阻断"})
    issued_after = sql("SELECT * FROM prescription WHERE id = ?", (issued["id"],))
    check("作废已发药处方 → 被拒（R-04 BLOCK「处方已发药，不可作废」）",
          body.get("success") is False and body.get("message") == "处方已发药，不可作废", body.get("message"))
    check("被拒后状态不变（处方 ISSUED / 调剂记录 ISSUED）",
          issued_after["prescription_status"] == "ISSUED"
          and sql("SELECT record_status FROM dispense_record WHERE prescription_id=? AND flag=1",
                  (issued["id"],))["record_status"] == "ISSUED", issued_after["prescription_status"])
    issued_inst = sql("SELECT id FROM flow_instance WHERE business_key='处方%s'" % issued["prescription_no"])
    check("已发药处方作废被拒后未动流程实例（无 TERMINATE）",
          sql("SELECT COUNT(*) c FROM flow_history WHERE instance_id=? AND action='TERMINATE'",
              (issued_inst["id"],))["c"] == 0)

    # R-04 第三态：已调剂（DISPENSING）→ VOID_WITH_ROLLBACK（确认「三分派」未回归）
    rx2 = sql("SELECT * FROM prescription WHERE prescription_no='CF000002'")
    rec2 = sql("SELECT * FROM dispense_record WHERE prescription_id=? AND flag=1", (rx2["id"],))
    st_c, body_c = call("POST", "/api/dispense/%d/confirm" % rec2["id"], headers["yaoshi"], {})
    if st_c == 200 and body_c.get("success"):
        status, body = call("POST", "/api/prescription/%d/cancel" % rx2["id"], headers["yishi"],
                            {"cancel_reason": "自测：已调剂作废回冲"})
        rollback_flows = sql("SELECT COUNT(*) c FROM herb_stock_flow WHERE prescription_id=? AND biz_type='VOID_ROLLBACK'",
                             (rx2["id"],))["c"]
        check("R-04 VOID_WITH_ROLLBACK：已调剂作废 → 回冲流水 %s 条、处方 VOIDED" % rollback_flows,
              body.get("success") is True and (body.get("data") or {}).get("dispatch") == "VOID_WITH_ROLLBACK"
              and rollback_flows >= 1
              and sql("SELECT prescription_status FROM prescription WHERE id=?",
                      (rx2["id"],))["prescription_status"] == "VOIDED", body.get("data"))
        check("已调剂处方作废不影响流程实例（该实例 APPROVED、非在办 → 不终止）",
              sql("SELECT status FROM flow_instance WHERE business_key='处方CF000002'")["status"] == "APPROVED")
    else:
        check("R-04 第三态用例前置（调剂确认）", False, "调剂确认失败：%s" % body_c.get("message"))

    # ================================================================ ⑧
    section("⑧ 修改密码（§5 / 完成标志 10）")
    audit_before = sql("SELECT COUNT(*) c FROM audit_logs WHERE action='CHANGE_PASSWORD'")["c"]
    status, body = call("POST", "/api/auth/password", headers["kufang"],
                        {"oldPassword": "wrong-old", "newPassword": "newpass123"})
    check("原密码错误 → 400 + 中文", status == 400 and "原密码" in body.get("message", ""),
          (status, body.get("message")))
    status, body = call("POST", "/api/auth/password", headers["kufang"],
                        {"oldPassword": "123456", "newPassword": "123456"})
    check("新密码 = 原密码 → 400 + 中文", status == 400 and body.get("success") is False,
          (status, body.get("message")))
    status, body = call("POST", "/api/auth/password", headers["kufang"],
                        {"oldPassword": "123456", "newPassword": "123"})
    check("新密码 < 6 位 → 400 + 中文", status == 400 and "6" in body.get("message", ""),
          (status, body.get("message")))
    status, body = call("POST", "/api/auth/password", headers["kufang"],
                        {"oldPassword": "123456", "newPassword": "kufang"})
    check("新密码 = 用户名 → 400 + 中文", status == 400 and "用户名" in body.get("message", ""),
          (status, body.get("message")))
    status, body = call("POST", "/api/auth/password", headers["kufang"], {"oldPassword": "123456"})
    check("缺 newPassword → 400 + 中文", status == 400, (status, body.get("message")))
    status, body = call("POST", "/api/auth/password", headers["kufang"],
                        {"oldPassword": "123456", "newPassword": "kufang888"})
    check("改密 → 200 + 中文提示", status == 200 and body.get("success") is True, body.get("message"))
    audit_after = sql("SELECT COUNT(*) c FROM audit_logs WHERE action='CHANGE_PASSWORD'")["c"]
    last_audit = sql("SELECT username FROM audit_logs WHERE action='CHANGE_PASSWORD' ORDER BY id DESC LIMIT 1")
    check("audit_logs 写 CHANGE_PASSWORD（+1）且记录本人",
          audit_after == audit_before + 1 and last_audit["username"] == "kufang", (audit_before, audit_after))
    check("密码落库为哈希（非明文）",
          sql("SELECT password FROM sys_user WHERE username='kufang'")["password"] != "kufang888")
    st_old, _ = call("POST", "/api/auth/login", payload={"username": "kufang", "password": "123456"})
    st_new, b_new = call("POST", "/api/auth/login", payload={"username": "kufang", "password": "kufang888"})
    check("旧密码失效（HTTP %s）/ 新密码可登录（HTTP %s）" % (st_old, st_new),
          st_old >= 400 and st_new == 200, (st_old, st_new))
    check("新密码登录后权限不变（仍含 herb:save）", "herb:save" in b_new["data"]["permissions"],
          b_new["data"]["permissions"][:3])

    # ================================================================ ⑨
    section("⑨ GET /api/ai/config 只读 + 不含密钥（§5）")
    import json as _json
    status, body = call("GET", "/api/ai/config", headers["admin"])
    data = body.get("data") or {}
    check("管理员可访问且字段齐备", status == 200 and {"provider", "model", "base_url", "configured"} <= set(data),
          sorted(data))
    check("envKeys = 4 个环境变量名（AI_PROVIDER/AI_API_KEY/AI_BASE_URL/AI_MODEL）",
          data.get("envKeys") == ["AI_PROVIDER", "AI_API_KEY", "AI_BASE_URL", "AI_MODEL"], data.get("envKeys"))
    check("hint 为中文（未配置时给启用指引）",
          bool(data.get("hint")) and any("\u4e00" <= ch <= "\u9fff" for ch in data.get("hint", "")), data.get("hint"))
    blob = _json.dumps(body, ensure_ascii=False)
    check("响应体不含密钥形态（sk-）", "sk-" not in blob)
    check("响应体不含密钥字段名（apiKey/api_key）", "apiKey" not in blob and "api_key" not in blob)
    status, body = call("GET", "/api/ai/config", headers["daozhen"])
    check("非管理员（daozhen）→ 403 + 中文", status == 403 and body.get("success") is False,
          (status, body.get("message")))
    status, body = call("GET", "/api/ai/config", headers["keshi"])
    check("非管理员（keshi 科室管理员）→ 403", status == 403, (status, body.get("message")))
    status, body = call("GET", "/api/ai/config")
    check("未登录 → 401", status == 401, status)

    # ================================================================ ⑩
    section("⑩ 演示库未被写入（血债校验）")
    demo_after = demo_fingerprint()
    check("演示库 data/app.db mtime/size 未变", demo_before == demo_after, (demo_before, demo_after))
    conn = sqlite3.connect("file:%s?mode=ro" % DEMO_DB.replace("\\", "/"), uri=True)
    try:
        baseline = {
            "flow_task TODO": conn.execute("SELECT COUNT(*) FROM flow_task WHERE status='TODO'").fetchone()[0],
            "flow_task DONE": conn.execute("SELECT COUNT(*) FROM flow_task WHERE status='DONE'").fetchone()[0],
            "flow_instance RUNNING": conn.execute("SELECT COUNT(*) FROM flow_instance WHERE status='RUNNING'").fetchone()[0],
            "flow_instance APPROVED": conn.execute("SELECT COUNT(*) FROM flow_instance WHERE status='APPROVED'").fetchone()[0],
            "flow_history": conn.execute("SELECT COUNT(*) FROM flow_history").fetchone()[0],
            "audit_logs": conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0],
            "dispense_record": conn.execute("SELECT COUNT(*) FROM dispense_record").fetchone()[0],
            "prescription": conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0],
        }
    finally:
        conn.close()
    expected = {"flow_task TODO": 4, "flow_task DONE": 8, "flow_instance RUNNING": 4,
                "flow_instance APPROVED": 8, "flow_history": 28, "audit_logs": 17,
                "dispense_record": 8, "prescription": 12}
    for key, value in expected.items():
        check("演示库基线：%s = %s" % (key, value), baseline[key] == value, baseline[key])

    print("\n" + "=" * 104)
    print("汇总：通过 %d / 失败 %d / 合计 %d（用例库 %s）" % (len(OK), len(NG), len(OK) + len(NG), DB))
    if NG:
        print("失败项：")
        for name in NG:
            print("   - %s" % name)
    else:
        print("全部断言通过。")
    print("=" * 104)
    return 1 if NG else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\n[FATAL] 自测脚本异常中断（上方为真实堆栈）")
        sys.exit(2)
