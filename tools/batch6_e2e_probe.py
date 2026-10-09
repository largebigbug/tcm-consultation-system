# -*- coding: utf-8 -*-
"""批次 6 端到端黑盒探针（真实服务器 + SPA + 演示库**副本**，跑完删副本）。

覆盖：首页与构建产物标识、未登录 401、六账号菜单回归、审批链端到端（通过/驳回）、
越权、作废终止、转办/催办、改密、AI 配置只读、演示库未污染。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch6_e2e_probe.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # tools/ 的上一层 = 项目根
BACKEND = os.path.join(PROJECT, "code-app", "backend")
DIST = os.path.join(PROJECT, "code-app", "frontend", "dist")
DEMO = os.path.join(BACKEND, "data", "app.db")
COPY = os.path.join(BACKEND, "data", "b6_e2e.db")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ["APP_DB_PATH"] = COPY
assert os.path.basename(COPY) != "app.db", "拒绝以演示库为探针库"

PORT = 5085
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-66s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:100]))
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
            p = resp.read()
            return resp.status, (p if raw else json.loads(p.decode() or "{}"))
    except urllib.error.HTTPError as exc:
        p = exc.read()
        if raw:
            return exc.code, p
        try:
            return exc.code, json.loads(p.decode() or "{}")
        except ValueError:
            return exc.code, {"_raw": p.decode("utf-8", "replace")[:100]}


def one(sql, params=()):
    conn = sqlite3.connect(COPY)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params)]
        return rows[0] if rows else None
    finally:
        conn.close()


def fingerprint(db):
    parts = []
    for tbl, cols in (("prescription", "id, prescription_no, prescription_status, reviewer_id, review_time"),
                      ("dispense_record", "id, dispense_no, prescription_id, record_status"),
                      ("flow_instance", "id, business_key, status"), ("flow_task", "id, instance_id, status, action"),
                      ("flow_history", "id, instance_id, action"), ("audit_logs", "id, user_id, action"),
                      ("herb", "id, herb_code, stock_quantity, herb_status"), ("visit", "id, visit_no, visit_status")):
        rows = [tuple(r) for r in sqlite3.connect(db).execute("SELECT %s FROM %s ORDER BY id" % (cols, tbl))]
        parts.append("%s=%d:%s" % (tbl, len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:10]))
    return " | ".join(parts)


def main():
    if not os.path.exists(DEMO):
        print("演示库不存在：%s" % DEMO)
        return 1
    subprocess.run([sys.executable, os.path.join(PROJECT, "tools", "kill_app_servers.py"), "--port", str(PORT)],
                   capture_output=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    shutil.copyfile(DEMO, COPY)
    fp_before = fingerprint(DEMO)

    from app import app as flask_app
    from config import settings as app_settings
    import db as db_module
    assert os.path.abspath(app_settings.resolve_db_path()) == os.path.abspath(COPY), "配置库不是副本"
    assert os.path.abspath(db_module._db_path) == os.path.abspath(COPY), "db 库不是副本"
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    section("① 首页与前端构建产物（批次 6 新特性标识）")
    st, raw = call("GET", "/", raw=True)
    html = raw.decode("utf-8", "replace") if st == 200 else ""
    check("首页 200 且为 SPA HTML", st == 200 and 'id="root"' in html, "HTTP %s" % st)
    assets = re.findall(r"/assets/([A-Za-z0-9._-]+\.(?:js|css))", html)
    bundle = ""
    ad = os.path.join(DIST, "assets")
    if os.path.isdir(ad):
        for n in sorted(os.listdir(ad)):
            if n.endswith((".js", ".css")):
                bundle += io.open(os.path.join(ad, n), encoding="utf-8", errors="replace").read()
    if check("读取到构建产物内容", bool(bundle), "%d 字符 / %s" % (len(bundle), assets)):
        for token in ("chat-resizer", "cp_chat_width", "中医问诊系统", "修改密码", "配置大模型",
                      "转办", "催办", "prescriptionId=", "recordId=", "/users/enabled"):
            check("产物含 %s" % token, token in bundle)
        check("底座文案已清除（客户管理技术底座）", "客户管理技术底座" not in bundle and "客户管理技术底座" not in html)

    section("② 未登录访问（401）")
    for m, p in (("GET", "/api/workbench/todo"), ("POST", "/api/auth/password"), ("GET", "/api/ai/config"),
                 ("GET", "/api/users/enabled")):
        st, b = call(m, p, body={} if m == "POST" else None)
        check("未登录 %s %s → 401" % (m, p), st == 401, st)

    section("③ 六账号登录 + 菜单回归")
    users = {"admin": "admin123", "keshi": "123456", "daozhen": "123456", "yishi": "123456",
             "yaoshi": "123456", "kufang": "123456"}
    tokens, menus = {}, {}
    for u, pwd in users.items():
        st, b = call("POST", "/api/auth/login", body={"username": u, "password": pwd})
        tokens[u] = (b.get("data") or {}).get("token") if st == 200 else None
        menus[u] = {m["name"] for m in ((b.get("data") or {}).get("menus") or [])} if st == 200 else set()
        check("%s 登录" % u, bool(tokens[u]), st)
    check("admin 菜单含批次 1～3 全部一级菜单",
          {"门诊管理", "药房管理", "库存管理", "随访管理", "统计报表", "基础数据"} <= menus.get("admin", set()),
          sorted(menus.get("admin", [])))
    check("kufang 仅见库存/基础（不回归）", "库存管理" in menus.get("kufang", set()), sorted(menus.get("kufang", [])))

    section("④ 审批链端到端（副本：通过 / 驳回）")
    todo = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    t = next((x for x in todo if x.get("business_key") == "处方CF000001"), None)
    if check("中药师待办含 CF000001", bool(t), [x.get("business_key") for x in todo][:5]):
        st, b = call("POST", "/api/workbench/todo/%d/approve" % t["id"], token=tokens["yaoshi"],
                     body={"comment": "端到端：同意调剂"})
        rx = one("SELECT id, prescription_status, review_time FROM prescription WHERE prescription_no = 'CF000001'")
        disp = one("SELECT COUNT(*) c FROM dispense_record WHERE prescription_id = ?", (rx["id"],))["c"]
        inst = one("SELECT status FROM flow_instance WHERE business_key = '处方CF000001'")
        check("通过后：处方 APPROVED + review_time + 调剂单 1 条 + 实例 APPROVED",
              rx["prescription_status"] == "APPROVED" and bool(rx["review_time"]) and disp == 1 and inst["status"] == "APPROVED",
              (rx["prescription_status"], disp, inst["status"]))
    t2 = next((x for x in todo if x.get("business_key") == "处方CF000002"), None)
    if t2:
        st, b = call("POST", "/api/workbench/todo/%d/reject" % t2["id"], token=tokens["yaoshi"],
                     body={"comment": "端到端：驳回"})
        rx2 = one("SELECT prescription_status, reject_reason FROM prescription WHERE prescription_no = 'CF000002'")
        check("驳回后：处方 REJECTED + 驳回原因",
              rx2["prescription_status"] == "REJECTED" and rx2["reject_reason"] == "端到端：驳回", rx2)

    section("⑤ 越权与作废终止")
    td = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    t3 = next((x for x in td if x.get("business_key") == "处方CF000012"), None)
    if t3:
        st, b = call("POST", "/api/workbench/todo/%d/approve" % t3["id"], token=tokens["daozhen"], body={"comment": "越权"})
        check("无 prescription:review 账号审批被拒", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:40]))
    running = one("""SELECT p.id, p.prescription_no, i.id AS inst_id FROM prescription p
                     JOIN flow_instance i ON i.business_key = '处方' || p.prescription_no
                     WHERE i.status = 'RUNNING' AND p.prescription_status = 'PENDING_REVIEW' LIMIT 1""")
    if running:
        st, b = call("POST", "/api/prescription/%d/cancel" % running["id"], token=tokens["yishi"],
                     body={"cancel_reason": "端到端：作废终止"})
        inst = one("SELECT status FROM flow_instance WHERE id = ?", (running["inst_id"],))
        left = one("SELECT COUNT(*) c FROM flow_task WHERE instance_id = ? AND status = 'TODO'", (running["inst_id"],))["c"]
        check("作废在办：实例 TERMINATED + 无残留待办", inst["status"] == "TERMINATED" and left == 0,
              (inst["status"], left))

    section("⑥ 转办 / 催办 / 改密 / AI 配置")
    opts = (call("GET", "/api/users/enabled", token=tokens["yaoshi"])[1].get("data") or [])
    ok_shape = bool(opts) and all(any(k in o for k in ("username", "real_name")) for o in opts)
    check("GET /api/users/enabled 返回启用用户（含 username/real_name）", ok_shape, (opts or [{}])[0])
    td = (call("GET", "/api/workbench/todo?page=1&size=50", token=tokens["yaoshi"])[1].get("data") or {}).get("list") or []
    if td and ok_shape:
        task = td[0]
        cand = [o for o in opts if str(o["id"]) != str(task.get("assignee_id"))]
        st, b = call("POST", "/api/workbench/todo/%d/urge" % task["id"], token=tokens["yaoshi"], body={})
        check("催办 → 200", st == 200, (st, str(b.get("message"))[:30]))
        if cand:
            st, b = call("POST", "/api/workbench/todo/%d/transfer" % task["id"], token=tokens["yaoshi"],
                         body={"assigneeId": cand[0]["id"]})
            row = one("SELECT assignee_id FROM flow_task WHERE id = ?", (task["id"],))
            check("转办 → 办理人改为所选用户", st == 200 and str(row["assignee_id"]) == str(cand[0]["id"]),
                  (st, row["assignee_id"], cand[0]["id"]))
    st, b = call("POST", "/api/auth/password", token=tokens["kufang"],
                 body={"oldPassword": "123456", "newPassword": "kufang888"})
    st_new, _ = call("POST", "/api/auth/login", body={"username": "kufang", "password": "kufang888"})
    check("改密 → 新密码可登录", st == 200 and st_new == 200, (st, st_new))
    st, b = call("GET", "/api/ai/config", token=tokens["admin"])
    check("AI 配置（管理员）200 且不含密钥", st == 200 and "sk-" not in json.dumps(b, ensure_ascii=False),
          sorted((b.get("data") or {})))
    st, b = call("GET", "/api/ai/config", token=tokens["daozhen"])
    check("AI 配置（非管理员）被拒", st >= 400 or b.get("success") is False, (st, str(b.get("message"))[:30]))

    srv.shutdown()
    section("⑦ 演示库未污染 + 副本清理")
    check("演示库八表指纹前后一致", fingerprint(DEMO) == fp_before, fp_before[:90])
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    check("副本已删除", not os.path.exists(COPY))

    print("\n" + "=" * 110)
    print("批次 6 端到端探针：通过 %d / 失败 %d" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for n in NG:
            print("   - %s" % n)
    print("=" * 110)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
