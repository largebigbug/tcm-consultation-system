# -*- coding: utf-8 -*-
"""批次 3 报表后端自测（6 张报表：查询 / 导出 / 口径 / 权限 / 引擎纪律）。

覆盖 docs/批次3-实现契约.md §3（报表引擎规范）、§4（六张报表口径）、§5（导出）、§8（子代理自测）：
  ① 每张报表的列顺序与 M7 resultColumns 完全一致；
  ② 合计＝全量分组行之和（与直连 SQL oracle 比对）；
  ③ 参数过滤（日期区间 / 科室 / 状态 / 维度 HERB|FORMULA / 触发类型 / 模糊匹配 / IN 多值）；
  ④ 分页与排序（含 size 越界截断、非法 size/page → 400、排序白名单）；
  ⑤ 字典外取值 → 中文报错；未知报表码 → 404；SUBTOTAL→窗口聚合；比率列返回小数；
  ⑥ 导出 XLSX（zipfile + XML 校验）与 CSV（utf-8-sig 解析）、合计行、格式非法 400、导出上限；
  ⑦ 权限矩阵（403 用例）与未登录 401；
  ⑧ 引擎纪律：主表 flag 在 WHERE、LEFT JOIN 表的 flag 在 ON、CTE 内 flag=1、? 参数化绑定。

用法：
  cd code-app/backend && .venv/Scripts/python.exe tools/check_batch3_report.py

隔离纪律：本脚本开头显式 os.environ["APP_DB_PATH"] = data/check_batch3_report.db，
自建 schema + 种子 + 固定数据集，**不读写演示库 data/app.db**。
"""
import copy
import csv
import datetime
import io
import os
import sys
import zipfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DB_PATH = os.path.join(BACKEND, "data", "check_batch3_report.db")
for _suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + _suffix):
        os.remove(DB_PATH + _suffix)
os.environ["APP_DB_PATH"] = DB_PATH
assert "app.db" not in os.path.basename(DB_PATH), "禁止触碰演示库 data/app.db"

from app import app  # noqa: E402

import db  # noqa: E402
from ontology.registry import get_dictionary_items, registry  # noqa: E402
from services import report_service  # noqa: E402

client = app.test_client()
OK, NG = [], []

VISIT_STATS = "RPT-VISIT-STATS-001"
SYNDROME_DIST = "RPT-SYNDROME-DIST-001"
HERB_USAGE = "RPT-HERB-USAGE-001"
VISIT_PRESCRIPTION = "QR-VISIT-PRESCRIPTION-001"
OVERDOSE = "QR-PRESCRIPTION-OVERDOSE-001"
FOLLOWUP = "RPT-FOLLOWUP-COMPLETION-001"
REPORTS = (VISIT_STATS, SYNDROME_DIST, HERB_USAGE, VISIT_PRESCRIPTION, OVERDOSE, FOLLOWUP)


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-66s %s" % ("[通过]" if cond else "[失败]", name, detail))
    return bool(cond)


def sec(title):
    print("\n=== %s ===" % title)


