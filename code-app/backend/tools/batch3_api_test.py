# -*- coding: utf-8 -*-
"""批次 3 主代独立验收（黑盒 HTTP + 直连 SQL oracle）。

原则：
  * 只走 HTTP 接口（真实 socket + urllib），不 import 子代理的实现代码来做断言；
  * 期望值来自**直连 SQL 的独立口径**（oracle）与**数据库权限授予事实**（权限矩阵），
    不复制被测实现的逻辑；
  * 失败即非零退出；输出逐项 PASS/FAIL 与真实计数。

用法（后端 venv）：
  code-app/backend/.venv/Scripts/python.exe tools/batch3_api_test.py
"""
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import io as _io
from xml.dom.minidom import parseString

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

DB = os.path.join(BACKEND, "data", "batch3_accept.db")
assert "app.db" not in os.path.basename(DB), "禁止触碰演示库"
if "--no-rebuild" not in sys.argv:
    import subprocess

    print("重建验收固定数据集（保证确定性与可重复性）…")
    _p = subprocess.run([sys.executable, os.path.join(BACKEND, "tools", "batch3_fixture.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        env=dict(os.environ, APP_DB_PATH=DB))
    if _p.returncode != 0:
        print((_p.stdout or "")[-1500:])
        print((_p.stderr or "")[-800:])
        raise SystemExit("固定数据集构建失败")
    print("  " + [l for l in (_p.stdout or "").splitlines() if "固定数据集就绪" in l or "实际数据量" in l][-1].strip())
assert os.path.exists(DB), "缺少验收数据集"
os.environ["APP_DB_PATH"] = DB

PORT = 5057
BASE = "http://127.0.0.1:%d" % PORT
RNG = ("2026-07-01", "2026-09-30")          # 报表测试用日期区间（覆盖固定数据集全部月份）
RPT_RNG = ("2026-06-01", "2026-09-30")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("[PASS]" if cond else "[FAIL]", name, ("　→ " + str(detail)[:220]) if detail else ""))
    return bool(cond)


def section(title):
    print("\n=== %s ===" % title)


def rows(sql, args=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def one(sql, args=()):
    r = rows(sql, args)
    return r[0][0] if r else None


# ─────────────────────────────────────────── HTTP 客户端
class Client:
    def __init__(self):
        self.tokens = {}

    def login(self, username, password):
        st, body, _h = self.req("POST", "/api/auth/login", json_body={"username": username, "password": password})
        assert st == 200 and body.get("success"), "登录失败 %s: %s" % (username, body)
        token = body["data"]["token"] if "data" in body else body.get("token")
        self.tokens[username] = token
        return token

    def req(self, method, path, token=None, json_body=None, headers=None):
        url = BASE + path
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        hdrs = {"Accept": "application/json"}
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        if token:
            hdrs["Authorization"] = "Bearer " + token
        hdrs.update(headers or {})
        rq = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=30) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                payload = json.loads(raw.decode("utf-8")) if "json" in ctype else raw
                return resp.status, payload, dict(resp.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = raw
            return e.code, payload, dict(e.headers)

    def q(self, report, params=None, token=None):
        qs = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        path = "/api/report/%s%s" % (report, ("?" + urllib.parse.urlencode(qs)) if qs else "")
        return self.req("GET", path, token=token)

    def export(self, report, fmt, params=None, token=None):
        qs = dict(params or {})
        qs["format"] = fmt
        path = "/api/report/%s/export?%s" % (report, urllib.parse.urlencode(qs))
        return self.req("GET", path, token=token)


def perm_expected(username, code):
    """数据库权限授予事实（与实现无关）：该账号是否被授予 code。"""
    from services.auth_service import has_permission

    uid = one("SELECT id FROM sys_user WHERE username = ?", (username,))
    return bool(has_permission(uid, code))


def report_perm(report_id):
    """由 M5 targetRef（= M2 行为）机械派生报表权限码，与 seed.py 同一实现。"""
    from seed import permission_code

    from ontology.registry import registry, load_ontology

    load_ontology()
    return permission_code(registry["query_reports"][report_id]["behaviorRef"])


# ─────────────────────────────────────────── 各报表 oracle（独立 SQL 口径）
def oracle_visit_stats(d_from, d_to, granularity="MONTH", dept=None, vtype=None):
    fmt = "%Y-%m" if granularity == "MONTH" else "%Y-%m-%d"   # 模型约定 7：粒度只取 MONTH / DAY
    where = ["v.flag = 1", "date(v.register_time) >= ?", "date(v.register_time) <= ?"]
    args = [d_from, d_to]
    if dept:
        where.append("v.dept_code = ?")
        args.append(dept)
    if vtype:
        where.append("v.visit_type = ?")
        args.append(vtype)
    w = " AND ".join(where)
    sql_total = ("SELECT COUNT(*) FROM (SELECT strftime('" + fmt + "', v.register_time) g, v.dept_code, v.doctor_id, "
                 "v.visit_type FROM visit v WHERE " + w + " GROUP BY 1,2,3,4)")
    total = one(sql_total, tuple(args))
    agg = rows("SELECT COUNT(*) visit_count, COUNT(DISTINCT v.patient_id) patient_count, "
               "SUM(CASE WHEN v.visit_type='FIRST' THEN 1 ELSE 0 END) first_cnt, "
               "SUM(CASE WHEN v.visit_type='FOLLOW_UP' THEN 1 ELSE 0 END) follow_cnt, "
               "SUM(CASE WHEN v.visit_status='COMPLETED' THEN 1 ELSE 0 END) completed_cnt, "
               "SUM(CASE WHEN v.visit_status='CANCELLED' THEN 1 ELSE 0 END) cancelled_cnt "
               "FROM visit v WHERE %s" % w, tuple(args))[0]
    return {"total": total, **{k: (agg[k] or 0) for k in agg.keys()}}


def oracle_syndrome_dist(d_from, d_to):
    total = one("SELECT COUNT(*) FROM (SELECT s.syndrome_code, s.syndrome_name, s.diagnosis_method, d.syndrome_nature "
                "FROM syndrome_diagnosis d JOIN syndrome_type s ON s.id = d.syndrome_id AND s.flag = 1 "
                "JOIN visit v ON v.id = d.visit_id AND v.flag = 1 "
                "WHERE d.flag = 1 AND date(v.register_time) >= ? AND date(v.register_time) <= ? GROUP BY 1,2,3,4)",
                (d_from, d_to))
    case_total = one("SELECT COUNT(*) FROM syndrome_diagnosis d JOIN visit v ON v.id = d.visit_id AND v.flag = 1 "
                     "WHERE d.flag = 1 AND date(v.register_time) >= ? AND date(v.register_time) <= ?", (d_from, d_to))
    return {"total": total, "case_total": case_total}


def oracle_herb_usage(d_from, d_to, dimension="HERB"):
    base = ("FROM prescription_item i "
            "JOIN prescription p ON p.id = i.prescription_id AND p.flag = 1 "
            "JOIN herb h ON h.id = i.herb_id AND h.flag = 1 "
            "LEFT JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
            "WHERE i.flag = 1 AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') "
            "AND date(p.prescribe_time) >= ? AND date(p.prescribe_time) <= ?")
    if dimension == "HERB":
        total = one("SELECT COUNT(*) FROM (SELECT h.herb_code %s GROUP BY h.herb_code)" % base, (d_from, d_to))
        sums = rows("SELECT SUM(p.doses) dose_count, SUM(i.single_dose * p.doses) total_qty, "
                    "COUNT(DISTINCT p.prescription_no) rx_cnt, COUNT(DISTINCT p.patient_id) pat_cnt %s" % base,
                    (d_from, d_to))[0]
    else:
        # 模型口径：主来源为处方，LEFT JOIN 方剂模板 → 按 formula.* 分组（未引用方剂的处方自成一组，值为 NULL）
        total = one("SELECT COUNT(*) FROM (SELECT f.formula_code, f.formula_name, f.formula_type "
                    "FROM prescription p LEFT JOIN formula_template f "
                    "ON f.id = p.formula_template_id AND f.flag = 1 "
                    "LEFT JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
                    "WHERE p.flag = 1 AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') "
                    "AND date(p.prescribe_time) >= ? AND date(p.prescribe_time) <= ? GROUP BY 1,2,3)", (d_from, d_to))
        linked = one("SELECT COUNT(*) FROM (SELECT f.formula_code FROM prescription p "
                     "JOIN formula_template f ON f.id = p.formula_template_id AND f.flag = 1 "
                     "LEFT JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
                     "WHERE p.flag = 1 AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') "
                     "AND date(p.prescribe_time) >= ? AND date(p.prescribe_time) <= ? GROUP BY 1)", (d_from, d_to))
        sums = dict(rows("SELECT NULL dose_count, NULL total_qty, COUNT(DISTINCT p.prescription_no) rx_cnt, NULL pat_cnt "
                    "FROM prescription p LEFT JOIN formula_template f "
                    "ON f.id = p.formula_template_id AND f.flag = 1 "
                    "LEFT JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
                    "WHERE p.flag = 1 AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') "
                    "AND date(p.prescribe_time) >= ? AND date(p.prescribe_time) <= ?", (d_from, d_to))[0])
        sums["linked_groups"] = linked
    return {"total": total, **{k: sums[k] for k in sums.keys()}}


def oracle_overdose(d_from, d_to, trigger="BOTH"):
    conds = {
        "BOTH": "(i.single_dose > h.max_common_dose OR h.toxicity_level <> 'NONE')",
        "OVERDOSE": "(i.single_dose > h.max_common_dose)",
        "TOXIC": "(h.toxicity_level <> 'NONE')",
    }[trigger]
    sql = ("SELECT COUNT(*) FROM prescription_item i "
           "JOIN prescription p ON p.id = i.prescription_id AND p.flag = 1 "
           "JOIN herb h ON h.id = i.herb_id AND h.flag = 1 "
           "WHERE i.flag = 1 AND %s AND date(p.prescribe_time) >= ? AND date(p.prescribe_time) <= ?" % conds)
    return one(sql, (d_from, d_to))


def oracle_followup(d_from, d_to):
    total = one("SELECT COUNT(*) FROM (SELECT strftime('%Y-%m', f.planned_follow_up_date) g, v.dept_code, v.doctor_id "
                "FROM follow_up f LEFT JOIN visit v ON v.id = f.source_visit_id AND v.flag = 1 "
                "WHERE f.flag = 1 AND date(f.planned_follow_up_date) >= ? AND date(f.planned_follow_up_date) <= ? "
                "GROUP BY 1,2,3)", (d_from, d_to))
    agg = rows("SELECT COUNT(*) planned, "
               "SUM(CASE WHEN f.record_status='COMPLETED' THEN 1 ELSE 0 END) completed, "
               "SUM(CASE WHEN f.record_status='LOST' THEN 1 ELSE 0 END) lost "
               "FROM follow_up f LEFT JOIN visit v ON v.id = f.source_visit_id AND v.flag = 1 "
               "WHERE f.flag = 1 AND date(f.planned_follow_up_date) >= ? AND date(f.planned_follow_up_date) <= ?",
               (d_from, d_to))[0]
    return {"total": total, **{k: (agg[k] or 0) for k in agg.keys()}}


def oracle_visit_prescription(d_from, d_to):
    master = one("SELECT COUNT(*) FROM visit v WHERE v.flag = 1 AND date(v.register_time) >= ? "
                 "AND date(v.register_time) <= ?", (d_from, d_to))
    rx = one("SELECT COUNT(*) FROM prescription p JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
             "WHERE p.flag = 1 AND date(v.register_time) >= ? AND date(v.register_time) <= ?", (d_from, d_to))
    items = one("SELECT COUNT(*) FROM prescription_item i JOIN prescription p ON p.id = i.prescription_id AND p.flag = 1 "
                "JOIN visit v ON v.id = p.visit_id AND v.flag = 1 "
                "WHERE i.flag = 1 AND date(v.register_time) >= ? AND date(v.register_time) <= ?", (d_from, d_to))
    return {"master": master, "rx": rx, "items": items}


def approx(a, b, tol=0.02):
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return a == b


# ─────────────────────────────────────────── 主体
def main():
    from werkzeug.serving import make_server

    from app import create_app

    app = create_app()
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.6)
    c = Client()
    for u, p in (("admin", "admin123"), ("daozhen", "123456"), ("yishi", "123456"),
                 ("yaoshi", "123456"), ("kufang", "123456"), ("keshi", "123456")):
        c.login(u, p)
    admin = c.tokens["admin"]

    REPORTS = ["RPT-VISIT-STATS-001", "RPT-SYNDROME-DIST-001", "RPT-HERB-USAGE-001",
               "QR-VISIT-PRESCRIPTION-001", "QR-PRESCRIPTION-OVERDOSE-001", "RPT-FOLLOWUP-COMPLETION-001"]

    # ① 权限矩阵（期望值来自数据库授予事实）
    section("① 权限矩阵（6 报表 × 6 账号 × 查询/导出）")
    for rid in REPORTS:
        code = report_perm(rid)
        for user in ("admin", "daozhen", "yishi", "yaoshi", "kufang", "keshi"):
            exp = perm_expected(user, code)
            st, _b, _h = c.q(rid, {"page": 1, "size": 5}, token=c.tokens[user])
            ok_body = (st == 200) and (not isinstance(_b, dict) or _b.get("success"))
            check("权限 %s %s(%s) 查询" % (rid, user, code), ok_body if exp else st == 403,
                  "HTTP %s 期望 %s" % (st, 200 if exp else 403))
            st2, _b2, _h2 = c.export(rid, "csv", {"page": 1, "size": 5}, token=c.tokens[user])
            check("权限 %s %s 导出" % (rid, user), st2 == (200 if exp else 403), "HTTP %s" % st2)
    check("锚点：科室管理员对 RPT-VISIT-STATS-001 有权限", perm_expected("keshi", report_perm("RPT-VISIT-STATS-001")))
    check("锚点：库房管理员对 RPT-VISIT-STATS-001 无权限", not perm_expected("kufang", report_perm("RPT-VISIT-STATS-001")))
    check("锚点：库房管理员对随访完成分析无权限", not perm_expected("kufang", report_perm("RPT-FOLLOWUP-COMPLETION-001")))

    # ② 门诊量统计
    section("② RPT-VISIT-STATS-001 门诊量统计（oracle 比对）")
    p = {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "granularity": "MONTH", "page": 1, "size": 100}
    st, b, _ = c.q("RPT-VISIT-STATS-001", p, token=admin)
    if check("查询返回 200", st == 200, b):
        d = b["data"]
        exp = oracle_visit_stats(*RNG)
        check("分组行数 = oracle", d["total"] == exp["total"], "%s vs %s" % (d["total"], exp["total"]))
        s = d.get("summary") or {}
        check("合计 visitCount = oracle", s.get("visitCount") == exp["visit_count"], "%s vs %s" % (s.get("visitCount"), exp["visit_count"]))
        check("合计 firstVisitCount = oracle", s.get("firstVisitCount") == exp["first_cnt"], s.get("firstVisitCount"))
        check("合计 followUpVisitCount = oracle", s.get("followUpVisitCount") == exp["follow_cnt"], s.get("followUpVisitCount"))
        check("合计 completedCount = oracle", s.get("completedCount") == exp["completed_cnt"], s.get("completedCount"))
        check("合计 cancelledCount = oracle", s.get("cancelledCount") == exp["cancelled_cnt"], s.get("cancelledCount"))
        check("合计 = 分组行之和", sum(r["visitCount"] for r in d["list"]) == s.get("visitCount"),
              "%s vs %s" % (sum(r["visitCount"] for r in d["list"]), s.get("visitCount")))
        check("就诊人数列存在且 >= 1 行分组数", all(r.get("patientCount") is not None for r in d["list"]))
        cols = [x["name"] for x in d["columns"]]
        check("列顺序与 M7 一致", cols == ["statDate", "deptCode", "doctorId", "visitType", "patientCount", "visitCount",
                                          "firstVisitCount", "followUpVisitCount", "completedCount", "cancelledCount",
                                          "followUpRatio"], cols)
        p2 = dict(p, granularity="DAY")
        st2, b2, _ = c.q("RPT-VISIT-STATS-001", p2, token=admin)
        check("按日粒度行数 = oracle", st2 == 200 and b2["data"]["total"] == oracle_visit_stats(*RNG, "DAY")["total"],
              b2["data"]["total"] if st2 == 200 else b2)
        p3 = dict(p, deptCode="TCM_INTERNAL")
        st3, b3, _ = c.q("RPT-VISIT-STATS-001", p3, token=admin)
        check("科室过滤生效", st3 == 200 and b3["data"]["total"] == oracle_visit_stats(*RNG, dept="TCM_INTERNAL")["total"],
              b3["data"]["total"] if st3 == 200 else b3)
        st4, b4, _ = c.q("RPT-VISIT-STATS-001", dict(p, visitType="FIRST"), token=admin)
        check("就诊类型过滤生效", st4 == 200 and b4["data"]["total"] == oracle_visit_stats(*RNG, vtype="FIRST")["total"],
              b4["data"]["total"] if st4 == 200 else b4)

    # ③ 证型分布统计
    section("③ RPT-SYNDROME-DIST-001 证型分布统计")
    p = {"visitDateFrom": RNG[0], "visitDateTo": RNG[1], "page": 1, "size": 100}
    st, b, _ = c.q("RPT-SYNDROME-DIST-001", p, token=admin)
    if check("查询返回 200", st == 200, b):
        d = b["data"]
        exp = oracle_syndrome_dist(*RNG)
        check("分组行数 = oracle", d["total"] == exp["total"], "%s vs %s" % (d["total"], exp["total"]))
        s = d.get("summary") or {}
        check("合计 caseCount = oracle", s.get("caseCount") == exp["case_total"], "%s vs %s" % (s.get("caseCount"), exp["case_total"]))
        ratios = [r.get("caseRatio") for r in d["list"] if r.get("caseRatio") is not None]
        check("占比列已计算且 0~1", bool(ratios) and all(0 <= float(x) <= 1.0001 for x in ratios), ratios[:3])
        check("占比之和 ≈ 1", ratios and abs(sum(float(x) for x in ratios) - 1) < 0.001,
              sum(float(x) for x in ratios) if ratios else None)

    # ④ 方剂与饮片使用统计
    section("④ RPT-HERB-USAGE-001 方剂与饮片使用统计（双维度）")
    for dim in ("HERB", "FORMULA"):
        p = {"prescribeDateFrom": RPT_RNG[0], "prescribeDateTo": RPT_RNG[1], "statsDimension": ("FORMULA_TEMPLATE" if dim == "FORMULA" else dim), "page": 1, "size": 100}
        st, b, _ = c.q("RPT-HERB-USAGE-001", p, token=admin)
        if check("维度 %s 查询返回 200" % dim, st == 200, b):
            d = b["data"]
            exp = oracle_herb_usage(*RPT_RNG, dim)
            check("维度 %s 行数 = oracle" % dim, d["total"] == exp["total"], "%s vs %s" % (d["total"], exp["total"]))
            s = d.get("summary") or {}
            if dim == "HERB":
                check("维度 HERB 合计 doseCount = oracle SUM(doses)",
                      approx(s.get("doseCount"), exp["dose_count"] or 0), "%s vs %s" % (s.get("doseCount"), exp["dose_count"]))
                check("维度 HERB 合计 totalQuantity = oracle",
                      approx(s.get("totalQuantity"), exp["total_qty"] or 0), "%s vs %s" % (s.get("totalQuantity"), exp["total_qty"]))
                check("维度 HERB 方剂列应为空", all(r.get("formulaCode") in (None, "") for r in d["list"]))
                check("维度 HERB 饮片列非空", all(r.get("herbCode") for r in d["list"]))
            else:
                check("维度 FORMULA 引用张数合计 = oracle",
                      approx(s.get("formulaRefCount"), exp["rx_cnt"] or 0), "%s vs %s" % (s.get("formulaRefCount"), exp["rx_cnt"]))
                check("维度 FORMULA 饮片列为空", all(r.get("herbCode") in (None, "") for r in d["list"]))
                check("维度 FORMULA 含已挂方剂模板的组（方剂编码非空）",
                      any(r.get("formulaCode") for r in d["list"]), [r.get("formulaCode") for r in d["list"]])
                check("维度 FORMULA 方剂组数 = oracle（含未引用方剂的一组）", d["total"] == exp["total"])
    st, b, _ = c.q("RPT-HERB-USAGE-001", {"prescribeDateFrom": RPT_RNG[0], "prescribeDateTo": RPT_RNG[1],
                                         "statsDimension": "BAD", "page": 1, "size": 5}, token=admin)
    check("统计维度非法值被拒（400）", st == 400, "HTTP %s" % st)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1],
                                          "granularity": "YEAR", "page": 1, "size": 5}, token=admin)
    check("日期粒度模型外取值 YEAR 被拒（400，模型约定 7 仅 DAY/MONTH）", st == 400, "HTTP %s" % st)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1],
                                          "granularity": "WEEK", "page": 1, "size": 5}, token=admin)
    check("日期粒度模型外取值 WEEK 被拒（400）", st == 400, "HTTP %s" % st)

    # ⑤ 就诊与处方记录查询（主从）
    section("⑤ QR-VISIT-PRESCRIPTION-001 就诊与处方记录查询（主从）")
    p = {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "page": 1, "size": 100}
    st, b, _ = c.q("QR-VISIT-PRESCRIPTION-001", p, token=admin)
    if check("查询返回 200", st == 200, b):
        d = b["data"]
        exp = oracle_visit_prescription(*RNG)
        check("主行数（就诊）= oracle", d["total"] == exp["master"], "%s vs %s" % (d["total"], exp["master"]))
        kids = sum(len(r.get("prescriptions") or []) for r in d["list"])
        check("从行合计（处方）= oracle", kids == exp["rx"], "%s vs %s" % (kids, exp["rx"]))
        items = sum(len(rx.get("items") or []) for r in d["list"] for rx in (r.get("prescriptions") or []))
        check("明细合计 = oracle", items == exp["items"], "%s vs %s" % (items, exp["items"]))
        check("masterDetail 元信息存在", bool(d.get("masterDetail")), d.get("masterDetail"))
        check("从表含处方状态字段", all("prescriptionStatus" in rx for r in d["list"] for rx in (r.get("prescriptions") or [])) or kids == 0)

    # ⑥ 超量·毒性台账
    section("⑥ QR-PRESCRIPTION-OVERDOSE-001 超量·毒性台账（触发类型裁剪）")
    for trig in ("BOTH", "OVERDOSE", "TOXIC"):
        p = {"prescribeDateFrom": RPT_RNG[0], "prescribeDateTo": RPT_RNG[1], "triggerType": trig, "page": 1, "size": 100}
        st, b, _ = c.q("QR-PRESCRIPTION-OVERDOSE-001", p, token=admin)
        if check("触发类型 %s 返回 200" % trig, st == 200, b):
            d = b["data"]
            exp = oracle_overdose(*RPT_RNG, trig)
            check("触发类型 %s 行数 = oracle" % trig, d["total"] == exp, "%s vs %s" % (d["total"], exp))
            if d["list"]:
                r = d["list"][0]
                check("触发类型 %s 含超出倍数列" % trig, r.get("exceedRatio") is not None, r.get("exceedRatio"))
    st, b, _ = c.q("QR-PRESCRIPTION-OVERDOSE-001", {"triggerType": "BAD"}, token=admin)
    check("触发类型非法值被拒（400）", st == 400, "HTTP %s" % st)

    # ⑦ 随访完成与失访分析
    section("⑦ RPT-FOLLOWUP-COMPLETION-001 随访完成与失访分析")
    p = {"plannedDateFrom": "2026-08-01", "plannedDateTo": "2026-09-30", "page": 1, "size": 100}
    st, b, _ = c.q("RPT-FOLLOWUP-COMPLETION-001", p, token=admin)
    if check("查询返回 200", st == 200, b):
        d = b["data"]
        exp = oracle_followup("2026-08-01", "2026-09-30")
        check("分组行数 = oracle", d["total"] == exp["total"], "%s vs %s" % (d["total"], exp["total"]))
        s = d.get("summary") or {}
        check("合计 plannedCount = oracle", s.get("plannedCount") == exp["planned"], "%s vs %s" % (s.get("plannedCount"), exp["planned"]))
        check("合计 completedCount = oracle", s.get("completedCount") == exp["completed"], s.get("completedCount"))
        check("合计 lostCount = oracle", s.get("lostCount") == exp["lost"], s.get("lostCount"))
        check("合计 = 分组行之和", sum(r["plannedCount"] for r in d["list"]) == s.get("plannedCount"))

        # 逐分组行独立 oracle：有效率分母＝已完成数（M7 sourceExpression；契约原写「计划」为偏差）——
        # 只比「能返回」测不出分母语义，故同时断言「库中存在分母≠计划数的分组」以证明确实区分了两种口径
        mk = None
        if d["list"]:
            keys = list(d["list"][0].keys())
            mk = ("statPeriod" if "statPeriod" in keys
                  else next((k for k in keys if "month" in k.lower() or "date" in k.lower()), None))
        if check("能找到分组期间列（供逐行 oracle 用）", bool(mk), mk):
            bad, tested, differs = [], 0, 0
            for r in d["list"]:
                g = dict(rows("SELECT SUM(CASE WHEN f.efficacy_level IN ('CURED','MARKED_EFFECT','EFFECTIVE') "
                              "THEN 1 ELSE 0 END) num, "
                              "SUM(CASE WHEN f.record_status = 'COMPLETED' THEN 1 ELSE 0 END) den, "
                              "COUNT(*) planned "
                              "FROM follow_up f LEFT JOIN visit v ON v.id = f.source_visit_id AND v.flag = 1 "
                              "WHERE f.flag = 1 AND strftime('%Y-%m', f.planned_follow_up_date) = ? "
                              "AND IFNULL(v.dept_code, '') = IFNULL(?, '') "
                              "AND IFNULL(v.doctor_id, -1) = IFNULL(?, -1)",
                              (r.get(mk), r.get("deptCode"), r.get("doctorId")))[0])
                if (g["den"] or 0) != (g["planned"] or 0):
                    differs += 1
                want = (float(g["num"]) / g["den"]) if g["den"] else None
                got = r.get("effectiveRatio")
                tested += 1
                ok = (got in (None, 0, 0.0)) if want is None else (got is not None and approx(got, want))
                if not ok:
                    bad.append((r.get(mk), got, want))
            check("有效率逐行 = oracle（分子 ÷ 已完成数，M7 语义）", not bad,
                  ("核对 %d 行，失配 %s" % (tested, bad[:2])) if bad
                  else "核对 %d 行，其中 %d 行分母 ≠ 计划数" % (tested, differs))
            check("分母语义确实被区分（存在「已完成数 ≠ 计划数」的分组）", differs >= 1,
                  "分母 ≠ 计划数的分组：%d" % differs)

    # ⑧ 分页 / 排序 / 负例
    section("⑧ 分页、排序与负例")
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "page": 1, "size": 2}, token=admin)
    check("page=1,size=2 返回 ≤2 行", st == 200 and len(b["data"]["list"]) <= 2, len(b["data"]["list"]) if st == 200 else st)
    check("size 生效回显", st == 200 and b["data"]["size"] == 2, b["data"].get("size") if st == 200 else None)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "page": 1, "size": 9999}, token=admin)
    check("size 超上限截断为 100", st == 200 and b["data"]["size"] == 100, b["data"].get("size") if st == 200 else st)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "size": 0}, token=admin)
    check("size=0 被拒（400）", st == 400, "HTTP %s" % st)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1],
                                          "sortField": "not_a_column", "size": 5}, token=admin)
    check("非法排序字段被拒（400）", st == 400, "HTTP %s" % st)
    st, b, _ = c.q("RPT-NOT-EXIST-001", {}, token=admin)
    check("未知报表码被拒（404/400）", st in (400, 404), "HTTP %s" % st)
    st, b, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "deptCode": "NOT_A_DEPT"}, token=admin)
    check("字典外取值不报 500（返回空或 400）", st in (200, 400), "HTTP %s" % st)
    st, b, _ = c.req("GET", "/api/report/RPT-VISIT-STATS-001", token=None)
    check("未登录访问被拒（401）", st == 401, "HTTP %s" % st)

    # ⑨ 导出
    section("⑨ 导出（XLSX / CSV）")
    st, raw, hdr = c.export("RPT-VISIT-STATS-001", "xlsx", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1]}, token=admin)
    if check("XLSX 导出返回 200", st == 200, "HTTP %s" % st):
        try:
            z = zipfile.ZipFile(_io.BytesIO(raw))
            names = z.namelist()
            check("XLSX 结构完整", "[Content_Types].xml" in names and any(n.startswith("xl/worksheets/") for n in names), names)
            sheet = z.read([n for n in names if n.startswith("xl/worksheets/")][0]).decode("utf-8")
            parseString(sheet)
            check("XLSX 含表头「统计日期」", "统计日期" in sheet)
            check("XLSX 含合计行", "合计" in sheet)
            nrows = sheet.count("<row ")
            stq, bq, _ = c.q("RPT-VISIT-STATS-001", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1], "page": 1, "size": 100}, token=admin)
            exp_rows = bq["data"]["total"] + 2 if stq == 200 else None
            check("XLSX 行数 = 数据行 + 表头 + 合计", nrows == exp_rows, "%s vs %s" % (nrows, exp_rows))
        except Exception as e:
            check("XLSX 可解析", False, e)
        check("导出响应含 Content-Disposition 文件名", "attachment" in (hdr.get("Content-Disposition") or ""), hdr.get("Content-Disposition"))
    st, raw, _ = c.export("RPT-VISIT-STATS-001", "csv", {"registerDateFrom": RNG[0], "registerDateTo": RNG[1]}, token=admin)
    if check("CSV 导出返回 200", st == 200, "HTTP %s" % st):
        text = raw.decode("utf-8-sig")
        check("CSV 含 BOM 与表头", raw[:3] == b"\xef\xbb\xbf" and "统计日期" in text, raw[:6])
        check("CSV 含合计行", "合计" in text)
    st, b, _ = c.export("RPT-VISIT-STATS-001", "pdf", {}, token=admin)
    check("非法导出格式被拒（400）", st == 400, "HTTP %s" % st)

    # ⑩ 随访登记（写路径）
    section("⑩ 复诊随访登记（完成 / 失访 / 权限交叉）")
    pend = rows("SELECT id FROM follow_up WHERE flag = 1 AND record_status = 'PENDING' ORDER BY id LIMIT 2")
    if len(pend) >= 2:
        frow = one("SELECT patient_id FROM follow_up WHERE id = ?", (pend[0]["id"],))
        avisit = one("SELECT id FROM visit WHERE patient_id = ? AND flag = 1 ORDER BY id LIMIT 1", (frow,))
        st, b, _ = c.req("POST", "/api/followup/%d/complete" % pend[0]["id"],
                         token=c.tokens["daozhen"], json_body={"actual_visit_id": avisit,
                                                              "actual_follow_up_date": "2026-09-30",
                                                              "efficacy_level": "EFFECTIVE",
                                                              "symptom_change": "验收用例：症状缓解"})
        check("导诊员完成随访（follow_up:complete）", st == 200 and (b or {}).get("success"), "%s %s" % (st, b))
        st, b, _ = c.req("POST", "/api/followup/%d/complete" % pend[1]["id"],
                         token=c.tokens["keshi"], json_body={"actual_visit_id": avisit,
                                                             "actual_follow_up_date": "2026-09-30",
                                                             "efficacy_level": "EFFECTIVE"})
        check("科室管理员无 follow_up:complete → 403", st == 403, "HTTP %s" % st)
        st, b, _ = c.req("POST", "/api/followup/%d/mark-lost" % pend[1]["id"], token=c.tokens["daozhen"],
                         json_body={"remark": "验收用例：电话三次未接通"})
        check("标记失访路径可用（非 404；成功或按前置中文拒绝）",
              st in (200, 400), "HTTP %s %s" % (st, (b or {}).get("message")))
        st, b, _ = c.req("GET", "/api/followup?page=1&size=5", token=c.tokens["keshi"])
        check("科室管理员可查询随访（权限交叉生效）", st == 200, "HTTP %s %s" % (st, b))
        st, b, _ = c.export("RPT-FOLLOWUP-COMPLETION-001", "csv", {"plannedDateFrom": "2026-08-01", "plannedDateTo": "2026-09-30"},
                            token=c.tokens["keshi"])
        check("科室管理员可导出随访报表（权限交叉生效）", st == 200, "HTTP %s" % st)
    else:
        check("存在待随访记录以测试写路径", False, len(pend))

    # ⑪ 处方作废三分派（UI-17 入口）
    section("⑪ 处方作废三分派（R-04）")
    # 已调剂 → 作废并回冲库存（R-04 第二分支）：先经 service 层真实调剂，再走 UI-17 的作废接口
    from services import dispense_service

    target = rows("SELECT d.id disp_id, p.id rx_id, i.herb_id, h.stock_quantity qty "
                  "FROM dispense_record d JOIN prescription p ON p.id = d.prescription_id AND p.flag = 1 "
                  "JOIN prescription_item i ON i.prescription_id = p.id AND i.flag = 1 "
                  "JOIN herb h ON h.id = i.herb_id AND h.flag = 1 "
                  "WHERE d.flag = 1 AND d.record_status = 'PENDING' AND p.prescription_status = 'APPROVED' LIMIT 1")
    if check("存在待调剂记录（前置数据）", bool(target), len(target)):
        t0 = target[0]
        urow = rows("SELECT * FROM sys_user WHERE username = 'yaoshi'")[0]
        st, b, _ = c.req("POST", "/api/dispense/%d/confirm" % t0["disp_id"], token=c.tokens["yaoshi"],
                         json_body={"remark": "验收：调剂"})
        check("调剂确认成功（进入已调剂）", st == 200, "%s %s" % (st, (b or {}).get("message")))
        rx_status = one("SELECT prescription_status FROM prescription WHERE id = ?", (t0["rx_id"],))
        qty_after_dispense = one("SELECT stock_quantity FROM herb WHERE id = ?", (t0["herb_id"],))
        check("处方状态已调剂 = M1 字典 code DISPENSING", rx_status == "DISPENSING", rx_status)
        st, b, _ = c.req("POST", "/api/prescription/%d/cancel" % t0["rx_id"], token=admin,
                         json_body={"cancel_reason": "验收用例：已调剂作废并回冲"})
        check("已调剂处方作废成功（回冲分派）", st == 200 and (b or {}).get("success"),
              "%s %s" % (st, (b or {}).get("message")))
        qty_after_cancel = one("SELECT stock_quantity FROM herb WHERE id = ?", (t0["herb_id"],))
        rollback = one("SELECT COUNT(*) FROM herb_stock_flow WHERE herb_id = ? AND biz_type = 'VOID_ROLLBACK' AND flag = 1",
                       (t0["herb_id"],))
        check("作废后库存已回冲（> 调剂后库存）", qty_after_cancel > qty_after_dispense,
              "%s → %s" % (qty_after_dispense, qty_after_cancel))
        check("存在作废回冲流水（FLOW_BIZ_TYPE=VOID_ROLLBACK）", (rollback or 0) >= 1, rollback)
        st, b, _ = c.req("POST", "/api/prescription/%d/cancel" % t0["rx_id"], token=admin,
                         json_body={"cancel_reason": "验收：重复作废应阻断"})
        check("已作废处方不可重复作废", not (b or {}).get("success"), (b or {}).get("message"))

    cancelable = rows("SELECT id FROM prescription WHERE flag = 1 AND prescription_status IN ('DRAFT','PENDING_REVIEW','APPROVED') LIMIT 1")
    check("存在可作废处方（前置数据）", bool(cancelable), len(cancelable))
    issued = rows("SELECT id FROM prescription WHERE flag = 1 AND prescription_status = 'ISSUED' LIMIT 1")
    if issued:
        st, b, _ = c.req("POST", "/api/prescription/%d/cancel" % issued[0]["id"], token=admin,
                         json_body={"cancel_reason": "验收：已发药应阻断"})
        msg = str((b or {}).get("message") or "") if isinstance(b, dict) else ""
        check("已发药处方作废被阻断（非 404、非成功、含中文原因）",
              st != 404 and not (b or {}).get("success") and ("发药" in msg or "不能" in msg),
              "HTTP %s %s" % (st, msg))
    if cancelable:
        st2, b2, _ = c.req("POST", "/api/prescription/%d/cancel" % cancelable[0]["id"], token=c.tokens["yaoshi"],
                           json_body={"cancel_reason": "验收：无权限账号"})
        check("中药师无 prescription:cancel → 403", st2 == 403, "HTTP %s" % st2)
        st, b, _ = c.req("POST", "/api/prescription/%d/cancel" % cancelable[0]["id"], token=admin,
                         json_body={"cancel_reason": "验收用例：仅作废"})
        check("可作废处方作废成功（仅作废分派）", st == 200 and (b or {}).get("success"), "%s %s" % (st, (b or {}).get("message")))
        after = one("SELECT prescription_status FROM prescription WHERE id = ?", (cancelable[0]["id"],))
        check("作废后状态为 VOIDED（M1 字典 code）", after == "VOIDED", after)

    print("\n%s" % ("=" * 70))
    print("独立验收结果：通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - %s" % f)
    srv.shutdown()
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
