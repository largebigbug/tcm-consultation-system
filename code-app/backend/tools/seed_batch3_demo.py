# -*- coding: utf-8 -*-
"""批次 3 演示数据扩展：让六张报表在演示库里有真实分布（走服务层，口径天然合规）。

与旧做法的区别：**不直接克隆行**，而是复用批次 2 演示脚本的链路（挂号→接诊→四诊→辨证→开方→
提交→审核→调剂→发药），因此流程实例、随访计划日期（＝挂号日 + 剂数天）、库存流水、编号规则
全部由业务代码生成，批次 2 演示库体检的不变量不会被破坏。

产出：跨 4 个月 / 4 个科室的就诊与处方分布、含毒性饮片与超量理由的处方（台账两分支）、
已挂方剂模板的已发药处方（方剂维度有数据）、跨月随访（含已完成 / 已失访）。

幂等：检测到 2026-07 已存在演示就诊即跳过。
用法：code-app/backend/.venv/Scripts/python.exe tools/seed_batch3_demo.py
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # 复用批次 2 演示脚本的夹具
os.chdir(BACKEND)

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402
from services import (diagnosis_service, dispense_service, followup_service, prescription_service,  # noqa: E402
                      visit_service)

db.init_db_path(settings.resolve_db_path())
registry_module.load_ontology()

import seed_batch2_demo as b2  # noqa: E402  （提供 _user/_patient/_syndrome/_items/FOUR_*）

MARK_MONTH = "2026-07"          # 本脚本扩展的标志月


def chain3(actors, *, patient, register_time, dept, complaint, four, syndrome, treat, items,
           doses=7, steps="issued", formula_template_id=None, over_reason=None, type_="FIRST",
           previous_visit_id=None):
    """带「科室」与「方剂模板」的链路（在批次 2 chain 基础上扩展两个入参）。"""
    daozhen, yishi, yaoshi = actors
    visit = visit_service.register_visit({
        "patient_id": b2._patient(patient), "visit_type": type_, "previous_visit_id": previous_visit_id,
        "dept_code": dept, "register_time": register_time, "remark": "批次 3 演示数据",
    }, daozhen)
    vid = visit["id"]
    visit_service.receive_visit(vid, {
        "receive_time": b2._plus_minutes(register_time, 30), "dept_code": dept, "chief_complaint": complaint,
        "vital_signs": four.pop("vital_signs", "T36.6 P76 BP120/78"),
        "present_illness": four.pop("present_illness", ""), "past_history": four.pop("past_history", "无特殊"),
    }, yishi)
    visit_service.save_four_diagnosis(vid, four, yishi)
    diag = diagnosis_service.create_diagnosis({
        "visit_id": vid, "diagnosis_method": "ZANGFU", "syndrome_id": b2._syndrome(syndrome),
        "syndrome_nature": "PRIMARY", "diagnosis_basis": complaint + "，舌脉合参符合" + syndrome,
        "treatment_principle": treat,
    }, yishi)
    diagnosis_service.confirm_diagnosis(diag["id"], yishi)

    items = [dict(it) for it in items]
    if over_reason:
        items[0]["over_dose_reason"] = over_reason
    rx = prescription_service.create_prescription({
        "visit_id": vid, "prescription_type": "HERBAL_DECOCTION", "doses": doses,
        "usage_method": "DAILY_1_2", "decoction_instruction": "水煎服，日一剂分两次温服",
        "medical_advice": "忌辛辣油腻，注意休息", "items": items,
        "formula_template_id": formula_template_id,
    }, yishi)
    prescription_service.submit_prescription(rx["id"], yishi)
    if steps == "submitted":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}
    prescription_service.review_prescription(rx["id"], {"action": "APPROVE", "comment": "用法用量合理，同意调剂"},
                                             yaoshi)
    if steps == "reviewed":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}
    rec = dispense_service.get_by_prescription(rx["id"])
    dispense_service.confirm_dispense(rec["id"], {}, yaoshi)
    if steps == "dispensing":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"],
                "dispense_no": rec["dispense_no"]}
    dispense_service.issue_dispense(rec["id"], {}, yaoshi)
    return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"],
            "dispense_no": rec["dispense_no"]}


def already_extended():
    return db.query_one("SELECT COUNT(*) AS c FROM visit WHERE flag = 1 AND register_time LIKE ?",
                        (MARK_MONTH + "%",))["c"] >= 1


def main():
    if already_extended():
        print("已存在 %s 的批次 3 演示就诊，跳过（幂等）。库：%s" % (MARK_MONTH, settings.resolve_db_path()))
        return 0

    actors = (b2._user("daozhen"), b2._user("yishi"), b2._user("yaoshi"))
    formula = db.query_one("SELECT id, formula_code, formula_name FROM formula_template WHERE flag = 1 "
                           "ORDER BY id LIMIT 1")
    assert formula, "演示库缺少方剂模板（请先跑批次 1 演示数据）"

    print("=== 场景 1：2026-07-15 妇科 · 已发药（挂方剂模板 %s，随访计划=挂号日+7 天）===" % formula["formula_code"])
    r1 = chain3(actors, patient="李静", register_time="2026-07-15 09:00:00", dept="TCM_GYN",
                complaint="月经后期伴胁胀，经前乳胀", four=dict(b2.FOUR_LIVER), syndrome="肝气郁结证",
                treat="疏肝理气、养血调经", doses=7, steps="issued", formula_template_id=formula["id"],
                items=b2._items([("柴胡", 6, "NONE"), ("白芍", 12, "NONE"), ("当归", 10, "NONE"),
                                 ("茯苓", 12, "NONE"), ("白术", 10, "NONE"), ("甘草", 3, "NONE")]))
    print("  %s → 处方 %s 已发药" % (r1["visit_no"], r1["rx_no"]))

    print("=== 场景 2：2026-07-15 妇科 · 已失访（计划已超期）===")
    r2 = chain3(actors, patient="王秀英", register_time="2026-07-15 10:30:00", dept="TCM_GYN",
                complaint="脘痞纳呆，大便黏滞", four=dict(b2.FOUR_DAMP), syndrome="脾胃湿热证",
                treat="清热化湿、健脾和中", doses=7, steps="issued",
                items=b2._items([("陈皮", 6, "NONE"), ("半夏", 9, "PRE_DECOCT"), ("茯苓", 12, "NONE"),
                                 ("白术", 10, "NONE"), ("甘草", 3, "NONE")]))
    fs = [x for x in followup_service.list_followups(1, 300, {})["list"] if x.get("source_visit_id") == r2["visit"]]
    if fs:
        followup_service.mark_lost(fs[0]["id"], {"remark": "电话三次未接通，家属称已赴外院就诊"}, b2._user("daozhen"))
        print("  %s → 处方 %s 已发药 → 随访 %s 已失访" % (r2["visit_no"], r2["rx_no"], fs[0]["follow_up_no"]))

    print("=== 场景 3：2026-07-28 针灸科 · 已发药（超量柴胡 + 毒性半夏）===")
    r3 = chain3(actors, patient="张伟", register_time="2026-07-28 14:00:00", dept="ACUPUNCTURE",
                complaint="腰腿痛伴脘胀，口苦", four=dict(b2.FOUR_DAMP), syndrome="脾胃湿热证",
                treat="清热化湿、通络止痛", doses=5, steps="issued",
                items=b2._items([("柴胡", 13, "NONE"), ("半夏", 9, "PRE_DECOCT"), ("茯苓", 12, "NONE"),
                                 ("甘草", 3, "NONE")]),
                over_reason="患者形体壮实、邪气较盛，依《伤寒论》法短期加量，已告知并嘱中病即止")
    print("  %s → 处方 %s 已发药（柴胡 13g 超常用量 10g，半夏先煎）" % (r3["visit_no"], r3["rx_no"]))

    print("=== 场景 4：2026-08-20 内科 · 已发药 → 随访已完成（复诊）===")
    r4 = chain3(actors, patient="张伟", register_time="2026-08-20 08:40:00", dept="TCM_INTERNAL",
                complaint="神疲乏力，食少便溏", four=dict(b2.FOUR_QI), syndrome="气血两虚证",
                treat="益气健脾、养血安神", doses=7, steps="issued",
                items=b2._items([("党参", 12, "NONE"), ("白术", 10, "NONE"), ("茯苓", 12, "NONE"),
                                 ("甘草", 3, "NONE"), ("当归", 10, "NONE")]))
    fs4 = [x for x in followup_service.list_followups(1, 300, {})["list"] if x.get("source_visit_id") == r4["visit"]]
    if fs4:
        revisit = visit_service.register_visit({"patient_id": b2._patient("张伟"), "visit_type": "FOLLOW_UP",
                                                "previous_visit_id": r4["visit"], "dept_code": "TCM_INTERNAL",
                                                "register_time": "2026-09-20 09:00:00",
                                                "remark": "随访复诊挂号"}, b2._user("daozhen"))
        followup_service.complete_followup(fs4[0]["id"], {
            "actual_visit_id": revisit["id"], "actual_follow_up_date": "2026-09-20",
            "efficacy_level": "MARKED_EFFECT", "symptom_change": "乏力明显改善，睡眠好转",
            "continue_medication": 1, "remark": "嘱继续服 7 剂巩固"}, b2._user("daozhen"))
        print("  %s → 处方 %s 已发药 → 随访 %s 已完成（复诊 %s）"
              % (r4["visit_no"], r4["rx_no"], fs4[0]["follow_up_no"], revisit["visit_no"]))

    print("=== 场景 5：2026-08-20 儿科 · 审核通过（待调剂）===")
    r5 = chain3(actors, patient="李静", register_time="2026-08-20 09:10:00", dept="TCM_PEDIATRIC",
                complaint="小儿纳差，夜卧不安", four=dict(b2.FOUR_QI), syndrome="气血两虚证",
                treat="健脾益气、安神助眠", doses=5, steps="reviewed",
                items=b2._items([("党参", 6, "NONE"), ("白术", 6, "NONE"), ("茯苓", 6, "NONE"),
                                 ("甘草", 2, "NONE")]))
    print("  %s → 处方 %s 审核通过（待调剂）" % (r5["visit_no"], r5["rx_no"]))

    print("=== 场景 6：2026-09-05 针灸科 · 待审核 ===")
    r6 = chain3(actors, patient="王秀英", register_time="2026-09-05 15:20:00", dept="ACUPUNCTURE",
                complaint="颈肩僵痛，遇寒加重", four=dict(b2.FOUR_LIVER), syndrome="肝气郁结证",
                treat="疏肝通络、温经止痛", doses=7, steps="submitted",
                items=b2._items([("柴胡", 9, "NONE"), ("白芍", 12, "NONE"), ("当归", 10, "NONE"),
                                 ("甘草", 3, "NONE")]))
    print("  %s → 处方 %s 待审核" % (r6["visit_no"], r6["rx_no"]))

    print("\n=== 演示库批次 3 数据汇总 ===")
    for label, sql in (
            ("就诊（按月）", "SELECT strftime('%Y-%m', register_time) m, COUNT(*) c FROM visit WHERE flag=1 GROUP BY 1 ORDER BY 1"),
            ("处方（按状态）", "SELECT prescription_status s, COUNT(*) c FROM prescription WHERE flag=1 GROUP BY 1"),
            ("已挂方剂模板的处方", "SELECT COUNT(*) c FROM prescription WHERE flag=1 AND formula_template_id IS NOT NULL"),
            ("超量药味", "SELECT COUNT(*) c FROM prescription_item i JOIN herb h ON h.id=i.herb_id WHERE i.flag=1 AND i.single_dose>h.max_common_dose"),
            ("毒性药味", "SELECT COUNT(*) c FROM prescription_item i JOIN herb h ON h.id=i.herb_id WHERE i.flag=1 AND h.toxicity_level<>'NONE'"),
            ("随访（按状态）", "SELECT record_status s, COUNT(*) c FROM follow_up WHERE flag=1 GROUP BY 1"),
            ("随访（按计划月）", "SELECT substr(planned_follow_up_date,1,7) m, COUNT(*) c FROM follow_up WHERE flag=1 GROUP BY 1 ORDER BY 1")):
        rows = db.query(sql)
        rendered = "，".join("=".join(str(x) for x in dict(r).values()) for r in rows)
        print("  %-18s %s" % (label, rendered or "无"))
    print("\n批次 3 演示数据写入完成（演示账号登录后即可在「随访管理 / 统计报表」看到分布）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
