# -*- coding: utf-8 -*-
"""批次 4 演示库只读体检：QR-HERB-STOCK-001 在**演示库**上是否真有数据、开关是否生效。

只读（仅 GET）：以真实 HTTP（werkzeug make_server）调用报表与导出接口，并断言演示库未被写入
（mtime + 关键计数不变）。写入类探针见 batch4_e2e_probe.py（跑副本）。
用法：code-app/backend/.venv/Scripts/python.exe tools/batch4_demo_verify.py
"""
import io
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

REPORT = "QR-HERB-STOCK-001"
DB = os.path.join(BACKEND, "data", "app.db")
assert os.path.basename(DB) == "app.db", "本脚本只用于演示库体检"
os.environ["APP_DB_PATH"] = DB
PORT = 5067
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-62s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:90]))
    return bool(cond)


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


def fingerprint():
    """业务数据指纹：行数 + 关键业务行的哈希。

    比 mtime 可靠——应用启动时的幂等初始化（建表/种子 INSERT OR IGNORE/WAL 切换）会触碰库文件，
    但不应改变任何业务行；以指纹为准才能区分「启动触碰」与「探针真写入」。
    """
    import hashlib
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        parts = []
        for query in ("SELECT id, herb_code, stock_quantity, low_stock_threshold, herb_status, flag "
                      "FROM herb ORDER BY id",
                      "SELECT id, visit_no, register_time, visit_status, flag FROM visit ORDER BY id",
                      "SELECT id, follow_up_no, record_status, planned_follow_up_date, flag "
                      "FROM follow_up ORDER BY id"):
            rows = [tuple(r) for r in conn.execute(query)]
            parts.append("%d:%s" % (len(rows), hashlib.sha256(
                repr(rows).encode("utf-8")).hexdigest()[:16]))
        return " | ".join(parts)
    finally:
        conn.close()


def counts():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "herb": conn.execute("SELECT COUNT(*) c FROM herb WHERE flag = 1").fetchone()["c"],
            "alert": conn.execute("SELECT COUNT(*) c FROM herb WHERE flag = 1 "
                                  "AND stock_quantity < low_stock_threshold").fetchone()["c"],
            "visit": conn.execute("SELECT COUNT(*) c FROM visit WHERE flag = 1").fetchone()["c"],
            "prescription": conn.execute("SELECT COUNT(*) c FROM prescription WHERE flag = 1").fetchone()["c"],
            "follow_up": conn.execute("SELECT COUNT(*) c FROM follow_up WHERE flag = 1").fetchone()["c"],
        }
    finally:
        conn.close()


def main():
    before = counts()
    fp_before = fingerprint()
    stat = os.stat(DB)

    from werkzeug.serving import make_server                          # noqa: E402

    from app import create_app                                        # noqa: E402

    app = create_app()
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    st, b, _ = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
    token = b.get("data", {}).get("token") if st == 200 else None
    check("admin 登录取令牌", bool(token), st)

    def q(params, raw=False):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return call("GET", "/api/report/%s%s" % (REPORT, ("?" + query) if query else ""), token=token, raw=raw)

    print("\n--- ① 查询与开关（演示库真实数据）---")
    st, b_all, _ = q({"page": 1, "size": 100})
    if check("查询返回 200", st == 200, b_all):
        d = b_all["data"]
        check("列 15 列且顺序来自后端", len(d["columns"]) == 15, [c["name"] for c in d["columns"]][:4])
        check("未传 onlyAlert → 全部饮片（API=%s，库内=%s）" % (d["total"], before["herb"]),
              d["total"] == before["herb"])
        check("演示库存在预警项（≥1，供界面演示）", before["alert"] >= 1, before["alert"])
        check("预警状态为中文口径", {r["alertStatus"] for r in d["list"]} <= {"预警", "正常"},
              {r["alertStatus"] for r in d["list"]})
    st, b_t, _ = q({"onlyAlert": "true", "page": 1, "size": 100})
    check("onlyAlert=true → 仅预警项（API=%s，库内=%s）" % (b_t.get("data", {}).get("total") if st == 200 else st,
                                                     before["alert"]),
          st == 200 and b_t["data"]["total"] == before["alert"])
    st, b_bad, _ = q({"onlyAlert": "abc"})
    check("非法布尔值 → 400 中文提示", st == 400 and "取值非法" in json.dumps(b_bad, ensure_ascii=False),
          b_bad.get("message"))

    print("\n--- ② 导出（演示库）---")
    st, raw, _ = call("GET", "/api/report/%s/export?format=xlsx" % REPORT, token=token, raw=True)
    if check("XLSX 导出 200", st == 200, st):
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            sheet = z.read([n for n in z.namelist() if n.startswith("xl/worksheets/")][0]).decode("utf-8")
            check("XLSX 含中文表头", "饮片编码" in sheet and "预警状态" in sheet)
        except Exception as exc:                                       # noqa: BLE001
            check("XLSX 可解析", False, str(exc))
    st, raw, _ = call("GET", "/api/report/%s/export?format=csv" % REPORT, token=token, raw=True)
    check("CSV 带 BOM 与表头", st == 200 and raw[:3] == b"\xef\xbb\xbf" and "饮片编码" in raw.decode("utf-8-sig"))

    print("\n--- ③ 未污染取证 ---")
    srv.shutdown()
    after = counts()
    check("关键计数不变（本脚本只读）", before == after, "%s → %s" % (before, after))
    check("业务行指纹不变（行数+行哈希；应用启动会触碰库文件属正常）", fingerprint() == fp_before,
          "before=%s after=%s" % (fp_before[:46], fingerprint()[:46]))
    if os.stat(DB).st_mtime != stat.st_mtime:
        print("  [注] 库文件 mtime 变化 = 应用启动的幂等初始化所致（业务行指纹已证明数据未变）")

    print("\n" + "=" * 100)
    print("批次 4 演示库体检：通过 %d / 失败 %d（库：%s）" % (len(OK), len(NG), DB))
    if NG:
        print("失败项：" + "；".join(NG))
    print("=" * 100)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
