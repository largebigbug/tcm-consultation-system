# -*- coding: utf-8 -*-
"""批次 6 小修复自测（真实 Flask test_client；隔离库 = 演示库副本）。

覆盖：
  ① `GET /api/users/enabled` 返回**启用用户**（id/username/real_name；**不含**角色字段）
     且 `GET /api/users/options` 行为不变（仍返回角色选项，含 code）
  ② 中药师（yaoshi）待办列表：每条记录 `business_objects` 中 `AGG-PRESCRIPTION-001` 的
     `status` 与库内 `prescription.prescription_status` **逐条一致**；`business_object_refs` 保留
  ③ 我的申请（yishi，requested）同样逐条校验
  ④ 已办（yaoshi，done）同样逐条校验
  ⑤ 筛选参数回归：flowName / activityName / dateFrom / dateTo / status 的 `total`
     与**独立 SQL 计数**相等（三页各跑一遍）
  ⑥ 演示库 data/app.db 未被写入（mtime/size + 8 项基线计数）

纪律（血债）：`APP_DB_PATH` 必须在 `import app` **之前**设置；用例库是演示库副本
（basename != app.db），对配置解析库与运行库都加硬断言；演示库全程只读。

用法：
  cd D:/hermes/workspace/中医问诊系统/code-app/backend
  ./.venv/Scripts/python.exe tools/check_batch6_fix.py
"""
import json
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
DB = os.path.join(BACKEND, "data", "check_batch6_fix.db")          # 用例库（演示库副本，本地删）

# ---- 隔离库：必须在 import app 之前设置（否则会连到演示库 data/app.db）----
os.environ["APP_DB_PATH"] = DB
assert os.path.basename(DB) != "app.db", "拒绝把演示库当用例库"
assert os.path.basename(DEMO_DB) == "app.db", "演示库路径异常"

for _suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB + _suffix):
        os.remove(DB + _suffix)
shutil.copyfile(DEMO_DB, DB)

from app import create_app          # noqa: E402
import db as db_module              # noqa: E402
from config import settings         # noqa: E402

# ---- 硬断言：配置解析库与运行库都必须是隔离库 ----
assert os.path.basename(settings.resolve_db_path()) != "app.db", "配置库是演示库！"
assert os.path.abspath(settings.resolve_db_path()) == os.path.abspath(DB), "配置库不是隔离库"
assert os.path.basename(db_module._db_path) != "app.db", "运行库是演示库！"
assert os.path.abspath(db_module._db_path) == os.path.abspath(DB), "db 库不是隔离库"

APP = create_app()
CLIENT = APP.test_client()

OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-72s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:130]))
    return bool(cond)


def section(title):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)


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


def login(username, password="123456"):
    status, body = call("POST", "/api/auth/login", payload={"username": username, "password": password})
    assert status == 200 and body.get("success"), "登录失败 %s：%s" % (username, body.get("message"))
    return {"Authorization": "Bearer " + body["data"]["token"]}


def uid(username):
    return sql("SELECT id FROM sys_user WHERE username = ?", (username,))["id"]


def demo_fingerprint():
    return (os.path.getmtime(DEMO_DB), os.path.getsize(DEMO_DB))


def business_objects_of(row):
    """返回 (business_objects 中 AGG-PRESCRIPTION-001 项, 该项状态, 原始 refs)。"""
    objs = row.get("business_objects")
    if not isinstance(objs, list):
        return None, None, row.get("business_object_refs")
    for o in objs:
        if isinstance(o, dict) and o.get("aggregateId") == "AGG-PRESCRIPTION-001":
            return o, o.get("status"), row.get("business_object_refs")
    return None, None, row.get("business_object_refs")


def verify_prescription_status(page, label, rows):
    """逐条比对：business_objects 里处方聚合的 status == 库内 prescription.prescription_status。"""
    checked, bad, missing = 0, [], []
    for row in rows:
        obj, status, raw_refs = business_objects_of(row)
        if obj is None or not obj.get("businessId"):
            missing.append(row.get("id"))
            continue
        expect = sql("SELECT prescription_status FROM prescription WHERE id = ?", (obj["businessId"],))
        expect = expect["prescription_status"] if expect else None
        checked += 1
        if status != expect:
            bad.append((row.get("id"), obj.get("businessId"), status, expect))
    check("%s：每条记录的处方聚合 status 与库内 prescription_status 逐条一致（抽查 %d 条）" % (label, checked),
          checked > 0 and not bad and not missing,
          "不一致=%s 缺引用=%s" % (bad, missing))
    return checked