def api(method, path, token=None, query=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    resp = getattr(client, method)(path, headers=headers, query_string=query or {})
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp, body or {}


def login(username, password="123456"):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    body = resp.get_json() or {}
    assert body.get("success"), (username, body)
    return body["data"]["token"]


def data(body):
    return body.get("data") or {}


def msg(body):
    return body.get("message")


def ok(body):
    return bool(body.get("success"))


def expect_fail(body, keyword):
    return (not ok(body)) and (keyword in str(msg(body)))


def get_report(report_code, token, query=None):
    return api("get", "/api/report/" + report_code, token, query)


def oracle(sql, params=()):
    return db.query(sql, params)


# ------------------------------------------------------------------ 固定数据集


def build_fixture():
    """固定数据集：3 患者 / 13 就诊（跨 3 月）/ 3 证型 / 10 辨证 / 4 饮片 / 2 方剂 /
    9 处方 / 18 处方明细 / 10 随访。全部显式时间，避免依赖运行时刻。"""
    conn = db.connect()
    try:
        conn.executemany(
            "INSERT INTO patient (patient_no, patient_name, gender, birth_date, age, phone, patient_status, flag) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', 1)",
            [("PA000101", "张三", "MALE", "1985-03-02", 41, "13800000101"),
             ("PA000102", "李四", "FEMALE", "1990-07-15", 36, "13800000102"),
             ("PA000103", "王五", "MALE", "1965-11-08", 60, "13800000103")])
        conn.executemany(
            "INSERT INTO syndrome_type (syndrome_code, syndrome_name, diagnosis_method, syndrome_status, flag) "
            "VALUES (?, ?, ?, 'ENABLED', 1)",
            [("ZH001", "肝郁气滞证", "ZANGFU"), ("ZH002", "脾胃虚弱证", "ZANGFU"),
             ("ZH003", "风寒束表证", "SIX_MERIDIANS")])
        conn.executemany(
            "INSERT INTO formula_template (formula_code, formula_name, formula_type, default_doses, "
            "formula_status, flag) VALUES (?, ?, ?, 7, 'ENABLED', 1)",
            [("F001", "柴胡疏肝散", "CLASSIC"), ("F002", "补中益气汤", "CLASSIC")])
        conn.executemany(
            "INSERT INTO herb (herb_code, herb_name, herb_category, min_common_dose, max_common_dose, "
            "toxicity_level, stock_quantity, herb_status, flag) VALUES (?, ?, ?, ?, ?, ?, 100, 'ENABLED', 1)",
            [("Y0001", "当归", "TONIFYING", 5, 10, "NONE"),
             ("Y0002", "附子", "WARMING_INTERIOR", 3, 15, "TOXIC"),
             ("Y0003", "细辛", "RELIEVING_EXTERIOR", 1, 3, "SLIGHT"),
             ("Y0004", "川乌", "WARMING_INTERIOR", 1, 3, "HIGHLY_TOXIC")])
        visits = [
            # (visit_no, patient_id, visit_type, register_time, doctor_id, dept_code, visit_status)
            ("ZC000101", 1, "FIRST", "2026-07-03 09:00:00", "2", "TCM_INTERNAL", "COMPLETED"),
            ("ZC000102", 1, "FOLLOW_UP", "2026-07-20 10:00:00", "2", "TCM_INTERNAL", "COMPLETED"),
            ("ZC000103", 2, "FIRST", "2026-07-20 11:00:00", "3", "TCM_GYN", "COMPLETED"),
            ("ZC000104", 1, "FOLLOW_UP", "2026-08-05 09:30:00", "2", "TCM_INTERNAL", "COMPLETED"),
            ("ZC000105", 3, "FIRST", "2026-08-05 14:00:00", "3", "ACUPUNCTURE", "REGISTERED"),
            ("ZC000106", 2, "FOLLOW_UP", "2026-08-18 15:00:00", "2", "TCM_GYN", "COMPLETED"),
            ("ZC000107", 3, "FOLLOW_UP", "2026-09-02 08:30:00", "2", "TCM_INTERNAL", "CANCELLED"),
            ("ZC000108", 1, "FIRST", "2026-09-02 09:00:00", "3", "TCM_INTERNAL", "COMPLETED"),
            ("ZC000109", 2, "FOLLOW_UP", "2026-09-15 10:15:00", "2", "TCM_GYN", "IN_PROGRESS"),
            ("ZC000110", 3, "FIRST", "2026-09-15 11:00:00", "2", "ACUPUNCTURE", "COMPLETED"),
            ("ZC000111", 1, "FOLLOW_UP", "2026-09-15 11:00:00", "3", "TCM_INTERNAL", "COMPLETED"),
            ("ZC000112", 2, "FIRST", "2026-09-28 16:00:00", "2", "TCM_INTERNAL", "REGISTERED"),
            ("ZC000113", 3, "FOLLOW_UP", "2026-09-28 17:00:00", "2", "TCM_INTERNAL", "CANCELLED"),
        ]
        conn.executemany(
            "INSERT INTO visit (visit_no, patient_id, visit_type, register_time, doctor_id, dept_code, "
            "chief_complaint, visit_status, flag) VALUES (?, ?, ?, ?, ?, ?, '自测数据集', ?, 1)", visits)
        diagnoses = [
            # (diagnosis_no, visit_id, method, syndrome_id, nature, status)
            ("BZ000101", 1, "ZANGFU", 1, "PRIMARY", "CONFIRMED"),
            ("BZ000102", 2, "ZANGFU", 1, "PRIMARY", "CONFIRMED"),
            ("BZ000103", 3, "ZANGFU", 2, "PRIMARY", "CONFIRMED"),
            ("BZ000104", 4, "ZANGFU", 1, "PRIMARY", "CONFIRMED"),
            ("BZ000105", 5, "SIX_MERIDIANS", 3, "PRIMARY", "CONFIRMED"),
            ("BZ000106", 6, "ZANGFU", 2, "PRIMARY", "CONFIRMED"),
            ("BZ000107", 8, "ZANGFU", 1, "PRIMARY", "CONFIRMED"),
            ("BZ000108", 9, "ZANGFU", 2, "SECONDARY", "CONFIRMED"),
            ("BZ000109", 10, "ZANGFU", 1, "PRIMARY", "CONFIRMED"),
            ("BZ000110", 11, "ZANGFU", 3, "SECONDARY", "DRAFT"),
        ]
        conn.executemany(
            "INSERT INTO syndrome_diagnosis (diagnosis_no, visit_id, diagnosis_method, syndrome_id, "
            "syndrome_nature, diagnosis_basis, treatment_principle, conclusion_status, flag) "
            "VALUES (?, ?, ?, ?, ?, '自测数据依据不少于十字', '疏肝理气', ?, 1)", diagnoses)
        prescriptions = [
            # (no, visit_id, patient_id, doctor_id, type, formula_id, doses, prescribe_time, status)
            ("CF000101", 1, 1, "2", "HERBAL_DECOCTION", 1, 7, "2026-07-03 09:30:00", "APPROVED"),
            ("CF000102", 2, 1, "2", "HERBAL_DECOCTION", 1, 5, "2026-07-20 10:30:00", "ISSUED"),
            ("CF000103", 3, 2, "3", "HERBAL_DECOCTION", None, 10, "2026-07-20 11:30:00", "DISPENSING"),
            ("CF000104", 4, 1, "2", "HERBAL_DECOCTION", 2, 6, "2026-08-05 10:00:00", "DRAFT"),
            ("CF000105", 5, 3, "3", "HERBAL_DECOCTION", None, 4, "2026-08-05 14:30:00", "VOIDED"),
            ("CF000106", 6, 2, "2", "HERBAL_DECOCTION", 2, 8, "2026-08-18 15:30:00", "APPROVED"),
            ("CF000107", 8, 1, "3", "HERBAL_DECOCTION", 1, 7, "2026-09-02 09:30:00", "ISSUED"),
            ("CF000108", 9, 2, "2", "HERBAL_DECOCTION", None, 3, "2026-09-15 10:45:00", "APPROVED"),
            ("CF000109", 10, 3, "2", "HERBAL_DECOCTION", None, 12, "2026-09-15 11:30:00", "APPROVED"),
            ("CF000110", 11, 1, "3", "GRANULE", None, 6, "2026-09-15 12:00:00", "APPROVED"),
        ]
        conn.executemany(
            "INSERT INTO prescription (prescription_no, visit_id, patient_id, doctor_id, prescription_type, "
            "formula_template_id, doses, usage_method, prescribe_time, prescription_status, reviewer_id, "
            "review_time, flag) VALUES (?, ?, ?, ?, ?, ?, ?, 'DAILY_1_2', ?, ?, '3', ?, 1)",
            [(no, visit, patient, doctor, ptype, formula, doses, ptime, status,
              ptime if status in ("APPROVED", "ISSUED", "DISPENSING") else None)
             for (no, visit, patient, doctor, ptype, formula, doses, ptime, status) in prescriptions])
        items = [
            # (prescription_id, item_id, seq, herb_id, single_dose, decoction, over_dose_reason)
            (1, "IT000101", 1, 1, 9, None, None),
            (1, "IT000102", 2, 3, 2, "LATE_ADD", None),
            (2, "IT000103", 1, 1, 12, None, "先煎"),
            (2, "IT000104", 2, 2, 10, "PRE_DECOCT", None),
            (3, "IT000105", 1, 2, 20, "PRE_DECOCT", "寒证重用"),
            (3, "IT000106", 2, 4, 5, "PRE_DECOCT", "剧毒先煎"),
            (4, "IT000107", 1, 1, 8, None, None),
            (5, "IT000108", 1, 2, 9, None, None),
            (6, "IT000109", 1, 1, 10, None, None),
            (6, "IT000110", 2, 3, 4, None, "细辛超量"),
            (7, "IT000111", 1, 1, 9, None, None),
            (7, "IT000112", 2, 2, 16, "PRE_DECOCT", "寒证重用"),
            (7, "IT000113", 3, 4, 2, "PRE_DECOCT", None),
            (8, "IT000114", 1, 3, 1, None, None),
            (9, "IT000115", 1, 1, 5, None, None),
            (9, "IT000116", 2, 2, 12, None, None),
        ]
        conn.executemany(
            "INSERT INTO prescription_item (prescription_id, item_id, seq_no, herb_id, single_dose, "
            "decoction_method, over_dose_reason, flag) VALUES (?, ?, ?, ?, ?, ?, ?, 1)", items)
        followups = [
            # (no, patient_id, source_visit_id, planned, actual, efficacy, status)
            ("SF0001", 1, 1, "2026-08-10", "2026-08-10", "CURED", "COMPLETED"),
            ("SF0002", 1, 2, "2026-08-20", "2026-08-21", "MARKED_EFFECT", "COMPLETED"),
            ("SF0003", 3, 5, "2026-08-25", None, None, "LOST"),
            ("SF0004", 1, 1, "2026-08-15", None, None, "PENDING"),
            ("SF0005", 1, 4, "2026-09-05", "2026-09-05", "EFFECTIVE", "COMPLETED"),
            ("SF0006", 2, 6, "2026-09-06", None, None, "PENDING"),
            ("SF0007", 3, 10, "2026-09-20", "2026-09-22", "INEFFECTIVE", "COMPLETED"),
            ("SF0008", 2, 9, "2026-09-20", "2026-09-20", "AGGRAVATED", "COMPLETED"),
            ("SF0009", 2, 3, "2026-09-28", None, None, "LOST"),
            ("SF0010", 1, 11, "2026-10-05", None, None, "PENDING"),
        ]
        conn.executemany(
            "INSERT INTO follow_up (follow_up_no, patient_id, source_visit_id, planned_follow_up_date, "
            "actual_follow_up_date, efficacy_level, record_status, flag) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            followups)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ 校验工具


def _col_index(ref):
    letters = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx - 1


def parse_xlsx(payload):
    """zipfile + XML 校验 XLSX，按单元格引用对齐列返回 (rows, sheet_name)。"""
    import re

    assert payload[:2] == b"PK", "XLSX 不是 zip 包"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        for required in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                         "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml"):
            assert required in names, "缺少部件 %s" % required
        wb = zf.read("xl/workbook.xml").decode("utf-8")
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    name = re.search(r'<sheet name="([^"]*)"', wb).group(1)
    rows = []
    for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = {}
        width = 0
        for cell_xml in re.findall(r'<c\s+r="([A-Z]+\d+)"[^>]*?(?:/>|>(.*?)</c>)', row_xml, re.S):
            ref, body = cell_xml[0], cell_xml[1]
            index = _col_index(ref)
            inline = re.search(r"<t[^>]*>(.*?)</t>", body or "", re.S)
            if inline:
                value = inline.group(1)
            else:
                num = re.search(r"<v>(.*?)</v>", body or "", re.S)
                value = num.group(1) if num else ""
            cells[index] = value
            width = max(width, index + 1)
        rows.append([cells.get(i, "") for i in range(width)])
    return rows, name


def parse_csv(payload):
    text = payload.decode("utf-8-sig")
    return [row for row in csv.reader(io.StringIO(text))]


def export_rows(report_code, token, query):
    resp = client.get("/api/report/%s/export" % report_code,
                      headers={"Authorization": "Bearer " + token}, query_string=query or {})
    return resp


# ------------------------------------------------------------------ 主流程


def main():
    build_fixture()
    tk_admin = login("admin", "admin123")
    tk_dao = login("daozhen")
    tk_yi = login("yishi")
    tk_yao = login("yaoshi")
    tk_ke = login("keshi")
    tk_kf = login("kufang")
    today = datetime.date.today()
    month_first = today.replace(day=1).strftime("%Y-%m-%d")

    # ---------------------------------------------------------- 0 元数据/引擎
    sec("0. 元数据与引擎纪律")
    reps = registry["query_reports"]
    check("M7 装载 7 个报表对象（本批 6 张）", len(reps) == 7, "共 %d 个" % len(reps))
    perms = {rid: report_service.permission_code_for_report(reps[rid]) for rid in REPORTS}
    check("权限码由 M7 behaviorRef 派生且与本批口径一致",
          perms == {VISIT_STATS: "visit:query-stats",
                    SYNDROME_DIST: "diagnosis:query-syndrome-distribution",
                    HERB_USAGE: "prescription:query-herb-usage",
                    VISIT_PRESCRIPTION: "visit:query-visit-and-prescription",
                    OVERDOSE: "prescription:query-overdose-review",
                    FOLLOWUP: "follow_up:query-completion"},
          str(perms))
    problems = report_service.validate_metadata(REPORTS)
    check("本批 6 张报表的模型元数据校验（列/条件/Join/分组/排序/字典字面量）", not problems,
          "; ".join(problems[:3]))
    out_of_scope = report_service.validate_metadata(["QR-HERB-STOCK-001"])
    check("批次 4 的 QR-HERB-STOCK-001 不在本批范围（其模型问题照实报出，不静默修改）",
          all("QR-HERB-STOCK-001" in p for p in out_of_scope), str(out_of_scope))

    broken = copy.deepcopy(reps[VISIT_STATS])
    broken["sourceObjects"][0]["alias"] = "visitX"
    try:
        report_service.ReportQuery(broken, {})
        check("白名单外数据源 → 中文异常", False, "未抛异常")
    except report_service.ReportError as e:
        check("白名单外数据源 → 中文异常", "未知数据源" in e.message, e.message)

    broken = copy.deepcopy(reps[VISIT_STATS])
    broken["resultColumns"][0]["sourceExpression"] = "visit.notARealAttr"
    try:
        report_service.ReportQuery(broken, {}).build_sql()
        check("白名单外属性 → 中文异常", False, "未抛异常")
    except report_service.ReportError as e:
        check("白名单外属性 → 中文异常", "不存在属性" in e.message, e.message)

    for report_code in REPORTS:
        sql, params = report_service.compile_sql(report_code, {})
        check("SQL 参数化绑定：%s 的 ? 数目＝绑定值数目" % report_code, sql.count("?") == len(params),
              "?=%d 值=%d" % (sql.count("?"), len(params)))

    sql, _ = report_service.compile_sql(VISIT_STATS, {})
    check("门诊量统计：主表 flag=1 在 WHERE、LEFT JOIN 表 flag=1 在 ON（共 2 处）",
          "WHERE (visit.flag = 1) AND (" in sql and sql.count("flag = 1") == 2,
          "flag=1 出现 %d 次" % sql.count("flag = 1"))
    check("门诊量统计：LEFT JOIN 表的 flag 写在 ON 内",
          "ON (visit.patient_id = patient.id) AND (patient.flag = 1)" in sql, "")
    sql_herb, _ = report_service.compile_sql(HERB_USAGE, {})
    sql_formula, _ = report_service.compile_sql(HERB_USAGE, {"statsDimension": ["FORMULA_TEMPLATE"]})
    check("方剂与饮片：CTE 内 flag = 1（预聚合）", "FROM prescription_item WHERE flag = 1 GROUP BY" in sql_herb, "")
    check("方剂与饮片：SUBTOTAL 已译为窗口聚合 SUM(...) OVER ()（FORMULA 维度分母不受分页影响）",
          "SUBTOTAL(" not in sql_formula and "OVER ()" in sql_formula, "")
    check("方剂与饮片：HERB 维度下引用占比整列置 NULL（不参与窗口分母）",
          "NULL AS formulaRefRatio" in sql_herb, "")
    sql, _ = report_service.compile_sql(SYNDROME_DIST, {})
    check("证型分布：占比列两段式（子查询 + 窗口）且分子分母同条件",
          sql.count("FROM syndrome_diagnosis AS diagnosis") == 1 and "SUM(__den_caseRatio) OVER ()" in sql, "")

    resp, body = get_report("RPT-NOT-EXIST-999", tk_admin)
    check("未知报表码 → 404 中文提示", resp.status_code == 404 and expect_fail(body, "报表不存在"),
          "HTTP %s %s" % (resp.status_code, msg(body)))

    # ---------------------------------------------------------- 1 门诊量统计
    sec("1. RPT-VISIT-STATS-001 门诊量统计")
    q_from, q_to = "2026-07-01", "2026-09-30"
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "size": 100})
    d = data(body)
    expect_cols = [c["name"] for c in reps[VISIT_STATS]["resultColumns"]]
    check("列顺序与 M7 一致（11 列）", [c["name"] for c in d["columns"]] == expect_cols, str([c["name"] for c in d["columns"]]))
    check("列元数据字段齐备（label/dataType/format/sortable/visible）",
          all(set(c) >= {"name", "label", "dataType", "format", "sortable", "visible"} for c in d["columns"]), "")
    check("report 元信息（id/name/alias/objectType/emptyValueDisplay）",
          d["report"]["id"] == VISIT_STATS and d["report"]["objectType"] == "REPORT"
          and d["report"]["emptyValueDisplay"] == "-", str(d["report"]))
    check("masterDetail 为 null（非主从报表）", d["masterDetail"] is None, str(d["masterDetail"]))

    oracle_total = oracle(
        "SELECT COUNT(*) c FROM (SELECT 1 FROM visit WHERE flag = 1 AND date(register_time) BETWEEN date(?) "
        "AND date(?) GROUP BY date(register_time), dept_code, doctor_id, visit_type)", (q_from, q_to))[0]["c"]
    check("total ＝ oracle 分组行数", d["total"] == oracle_total, "接口 %d / oracle %d" % (d["total"], oracle_total))

    oracle_visits = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND date(register_time) BETWEEN "
                           "date(?) AND date(?)", (q_from, q_to))[0]["c"]
    check("就诊人次合计 ＝ oracle 就诊条数", d["summary"]["visitCount"] == oracle_visits,
          "%s / %s" % (d["summary"]["visitCount"], oracle_visits))
    check("summary 等于全量分组行之和（不受分页影响）",
          d["summary"]["visitCount"] == sum(r["visitCount"] for r in d["list"]), "")
    oracle_first = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND visit_type = 'FIRST' AND "
                          "date(register_time) BETWEEN date(?) AND date(?)", (q_from, q_to))[0]["c"]
    oracle_completed = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND visit_status = 'COMPLETED' "
                              "AND date(register_time) BETWEEN date(?) AND date(?)", (q_from, q_to))[0]["c"]
    oracle_cancelled = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND visit_status = 'CANCELLED' "
                              "AND date(register_time) BETWEEN date(?) AND date(?)", (q_from, q_to))[0]["c"]
    check("summary 初诊人次 ＝ oracle", d["summary"]["firstVisitCount"] == oracle_first,
          "%s / %s" % (d["summary"]["firstVisitCount"], oracle_first))
    check("summary 已完成/已取消人次 ＝ oracle",
          d["summary"]["completedCount"] == oracle_completed and d["summary"]["cancelledCount"] == oracle_cancelled,
          "%s/%s" % (d["summary"]["completedCount"], d["summary"]["cancelledCount"]))
    check("summary 键＝M7 totalFields",
          sorted(d["summary"]) == sorted(reps[VISIT_STATS]["reportOptions"]["totalFields"]), str(sorted(d["summary"])))
    check("summary 不含比率列（followUpRatio）", "followUpRatio" not in d["summary"], "")

    row = d["list"][0]
    oracle_row = oracle(
        "SELECT COUNT(DISTINCT patient_id) pc, COUNT(*) vc FROM visit WHERE flag = 1 "
        "AND date(register_time) = date(?) AND dept_code = ? AND doctor_id = ? AND visit_type = ?",
        (row["statDate"], row["deptCode"], row["doctorId"], row["visitType"]))[0]
    check("分组单元格（就诊人数/就诊人次）＝ oracle",
          row["patientCount"] == oracle_row["pc"] and row["visitCount"] == oracle_row["vc"],
          "行=%s" % row)
    expected_ratio = (row["followUpVisitCount"] * 1.0 / row["visitCount"]) if row["visitCount"] else None
    check("复诊占比 ＝ 复诊人次 ÷ 就诊人次（小数，不做百分比化）",
          abs((row["followUpRatio"] or 0) - expected_ratio) < 1e-9 and (row["followUpRatio"] is None or row["followUpRatio"] <= 1),
          "得到 %s 期望 %s" % (row["followUpRatio"], expected_ratio))

    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "granularity": "MONTH", "size": 100})
    months = {r["statDate"] for r in data(body)["list"]}
    check("granularity=MONTH → 统计日期为 yyyy-MM", all(len(m) == 7 and m[4] == "-" for m in months), str(sorted(months)))
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "granularity": "WEEK"})
    check("granularity 非法 → 中文异常", expect_fail(body, "粒度"), str(msg(body)))

    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": "2026-08-01", "registerDateTo": "2026-08-31",
                                              "size": 100})
    aug_total = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND date(register_time) BETWEEN "
                       "date('2026-08-01') AND date('2026-08-31')")[0]["c"]
    check("日期区间过滤生效（8 月）", data(body)["summary"]["visitCount"] == aug_total,
          "%s / %s" % (data(body)["summary"]["visitCount"], aug_total))
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "deptCode": "TCM_GYN", "size": 100})
    check("科室过滤生效（TCM_GYN）", all(r["deptCode"] == "TCM_GYN" for r in data(body)["list"])
          and data(body)["total"] == oracle("SELECT COUNT(*) c FROM (SELECT 1 FROM visit WHERE flag = 1 "
                                            "AND dept_code = 'TCM_GYN' AND date(register_time) BETWEEN date(?) "
                                            "AND date(?) GROUP BY date(register_time), dept_code, doctor_id, "
                                            "visit_type)", (q_from, q_to))[0]["c"], "")
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "visitStatus": "CANCELLED", "size": 100})
    check("就诊状态过滤生效（CANCELLED）", all(r["completedCount"] == 0 for r in data(body)["list"])
          and data(body)["summary"]["cancelledCount"] == oracle(
              "SELECT COUNT(*) c FROM visit WHERE flag = 1 AND visit_status = 'CANCELLED' "
              "AND date(register_time) BETWEEN date(?) AND date(?)", (q_from, q_to))[0]["c"], "")
    _, body = get_report(VISIT_STATS, tk_yi, {"visitType": "FOLLOW_UP"})
    check("就诊类型过滤生效（FOLLOW_UP）", all(r["visitType"] == "FOLLOW_UP" for r in data(body)["list"]), "")
    _, body = get_report(VISIT_STATS, tk_yi, {"deptCode": "INTERNAL"})
    check("字典外取值 → 中文异常（科室）", expect_fail(body, "字典"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"visitType": "初诊"})
    check("字典 label 不被接受（只收 code）→ 中文异常", expect_fail(body, "字典"), str(msg(body)))

    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to, "size": 2})
    check("size=2 → 返回 2 行且 total 为全量", len(data(body)["list"]) == 2 and data(body)["total"] == oracle_total, "")
    _, page2 = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                               "size": 2, "page": 2})
    check("分页 page=2 与 page=1 行不同", data(body)["list"][0] != data(page2)["list"][0], "")
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to, "size": 1000})
    check("size 超上限截断为 100 并返回实际 size", data(body)["size"] == 100, str(data(body)["size"]))
    _, body = get_report(VISIT_STATS, tk_yi, {"size": 0})
    check("size<=0 → 400 中文提示", expect_fail(body, "size"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"size": "abc"})
    check("size 非数字 → 400 中文提示", expect_fail(body, "整数"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"page": 0})
    check("page<=0 → 400 中文提示", expect_fail(body, "page"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to})
    check("默认 page=1 / size=20（M7 pagination）", data(body)["page"] == 1 and data(body)["size"] == 20, "")

    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "size": 100, "sortField": "visitCount", "sortDir": "DESC"})
    counts = [r["visitCount"] for r in data(body)["list"]]
    check("排序 sortField=visitCount DESC 生效", counts == sorted(counts, reverse=True), str(counts))
    _, body = get_report(VISIT_STATS, tk_yi, {"sortField": "visitCount", "sortDir": "XX"})
    check("排序方向非法 → 400 中文提示", expect_fail(body, "排序方向"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"sortField": "patientCount"})
    check("不可排序列 → 400 中文提示", expect_fail(body, "不可排序"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"sortField": "dropTable"})
    check("未知排序字段 → 400 中文提示", expect_fail(body, "排序字段"), str(msg(body)))
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to, "size": 100})
    dates = [r["statDate"] for r in data(body)["list"]]
    check("默认排序＝M7 orderBy（statDate DESC）", dates == sorted(dates, reverse=True), str(dates[:3]))

    # 导出
    resp = export_rows(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to})
    check("导出 XLSX：Content-Type 与文件名（报表名_时间戳）",
          resp.status_code == 200
          and resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          and "filename*=UTF-8''" in resp.headers.get("Content-Disposition", ""),
          "%s | %s" % (resp.mimetype, resp.headers.get("Content-Disposition")))
    rows, sheet = parse_xlsx(resp.data)
    check("导出 XLSX 可解析且表头＝列 label（11 列）",
          rows and rows[0] == [c["label"] for c in data(body)["columns"]], "sheet=%s 表头=%s" % (sheet, rows[0] if rows else None))
    check("导出 XLSX 数据行数＝分组行数，末行合计（首列「合计」）",
          len(rows) == oracle_total + 2 and rows[-1][0] == "合计", "行数=%d" % len(rows))
    check("导出 XLSX 合计行数值＝summary（就诊人次）",
          str(d["summary"]["visitCount"]) == rows[-1][5], "合计列=%s vs %s" % (rows[-1][5], d["summary"]["visitCount"]))
    resp = export_rows(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to, "format": "csv"})
    csv_rows = parse_csv(resp.data)
    check("导出 CSV 可解析（utf-8-sig）表头与行数一致",
          csv_rows[0] == rows[0] and len(csv_rows) == len(rows) and csv_rows[-1][0] == "合计",
          "行数=%d" % len(csv_rows))
    resp = export_rows(VISIT_STATS, tk_yi, {"format": "pdf"})
    check("导出格式非法 → 400 中文提示", resp.status_code == 400 and expect_fail(resp.get_json(), "导出格式"),
          "HTTP %s" % resp.status_code)

    # ---------------------------------------------------------- 2 证型分布统计
    sec("2. RPT-SYNDROME-DIST-001 证型分布统计")
    d_from, d_to = "2026-07-01", "2026-09-30"
    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to, "size": 100})
    d = data(body)
    check("列顺序与 M7 一致（6 列）",
          [c["name"] for c in d["columns"]] == [c["name"] for c in reps[SYNDROME_DIST]["resultColumns"]], "")
    oracle_total = oracle("SELECT COUNT(*) c FROM (SELECT 1 FROM syndrome_diagnosis d JOIN visit v ON "
                          "v.id = d.visit_id WHERE d.flag = 1 AND v.flag = 1 AND date(v.register_time) "
                          "BETWEEN date(?) AND date(?) GROUP BY d.syndrome_id, d.syndrome_nature)", (d_from, d_to))[0]["c"]
    check("total ＝ oracle 分组行数", d["total"] == oracle_total, "%d / %d" % (d["total"], oracle_total))
    oracle_cases = oracle("SELECT COUNT(*) c FROM syndrome_diagnosis d JOIN visit v ON v.id = d.visit_id "
                          "WHERE d.flag = 1 AND v.flag = 1 AND date(v.register_time) BETWEEN date(?) AND date(?)",
                          (d_from, d_to))[0]["c"]
    check("summary.caseCount ＝ oracle 辨证例数（合计＝分组行之和）",
          d["summary"]["caseCount"] == oracle_cases
          and d["summary"]["caseCount"] == sum(r["caseCount"] for r in d["list"]), "%s / %s" % (d["summary"]["caseCount"], oracle_cases))
    ratios_ok = all(abs((r["caseRatio"] or 0) - r["caseCount"] * 1.0 / oracle_cases) < 1e-9 for r in d["list"])
    check("占比 ＝ 该分组例数 ÷ 全量例数（SUBTOTAL→窗口聚合，分母同条件）", ratios_ok,
          str([(r["syndromeCode"], r["caseCount"], r["caseRatio"]) for r in d["list"]]))
    check("占比之和 ≈ 1（0~1 小数，不做百分比化）", abs(sum(r["caseRatio"] or 0 for r in d["list"]) - 1) < 1e-9, "")
    check("证型编码/名称来自证型字典（LEFT JOIN 命中）",
          all(r["syndromeCode"] and r["syndromeName"] for r in d["list"]), str([r["syndromeCode"] for r in d["list"]]))
    check("默认排序＝辨证例数 DESC", [r["caseCount"] for r in d["list"]] == sorted(
        [r["caseCount"] for r in d["list"]], reverse=True), "")
    check("summary 键＝M7 totalFields（仅 caseCount）",
          list(d["summary"]) == reps[SYNDROME_DIST]["reportOptions"]["totalFields"], str(list(d["summary"])))

    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to,
                                                "syndromeNature": "SECONDARY", "size": 100})
    check("证型性质过滤生效（SECONDARY）", all(r["syndromeNature"] == "SECONDARY" for r in data(body)["list"])
          and data(body)["total"] > 0, "")
    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to,
                                                "syndromeId": "1,2", "size": 100})
    check("证型过滤（IN 多值）生效", all(r["syndromeCode"] in ("ZH001", "ZH002") for r in data(body)["list"]), "")
    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to,
                                                "diagnosisMethod": "ZANGFU", "size": 100})
    oracle_zf = oracle("SELECT COUNT(*) c FROM syndrome_diagnosis d JOIN visit v ON v.id = d.visit_id "
                       "WHERE d.flag = 1 AND v.flag = 1 AND d.diagnosis_method = 'ZANGFU' AND "
                       "date(v.register_time) BETWEEN date(?) AND date(?)", (d_from, d_to))[0]["c"]
    check("辨证体系过滤按模型作用在「辨证记录」上（C03 diagnosis.diagnosisMethod）",
          data(body)["summary"]["caseCount"] == oracle_zf, "%s / %s"
          % (data(body)["summary"]["caseCount"], oracle_zf))
    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to,
                                                "deptCode": "TCM_GYN", "doctorId": "2", "size": 100})
    check("科室+医师过滤生效（TCM_GYN/2）", data(body)["total"] >= 1, "行数=%s" % data(body)["total"])
    _, body = get_report(SYNDROME_DIST, tk_ke, {"syndromeNature": "PRIMARY_X"})
    check("证型性质字典外取值 → 中文异常", expect_fail(body, "字典"), str(msg(body)))
    resp = export_rows(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to})
    rows2, _ = parse_xlsx(resp.data)
    check("导出 XLSX 含占比列小数（未百分比化）",
          any(r[len(r) - 1].replace(".", "").isdigit() for r in rows2[1:-1]), str(rows2[1] if len(rows2) > 1 else None))

    # ---------------------------------------------------------- 3 方剂与饮片使用
    sec("3. RPT-HERB-USAGE-001 方剂与饮片使用统计")
    h_from, h_to = "2026-07-01", "2026-09-30"
    status_list = [p.strip() for p in reps[HERB_USAGE]["conditions"][2]["fixedValue"].strip("[]").split(",")]
    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to, "size": 100})
    d = data(body)
    check("列顺序与 M7 一致（14 列）",
          [c["name"] for c in d["columns"]] == [c["name"] for c in reps[HERB_USAGE]["resultColumns"]], "")
    check("默认维度 HERB：方剂列全部置空",
          all(r["formulaCode"] is None and r["formulaName"] is None and r["formulaType"] is None
              and r["formulaRefCount"] is None and r["formulaRefRatio"] is None for r in d["list"]), "")
    check("默认维度 HERB：饮片列有效（无明细处方形成饮片 NULL 组 —— M7 J01 为 LEFT JOIN）",
          all((r["herbCode"] is None) or (r["herbName"] and r["herbCategory"]) for r in d["list"])
          and any(r["herbCode"] for r in d["list"]) and any(r["herbCode"] is None for r in d["list"]),
          str([r["herbCode"] for r in d["list"]]))
    oracle_total = oracle(
        "SELECT COUNT(*) c FROM (SELECT 1 FROM prescription p LEFT JOIN prescription_item i ON "
        "i.prescription_id = p.id AND i.flag = 1 LEFT JOIN herb h ON h.id = i.herb_id AND h.flag = 1 "
        "WHERE p.flag = 1 AND date(p.prescribe_time) BETWEEN date(?) AND date(?) AND p.prescription_status "
        "IN ('APPROVED','DISPENSING','ISSUED') GROUP BY h.herb_code, h.herb_name, h.herb_category, "
        "h.toxicity_level)", (h_from, h_to))[0]["c"]
    check("total ＝ oracle 分组行数（含常量条件 C03 仅统计已通过/已调剂/已发药）",
          d["total"] == oracle_total, "%d / %d" % (d["total"], oracle_total))
    check("常量条件 C03 生效：DRAFT/VOIDED 处方未计入（其药味未出现在结果中）",
          oracle("SELECT COUNT(DISTINCT herb_id) c FROM prescription_item i JOIN prescription p ON p.id = "
                 "i.prescription_id WHERE p.prescription_status IN ('DRAFT','VOIDED') AND i.flag = 1")[0]["c"] > 0
          and all(r["totalQuantity"] is None or r["doseCount"] > 0 for r in d["list"]), "")
    row = None
    for r in d["list"]:
        if r["herbCode"] == "Y0001":
            row = r
    oracle_qty = oracle(
        "SELECT SUM(i.single_dose * p.doses) q, SUM(p.doses) ds, COUNT(DISTINCT p.prescription_no) pc, "
        "COUNT(DISTINCT p.patient_id) pt FROM prescription p JOIN prescription_item i ON "
        "i.prescription_id = p.id AND i.flag = 1 JOIN herb h ON h.id = i.herb_id AND h.flag = 1 "
        "WHERE p.flag = 1 AND h.herb_code = 'Y0001' AND date(p.prescribe_time) BETWEEN date(?) AND date(?) "
        "AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED')", (h_from, h_to))[0]
    check("累计用量/使用剂数/涉及处方张数/患者数 ＝ oracle",
          row and abs(row["totalQuantity"] - oracle_qty["q"]) < 1e-6
          and row["doseCount"] == oracle_qty["ds"] and row["prescriptionCount"] == oracle_qty["pc"]
          and row["patientCount"] == oracle_qty["pt"],
          "行=%s oracle=%s" % (row, oracle_qty))
    check("单剂平均用量 ＝ 累计用量 ÷ 使用剂数（浮点）",
          row and abs(row["avgSingleDose"] - row["totalQuantity"] * 1.0 / row["doseCount"]) < 1e-9, "")
    def _col_sum(rows, key):
        return sum(r[key] or 0 for r in rows)

    check("summary ＝ 全量分组行之和（数值列各自求和，NULL 视作不计）",
          d["summary"]["doseCount"] == _col_sum(d["list"], "doseCount")
          and d["summary"]["prescriptionCount"] == _col_sum(d["list"], "prescriptionCount")
          and abs(d["summary"]["totalQuantity"] - _col_sum(d["list"], "totalQuantity")) < 1e-6,
          str(d["summary"]))
    check("summary 键＝M7 totalFields", sorted(d["summary"]) == sorted(
        reps[HERB_USAGE]["reportOptions"]["totalFields"]), str(sorted(d["summary"])))

    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to,
                                             "statsDimension": "FORMULA_TEMPLATE", "size": 100})
    f = data(body)
    check("维度 FORMULA：饮片列与饮片预聚合列置空",
          all(r["herbCode"] is None and r["herbName"] is None and r["herbCategory"] is None
              and r["toxicityLevel"] is None and r["totalQuantity"] is None and r["avgSingleDose"] is None
              for r in f["list"]), str(f["list"][0]))
    check("维度 FORMULA：引用张数 ＝ oracle（按方剂编码分组，含未指定方剂组）",
          all(r["formulaRefCount"] == oracle(
                  "SELECT COUNT(DISTINCT p.prescription_no) c FROM prescription p LEFT JOIN formula_template ft "
                  "ON ft.id = p.formula_template_id AND ft.flag = 1 WHERE p.flag = 1 AND "
                  "(ft.formula_code = ? OR (ft.formula_code IS NULL AND ? IS NULL)) AND "
                  "date(p.prescribe_time) BETWEEN date(?) AND date(?) AND p.prescription_status IN "
                  "('APPROVED','DISPENSING','ISSUED')", (r["formulaCode"], r["formulaCode"], h_from, h_to))[0]["c"]
              for r in f["list"]) and any(r["formulaCode"] is None for r in f["list"]),
          str([(r["formulaCode"], r["formulaRefCount"]) for r in f["list"]]))
    check("维度 FORMULA：引用占比 ＝ 引用张数 ÷ 全量引用张数（窗口分母）",
          all(abs((r["formulaRefRatio"] or 0) - r["formulaRefCount"] * 1.0 / f["summary"]["formulaRefCount"]) < 1e-9
              for r in f["list"]) and abs(sum(r["formulaRefRatio"] or 0 for r in f["list"]) - 1) < 1e-9,
          str([r["formulaRefRatio"] for r in f["list"]]))
    check("维度 FORMULA：分组按方剂（LEFT JOIN 方剂表，未指定方剂归入 NULL 组）",
          f["total"] == oracle("SELECT COUNT(*) c FROM (SELECT 1 FROM prescription p LEFT JOIN formula_template ft "
                               "ON ft.id = p.formula_template_id AND ft.flag = 1 WHERE p.flag = 1 AND "
                               "date(p.prescribe_time) BETWEEN date(?) AND date(?) AND p.prescription_status IN "
                               "('APPROVED','DISPENSING','ISSUED') GROUP BY ft.formula_code, ft.formula_name, "
                               "ft.formula_type)", (h_from, h_to))[0]["c"] and f["total"] == 3, "total=%s" % f["total"])
    _, body = get_report(HERB_USAGE, tk_ke, {"statsDimension": "BY_WEIGHT"})
    check("统计维度非法 → 中文异常", expect_fail(body, "取值非法"), str(msg(body)))

    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to,
                                             "herbId": "Y0002"})
    by_code = data(body)
    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to, "herbId": "2"})
    by_id = data(body)
    check("饮片过滤：业务编号与主键 id 等价命中同一饮片",
          by_code["total"] == 1 and [r["herbCode"] for r in by_code["list"]] == ["Y0002"]
          and [r["herbCode"] for r in by_id["list"]] == ["Y0002"], str([r["herbCode"] for r in by_id["list"]]))
    _, body = get_report(HERB_USAGE, tk_ke, {"herbCategory": "NOT_A_CATEGORY"})
    check("饮片类别字典外取值 → 中文异常", expect_fail(body, "字典"), str(msg(body)))
    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": "2026-09-01", "prescribeDateTo": "2026-09-30"})
    oracle_sep = oracle(
        "SELECT SUM(s) t FROM (SELECT SUM(p.doses) s FROM prescription p LEFT JOIN prescription_item i ON "
        "i.prescription_id = p.id AND i.flag = 1 LEFT JOIN herb h ON h.id = i.herb_id AND h.flag = 1 WHERE "
        "p.flag = 1 AND p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') AND "
        "date(p.prescribe_time) BETWEEN date('2026-09-01') AND date('2026-09-30') GROUP BY h.herb_code, "
        "h.herb_name, h.herb_category, h.toxicity_level)")[0]["t"]
    check("日期过滤生效（仅 9 月）且合计＝分组行之和",
          data(body)["summary"]["doseCount"] == oracle_sep, "%s / %s"
          % (data(body)["summary"]["doseCount"], oracle_sep))
    resp = export_rows(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to})
    rows3, _ = parse_xlsx(resp.data)
    check("导出 XLSX（HERB 维度）列数 14 + 合计行",
          len(rows3[0]) == 14 and rows3[-1][0] == "合计" and len(rows3) == d["total"] + 2,
          "列数=%d 行数=%d" % (len(rows3[0]), len(rows3)))

    # ---------------------------------------------------------- 4 就诊与处方记录查询（主从）
    sec("4. QR-VISIT-PRESCRIPTION-001 就诊与处方记录查询（主从三级）")
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                      "registerDateTo": "2026-09-30", "size": 100})
    d = data(body)
    check("列顺序与 M7 一致（27 列）",
          [c["name"] for c in d["columns"]] == [c["name"] for c in reps[VISIT_PRESCRIPTION]["resultColumns"]], "")
    check("masterDetail 结构（level/childKey/childColumns/grandchildKey/grandchildColumns/detailRowKey）",
          d["masterDetail"] and d["masterDetail"]["level"] == "VISIT"
          and d["masterDetail"]["childKey"] == "prescriptions"
          and d["masterDetail"]["grandchildKey"] == "items"
          and d["masterDetail"]["detailRowKey"] == "id", str(d["masterDetail"] and list(d["masterDetail"])))
    child_names = [c["name"] for c in (d["masterDetail"] or {}).get("childColumns", [])]
    check("childColumns ＝ 处方层 M7 列（含 itemAgg 聚合列）",
          child_names == ["prescriptionNo", "prescriptionStatus", "prescriptionType", "doses", "usageMethod",
                          "prescribeTime", "reviewerId", "reviewTime", "rejectReason",
                          "itemsPerPrescription", "prescriptionTotalDose"], str(child_names))
    grand_names = [c["name"] for c in (d["masterDetail"] or {}).get("grandchildColumns", [])]
    check("grandchildColumns ＝ 明细层 M7 列（药味名称/单剂剂量/特殊煎法）",
          grand_names == ["itemHerbName", "itemSingleDose", "itemDecoctionMethod"], str(grand_names))
    check("summary 为 null（该报表 M7 无 totalFields）", d["summary"] is None, str(d["summary"]))
    oracle_visits = oracle("SELECT COUNT(*) c FROM visit WHERE flag = 1 AND date(register_time) BETWEEN "
                           "date('2026-07-01') AND date('2026-09-30')")[0]["c"]
    check("分页作用于主行（就诊）：total ＝ oracle 就诊数", d["total"] == oracle_visits,
          "%d / %d" % (d["total"], oracle_visits))
    master = [r for r in d["list"] if r["prescriptions"]]
    check("主行携带 prescriptions[]，处方行含 id/prescriptionStatus/cancelReason",
          master and master[0]["prescriptions"][0]["id"]
          and "prescriptionStatus" in master[0]["prescriptions"][0]
          and "cancelReason" in master[0]["prescriptions"][0], str(master[0] if master else None))
    check("处方行携带 items[]（明细）",
          any(p["items"] for r in master for p in r["prescriptions"]), "")
    oracle_items = oracle(
        "SELECT COUNT(*) c FROM visit v JOIN prescription p ON p.visit_id = v.id AND p.flag = 1 "
        "JOIN prescription_item i ON i.prescription_id = p.id AND i.flag = 1 WHERE v.flag = 1 AND "
        "date(v.register_time) BETWEEN date('2026-07-01') AND date('2026-09-30')")[0]["c"]
    got_items = sum(len(p["items"]) for r in master for p in r["prescriptions"])
    check("明细行数 ＝ oracle 明细条数", got_items == oracle_items, "%d / %d" % (got_items, oracle_items))
    oracle_agg = oracle(
        "SELECT p.id pid, COUNT(i.id) c, SUM(i.single_dose) s FROM prescription p LEFT JOIN "
        "prescription_item i ON i.prescription_id = p.id AND i.flag = 1 WHERE p.flag = 1 GROUP BY p.id")[0]
    child = None
    for r in master:
        for p in r["prescriptions"]:
            if p["id"] == oracle_agg["pid"]:
                child = p
    check("从表聚合列（处方药味数/处方总量）＝ oracle itemAgg 预聚合",
          child and child["itemsPerPrescription"] == oracle_agg["c"]
          and abs((child["prescriptionTotalDose"] or 0) - (oracle_agg["s"] or 0) * child["doses"]) < 1e-6,
          str(child and {k: child[k] for k in ("itemsPerPrescription", "prescriptionTotalDose", "doses")}))
    visit_agg = oracle("SELECT v.id vid, COUNT(p.id) c, SUM(p.doses) s FROM visit v LEFT JOIN "
                       "prescription p ON p.visit_id = v.id AND p.flag = 1 WHERE v.flag = 1 GROUP BY v.id")
    agg_map = {r["vid"]: r for r in visit_agg}
    ok_agg = all(
        (r["visitPrescriptionCount"] == agg_map[r["id"]]["c"] and r["visitDoseTotal"] == agg_map[r["id"]]["s"])
        if agg_map[r["id"]]["c"] else (r["visitPrescriptionCount"] is None and r["visitDoseTotal"] is None)
        for r in d["list"])
    check("主行聚合列＝oracle visitPrescriptionAgg（无处方就诊按 M7 nullable 返回 null）", ok_agg,
          str([(r["visitNo"], r["visitPrescriptionCount"], r["visitDoseTotal"]) for r in d["list"]][:4]))

    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                      "registerDateTo": "2026-09-30",
                                                      "patientName": "张", "size": 100})
    check("患者姓名包含匹配（LIKE）", all(r["patientName"] == "张三" for r in data(body)["list"])
          and data(body)["total"] == 5, "total=%s" % data(body)["total"])
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"visitNo": "ZC000108"})
    check("就诊号过滤（LIKE）命中单条", data(body)["total"] == 1
          and data(body)["list"][0]["visitNo"] == "ZC000108", "")
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"prescriptionNo": "CF000107"})
    check("处方号过滤（LIKE）命中主行", data(body)["total"] == 1
          and data(body)["list"][0]["prescriptions"][0]["prescriptionNo"] == "CF000107", "")
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                      "registerDateTo": "2026-09-30",
                                                      "prescriptionStatus": "ISSUED", "size": 100})
    check("处方状态 IN 过滤生效（ISSUED）",
          all(p["prescriptionStatus"] == "ISSUED" for r in data(body)["list"] for p in r["prescriptions"]), "")
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                      "registerDateTo": "2026-09-30",
                                                      "visitStatus": "CANCELLED", "size": 100})
    check("就诊状态 IN 过滤生效（CANCELLED）",
          all(r["visitStatus"] == "CANCELLED" for r in data(body)["list"]), "")
    _, body = get_report(VISIT_PRESCRIPTION, tk_dao, {"prescriptionStatus": "PAID"})
    check("处方状态字典外取值 → 中文异常", expect_fail(body, "字典"), str(msg(body)))
    _, b1 = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                    "registerDateTo": "2026-09-30", "size": 2})
    check("主行分页：size=2 → 2 个主行且 total 为就诊数", len(data(b1)["list"]) == 2
          and data(b1)["total"] == oracle_visits, "")
    _, b2 = get_report(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                    "registerDateTo": "2026-09-30",
                                                    "sortField": "visitNo", "sortDir": "ASC", "size": 100})
    nos = [r["visitNo"] for r in data(b2)["list"]]
    check("排序 sortField=visitNo ASC 生效", nos == sorted(nos), str(nos[:4]))
    resp = export_rows(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-07-01",
                                                    "registerDateTo": "2026-09-30"})
    rows4, _ = parse_xlsx(resp.data)
    per_prescription = oracle(
        "SELECT SUM(CASE WHEN c = 0 THEN 1 ELSE c END) s FROM (SELECT p.id pid, (SELECT COUNT(*) FROM "
        "prescription_item i WHERE i.prescription_id = p.id AND i.flag = 1) c FROM visit v JOIN prescription p "
        "ON p.visit_id = v.id AND p.flag = 1 WHERE v.flag = 1 AND date(v.register_time) BETWEEN date('2026-07-01') "
        "AND date('2026-09-30'))")[0]["s"]
    no_rx_visits = oracle("SELECT COUNT(*) c FROM visit v WHERE v.flag = 1 AND date(v.register_time) BETWEEN "
                          "date('2026-07-01') AND date('2026-09-30') AND NOT EXISTS (SELECT 1 FROM prescription p "
                          "WHERE p.visit_id = v.id AND p.flag = 1)")[0]["c"]
    check("导出扁平化（一行一味）：行数 ＝ Σ max(1, 处方明细数) + 无处方主行数",
          len(rows4[0]) == 27 and len(rows4) - 1 == per_prescription + no_rx_visits,
          "数据行=%d 期望=%d（明细展开 %d + 无处方 %d）" % (len(rows4) - 1, per_prescription + no_rx_visits,
                                                          per_prescription, no_rx_visits))
    check("导出扁平化：处方列重复填充 / 合计行不存在（无 totalFields）",
          rows4[-1][0] != "合计" and abs(len([r for r in rows4[1:] if r and r[0]])) > 0, str(rows4[-1][:2]))

    # ---------------------------------------------------------- 5 超量·毒性台账
    sec("5. QR-PRESCRIPTION-OVERDOSE-001 超量·毒性处方审核台账")
    _, body = get_report(OVERDOSE, tk_yao, {"size": 100})
    d = data(body)
    check("列顺序与 M7 一致（14 列）",
          [c["name"] for c in d["columns"]] == [c["name"] for c in reps[OVERDOSE]["resultColumns"]], "")
    check("summary/masterDetail 为 null", d["summary"] is None and d["masterDetail"] is None, "")
    oracle_both = oracle(
        "SELECT COUNT(*) c FROM prescription p JOIN prescription_item i ON i.prescription_id = p.id AND "
        "i.flag = 1 JOIN herb h ON h.id = i.herb_id AND h.flag = 1 WHERE p.flag = 1 AND "
        "(i.single_dose > h.max_common_dose OR h.toxicity_level <> 'NONE')")[0]["c"]
    check("triggerType=BOTH（默认）：total ＝ oracle（超量 OR 毒性，INNER JOIN 明细与饮片）",
          d["total"] == oracle_both, "%d / %d" % (d["total"], oracle_both))
    check("毒性判定按 M7 C04（toxicity_level <> NONE，含 SLIGHT）——与契约 §4.5 的 TOXIC/HIGHLY_TOXIC 有偏差，见交付报告",
          {r["toxicityLevel"] for r in d["list"]} >= {"SLIGHT", "TOXIC", "HIGHLY_TOXIC"},
          str(sorted({r["toxicityLevel"] for r in d["list"]})))
    row = None
    for r in d["list"]:
        if r["prescriptionNo"] == "CF000103":
            row = r
    check("超出倍数 ＝ 单剂剂量 ÷ 常用最大量（浮点小数）",
          row and abs(row["exceedRatio"] - row["singleDose"] * 1.0 / row["maxCommonDose"]) < 1e-9,
          str(row and (row["singleDose"], row["maxCommonDose"], row["exceedRatio"])))
    check("排序＝开方日期 DESC，其次超出倍数 DESC（M7 orderBy）",
          [r["prescribeDate"] for r in d["list"]] == sorted([r["prescribeDate"] for r in d["list"]], reverse=True), "")
    no_items = oracle("SELECT id, prescription_no FROM prescription WHERE flag = 1 AND id NOT IN "
                      "(SELECT prescription_id FROM prescription_item WHERE flag = 1)")[0]
    check("无明细的处方不出现（INNER JOIN 语义）",
          all(r["prescriptionNo"] != no_items["prescription_no"] for r in d["list"]), no_items["prescription_no"])
    _, body = get_report(OVERDOSE, tk_yao, {"triggerType": "OVERDOSE", "size": 100})
    overdose_rows = data(body)
    check("triggerType=OVERDOSE：仅超量行且 ＝ oracle",
          overdose_rows["total"] == oracle(
              "SELECT COUNT(*) c FROM prescription p JOIN prescription_item i ON i.prescription_id = p.id AND "
              "i.flag = 1 JOIN herb h ON h.id = i.herb_id AND h.flag = 1 WHERE p.flag = 1 AND "
              "i.single_dose > h.max_common_dose")[0]["c"]
          and all(r["singleDose"] > r["maxCommonDose"] for r in overdose_rows["list"]),
          "total=%s" % overdose_rows["total"])
    _, body = get_report(OVERDOSE, tk_yao, {"triggerType": "TOXIC", "size": 100})
    toxic_rows = data(body)
    check("triggerType=TOXIC：仅毒性行且 ＝ oracle",
          toxic_rows["total"] == oracle(
              "SELECT COUNT(*) c FROM prescription p JOIN prescription_item i ON i.prescription_id = p.id AND "
              "i.flag = 1 JOIN herb h ON h.id = i.herb_id AND h.flag = 1 WHERE p.flag = 1 AND "
              "h.toxicity_level <> 'NONE'")[0]["c"]
          and all(r["toxicityLevel"] != "NONE" for r in toxic_rows["list"]), "total=%s" % toxic_rows["total"])
    check("OVERDOSE/TOXIC 为 BOTH 的真子集", overdose_rows["total"] + toxic_rows["total"] >= d["total"]
          and overdose_rows["total"] < d["total"] and toxic_rows["total"] < d["total"], "")
    _, body = get_report(OVERDOSE, tk_yao, {"triggerType": "NEVER"})
    check("触发类型非法 → 中文异常", expect_fail(body, "取值非法"), str(msg(body)))
    _, body = get_report(OVERDOSE, tk_yao, {"reviewerId": "3", "size": 100})
    check("审核药师过滤生效", all(r["reviewerId"] == "3" for r in data(body)["list"]), "")
    _, body = get_report(OVERDOSE, tk_yao, {"prescriptionStatus": "APPROVED", "size": 100})
    check("处方状态过滤生效（APPROVED）", all(r["prescriptionStatus"] == "APPROVED"
                                            for r in data(body)["list"]), "")
    resp = export_rows(OVERDOSE, tk_yao, {"format": "csv"})
    csv5 = parse_csv(resp.data)
    check("导出 CSV 行数 ＝ total+1（无合计行）", len(csv5) == d["total"] + 1, "行数=%d" % len(csv5))

    # ---------------------------------------------------------- 6 随访完成与失访
    sec("6. RPT-FOLLOWUP-COMPLETION-001 随访完成与失访分析")
    f_from, f_to = "2026-08-01", "2026-10-31"
    _, body = get_report(FOLLOWUP, tk_ke, {"plannedDateFrom": f_from, "plannedDateTo": f_to, "size": 100})
    d = data(body)
    check("列顺序与 M7 一致（14 列）",
          [c["name"] for c in d["columns"]] == [c["name"] for c in reps[FOLLOWUP]["resultColumns"]], "")
    oracle_total = oracle(
        "SELECT COUNT(*) c FROM (SELECT 1 FROM follow_up f JOIN visit v ON v.id = f.source_visit_id AND "
        "v.flag = 1 WHERE f.flag = 1 AND date(f.planned_follow_up_date) BETWEEN date(?) AND date(?) "
        "GROUP BY strftime('%Y-%m', f.planned_follow_up_date), v.dept_code, v.doctor_id)", (f_from, f_to))[0]["c"]
    check("total ＝ oracle 分组行数（计划月份+科室+医师）", d["total"] == oracle_total,
          "%d / %d" % (d["total"], oracle_total))
    oracle_planned = oracle("SELECT COUNT(*) c FROM follow_up f JOIN visit v ON v.id = f.source_visit_id AND "
                            "v.flag = 1 WHERE f.flag = 1 AND date(f.planned_follow_up_date) BETWEEN date(?) "
                            "AND date(?)", (f_from, f_to))[0]["c"]
    check("summary.plannedCount ＝ oracle 计划随访数（＝分组行之和）",
          d["summary"]["plannedCount"] == oracle_planned
          and d["summary"]["plannedCount"] == sum(r["plannedCount"] for r in d["list"]), "")
    check("summary 键＝M7 totalFields（8 列，不含比率列）",
          sorted(d["summary"]) == sorted(reps[FOLLOWUP]["reportOptions"]["totalFields"])
          and "completionRatio" not in d["summary"], str(sorted(d["summary"])))
    aug = None
    for r in d["list"]:
        if r["statPeriod"] == "2026-08" and r["deptCode"] == "TCM_INTERNAL":
            aug = r
    check("完成率/失访率/有效率返回 0~1 小数（2/3 不截断为 0）",
          aug and abs(aug["completionRatio"] - 2.0 / 3) < 1e-9 and abs(aug["lostRatio"] - 0) < 1e-9
          and abs(aug["effectiveRatio"] - 1.0) < 1e-9, str(aug))
    check("率值由本行分组成分计算（完成率＝已完成÷计划；有效率分母＝已完成 —— 以 M7 表达式为准，契约 §4.6 写「计划」为偏差）",
          all(abs((r["completionRatio"] or 0) - r["completedCount"] * 1.0 / r["plannedCount"]) < 1e-9
              for r in d["list"])
          and all(abs((r["effectiveRatio"] or 0) - (r["curedCount"] + r["markedEffectCount"]
                                                    + r["effectiveCount"]) * 1.0 / r["completedCount"]) < 1e-9
                  for r in d["list"] if r["completedCount"]), "")
    check("各疗效等级条件计数之和 ≤ 已完成数（口径自洽）",
          all(r["curedCount"] + r["markedEffectCount"] + r["effectiveCount"] + r["ineffectiveCount"]
              + r["aggravatedCount"] <= r["plannedCount"] for r in d["list"]), "")
    check("统计期间＝plannedFollowUpDate 的月份（yyyy-MM）",
          all(len(r["statPeriod"]) == 7 for r in d["list"]), str(sorted({r["statPeriod"] for r in d["list"]})))
    _, body = get_report(FOLLOWUP, tk_ke, {"plannedDateFrom": f_from, "plannedDateTo": f_to,
                                           "recordStatus": "COMPLETED", "size": 100})
    check("随访状态 IN 过滤生效（COMPLETED）", data(body)["summary"]["plannedCount"] == oracle(
        "SELECT COUNT(*) c FROM follow_up f JOIN visit v ON v.id = f.source_visit_id AND v.flag = 1 WHERE "
        "f.flag = 1 AND f.record_status = 'COMPLETED' AND date(f.planned_follow_up_date) BETWEEN date(?) AND "
        "date(?)", (f_from, f_to))[0]["c"], "")
    _, body = get_report(FOLLOWUP, tk_ke, {"plannedDateFrom": f_from, "plannedDateTo": f_to,
                                           "efficacyLevel": "CURED,EFFECTIVE", "size": 100})
    check("疗效评价 IN 多值过滤生效", data(body)["summary"]["plannedCount"] == oracle(
        "SELECT COUNT(*) c FROM follow_up f JOIN visit v ON v.id = f.source_visit_id AND v.flag = 1 WHERE "
        "f.flag = 1 AND f.efficacy_level IN ('CURED','EFFECTIVE') AND date(f.planned_follow_up_date) BETWEEN "
        "date(?) AND date(?)", (f_from, f_to))[0]["c"], "")
    _, body = get_report(FOLLOWUP, tk_ke, {"plannedDateFrom": f_from, "plannedDateTo": f_to,
                                           "deptCode": "TCM_GYN", "size": 100})
    check("科室过滤生效（TCM_GYN）", all(r["deptCode"] == "TCM_GYN" for r in data(body)["list"]), "")
    _, body = get_report(FOLLOWUP, tk_ke, {"recordStatus": "DONE"})
    check("随访状态字典外取值 → 中文异常", expect_fail(body, "字典"), str(msg(body)))
    resp = export_rows(FOLLOWUP, tk_ke, {"plannedDateFrom": f_from, "plannedDateTo": f_to})
    rows6, _ = parse_xlsx(resp.data)
    check("导出 XLSX 追加合计行且比率列留空",
          rows6[-1][0] == "合计" and rows6[-1][6] == "" and str(d["summary"]["plannedCount"]) == rows6[-1][3],
          str(rows6[-1][:8]))

    # 日期默认值（MONTH_START/MONTH_END）：动态断言落在本月
    _, body = get_report(FOLLOWUP, tk_ke, {"size": 100})
    check("日期默认值 MONTH_START/MONTH_END 解析为本月",
          all(r["statPeriod"] == today.strftime("%Y-%m") for r in data(body)["list"]),
          "%s → %s" % (month_first, sorted({r["statPeriod"] for r in data(body)["list"]})))

    # ---------------------------------------------------------- 7 权限矩阵
    sec("7. 权限矩阵（403 用例 / 401）")
    resp, body = api("get", "/api/report/" + VISIT_STATS)
    check("未登录 → 401", resp.status_code == 401, "HTTP %s" % resp.status_code)
    matrix = [
        ("导诊员（ROLE-01）", tk_dao, {FOLLOWUP: 200, VISIT_PRESCRIPTION: 200, VISIT_STATS: 403,
                                       SYNDROME_DIST: 403, HERB_USAGE: 403, OVERDOSE: 403}),
        ("中医师（ROLE-02）", tk_yi, {VISIT_STATS: 200, SYNDROME_DIST: 200, VISIT_PRESCRIPTION: 200,
                                      FOLLOWUP: 200, HERB_USAGE: 403, OVERDOSE: 403}),
        ("中药师（ROLE-03）", tk_yao, {OVERDOSE: 200, VISIT_PRESCRIPTION: 200, VISIT_STATS: 403,
                                       SYNDROME_DIST: 403, HERB_USAGE: 403, FOLLOWUP: 403}),
        ("科室管理员（ROLE-05）", tk_ke, dict((rid, 200) for rid in REPORTS)),
        ("库房管理员（ROLE-04）", tk_kf, dict((rid, 403) for rid in REPORTS)),
    ]
    for role_name, token, expect in matrix:
        bad = []
        for rid, status in expect.items():
            resp, _body = get_report(rid, token, {"size": 1})
            if resp.status_code != status:
                bad.append("%s→%s（期望 %s）" % (rid, resp.status_code, status))
        check("%s 报表权限矩阵正确" % role_name, not bad, "; ".join(bad))
    resp, body = get_report(HERB_USAGE, tk_yi, {"size": 1})
    check("越权中文提示与 HTTP 403 一致", resp.status_code == 403 and expect_fail(body, "无权限"),
          "HTTP %s %s" % (resp.status_code, msg(body)))
    resp = export_rows(HERB_USAGE, tk_yi, {"format": "csv"})
    check("导出与查询同权限（中医师导出饮片统计 → 403）", resp.status_code == 403, "HTTP %s" % resp.status_code)
    resp = export_rows(OVERDOSE, tk_yao, {"format": "xlsx"})
    check("导出与查询同权限（中药师导出台账 → 200）", resp.status_code == 200, "HTTP %s" % resp.status_code)

    # ---------------------------------------------------------- 8 补充口径/边界
    sec("8. 补充口径与边界")
    # SUBTOTAL 分母与分子同条件（带过滤时也要用过滤后的总数）
    _, body = get_report(SYNDROME_DIST, tk_ke, {"visitDateFrom": d_from, "visitDateTo": d_to,
                                                "deptCode": "TCM_GYN", "size": 100})
    gyn = data(body)
    gyn_total = sum(r["caseCount"] for r in gyn["list"])
    check("占比分母随过滤条件同步（TCM_GYN 过滤后之和仍 ≈ 1）",
          gyn_total > 0 and abs(sum(r["caseRatio"] or 0 for r in gyn["list"]) - 1) < 1e-9
          and all(abs((r["caseRatio"] or 0) - r["caseCount"] * 1.0 / gyn_total) < 1e-9 for r in gyn["list"]),
          "过滤后例数=%d" % gyn_total)
    # 触发组与 BASE 组用 AND 连接并加括号（SQL 形状）
    sql_both, _ = report_service.compile_sql(OVERDOSE, {})
    sql_ov, _ = report_service.compile_sql(OVERDOSE, {"triggerType": ["OVERDOSE"]})
    sql_tx, _ = report_service.compile_sql(OVERDOSE, {"triggerType": ["TOXIC"]})
    check("OVERDOSE/TOXIC 触发组按 triggerKind 取成员（组内 OR、组间 AND 并加括号）",
          "(prescriptionItem.single_dose > herb.max_common_dose) OR (herb.toxicity_level <> ?)" in sql_both
          and "OR (herb.toxicity_level" not in sql_ov
          and "(prescriptionItem.single_dose > herb.max_common_dose))" in sql_ov
          and "single_dose > herb.max_common_dose" not in sql_tx
          and "WHERE (prescription.flag = 1) AND ((herb.toxicity_level <> ?))" in sql_tx, "")
    _, body = get_report(OVERDOSE, tk_yao, {"triggerType": "BOTH", "size": 100})
    check("显式 triggerType=BOTH 与默认一致", data(body)["total"] == 11, "total=%s" % data(body)["total"])
    # size/分页边界：超出末页返回空列表而 total 不变
    vs_total = oracle("SELECT COUNT(*) c FROM (SELECT 1 FROM visit WHERE flag = 1 AND date(register_time) "
                      "BETWEEN date(?) AND date(?) GROUP BY date(register_time), dept_code, doctor_id, "
                      "visit_type)", (q_from, q_to))[0]["c"]
    _, body = get_report(VISIT_STATS, tk_yi, {"registerDateFrom": q_from, "registerDateTo": q_to,
                                              "page": 99, "size": 2})
    check("page 超出末页 → list 空、total 不变",
          data(body)["list"] == [] and data(body)["total"] == vs_total and data(body)["page"] == 99, "")
    # 分组分页：饮片统计 size=2
    herb_groups = oracle("SELECT COUNT(*) c FROM (SELECT 1 FROM prescription p LEFT JOIN prescription_item i ON "
                         "i.prescription_id = p.id AND i.flag = 1 LEFT JOIN herb h ON h.id = i.herb_id AND "
                         "h.flag = 1 WHERE p.flag = 1 AND date(p.prescribe_time) BETWEEN date(?) AND date(?) AND "
                         "p.prescription_status IN ('APPROVED','DISPENSING','ISSUED') GROUP BY h.herb_code, "
                         "h.herb_name, h.herb_category, h.toxicity_level)", (h_from, h_to))[0]["c"]
    _, body = get_report(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to, "size": 2})
    check("分组报表分页 size=2 → 2 行、total 为分组数",
          len(data(body)["list"]) == 2 and data(body)["total"] == herb_groups, "total=%s" % data(body)["total"])
    # 空值显示：饮片维度下「未指定饮片」组的累计用量为 NULL → 导出为 emptyValueDisplay('-')
    resp = export_rows(HERB_USAGE, tk_ke, {"prescribeDateFrom": h_from, "prescribeDateTo": h_to})
    rows7, _ = parse_xlsx(resp.data)
    check("导出空值用 emptyValueDisplay('-')（未指定饮片组的累计用量）",
          any(row[5] == "-" or row[4] == "-" for row in rows7[1:-1]), str(rows7[-2:] if len(rows7) > 2 else rows7))

    # 重复参数（?x=A&x=B）等价于 IN 多值
    _, body = get_report(OVERDOSE, tk_yao, None)
    import urllib.parse as _up
    qs = _up.urlencode([("prescriptionStatus", "APPROVED"), ("prescriptionStatus", "DISPENSING")])
    resp = client.get("/api/report/%s?%s" % (OVERDOSE, qs), headers={"Authorization": "Bearer " + tk_yao})
    rep_body = resp.get_json() or {}
    check("重复查询参数按 IN 多值处理（?prescriptionStatus=A&prescriptionStatus=B）",
          ok(rep_body) and {r["prescriptionStatus"] for r in data(rep_body)["list"]} <= {"APPROVED", "DISPENSING"}
          and len(data(rep_body)["list"]) > 0, str(sorted({r["prescriptionStatus"]
                                                          for r in data(rep_body).get("list", [])})))
    # skipWhenParameterEmpty=false 且参数为空 → 缺参中文异常（合成元数据用例）
    strict = copy.deepcopy(reps[VISIT_STATS])
    strict["parameters"].append({"name": "strictDept", "label": "必填科室", "dataType": "DictionaryRef",
                                 "required": True, "allowedOperators": ["EQ"],
                                 "sourceField": "visit.deptCode"})
    strict["conditions"].append({"conditionId": "C99", "leftExpression": "visit.deptCode", "operator": "EQ",
                                 "parameterRef": "strictDept", "logicalConnector": "AND", "group": "BASE",
                                 "skipWhenParameterEmpty": False})
    try:
        report_service.ReportQuery(strict, {}).build_sql()
        check("skipWhenParameterEmpty=false 且参数为空 → 中文异常", False, "未抛异常")
    except report_service.ReportError as e:
        check("skipWhenParameterEmpty=false 且参数为空 → 中文异常",
              "参数" in e.message and "必填" in e.message, e.message)

    # 导出上限：> 10000 行 → 中文报错
    conn = db.connect()
    try:
        conn.execute("INSERT INTO visit (visit_no, patient_id, visit_type, register_time, doctor_id, "
                     "dept_code, chief_complaint, visit_status, flag) VALUES ('ZC099999', 1, 'FIRST', "
                     "'2026-09-29 09:00:00', '2', 'TCM_INTERNAL', '导出上限自测', 'COMPLETED', 1)")
        vid = conn.execute("SELECT id FROM visit WHERE visit_no = 'ZC099999'").fetchone()["id"]
        conn.execute("INSERT INTO prescription (prescription_no, visit_id, patient_id, doctor_id, "
                     "prescription_type, doses, usage_method, prescribe_time, prescription_status, flag) "
                     "VALUES ('CF099999', ?, 1, '2', 'HERBAL_DECOCTION', 1, 'DAILY_1_2', "
                     "'2026-09-29 09:10:00', 'APPROVED', 1)", (vid,))
        pid = conn.execute("SELECT id FROM prescription WHERE prescription_no = 'CF099999'").fetchone()["id"]
        conn.executemany("INSERT INTO prescription_item (prescription_id, item_id, seq_no, herb_id, "
                         "single_dose, flag) VALUES (?, ?, ?, 2, 30, 1)",
                         [(pid, "IT9%05d" % i, i) for i in range(1, 10002)])
        conn.commit()
    finally:
        conn.close()
    resp = export_rows(OVERDOSE, tk_yao, {"format": "csv"})
    check("导出超过 10000 行 → 400 中文提示「导出数据量过大」",
          resp.status_code == 400 and "导出数据量过大" in str((resp.get_json() or {}).get("message")),
          "HTTP %s %s" % (resp.status_code, (resp.get_json() or {}).get("message")))
    resp, _body = get_report(OVERDOSE, tk_yao, {"size": 5})
    check("同一台账分页查询仍可用（仅导出受限）", resp.status_code == 200, "HTTP %s" % resp.status_code)
    resp = export_rows(VISIT_PRESCRIPTION, tk_dao, {"registerDateFrom": "2026-09-29",
                                                    "registerDateTo": "2026-09-29", "format": "csv"})
    check("主从报表导出上限按「展平后」行数计（该日 10001 条明细 → 400）",
          resp.status_code == 400 and "导出数据量过大" in str((resp.get_json() or {}).get("message")),
          "HTTP %s %s" % (resp.status_code, (resp.get_json() or {}).get("message")))

    # ---------------------------------------------------------- 汇总
    print("\n" + "=" * 96)
    print("批次 3 报表后端自测：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
    for name in NG:
        print("  - " + name)
    print("数据库（隔离）：%s" % DB_PATH)
    print("=" * 96)
    return 1 if NG else 0


if __name__ == "__main__":
    sys.exit(main())
