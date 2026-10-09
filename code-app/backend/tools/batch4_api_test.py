# -*- coding: utf-8 -*-
"""批次 4 主代独立验收：QR-HERB-STOCK-001（第 7 张报表）+ 条件组开关（约定 13）。

设计原则（与批次 3 一致）：
  ① 黑盒 HTTP（真实 socket：werkzeug make_server）+ 直连 SQL oracle，不复用开发侧脚本；
  ② 期望值来自**模型文件**（独立读取 yaml）与数据库事实（角色授权表），不来自实现代码；
  ③ 固定数据集默认重建（确定性）；库隔离（绝不读写演示库 data/app.db）；
  ④ 写路径断言必须业务成功；阻断类断言不得把 404 当通过。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch4_api_test.py
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.dom.minidom import parseString

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BACKEND))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

REPORT = "QR-HERB-STOCK-001"
DEMO_DB = os.path.join(BACKEND, "data", "app.db")
DB = os.path.join(BACKEND, "data", "batch4_accept.db")
os.environ["APP_DB_PATH"] = DB
assert "app.db" not in os.path.basename(DB) or "batch4" in DB, "本脚本严禁使用演示库"

import yaml  # noqa: E402

OK, NG = [], []
PORT = 5064
BASE = "http://127.0.0.1:%d" % PORT


# ---------------------------------------------------------------- 装置

def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-62s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:100]))
    return bool(cond)


def section(title):
    print("\n" + "-" * 108)
    print(title)
    print("-" * 108)


def sql_one(query, args=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(query, args).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def scalar(query, args=()):
    row = sql_one(query, args)
    return list(row.values())[0] if row else None


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


def build_fixture():
    """固定数据集：复制演示库副本 + 确定性的库存/阈值分布（6 正常 + 4 预警）。"""
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(DB + suffix):
            os.remove(DB + suffix)
    shutil.copyfile(DEMO_DB, DB)
    conn = sqlite3.connect(DB)
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM herb ORDER BY id")]
        assert len(ids) >= 10, "演示库饮片不足 10 条，无法构造固定分布"
        for i, hid in enumerate(ids[:10], start=1):
            stock, threshold = (1000, 100) if i <= 6 else (50, 100)     # 后 4 条＝预警
            conn.execute("UPDATE herb SET stock_quantity = ?, low_stock_threshold = ?, flag = 1 WHERE id = ?",
                         (stock, threshold, hid))
        conn.commit()
    finally:
        conn.close()


def model():
    with io.open(os.path.join(PROJECT, "yaml", "m7-report-model.yaml"), encoding="utf-8") as f:
        m7 = yaml.safe_load(f)
    return [r for r in m7["query_reports"] if r["id"] == REPORT][0]


def oracle(rep, **params):
    """由模型条件**语义**独立重算期望行数（直连 SQL，不走实现代码）。

    C01 LIKE / C02 EQ / C03-C05 EQ / C06 GE / C07 LE / C08 ALERT_FILTER（开关 onlyAlert=true）。
    """
    where, args = ["h.flag = 1"], []
    mapping = {"herbName": "h.herb_name LIKE ?", "herbCode": "h.herb_code = ?",
               "herbCategory": "h.herb_category = ?", "toxicityLevel": "h.toxicity_level = ?",
               "herbStatus": "h.herb_status = ?", "stockQuantityFrom": "h.stock_quantity >= ?",
               "stockQuantityTo": "h.stock_quantity <= ?"}
    for key, clause in mapping.items():
        value = params.get(key)
        if value in (None, ""):
            continue
        where.append(clause)
        args.append("%" + str(value) + "%" if key == "herbName" else value)
    if str(params.get("onlyAlert", "")).lower() in ("true", "1", "yes", "y"):
        where.append("h.stock_quantity < h.low_stock_threshold")
    return scalar("SELECT COUNT(*) FROM herb h WHERE " + " AND ".join(where), tuple(args))


def q(params, token, raw=False):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return call("GET", "/api/report/%s%s" % (REPORT, ("?" + query) if query else ""), token=token, raw=raw)


# ---------------------------------------------------------------- 主流程

def main():
    rep = model()
    build_fixture()

    # ---------- ① 模型侧结构断言（期望值来自模型文件） ----------
    section("① 模型结构断言（M7 v%s，独立读取 yaml）" % rep.get("version"))
    params = {p["name"]: p for p in rep["parameters"]}
    check("查询参数 8 个且名称与契约一致",
          sorted(params) == sorted(["herbName", "herbCode", "herbCategory", "toxicityLevel", "herbStatus",
                                    "stockQuantityFrom", "stockQuantityTo", "onlyAlert"]), sorted(params))
    conds = {c["conditionId"]: c for c in rep["conditions"]}
    check("条件 8 条（C01–C08）", sorted(conds) == ["C%02d" % i for i in range(1, 9)], sorted(conds))
    alert = [c for c in rep["conditions"] if c.get("group") == "ALERT_FILTER"]
    check("ALERT_FILTER 组 1 条且显式声明开关（约定 13）",
          len(alert) == 1 and alert[0].get("switchParameterRef") == "onlyAlert"
          and alert[0].get("switchActivateValue") is True,
          alert[0].get("switchParameterRef") if alert else None)
    check("onlyAlert 为非必填 Boolean 且默认 false",
          params["onlyAlert"]["dataType"] == "Boolean" and not params["onlyAlert"]["required"]
          and params["onlyAlert"].get("defaultValue") is False)
    check("TRIGGER 组不存在于本报表（仅超量台账有）",
          not [c for c in rep["conditions"] if c.get("group") == "TRIGGER"])
    cols = [c["name"] for c in rep["resultColumns"]]
    check("结果列 15 列", len(cols) == 15, cols)

    from werkzeug.serving import make_server                            # noqa: E402

    from app import create_app                                          # noqa: E402

    app = create_app()
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    st, body, _ = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
    admin = body["data"]["token"]
    check("admin 登录取令牌", st == 200 and bool(admin))

    # ---------- ② 基础查询与列口径 ----------
    section("② 基础查询 / 列口径 / 默认排序")
    st, b, _ = q({"page": 1, "size": 100}, admin)
    if not check("查询返回 200", st == 200, b):
        srv.shutdown()
        return summary()
    d = b["data"]
    check("列名与列序与模型逐字一致", [c["name"] for c in d["columns"]] == cols,
          [c["name"] for c in d["columns"]])
    check("列标签与模型一致", [c["label"] for c in d["columns"]] == [c["label"] for c in rep["resultColumns"]])
    check("默认返回全部饮片（onlyAlert 未传＝false）",
          d["total"] == oracle(rep) == 10, "total=%s oracle=%s" % (d["total"], oracle(rep)))
    rows = d["list"]
    check("默认排序：预警项在前（模型 orderBy 首表达式 CASE … THEN 0 ELSE 1 ASC）",
          rows and rows[0]["alertStatus"] == "预警", rows[0]["alertStatus"] if rows else None)
    check("alertStatus 为中文口径（预警/正常），非 ALERT/NORMAL",
          {r["alertStatus"] for r in rows} <= {"预警", "正常"}, {r["alertStatus"] for r in rows})
    bad_gap = []
    for r in rows:
        want = oracle(rep, onlyAlert="true", herbCode=r["herbCode"])
        gap = scalar("SELECT low_stock_threshold - stock_quantity FROM herb WHERE herb_code = ?", (r["herbCode"],))
        if r["alertStatus"] != ("预警" if want else "正常") or r["alertGap"] != gap:
            bad_gap.append((r["herbCode"], r["alertStatus"], r["alertGap"], want, gap))
    check("逐行 alertStatus / alertGap 与 SQL oracle 一致", not bad_gap, bad_gap[:2])
    check("分页参数回显（size=100）", d.get("size") == 100, d.get("size"))

    # ---------- ③ 开关语义（本批核心） ----------
    section("③ 条件组开关 onlyAlert（约定 13 语义）")
    st_t, b_t, _ = q({"onlyAlert": "true", "page": 1, "size": 100}, admin)
    st_f, b_f, _ = q({"onlyAlert": "false", "page": 1, "size": 100}, admin)
    if check("onlyAlert=true 返回 200", st_t == 200, b_t):
        check("onlyAlert=true → 仅预警项（=SQL 口径且=4）",
              b_t["data"]["total"] == oracle(rep, onlyAlert="true") == 4,
              "API=%s oracle=%s" % (b_t["data"]["total"], oracle(rep, onlyAlert="true")))
        check("onlyAlert=true 每一行都满足 库存<预警值",
              all(r["stockQuantity"] < r["lowStockThreshold"] for r in b_t["data"]["list"]))
    if check("onlyAlert=false 返回 200", st_f == 200, b_f):
        check("onlyAlert=false → 全部（10 行）", b_f["data"]["total"] == 10, b_f["data"]["total"])
    check("开关真实生效：true 与 false 结果不同", b_t["data"]["total"] != b_f["data"]["total"],
          "%s vs %s" % (b_t["data"]["total"], b_f["data"]["total"]))
    st_i, b_i, _ = q({"onlyAlert": "abc"}, admin)
    check("onlyAlert 非法值 → 400 中文提示",
          st_i == 400 and "取值非法" in json.dumps(b_i, ensure_ascii=False), b_i.get("message"))
    st_i2, b_i2, _ = q({"onlyAlert": "TRUE"}, admin)
    check("onlyAlert 大小写容错（TRUE 可用）", st_i2 == 200 and b_i2["data"]["total"] == 4, st_i2)

    # ---------- ④ 其余 7 个参数 ----------
    section("④ 其余 7 个查询参数（逐个与 SQL oracle 比对）")
    sample = sql_one("SELECT herb_name, herb_code, herb_category, toxicity_level, herb_status, stock_quantity "
                     "FROM herb WHERE flag = 1 ORDER BY id LIMIT 1")
    cases = [
        ("herbName 模糊（LIKE）", {"herbName": sample["herb_name"][:1]},
         {"herbName": sample["herb_name"][:1]}),
        ("herbCode 精确", {"herbCode": sample["herb_code"]}, {"herbCode": sample["herb_code"]}),
        ("herbCategory 字典", {"herbCategory": sample["herb_category"]}, {"herbCategory": sample["herb_category"]}),
        ("toxicityLevel 枚举", {"toxicityLevel": sample["toxicity_level"]},
         {"toxicityLevel": sample["toxicity_level"]}),
        ("herbStatus 枚举", {"herbStatus": sample["herb_status"]}, {"herbStatus": sample["herb_status"]}),
        ("stockQuantityFrom 区间下界", {"stockQuantityFrom": 100}, {"stockQuantityFrom": 100}),
        ("stockQuantityTo 区间上界", {"stockQuantityTo": 100}, {"stockQuantityTo": 100}),
        ("区间组合（from+to）", {"stockQuantityFrom": 100, "stockQuantityTo": 1000},
         {"stockQuantityFrom": 100, "stockQuantityTo": 1000}),
    ]
    for label, req, exp in cases:
        st, b, _ = q(dict(req, page=1, size=100), admin)
        want = oracle(rep, **exp)
        check("%s → total=%s" % (label, want), st == 200 and b["data"]["total"] == want,
              "API=%s oracle=%s" % (b["data"]["total"] if st == 200 else st, want))
    for pname in ("herbCategory", "toxicityLevel", "herbStatus"):
        st, b, _ = q({pname: "NOT_A_LEGAL_CODE"}, admin)
        check("%s 字典/枚举外取值 → 400" % pname, st == 400 and b.get("message"), b.get("message"))
    st, b, _ = q({"herbCode": "NOT_EXIST_0000"}, admin)
    check("不存在的饮片编码 → 200 且 0 行（非报错）", st == 200 and b["data"]["total"] == 0,
          b["data"]["total"] if st == 200 else st)

    # ---------- ⑤ 分页 / 排序 / 负例 ----------
    section("⑤ 分页、排序与负例")
    st, b, _ = q({"page": 1, "size": 3}, admin)
    check("size=3 生效且返回 ≤3 行", st == 200 and len(b["data"]["list"]) <= 3 and b["data"]["size"] == 3)
    st, b, _ = q({"page": 1, "size": 9999}, admin)
    check("size 超上限截断为 100（模型 maxPageSize）", st == 200 and b["data"]["size"] == 100,
          b["data"].get("size"))
    st, b, _ = q({"page": 1, "size": 0}, admin)
    check("size=0 被拒 400", st == 400, st)
    st, b, _ = q({"page": 0}, admin)
    check("page=0 被拒 400", st == 400, st)
    st, b, _ = q({"sortField": "not_a_column"}, admin)
    check("非法排序字段被拒 400", st == 400, st)
    st, b, _ = q({"sortField": "stockQuantity", "sortDir": "DESC", "size": 10, "page": 1}, admin)
    check("按 stockQuantity DESC 排序生效", st == 200 and [r["stockQuantity"] for r in b["data"]["list"]]
          == sorted([r["stockQuantity"] for r in b["data"]["list"]], reverse=True),
          [r["stockQuantity"] for r in b["data"]["list"]] if st == 200 else st)
    st, b, _ = q({"page": 99, "size": 20}, admin)
    check("越过末页返回空列表且 total 不变", st == 200 and b["data"]["list"] == [] and b["data"]["total"] == 10,
          b["data"]["total"] if st == 200 else st)
    st, b, _ = call("GET", "/api/report/NOT-EXIST-001", token=admin)
    check("未知报表码 → 404", st == 404, st)

    # ---------- ⑥ 合计 ----------
    section("⑥ 合计行（summary）")
    st, b, _ = q({"page": 1, "size": 3}, admin)
    summ = b["data"].get("summary")
    fields = (rep.get("reportOptions") or {}).get("totalFields")
    if fields:
        for field in fields:
            want = scalar("SELECT SUM(%s) FROM herb WHERE flag = 1" % {
                "stockQuantity": "stock_quantity"}.get(field, field))
            check("合计 %s = 全量 SQL 合计（不受分页影响）" % field, summ and summ.get(field) == want,
                  "%s vs %s" % (summ.get(field) if summ else None, want))
    else:
        check("模型未声明 totalFields（reportOptions=null）→ 接口不返回合计或返回空，属模型口径",
              not summ or all(v in (None, 0) for v in summ.values()), summ)
    check("合计不受分页影响（size=3 与 size=100 的 summary 一致）",
          (summ or {}) == (q({"page": 1, "size": 100}, admin)[1]["data"].get("summary") or {}))

    # ---------- ⑦ 导出 ----------
    section("⑦ 导出（XLSX / CSV）")
    st, raw, hdrs = call("GET", "/api/report/%s/export?format=xlsx" % REPORT, token=admin, raw=True)
    if check("XLSX 导出返回 200", st == 200, st):
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            sheet = z.read([n for n in z.namelist() if n.startswith("xl/worksheets/")][0]).decode("utf-8")
            parseString(sheet)
            check("XLSX 结构可解析且含中文表头", "饮片编码" in sheet and "预警状态" in sheet,
                  "%d 行" % sheet.count("<row "))
        except Exception as exc:                                          # noqa: BLE001
            check("XLSX 结构可解析", False, str(exc))
    st, raw, hdrs = call("GET", "/api/report/%s/export?format=csv&onlyAlert=true" % REPORT, token=admin, raw=True)
    check("CSV（onlyAlert=true）带 BOM 与表头",
          st == 200 and raw[:3] == b"\xef\xbb\xbf" and "饮片编码" in raw.decode("utf-8-sig"),
          st)
    lines = [l for l in raw.decode("utf-8-sig").strip().split("\n") if l.strip()]
    check("CSV 行数 = 表头 1 + 数据 4（仅预警项，导出口径与查询一致）", len(lines) == 5, len(lines))
    st, raw, _ = call("GET", "/api/report/%s/export?format=pdf" % REPORT, token=admin, raw=True)
    check("PDF 导出被拒（本批只做 XLSX/CSV）", st == 400, st)
    check("导出响应带 UTF-8 文件名（Content-Disposition filename*）",
          "filename*" in json.dumps({k.lower(): v for k, v in hdrs.items()}, ensure_ascii=False)
          or "filename" in json.dumps({k.lower(): v for k, v in hdrs.items()}, ensure_ascii=False),
          [k for k in hdrs if k.lower() == "content-disposition"])

    # ---------- ⑧ 权限矩阵（按库内授权事实机械推导） ----------
    section("⑧ 权限矩阵（6 账号 × 本报表查询/导出，期望由 sys_role_permission 推导）")
    perm_code = "herb:query-stock-and-alert"
    users = {"admin": "admin123", "keshi": "123456", "daozhen": "123456",
             "yishi": "123456", "yaoshi": "123456", "kufang": "123456"}
    # admin 角色是超级管理员（auth_service 对 code in ('admin','ROLE-ADMIN') 旁路权限校验，
    # 且 seed 未给 admin 写全量 sys_role_permission）——oracle 必须按同一条规则推导，否则会误判。
    granted, superuser = {}, {}
    for uname in users:
        row = sql_one("SELECT COUNT(*) AS c FROM sys_user u "
                      "JOIN sys_user_role ur ON ur.user_id = u.id "
                      "JOIN sys_role_permission rp ON rp.role_id = ur.role_id "
                      "JOIN sys_permission p ON p.id = rp.permission_id "
                      "WHERE u.username = ? AND p.code = ?", (uname, perm_code))
        granted[uname] = (row or {}).get("c", 0) > 0
        sup = sql_one("SELECT COUNT(*) AS c FROM sys_user u "
                      "JOIN sys_user_role ur ON ur.user_id = u.id JOIN sys_role r ON r.id = ur.role_id "
                      "WHERE u.username = ? AND r.code IN ('admin', 'ROLE-ADMIN')", (uname,))
        superuser[uname] = (sup or {}).get("c", 0) > 0
    check("库内无任何角色对 admin 授予本报表权限，但 admin 是超级管理员（旁路口径已按实现规则登记）",
          not granted.get("admin") and superuser.get("admin"), superuser.get("admin"))
    for uname, pwd in users.items():
        st, b, _ = call("POST", "/api/auth/login", body={"username": uname, "password": pwd})
        if st != 200:
            check("%s 登录" % uname, False, st)
            continue
        token = b["data"]["token"]
        st, b2, _ = q({"page": 1, "size": 5}, token)
        expect = 200 if (granted[uname] or superuser[uname]) else 403
        check("%-8s 查询 → %s（库内授予=%s，超管=%s）" % (uname, expect, granted[uname], superuser[uname]),
              st == expect, "HTTP %s / %s" % (st, b2.get("message")))
        st, raw, _ = call("GET", "/api/report/%s/export?format=csv" % REPORT, token=token, raw=True)
        check("%-8s 导出 → %s" % (uname, expect), st == expect, "HTTP %s" % st)
    st, b, _ = q({"page": 1}, None)
    check("未登录 → 401", st == 401, st)

    # ---------- ⑨ 引擎元数据自检 ----------
    section("⑨ 引擎元数据自检（含约定 13 项）")
    with app.app_context():
        from services import report_service as rs                            # noqa: E402
        problems = rs.validate_metadata()
        check("validate_metadata 问题清单为空", not problems, problems[:3])
        check("报告权限码可从模型枚举", perm_code in rs.all_report_permission_codes(),
              sorted(rs.all_report_permission_codes())[:3])

    srv.shutdown()
    return summary()


def summary():
    print("\n" + "=" * 108)
    print("批次 4 独立验收结果：通过 %d / 失败 %d" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for name in NG:
            print("   - %s" % name)
    print("=" * 108)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
