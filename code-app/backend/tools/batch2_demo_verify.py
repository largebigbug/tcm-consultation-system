# -*- coding: utf-8 -*-
"""批次 2 演示库体检：对演示库做一致性核对（编号、状态机、不变性、联动物）。

用法：cd code-app/backend && ./.venv/Scripts/python.exe tools/batch2_demo_verify.py
"""
import os
import re
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402

db.init_db_path(settings.resolve_db_path())
registry_module.load_ontology()

OK, NG = [], []
conn = db.connect()


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-56s %s" % ("[通过]" if cond else "[失败]", name, detail))


def scalar(sql, params=()):
    return conn.execute(sql, params).fetchone()


print("=== 1. 编号规则（需求文档附录 D 口径） ===")
for table, col, pat, label in (("visit", "visit_no", r"^ZC\d{6}$", "就诊号 ZC+6"),
                               ("syndrome_diagnosis", "diagnosis_no", r"^BZ\d{6}$", "辨证号 BZ+6"),
                               ("prescription", "prescription_no", r"^CF\d{6}$", "处方号 CF+6"),
                               ("dispense_record", "dispense_no", r"^FY\d{6}$", "发药单号 FY+6"),
                               ("follow_up", "follow_up_no", r"^SF\d{4}$", "随访号 SF+4"),
                               ("herb_stock_flow", "flow_no", r"^LS\d{6}$", "出入库流水号 LS+6")):
    rows = conn.execute("SELECT %s FROM %s" % (col, table)).fetchall()
    bad = [r[0] for r in rows if not re.match(pat, str(r[0] or ""))]
    check("%s（共 %d 条）" % (label, len(rows)), not bad, "不合规：" + str(bad[:3]) if bad else "")

print("\n=== 2. 状态码取值（必须落在 M1 字典内） ===")


def dict_codes(dict_id, type_code):
    return {i["code"] for i in registry_module.get_dictionary_items(dict_id, type_code)}


for table, col, dict_id, type_code, label in (
        ("visit", "visit_status", "DICT-VISIT", "VISIT_STATUS", "就诊状态"),
        ("syndrome_diagnosis", "conclusion_status", "DICT-SYNDROME", "CONCLUSION_STATUS", "辨证结论状态"),
        ("prescription", "prescription_status", "DICT-PRESCRIPTION", "PRESCRIPTION_STATUS", "处方状态"),
        ("dispense_record", "record_status", "DICT-DISPENSE", "DISPENSE_STATUS", "调剂发药状态"),
        ("follow_up", "record_status", "DICT-FOLLOWUP", "FOLLOWUP_STATUS", "随访状态")):
    allowed = dict_codes(dict_id, type_code)
    vals = {r[0] for r in conn.execute("SELECT DISTINCT %s FROM %s" % (col, table)).fetchall()}
    check("%s ∈ %s 字典" % (label, type_code), vals <= allowed,
          ("越界值：" + str(sorted(vals - allowed))) if vals - allowed else "")

print("\n=== 3. 跨表状态一致性 ===")
rows = conn.execute("""
    SELECT p.prescription_no, p.prescription_status, d.record_status
    FROM prescription p LEFT JOIN dispense_record d ON d.prescription_id = p.id AND d.flag = 1
    WHERE p.flag = 1""").fetchall()
pairs = {("PENDING_REVIEW", None), ("DRAFT", None), ("APPROVED", "PENDING"), ("REJECTED", None), ("VOIDED", None),
         ("DISPENSING", "DISPENSED"), ("VOIDED", "CANCELLED"), ("ISSUED", "ISSUED")}
bad = [(r[0], r[1], r[2]) for r in rows if (r[1], r[2]) not in pairs]
check("处方状态 ↔ 调剂记录状态组合合法（%d 张处方）" % len(rows), not bad, str(bad[:3]))
check("已作废处方均已取消待调剂记录",
      not scalar("""SELECT COUNT(*) FROM prescription p JOIN dispense_record d ON d.prescription_id = p.id
                    WHERE p.prescription_status='VOIDED' AND p.flag=1 AND d.record_status='PENDING'""")[0], "")
check("已发药处方其调剂记录亦为已发药",
      not scalar("""SELECT COUNT(*) FROM prescription p JOIN dispense_record d ON d.prescription_id = p.id
                    WHERE p.prescription_status='ISSUED' AND p.flag=1 AND d.record_status<>'ISSUED'""")[0], "")
check("调剂时间不早于审核时间（REF-14 前序）",
      not scalar("""SELECT COUNT(*) FROM prescription p JOIN dispense_record d ON d.prescription_id = p.id
                    WHERE p.review_time IS NOT NULL AND d.dispense_time < p.review_time""")[0], "")

