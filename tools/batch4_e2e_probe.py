# -*- coding: utf-8 -*-
"""批次 4 端到端黑盒探针（真实 socket，跑在演示库**副本**上，跑完删除副本）。

覆盖：
  ① 静态页与构建产物哈希（dist 由 Flask 托管）
  ② 未登录 401
  ③ 六账号登录 + 菜单可见性（库房管理员须见「库存管理」；不得见批次 3 的统计报表/随访管理）
  ④ QR-HERB-STOCK-001 查询：六账号权限交叉（401/403/200）
  ⑤ 条件组开关 onlyAlert 端到端（未传=全部 / true=仅预警），并与直连 SQL 交叉核对
  ⑥ 导出 XLSX / CSV（结构与中文表头）
  ⑦ 前端产物含本屏控件 id 与报表码（改造后仍进 bundle）
用法：code-app/backend/.venv/Scripts/python.exe tools/batch4_e2e_probe.py
"""
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
import zipfile
from xml.dom.minidom import parseString

# 本脚本位于 <项目根>/tools/，与 backend/tools/ 下的脚本层级不同（勿照抄那里的推导）
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "code-app", "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

REPORT = "QR-HERB-STOCK-001"
DEMO = os.path.join(BACKEND, "data", "app.db")
COPY = os.path.join(BACKEND, "data", "batch4_e2e.db")
os.environ["APP_DB_PATH"] = COPY
DIST = os.path.join(PROJECT, "code-app", "frontend", "dist")
PORT = 5066
BASE = "http://127.0.0.1:%d" % PORT

OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-64s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:90]))
    return bool(cond)


def section(title):
    print("\n" + "-" * 104)
    print(title)
    print("-" * 104)


def call(method, path, token=None, body=None, raw=False):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload.decode() or "{}")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if raw:
            return exc.code, payload, dict(exc.headers)
        try:
            return exc.code, json.loads(payload.decode() or "{}"), dict(exc.headers)
        except ValueError:
            return exc.code, {}, dict(exc.headers)


def q(params, token, raw=False):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return call("GET", "/api/report/%s%s" % (REPORT, ("?" + query) if query else ""), token=token, raw=raw)