def main():
    print("批次 6 小修复自测（用例库：%s）" % DB)
    print("演示库：%s（只读；用例库为其副本）" % DEMO_DB)
    demo_before = demo_fingerprint()

    h_yaoshi, h_yishi, h_daozhen = login("yaoshi"), login("yishi"), login("daozhen")
    yaoshi_uid, yishi_uid = uid("yaoshi"), uid("yishi")
    print("登录成功：yaoshi(id=%s) / yishi(id=%s) / daozhen(id=%s)" % (yaoshi_uid, yishi_uid, uid("daozhen")))

    # ================================================================ ①
    section("① GET /api/users/enabled（启用用户）与 GET /api/users/options（角色选项）语义隔离")
    status, body = call("GET", "/api/users/enabled", h_yaoshi)
    data = body.get("data")
    print("  原始响应：HTTP %s %s" % (status, json.dumps(body, ensure_ascii=False)))
    expected_users = sql("SELECT id, username, real_name FROM sys_user WHERE status = 1 ORDER BY id", (), False)
    check("HTTP 200 + success", status == 200 and body.get("success") is True, status)
    check("data 为数组且与库内启用用户（status=1）逐一相等", data == expected_users,
          "API=%s / SQL=%s" % (data, expected_users))
    check("按 id 升序", [u.get("id") for u in (data or [])] == sorted(u.get("id") for u in (data or [])),
          [u.get("id") for u in (data or [])])
    check("元素形状固定 {id, username, real_name}（无多余字段）",
          all(set(u) == {"id", "username", "real_name"} for u in (data or [])),
          (data or [{}])[0])
    check("含 username / real_name（示例：yaoshi=赵中药师）",
          any(u["username"] == "yaoshi" and u["real_name"] == "赵中药师" for u in (data or [])))
    check("不含角色字段（code / name 角色名 / roles 均不得出现）",
          all("code" not in u and "roles" not in u for u in (data or [])))
    check("不含 password 字段", all("password" not in u for u in (data or [])))
    status, body = call("GET", "/api/users/enabled")
    check("未登录 → 401", status == 401, status)

    # 负例：把副本库里的 kufang 停用，验证「仅启用」过滤真实生效（仅作用于副本库）
    db_module.execute("UPDATE sys_user SET status = 0 WHERE username = 'kufang'")
    status, body = call("GET", "/api/users/enabled", h_yaoshi)
    names = [u["username"] for u in (body.get("data") or [])]
    check("停用 kufang(status=0) 后不再出现在 /enabled", "kufang" not in names and len(names) == 5, names)
    status, options_body = call("GET", "/api/users/options", h_yaoshi)
    check("/options 与 /enabled 互不干扰（/options 仍返回角色，非用户）",
          all("code" in r for r in (options_body.get("data") or []))
          and not any(r.get("username") for r in (options_body.get("data") or [])), options_body.get("data"))
    db_module.execute("UPDATE sys_user SET status = 1 WHERE username = 'kufang'")
    status, body = call("GET", "/api/users/enabled", h_yaoshi)
    check("恢复 kufang(status=1) 后重新出现（共 6 人）", len(body.get("data") or []) == 6)

    status, body = call("GET", "/api/users/options", h_yaoshi)
    expected_roles = sql("SELECT id, name, code FROM sys_role WHERE status = 1 ORDER BY id", (), False)
    print("  /options 原始响应：HTTP %s %s" % (status, json.dumps(body, ensure_ascii=False)[:300]))
    check("/options 行为不变：仍返回角色选项（与库内 sys_role status=1 一致）",
          status == 200 and body.get("data") == expected_roles,
          "API=%s / SQL=%s" % (body.get("data"), expected_roles))
    check("/options 元素含角色 code（语义未被改成用户）",
          all({"id", "name", "code"} == set(r) for r in (body.get("data") or [])))
    status, body = call("GET", "/api/users/options")
    check("/options 未登录 → 401（口径不变）", status == 401, status)

    # ================================================================ ②
    section("② 待办列表（yaoshi）：business_objects 处方聚合 status 与库内逐条一致")
    status, body = call("GET", "/api/workbench/todo?page=1&size=100", h_yaoshi)
    rows = body["data"]["list"]
    print("  todo total=%s，示例首条 business_objects=%s" %
          (body["data"]["total"], json.dumps(rows[0].get("business_objects"), ensure_ascii=False) if rows else None))
    check("todo 基线 total=4（演示库待办）", body["data"]["total"] == 4 == len(rows), (body["data"]["total"], len(rows)))
    check("每条记录都带 business_objects（数组）且保留 business_object_refs",
          all(isinstance(r.get("business_objects"), list) and r.get("business_object_refs") is not None for r in rows))
    check("business_objects 元素形状固定 {aggregateId,businessId,businessNo,status}",
          all(set(o) == {"aggregateId", "businessId", "businessNo", "status"}
              for r in rows for o in r["business_objects"]))
    verify_prescription_status("todo", "todo", rows)
    # 逐条打印（真实输出）
    for r in rows:
        obj, st, _ = business_objects_of(r)
        db_st = sql("SELECT prescription_status FROM prescription WHERE id = ?", (obj["businessId"],))["prescription_status"]
        print("    task#%-3s %-12s businessId=%-3s API status=%-14s 库内=%-14s %s"
              % (r["id"], r["business_key"], obj["businessId"], st, db_st, "OK" if st == db_st else "MISMATCH"))

    # 调剂聚合（回落关联）：CF000003 已发药 → record_status=ISSUED；CF000008（无调剂记录→null 需先确认）
    print("  todo 中 AGG-DISPENSE-001 项示例：")
    for r in rows:
        dis = [o for o in r["business_objects"] if o["aggregateId"] == "AGG-DISPENSE-001"]
        if dis:
            print("    task#%-3s %s → %s" % (r["id"], r["business_key"], json.dumps(dis[0], ensure_ascii=False)))
    disp_ok = True
    for r in rows:
        obj, _, _ = business_objects_of(r)
        dis = [o for o in r["business_objects"] if o["aggregateId"] == "AGG-DISPENSE-001"]
        db_rec = sql("SELECT id, dispense_no, record_status FROM dispense_record WHERE prescription_id = ? AND flag = 1",
                     (obj["businessId"],))
        want = db_rec["record_status"] if db_rec else None
        if dis and (dis[0]["status"] != want or (db_rec and dis[0]["businessId"] != db_rec["id"])):
            disp_ok = False
    check("todo：调剂聚合 status == dispense_record.record_status（无记录则 null，businessId 回落到调剂单 id）",
          disp_ok)

    # ================================================================ ③
    section("③ 我的申请（yishi，requested）：business_objects 处方聚合 status 与库内逐条一致")
    status, body = call("GET", "/api/workbench/requested?page=1&size=100", h_yishi)
    rows = body["data"]["list"]
    print("  requested total=%s，首条 business_objects=%s" %
          (body["data"]["total"], json.dumps(rows[0].get("business_objects"), ensure_ascii=False) if rows else None))
    check("requested 基线 total=12 且列表同长", body["data"]["total"] == 12 == len(rows),
          (body["data"]["total"], len(rows)))
    check("requested 仍带 current_activity_names / status_label / business_object_refs（既有字段未回归）",
          all(all(k in r for k in ("current_activity_names", "status_label", "business_object_refs")) for r in rows))
    verify_prescription_status("requested", "requested", rows)
    for r in rows:
        obj, st, _ = business_objects_of(r)
        db_st = sql("SELECT prescription_status FROM prescription WHERE id = ?", (obj["businessId"],))["prescription_status"]
        print("    inst#%-3s %-12s 处方状态 API=%-14s 库内=%-14s 实例状态=%-9s %s"
              % (r["id"], r["business_key"], st, db_st, r["status"], "OK" if st == db_st else "MISMATCH"))

    # ================================================================ ④
    section("④ 已办（yaoshi，done）：business_objects 处方聚合 status 与库内逐条一致")
    status, body = call("GET", "/api/workbench/done?page=1&size=100", h_yaoshi)
    rows = body["data"]["list"]
    print("  done total=%s，首条 business_objects=%s" %
          (body["data"]["total"], json.dumps(rows[0].get("business_objects"), ensure_ascii=False) if rows else None))
    check("done 基线 total=8 且列表同长", body["data"]["total"] == 8 == len(rows), (body["data"]["total"], len(rows)))
    check("done 每条记录都带 business_object_refs（新增列未破坏既有 SELECT）",
          all("business_object_refs" in r for r in rows))
    verify_prescription_status("done", "done", rows)
    for r in rows:
        obj, st, _ = business_objects_of(r)
        db_st = sql("SELECT prescription_status FROM prescription WHERE id = ?", (obj["businessId"],))["prescription_status"]
        print("    task#%-3s %-12s action=%-8s 处方状态 API=%-14s 库内=%-14s %s"
              % (r["id"], r["business_key"], r["action"], st, db_st, "OK" if st == db_st else "MISMATCH"))

    # ================================================================ ⑤
    section("⑤ 筛选参数回归：API total 与独立 SQL 计数相等（flowName/activityName/dateFrom/dateTo/status）")
    q = urllib.parse.quote
    task_date = sql("SELECT date(MAX(created_at)) d FROM flow_task WHERE status='TODO'")["d"]
    done_date = sql("SELECT date(MAX(done_at)) d FROM flow_task WHERE status IN ('DONE','CANCEL')")["d"]
    inst_date = sql("SELECT date(MAX(started_at)) d FROM flow_instance WHERE creator_id=?", (yishi_uid,))["d"]
    flow_name = sql("SELECT name FROM flow_definition ORDER BY id LIMIT 1")["name"]
    print("  样本值：flowName=%s / todo 任务日=%s / done 完成日=%s / 申请发起日=%s" % (flow_name, task_date, done_date, inst_date))

    # --- todo（yaoshi）---
    base_todo = ("t.status='TODO' AND (t.assignee_id=? OR t.role_ref IN "
                 "(SELECT r.code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id "
                 "WHERE ur.user_id=? AND r.status=1))")

    def todo_sql(extra="", params=()):
        return sql("SELECT COUNT(*) c FROM flow_task t JOIN flow_instance i ON i.id=t.instance_id "
                   "JOIN flow_definition d ON d.id=i.def_id WHERE " + base_todo + " " + extra,
                   (yaoshi_uid, yaoshi_uid) + tuple(params))["c"]

    cases_todo = [
        ("flowName", "&flowName=" + q(flow_name), "AND d.name LIKE ?", ("%" + flow_name + "%",)),
        ("activityName", "&activityName=" + q("中药师审核处方"), "AND t.activity_name LIKE ?", ("%中药师审核处方%",)),
        ("dateFrom", "&dateFrom=" + task_date, "AND date(t.created_at) >= date(?)", (task_date,)),
        ("dateTo", "&dateTo=" + task_date, "AND date(t.created_at) <= date(?)", (task_date,)),
        ("status", "&status=TODO", "AND t.status = ?", ("TODO",)),
        ("组合", "&flowName=" + q(flow_name) + "&activityName=" + q("中药师审核处方") + "&status=TODO"
                 + "&dateFrom=" + task_date + "&dateTo=" + task_date,
         "AND d.name LIKE ? AND t.activity_name LIKE ? AND t.status = ? AND date(t.created_at) >= date(?) "
         "AND date(t.created_at) <= date(?)",
         ("%" + flow_name + "%", "%中药师审核处方%", "TODO", task_date, task_date)),
    ]
    print("  -- todo（yaoshi）--")
    for label, query, extra, values in cases_todo:
        status, body = call("GET", "/api/workbench/todo?page=1&size=100" + query, h_yaoshi)
        expect = todo_sql(extra, values)
        check("todo %-13s total=%s == SQL %s" % (label, body["data"]["total"], expect),
              status == 200 and body["data"]["total"] == expect, (status, body["data"]["total"], expect))

    # --- done（yaoshi）---
    base_done = ("t.status IN ('DONE','CANCEL') AND (t.assignee_id=? OR t.role_ref IN "
                 "(SELECT r.code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id "
                 "WHERE ur.user_id=? AND r.status=1))")

    def done_sql(extra="", params=()):
        return sql("SELECT COUNT(*) c FROM flow_task t JOIN flow_instance i ON i.id=t.instance_id "
                   "JOIN flow_definition d ON d.id=i.def_id WHERE " + base_done + " " + extra,
                   (yaoshi_uid, yaoshi_uid) + tuple(params))["c"]

    cases_done = [
        ("flowName", "&flowName=" + q(flow_name), "AND d.name LIKE ?", ("%" + flow_name + "%",)),
        ("activityName", "&activityName=" + q("中药师审核处方"), "AND t.activity_name LIKE ?", ("%中药师审核处方%",)),
        ("dateFrom", "&dateFrom=" + done_date, "AND date(t.done_at) >= date(?)", (done_date,)),
        ("dateTo", "&dateTo=" + done_date, "AND date(t.done_at) <= date(?)", (done_date,)),
        ("status", "&status=APPROVE", "AND t.action = ?", ("APPROVE",)),
        ("组合", "&flowName=" + q(flow_name) + "&status=APPROVE&dateFrom=" + done_date + "&dateTo=" + done_date,
         "AND d.name LIKE ? AND t.action = ? AND date(t.done_at) >= date(?) AND date(t.done_at) <= date(?)",
         ("%" + flow_name + "%", "APPROVE", done_date, done_date)),
    ]
    print("  -- done（yaoshi）--")
    for label, query, extra, values in cases_done:
        status, body = call("GET", "/api/workbench/done?page=1&size=100" + query, h_yaoshi)
        expect = done_sql(extra, values)
        check("done %-13s total=%s == SQL %s" % (label, body["data"]["total"], expect),
              status == 200 and body["data"]["total"] == expect, (status, body["data"]["total"], expect))

    # --- requested（yishi）---
    def req_sql(extra="", params=()):
        return sql("SELECT COUNT(*) c FROM flow_instance i LEFT JOIN flow_definition d ON d.id=i.def_id "
                   "WHERE i.creator_id=? " + extra, (yishi_uid,) + tuple(params))["c"]

    cases_req = [
        ("flowName", "&flowName=" + q(flow_name), "AND d.name LIKE ?", ("%" + flow_name + "%",)),
        ("activityName", "&activityName=" + q("中药师审核处方"),
         "AND EXISTS (SELECT 1 FROM flow_task ft WHERE ft.instance_id = i.id AND ft.status='TODO' "
         "AND ft.activity_name LIKE ?)", ("%中药师审核处方%",)),
        ("dateFrom", "&dateFrom=" + inst_date, "AND date(i.started_at) >= date(?)", (inst_date,)),
        ("dateTo", "&dateTo=" + inst_date, "AND date(i.started_at) <= date(?)", (inst_date,)),
        ("status", "&status=RUNNING", "AND i.status = ?", ("RUNNING",)),
        ("组合", "&flowName=" + q(flow_name) + "&status=RUNNING&dateFrom=" + inst_date + "&dateTo=" + inst_date,
         "AND d.name LIKE ? AND i.status = ? AND date(i.started_at) >= date(?) AND date(i.started_at) <= date(?)",
         ("%" + flow_name + "%", "RUNNING", inst_date, inst_date)),
    ]
    print("  -- requested（yishi）--")
    for label, query, extra, values in cases_req:
        status, body = call("GET", "/api/workbench/requested?page=1&size=100" + query, h_yishi)
        expect = req_sql(extra, values)
        check("requested %-10s total=%s == SQL %s" % (label, body["data"]["total"], expect),
              status == 200 and body["data"]["total"] == expect, (status, body["data"]["total"], expect))

    # 分页自洽 + 参数校验口径未回归
    status, body = call("GET", "/api/workbench/todo?page=2&size=2", h_yaoshi)
    check("分页自洽：page=2&size=2 → total=4 且 list 长度 2",
          body["data"]["total"] == 4 and len(body["data"]["list"]) == 2,
          (body["data"]["total"], len(body["data"]["list"])))
    status, body = call("GET", "/api/workbench/todo?page=1&size=101", h_yaoshi)
    check("size>100 → 400（参数校验未回归）", status == 400, status)
    status, body = call("GET", "/api/workbench/todo?page=1&size=10", headers=None)
    check("todo 未登录 → 401", status == 401, status)

    # ================================================================ ⑥
    section("⑥ 演示库未被写入（血债校验）")
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
        check("演示库基线：%-24s = %s" % (key, value), baseline[key] == value, baseline[key])

    print("\n" + "=" * 110)
    print("汇总：通过 %d / 失败 %d / 合计 %d（用例库 %s）" % (len(OK), len(NG), len(OK) + len(NG), DB))
    if NG:
        print("失败项：")
        for name in NG:
            print("   - %s" % name)
    else:
        print("全部断言通过。")
    print("=" * 110)
    return 1 if NG else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\n[FATAL] 自测脚本异常中断（上方为真实堆栈）")
        sys.exit(2)
