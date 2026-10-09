# -*- coding: utf-8 -*-
"""批次 6 演示库**只读**体检：不起写操作、**不登录**（登录会写 audit_logs），
只验：库内基线/指纹/自洽性 + SPA 与产物标识 + 未登录 401 + 无残留副本。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch6_demo_verify.py
"""
import hashlib
import io
from datetime import datetime
import json
import os
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BACKEND))
DEMO = os.path.join(BACKEND, "data", "app.db")
DIST = os.path.join(PROJECT, "code-app", "frontend", "dist")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ["APP_DB_PATH"] = DEMO          # 只读使用：全程不发写请求、不登录
PORT = 5087
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []

# 业务/流程表是硬不变量；audit_logs 会因其它批次的「演示库体检」登录而增长（仅 LOGIN），
# 故只要求「不减少 + 新增行必须全是 LOGIN」。
BASELINE = {"task_TODO": 4, "task_DONE": 8, "inst_RUNNING": 4, "inst_APPROVED": 8,
            "history": 28, "audit": 17, "dispense": 8, "prescription": 12}
INVARIANT = ("task_TODO", "task_DONE", "inst_RUNNING", "inst_APPROVED", "history", "dispense", "prescription")
RX_STATUS = {"DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "DISPENSING", "ISSUED", "VOIDED"}


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-62s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:90]))
    return bool(cond)


def connect():
    conn = sqlite3.connect(DEMO)
    conn.row_factory = sqlite3.Row
    return conn


def scal(c, sql):
    return list(c.execute(sql))[0][0]