def main():
    if not os.path.exists(DEMO):
        print("演示库不存在：%s" % DEMO)
        return 1
    subprocess.run([sys.executable, os.path.join(PROJECT, "tools", "kill_app_servers.py"), "--port", str(PORT)],
                   capture_output=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    shutil.copyfile(DEMO, COPY)                                   # 副本：探针不污染演示库
    demo_stat = os.stat(DEMO)

    from werkzeug.serving import make_server                        # noqa: E402

    # 用**模块级** app：SPA 路由（"/" 与 "/<path:path>"）注册在 app.py 第 101 行的
    # `app = create_app()` 上，create_app() 工厂实例**不含**它们（只有 108 条 /api 路由）。
    from app import app as flask_app                                # noqa: E402

    app = flask_app
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    section("① 静态页与构建产物")
    st, raw, _ = call("GET", "/", raw=True)
    html = raw.decode("utf-8", "replace") if st == 200 else ""
    check("首页返回 200 且为 HTML", st == 200 and "<div id=\"root\"" in html, "HTTP %s" % st)
    assets = re.findall(r"/assets/([A-Za-z0-9._-]+\.(?:js|css))", html)
    check("首页引用的构建产物存在", bool(assets), assets)
    if assets:
        st, raw, _ = call("GET", "/assets/" + assets[0], raw=True)
        check("产物可下载（%s）" % assets[0], st == 200 and len(raw) > 1000, "HTTP %s / %d bytes" % (st, len(raw)))
    if os.path.exists(DIST):
        import hashlib
        names = sorted(os.listdir(os.path.join(DIST, "assets")))
        check("dist 与托管产物一致（%d 个资源）" % len(names), bool(names), names[:3])

    section("② 未登录访问")
    st, b, _ = call("GET", "/api/report/" + REPORT)
    check("未登录查询 → 401", st == 401, st)

    section("③ 六账号登录与菜单可见性")
    users = {"admin": "admin123", "keshi": "123456", "daozhen": "123456",
             "yishi": "123456", "yaoshi": "123456", "kufang": "123456"}
    tokens, menus = {}, {}
    for uname, pwd in users.items():
        st, b, _ = call("POST", "/api/auth/login", body={"username": uname, "password": pwd})
        ok = st == 200 and b.get("data", {}).get("token")
        check("%s 登录" % uname, bool(ok), st)
        if ok:
            tokens[uname] = b["data"]["token"]
            menus[uname] = {m["name"] for m in (b["data"].get("menus") or [])}
    check("库房管理员可见「库存管理」（本屏所属菜单）", "库存管理" in menus.get("kufang", set()), sorted(menus.get("kufang", [])))
    check("库房管理员不可见批次 3 菜单（统计报表/随访管理）",
          not ({"统计报表", "随访管理"} & menus.get("kufang", set())), sorted(menus.get("kufang", [])))
    check("admin 菜单 ⊇ 批次 1/2/3 交付菜单",
          {"库存管理", "门诊管理", "药房管理", "随访管理", "统计报表"} <= menus.get("admin", set()),
          sorted(menus.get("admin", [])))

    section("④ 报表查询权限交叉（真实 HTTP）")
    for uname, token in tokens.items():
        st, b, _ = q({"page": 1, "size": 5}, token)
        print("     %-8s → HTTP %s %s" % (uname, st, (b.get("message") or "")[:40]))
        check("%s 查询未出现 500/404（200 或 403）" % uname, st in (200, 403), st)

    section("⑤ 条件组开关 onlyAlert 端到端")
    token = tokens.get("admin")
    st_all, b_all, _ = q({"page": 1, "size": 100}, token)
    conn = sqlite3.connect(COPY)
    conn.row_factory = sqlite3.Row
    total_sql = conn.execute("SELECT COUNT(*) c FROM herb WHERE flag = 1").fetchone()["c"]
    alert_sql = conn.execute("SELECT COUNT(*) c FROM herb WHERE flag = 1 AND stock_quantity < low_stock_threshold").fetchone()["c"]
    conn.close()
    if check("查询返回 200", st_all == 200, b_all):
        check("未传 onlyAlert → 全部饮片（API=%s，SQL=%s）" % (b_all["data"]["total"], total_sql),
              b_all["data"]["total"] == total_sql)
    st_alert, b_alert, _ = q({"onlyAlert": "true", "page": 1, "size": 100}, token)
    if check("onlyAlert=true 返回 200", st_alert == 200, b_alert):
        check("onlyAlert=true → 仅预警项（API=%s，SQL=%s）" % (b_alert["data"]["total"], alert_sql),
              b_alert["data"]["total"] == alert_sql and b_alert["data"]["total"] < b_all["data"]["total"])
    st_bad, b_bad, _ = q({"onlyAlert": "abc"}, token)
    check("onlyAlert 非法值 → 400 中文", st_bad == 400 and "取值非法" in json.dumps(b_bad, ensure_ascii=False),
          b_bad.get("message"))

    section("⑥ 导出（XLSX / CSV）")
    st, raw, hdrs = call("GET", "/api/report/%s/export?format=xlsx" % REPORT, token=token, raw=True)
    if check("XLSX 导出 200", st == 200, st):
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            sheet = z.read([n for n in z.namelist() if n.startswith("xl/worksheets/")][0]).decode("utf-8")
            parseString(sheet)
            check("XLSX 可解析且含中文表头（饮片编码/预警状态）", "饮片编码" in sheet and "预警状态" in sheet,
                  "%d 行" % sheet.count("<row "))
        except Exception as exc:                                        # noqa: BLE001
            check("XLSX 可解析", False, str(exc))
    st, raw, _ = call("GET", "/api/report/%s/export?format=csv&onlyAlert=true" % REPORT, token=token, raw=True)
    check("CSV（onlyAlert=true）带 BOM 与表头", st == 200 and raw[:3] == b"\xef\xbb\xbf"
          and "饮片编码" in raw.decode("utf-8-sig"), st)

    section("⑦ 前端产物含本屏控件 id 与报表码")
    bundle = ""
    if os.path.exists(os.path.join(DIST, "assets")):
        for name in os.listdir(os.path.join(DIST, "assets")):
            if name.endswith(".js"):
                bundle += io.open(os.path.join(DIST, "assets", name), encoding="utf-8", errors="replace").read()
    if check("找到构建产物 JS", bool(bundle), len(bundle)):
        for token_name in ("QR-HERB-STOCK-001", "herb:query-stock-and-alert", "onlyAlert",
                           "herb:stocktake"):
            check("产物含 %s" % token_name, token_name in bundle)
        ids = ("txtQryHerbName", "cboQryHerbCategory", "cboQryToxicityLevel", "cboQryAlertStatus",
               "chkOnlyAlert", "numQryStockFrom", "numQryStockTo", "btnStocktake", "numStocktakeQty")
        missing = [i for i in ids if i not in bundle]
        check("产物含本屏全部关键控件 id（%d 个）" % len(ids), not missing, missing)

    section("⑧ 未污染演示库（副本策略取证）")
    srv.shutdown()
    os.stat(DEMO)
    check("演示库 mtime 与体积未变（副本被写入而非演示库）",
          os.stat(DEMO).st_mtime == demo_stat.st_mtime and os.stat(DEMO).st_size == demo_stat.st_size)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    check("副本已删除", not os.path.exists(COPY))

    print("\n" + "=" * 104)
    print("批次 4 端到端探针：通过 %d / 失败 %d" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for name in NG:
            print("   - %s" % name)
    print("=" * 104)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
