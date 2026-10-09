# -*- coding: utf-8 -*-
"""批次 6（工作台补齐）开工前侦察：把「静态读代码发现」升级为「行为实测证据」。

在**演示库副本**上真实跑一遍审批，观测：
  ① 工作台三页在现有数据下的真实返回（待办/已办/我的申请）
  ② §6.4 第 3 步「流程状态 → 业务对象状态」回写**是否发生**（审批通过后处方状态变没变）
  ③ 撤回 / 转办 / 催办 三个动作在当前接口层**是否可用**（存在性实测，不猜）
  ④ 流程实例与业务状态的一致性基线（审批前后对照）

用法：code-app/backend/.venv/Scripts/python.exe tools/recon_batch6.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
DEMO = os.path.join(BACKEND, "data", "app.db")
COPY = os.path.join(BACKEND, "data", "b6_base.db")
PORT = 5080
BASE = "http://127.0.0.1:%d" % PORT


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw or "{}")
        except ValueError:
            return exc.code, {"_raw": raw[:120]}


def db_state(db, rx_no):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        p = conn.execute("SELECT id, prescription_status, prescription_no FROM prescription WHERE prescription_no = ?",
                         (rx_no,)).fetchone()
        inst = conn.execute("SELECT id, status, current_activity_ids FROM flow_instance WHERE business_key = ?",
                            ("处方" + rx_no,)).fetchone()
        tasks = [dict(r) for r in conn.execute(
            "SELECT id, activity_id, activity_name, role_ref, assignee_id, status, action FROM flow_task WHERE instance_id = ?",
            (inst["id"] if inst else -1,))]
        disp = conn.execute("SELECT COUNT(*) FROM dispense_record WHERE prescription_id = ?", (p["id"],)).fetchone()[0] \
            if p else None
        return {"prescription": dict(p) if p else None, "instance": dict(inst) if inst else None,
                "tasks": tasks, "dispense_rows": disp}
    finally:
        conn.close()


def main():
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    shutil.copyfile(DEMO, COPY)

    # ！硬要求：必须在 import app 之前把库指到副本，否则服务器连演示库、实测会写进演示库。
    os.environ["APP_DB_PATH"] = COPY
    assert os.path.basename(os.environ["APP_DB_PATH"]) != "app.db", "拒绝以演示库作为实测库"
    from app import app as flask_app
    # 硬断言（不给"跳过"的机会）：配置解析出的库、db 模块实际使用的库，都必须等于副本
    from config import settings as app_settings
    import db as db_module
    resolved, inuse = os.path.abspath(app_settings.resolve_db_path()), os.path.abspath(db_module._db_path)
    print("实测库 =", COPY)
    print("配置解析库 =", resolved, "｜db 实际使用库 =", inuse)
    assert resolved == os.path.abspath(COPY), "配置解析出的库不是副本：拒绝继续（防止写进演示库）"
    assert inuse == os.path.abspath(COPY), "db 模块使用的库不是副本：拒绝继续（防止写进演示库）"
    assert os.path.basename(inuse) != "app.db", "目标是演示库：拒绝继续"
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("=" * 104)
    print("① 工作台三页在现有数据下的真实返回")
    print("=" * 104)
    tokens = {}
    for u, pwd in (("yaoshi", "123456"), ("yishi", "123456"), ("admin", "admin123")):
        st, b = call("POST", "/api/auth/login", body={"username": u, "password": pwd})
        tokens[u] = b.get("data", {}).get("token")
        print("   %-8s 登录 %s" % (u, st))
    for u in ("yaoshi", "yishi"):
        for page in ("todo", "done", "requested"):
            st, b = call("GET", "/api/workbench/%s?page=1&size=10" % page, token=tokens[u])
            d = b.get("data") or {}
            print("   %-8s /%-9s HTTP %s  total=%-4s 首行=%s" % (
                u, page, st, d.get("total"),
                json.dumps(d["list"][0], ensure_ascii=False)[:90] if d.get("list") else "无"))

    print("\n" + "=" * 104)
    print("② 撤回 / 转办 / 催办 当前接口层是否可用（存在性实测）")
    print("=" * 104)
    # 说明：未知 POST /api 路径会被 GET-only 的 SPA 兜底路由 `/<path:path>` 捕获 → 405 → 被
    # @app.errorhandler(Exception) 包成 500「服务器内部错误」。因此**不能只看状态码**，
    # 必须同时用 url_map 判定路由是否真实存在（这才是"接口是否已暴露"的硬证据）。
    rules = {str(r.rule): sorted(r.methods - {"HEAD", "OPTIONS"}) for r in flask_app.url_map.iter_rules()}
    print("   路由表里含 withdraw/transfer/urge 的规则:",
          {k: v for k, v in rules.items() if any(x in k for x in ("withdraw", "transfer", "urge"))} or "无")
    for label, method, path, body in (
            ("撤回 withdraw", "POST", "/api/workbench/todo/1/withdraw", {"reason": "实测"}),
            ("撤回(flow侧)", "POST", "/api/flow/instances/1/withdraw", {"reason": "实测"}),
            ("转办 transfer", "POST", "/api/workbench/todo/1/transfer", {"assignee_id": 5}),
            ("转办(flow侧)", "POST", "/api/flow/tasks/1/transfer", {"assignee_id": 5}),
            ("催办 urge", "POST", "/api/workbench/todo/1/urge", {}),
            ("催办(flow侧)", "POST", "/api/flow/tasks/1/urge", {})):
        st, b = call(method, path, token=tokens["admin"], body=body)
        exists = "--" if path.split("/api/")[-1] in rules else path in rules
        declared = path in rules
        print("   %-16s %-34s → HTTP %-4s 路由已声明=%-5s %s" % (
            label, path, st, declared, json.dumps(b, ensure_ascii=False)[:52]))

    print("\n" + "=" * 104)
    print("③ 【核心证据】审批链是否回写业务状态（§6.4 第 3 步）——用 CF000001 实测")
    print("=" * 104)
    print("   审批前：", json.dumps(db_state(COPY, "CF000001"), ensure_ascii=False))
    st, b = call("GET", "/api/workbench/todo?page=1&size=10", token=tokens["yaoshi"])
    target = next((t for t in (b.get("data") or {}).get("list", []) if t.get("business_key") == "处方CF000001"), None)
    print("   中药师待办里找到 CF000001 任务:", bool(target), "task_id=%s" % (target or {}).get("id"))
    if target:
        st, b = call("POST", "/api/workbench/todo/%d/approve" % target["id"], token=tokens["yaoshi"],
                     body={"comment": "侦察实测：同意调剂"})
        print("   审批调用 → HTTP %s %s" % (st, json.dumps(b, ensure_ascii=False)[:80]))
        print("   审批后：", json.dumps(db_state(COPY, "CF000001"), ensure_ascii=False))
        after = db_state(COPY, "CF000001")
        inst_ok = after["instance"] and after["instance"]["status"] in ("APPROVED", "RUNNING")
        rx = after["prescription"]["prescription_status"]
        print("\n   >>> 结论：流程实例状态 = %s ；处方业务状态 = %s" % (after["instance"]["status"], rx))
        if after["instance"]["status"] == "APPROVED" and rx == "PENDING_REVIEW":
            print("   >>> 【缺口实锤】流程已 APPROVED，处方仍是 PENDING_REVIEW —— §6.4 第 3 步未实现")
        elif after["instance"]["status"] != inst_ok:
            print("   >>> 其他情况，需人工判读")

    print("\n" + "=" * 104)
    print("④ 全库一致性基线（业务状态 vs 流程状态）")
    print("=" * 104)
    conn = sqlite3.connect(COPY)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.prescription_no, p.prescription_status, i.status AS inst_status
        FROM prescription p LEFT JOIN flow_instance i ON i.business_key = '处方' || p.prescription_no
        ORDER BY p.id""").fetchall()
    mismatch = [(r["prescription_no"], r["prescription_status"], r["inst_status"]) for r in rows
                if r["inst_status"] and not (
                    (r["inst_status"] == "APPROVED" and r["prescription_status"] in ("APPROVED", "DISPENSING", "ISSUED", "VOIDED"))
                    or (r["inst_status"] == "RUNNING" and r["prescription_status"] in ("PENDING_REVIEW", "APPROVED")))]
    for r in rows:
        print("   %-12s 业务=%-14s 流程=%s" % (r["prescription_no"], r["prescription_status"], r["inst_status"]))
    print("   不一致条数（按「流程 RUNNING→待审核/审核通过；APPROVED→通过及之后」口径）:", len(mismatch), mismatch)
    conn.close()

    print("\n" + "=" * 104)
    print("⑤ M6 真实分支实测：作废 → Q03「处方已作废」→ QE02 终止（模型要求实例终止，现状用 reject 表达）")
    print("=" * 104)
    cand = None
    conn = sqlite3.connect(COPY)
    conn.row_factory = sqlite3.Row
    for r in conn.execute("""SELECT p.id, p.prescription_no, i.id AS inst_id, i.status AS inst_status
                             FROM prescription p JOIN flow_instance i ON i.business_key = '处方' || p.prescription_no
                             WHERE i.status = 'RUNNING' ORDER BY p.id"""):
        cand = dict(r)
        break
    conn.close()
    print("   选取在办样本:", cand)
    if cand:
        st, b = call("POST", "/api/prescription/%d/cancel" % cand["id"], token=tokens["yishi"],
                     body={"cancel_reason": "侦察实测：作废终止分支"})
        print("   作废调用 → HTTP %s %s" % (st, json.dumps(b, ensure_ascii=False)[:110]))
        st2, b2 = call("GET", "/api/prescription/%d" % cand["id"], token=tokens["yishi"])
        d2 = b2.get("data") or {}
        print("   作废后处方状态 =", d2.get("prescriptionStatus") or d2.get("prescription_status"))
        after = db_state(COPY, cand["prescription_no"])
        print("   作废后实例:", after["instance"])
        print("   作废后任务:", [(t["id"], t["activity_id"], t["activity_name"], t["role_ref"], t["status"], t["action"])
                            for t in after["tasks"]])
        left_todo = [t for t in after["tasks"] if t["status"] == "TODO"]
        print("\n   >>> 模型要求：作废 → 终止（QE02，实例结束、无新待办）")
        print("   >>> 实测：实例状态 = %s ；残留 TODO 任务 = %d 个 %s" % (
            after["instance"]["status"], len(left_todo),
            [(t["activity_name"], t["role_ref"]) for t in left_todo]))
        if after["instance"]["status"] == "RUNNING" and left_todo:
            print("   >>> 【缺口】作废后实例仍在办、且产生了新的待办 → 未走 QE02 终止分支（现实现用 reject 代替）")
        elif after["instance"]["status"] in ("REJECTED", "CANCELED"):
            print("   >>> 实例已结束（状态 %s），但注意：模型要求的是 QE02「终止」而非 REJECTED" % after["instance"]["status"])

    srv.shutdown()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    print("\n   演示库副本已删除:", not os.path.exists(COPY))


if __name__ == "__main__":
    main()