def main():
    if not os.path.exists(DEMO):
        print("演示库不存在：%s" % DEMO)
        return 1
    print("=" * 110)
    print("批次 6 演示库只读体检（不登录、不发写请求）")
    print("=" * 110)
    c = connect()

    print("\n① 演示库基线（批次 6 口径）")
    got = {"task_TODO": scal(c, "SELECT COUNT(*) FROM flow_task WHERE status='TODO'"),
           "task_DONE": scal(c, "SELECT COUNT(*) FROM flow_task WHERE status='DONE'"),
           "inst_RUNNING": scal(c, "SELECT COUNT(*) FROM flow_instance WHERE status='RUNNING'"),
           "inst_APPROVED": scal(c, "SELECT COUNT(*) FROM flow_instance WHERE status='APPROVED'"),
           "history": scal(c, "SELECT COUNT(*) FROM flow_history"),
           "audit": scal(c, "SELECT COUNT(*) FROM audit_logs"),
           "dispense": scal(c, "SELECT COUNT(*) FROM dispense_record"),
           "prescription": scal(c, "SELECT COUNT(*) FROM prescription")}
    for k in INVARIANT:
        check("基线 %s = %s" % (k, BASELINE[k]), got[k] == BASELINE[k], "实测 %s" % got[k])
    check("基线 audit >= %d（只增不减）" % BASELINE["audit"], got["audit"] >= BASELINE["audit"], "实测 %s" % got["audit"])

    print("\n② 状态取值域与流程自洽")
    insts = {r[0] for r in c.execute("SELECT DISTINCT status FROM flow_instance")}
    check("flow_instance.status ⊆ {RUNNING,APPROVED,REJECTED,TERMINATED}",
          insts <= {"RUNNING", "APPROVED", "REJECTED", "TERMINATED"}, insts)
    rxs = {r[0] for r in c.execute("SELECT DISTINCT prescription_status FROM prescription")}
    check("prescription_status ⊆ M1 字典 7 值", rxs <= RX_STATUS, rxs)
    bad = scal(c, """SELECT COUNT(*) FROM flow_instance i WHERE i.status='RUNNING'
                     AND NOT EXISTS (SELECT 1 FROM flow_task t WHERE t.instance_id = i.id AND t.status='TODO')""")
    check("每个 RUNNING 实例都有 TODO 任务", bad == 0, "异常 %d 个" % bad)
    orphan = scal(c, """SELECT COUNT(*) FROM flow_task t WHERE t.status='DONE'
                        AND (t.action IS NULL OR t.action='')""")
    check("DONE 任务都有处理动作 action", orphan == 0, "异常 %d 个" % orphan)

    print("\n③ 关键表指纹（未污染证据）")
    for tbl, cols in (("herb", "id, herb_code, stock_quantity, low_stock_threshold, herb_status, flag"),
                      ("visit", "id, visit_no, register_time, visit_status, flag"),
                      ("flow_task", "id, instance_id, activity_id, status, action"),
                      ("flow_instance", "id, business_key, status"),
                      ("prescription", "id, prescription_no, prescription_status, reviewer_id, review_time")):
        rows = [tuple(r) for r in c.execute("SELECT %s FROM %s ORDER BY id" % (cols, tbl))]
        print("   %-14s %d:%s" % (tbl, len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:16]))

    print("\n④ 只读校验：库以只读方式可打开、今日零写入")
    ro = sqlite3.connect("file:%s?mode=ro" % DEMO.replace("\\", "/"), uri=True)
    try:
        check("演示库可以只读方式打开", list(ro.execute("SELECT COUNT(*) FROM sqlite_master"))[0][0] > 0)
    finally:
        ro.close()
    # 日期必须动态取（写死日期会在跨天后变成假通过/假失败——批次 3 的跨月缺陷同源）
    today = datetime.now().strftime("%Y-%m-%d")
    today_audit = scal(c, "SELECT COUNT(*) FROM audit_logs WHERE created_at LIKE '%s%%'" % today)
    # 允许的动作：LOGIN（体检登录）+ AI_*（真实用户对话，服务照设计写审计）+ CHANGE_PASSWORD（改密自测）。
    # 其它动作说明有非预期写库。
    ALLOWED = "('LOGIN', 'AI_CHAT', 'AI_TOOL_CALL', 'AI_SQL_QUERY', 'CHANGE_PASSWORD')"
    today_unexpected = scal(c, "SELECT COUNT(*) FROM audit_logs WHERE created_at LIKE '%s%%' AND action NOT IN %s" % (today, ALLOWED))
    today_hist = scal(c, "SELECT COUNT(*) FROM flow_history WHERE created_at LIKE '%s%%'" % today)
    # 其它批次的「演示库体检」会登录（写 LOGIN 审计行），故只硬断言「无业务类审计」；
    # 本装置自身不登录，单独跑时应为 0。
    check("今日 audit_logs 无「非预期动作」写入（允许 LOGIN / AI_* / CHANGE_PASSWORD）", today_unexpected == 0,
          "今日 %d 条（其中非预期 %d）" % (today_audit, today_unexpected))
    check("今日 flow_history 写入 = 0", today_hist == 0, today_hist)
    c.close()

    print("\n⑤ SPA 与批次 6 构建产物")
    from app import app as flask_app
    from config import settings as app_settings
    import db as db_module
    assert os.path.abspath(app_settings.resolve_db_path()) == os.path.abspath(DEMO), "体检必须针对演示库"
    assert os.path.abspath(db_module._db_path) == os.path.abspath(DEMO), "体检必须针对演示库"
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    st, raw = 0, b""
    try:
        with urllib.request.urlopen(BASE + "/", timeout=20) as resp:
            st, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        st, raw = exc.code, exc.read()
    html = raw.decode("utf-8", "replace")
    check("首页 200 且为 SPA", st == 200 and 'id="root"' in html, st)
    bundle = ""
    ad = os.path.join(DIST, "assets")
    if os.path.isdir(ad):
        for n in sorted(os.listdir(ad)):
            if n.endswith((".js", ".css")):
                bundle += io.open(os.path.join(ad, n), encoding="utf-8", errors="replace").read()
    for token in ("chat-resizer", "cp_chat_width", "中医问诊系统", "修改密码", "配置大模型", "转办", "催办"):
        check("产物含 %s" % token, token in bundle)
    check("产物无「客户管理技术底座」残留", "客户管理技术底座" not in bundle and "客户管理技术底座" not in html)

    print("\n⑥ 未登录访问（401，不写库）")
    for m, p in (("GET", "/api/workbench/todo"), ("GET", "/api/ai/config"), ("GET", "/api/users/enabled")):
        try:
            with urllib.request.urlopen(BASE + p, timeout=20) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        check("未登录 %s → 401" % p, code == 401, code)
    srv.shutdown()

    print("\n⑦ 收尾")
    c2 = connect()
    after = {"task_TODO": scal(c2, "SELECT COUNT(*) FROM flow_task WHERE status='TODO'"),
             "audit": scal(c2, "SELECT COUNT(*) FROM audit_logs"),
             "history": scal(c2, "SELECT COUNT(*) FROM flow_history"),
             "dispense": scal(c2, "SELECT COUNT(*) FROM dispense_record")}
    c2.close()
    check("体检前后业务/流程表基线不变", all(after[k] == BASELINE[k] for k in after if k != "audit"), after)
    check("体检前后 audit 只增不减", after["audit"] >= BASELINE["audit"], after["audit"])
    leftovers = [f for f in os.listdir(os.path.join(BACKEND, "data")) if f.startswith(("b6_", "check_batch6"))]
    check("无残留用例/副本库", not leftovers, leftovers)

    print("\n" + "=" * 110)
    print("批次 6 演示库只读体检：通过 %d / 失败 %d" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for n in NG:
            print("   - %s" % n)
    print("=" * 110)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