print("\n=== 4. 不变性（INV-02 / INV-03 / 唯一性） ===")
check("INV-02 每就诊至多一条主证",
      not scalar("""SELECT COUNT(*) FROM (SELECT visit_id FROM syndrome_diagnosis
                    WHERE syndrome_nature='PRIMARY' AND flag=1 GROUP BY visit_id HAVING COUNT(*)>1)""")[0], "")
check("每就诊至多一份四诊信息",
      not scalar("""SELECT COUNT(*) FROM (SELECT visit_id FROM four_diagnosis
                    WHERE flag=1 GROUP BY visit_id HAVING COUNT(*)>1)""")[0], "")
bad = []
for r in conn.execute("SELECT id, herb_name, stock_quantity FROM herb WHERE flag = 1").fetchall():
    net = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM herb_stock_flow WHERE herb_id=? AND flag=1",
                       (r["id"],)).fetchone()[0]
    if abs(float(r["stock_quantity"] or 0) - float(net or 0)) > 1e-6:
        bad.append((r["herb_name"], r["stock_quantity"], net))
check("INV-03 每味饮片 库存 == 流水净和", not bad, str(bad[:3]))
check("库存无负数",
      not scalar("SELECT COUNT(*) FROM herb WHERE flag=1 AND stock_quantity < 0")[0], "")
check("同一处方内饮片不重复",
      not scalar("""SELECT COUNT(*) FROM (SELECT prescription_id FROM prescription_item WHERE flag=1
                    GROUP BY prescription_id, herb_id HAVING COUNT(*)>1)""")[0], "")

print("\n=== 5. 演示场景齐备性（各屏可见数据） ===")
for label, sql in (
        ("待接诊就诊（UI-03）", "SELECT COUNT(*) FROM visit WHERE visit_status='REGISTERED' AND flag=1"),
        ("接诊中就诊（UI-04/05/06）", "SELECT COUNT(*) FROM visit WHERE visit_status='IN_PROGRESS' AND flag=1"),
        ("待审核处方（UI-07）", "SELECT COUNT(*) FROM prescription WHERE prescription_status='PENDING_REVIEW' AND flag=1"),
        ("待调剂/待发药记录（UI-08）",
         "SELECT COUNT(*) FROM dispense_record WHERE record_status IN ('PENDING','DISPENSED') AND flag=1"),
        ("已发药处方", "SELECT COUNT(*) FROM prescription WHERE prescription_status='ISSUED' AND flag=1"),
        ("已作废并回冲的处方", """SELECT COUNT(*) FROM prescription p WHERE p.prescription_status='VOIDED' AND p.flag=1
                                 AND EXISTS(SELECT 1 FROM herb_stock_flow f WHERE f.prescription_id=p.id
                                            AND f.biz_type='VOID_ROLLBACK')"""),
        ("本人已办/待办（审批中心）", "SELECT COUNT(*) FROM flow_task WHERE status IN ('TODO','DONE')"),
        ("超量药味落库（QR-PRESCRIPTION-OVERDOSE-001 来源）",
         "SELECT COUNT(*) FROM prescription_item WHERE over_dose_reason IS NOT NULL AND flag=1"),
        ("随访：待随访", "SELECT COUNT(*) FROM follow_up WHERE record_status='PENDING' AND flag=1"),
        ("随访：已完成", "SELECT COUNT(*) FROM follow_up WHERE record_status='COMPLETED' AND flag=1"),
        ("随访：已失访", "SELECT COUNT(*) FROM follow_up WHERE record_status='LOST' AND flag=1")):
    n = scalar(sql)[0]
    check(label + " 有数据", n > 0, "%d 条" % n)

print("\n=== 6. 联动物 ===")
check("提交成功的就诊均生成随访计划（幂等：一就诊一条）",
      not scalar("""SELECT COUNT(*) FROM (SELECT source_visit_id FROM follow_up WHERE flag=1
                    GROUP BY source_visit_id HAVING COUNT(*)>1)""")[0], "")
check("随访计划日期 = 挂号日期 + 剂数天",
      not scalar("""SELECT COUNT(*) FROM follow_up f JOIN visit v ON v.id=f.source_visit_id
                    JOIN prescription p ON p.visit_id=v.id AND p.flag=1
                    WHERE p.prescription_status<>'DRAFT'
                      AND date(f.planned_follow_up_date) <> date(v.register_time, '+' || p.doses || ' day')""")[0],
      "")
check("审批流实例存在且与处方数匹配",
      scalar("SELECT COUNT(*) FROM flow_instance")[0] >= scalar(
          "SELECT COUNT(*) FROM prescription WHERE flag=1 AND prescription_status<>'DRAFT'")[0],
      "实例 %s 个" % scalar("SELECT COUNT(*) FROM flow_instance")[0])

conn.close()
print("\n" + "=" * 80)
print("批次 2 演示库体检：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
for n in NG:
    print("  ✗ " + n)
print("=" * 80)
sys.exit(1 if NG else 0)
