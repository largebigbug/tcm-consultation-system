# -*- coding: utf-8 -*-
"""批次 2 演示数据：门诊业务流全链路的多种状态（供登录界面逐屏查看）。

覆盖：待接诊 / 接诊中(含四诊+已确认辨证) / 待审核 / 待调剂 / 已发药 / 已作废并回冲 /
随访待随访·已完成·已失访。全部经 service 层写入（编号、规则、事务、联动与界面完全一致）。

用法（后端 venv 解释器）：
  D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/seed_batch2_demo.py
前置：批次 1 演示数据（患者/证型/饮片/方剂）已存在；不存在时本脚本会先自动灌一次。
已存在批次 2 就诊数据时跳过（加 --force 可强制再灌一份）。
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))
os.chdir(BACKEND)

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402
from services import (diagnosis_service, dispense_service, followup_service,  # noqa: E402
                      prescription_service, visit_service)

db.init_db_path(settings.resolve_db_path())
registry_module.load_ontology()

DEPT = "TCM_INTERNAL"
TODAY = "2026-09-30"


def _user(username):
    row = db.query_one("SELECT id, username, real_name FROM sys_user WHERE username = ?", (username,))
    if not row:
        raise SystemExit("缺少账号 %s，请先跑 tools/check_seed.py" % username)
    return {"id": row["id"], "username": row["username"], "real_name": row["real_name"]}


def _herb(name):
    row = db.query_one("SELECT id, herb_name FROM herb WHERE herb_name = ? AND flag = 1", (name,))
    if not row:
        raise SystemExit("缺少饮片 %s，请先跑 tools/seed_demo_data.py" % name)
    return row["id"]


def _syndrome(name):
    row = db.query_one("SELECT id, syndrome_name FROM syndrome_type WHERE syndrome_name = ? AND flag = 1", (name,))
    return row["id"] if row else None


def _patient(name):
    row = db.query_one("SELECT id, patient_name FROM patient WHERE patient_name = ? AND flag = 1", (name,))
    if not row:
        raise SystemExit("缺少患者 %s" % name)
    return row["id"]


def _plus_minutes(dt_text, minutes):
    """挂号时间 + N 分钟（REF-05：接诊时间不得早于挂号时间）。"""
    import datetime
    base = datetime.datetime.strptime(dt_text[:19], "%Y-%m-%d %H:%M:%S")
    return (base + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _items(pairs):
    return [{"seq_no": i, "herb_id": _herb(n), "single_dose": d, "decoction_method": m}
            for i, (n, d, m) in enumerate(pairs, start=1)]


def chain(daozhen, yishi, yaoshi, keshi, *, patient, register_time, complaint, four, syndrome, treat,
          items, doses=7, type_="FIRST", previous_visit_id=None, steps="dispensed", over_reason=None):
    """跑一条链路：挂号 → 接诊 → 四诊 → 辨证确认 →(开方→提交→审核)→(调剂)→(发药)。"""
    visit = visit_service.register_visit({
        "patient_id": _patient(patient), "visit_type": type_, "previous_visit_id": previous_visit_id,
        "dept_code": DEPT, "register_time": register_time, "remark": "演示数据",
    }, daozhen)
    vid = visit["id"]
    visit_service.receive_visit(vid, {
        "receive_time": _plus_minutes(register_time, 30), "dept_code": DEPT, "chief_complaint": complaint,
        "vital_signs": four.pop("vital_signs", "T36.6 P76 BP120/78"),
        "present_illness": four.pop("present_illness", ""), "past_history": four.pop("past_history", "无特殊"),
    }, yishi)
    visit_service.save_four_diagnosis(vid, four, yishi)
    syn_id = _syndrome(syndrome)
    diag = diagnosis_service.create_diagnosis({
        "visit_id": vid, "diagnosis_method": "ZANGFU", "syndrome_id": syn_id, "syndrome_nature": "PRIMARY",
        "diagnosis_basis": complaint + "，舌脉合参符合" + syndrome, "treatment_principle": treat,
    }, yishi)
    diagnosis_service.confirm_diagnosis(diag["id"], yishi)
    if steps == "receive":
        return {"visit": vid, "visit_no": visit["visit_no"]}

    items = [dict(it) for it in items]
    if over_reason:
        items[0]["over_dose_reason"] = over_reason
    rx = prescription_service.create_prescription({
        "visit_id": vid, "prescription_type": "HERBAL_DECOCTION", "doses": doses,
        "usage_method": "DAILY_1_2", "decoction_instruction": "水煎服，日一剂分两次温服",
        "medical_advice": "忌辛辣油腻，注意休息", "items": items,
    }, yishi)
    if steps == "draft":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}
    prescription_service.submit_prescription(rx["id"], yishi)
    if steps in ("submitted", "receive"):
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}
    if steps == "reviewed":
        prescription_service.review_prescription(rx["id"], {"action": "APPROVE", "comment": "用法用量合理，同意调剂"},
                                                 yaoshi)
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}
    prescription_service.review_prescription(rx["id"], {"action": "APPROVE", "comment": "用法用量合理，同意调剂"},
                                             yaoshi)
    rec = dispense_service.get_by_prescription(rx["id"])
    if steps == "dispensing":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"],
                "dispense_no": rec["dispense_no"]}
    dispense_service.confirm_dispense(rec["id"], {}, yaoshi)
    if steps == "issued":
        dispense_service.issue_dispense(rec["id"], {}, yaoshi)
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"],
                "dispense_no": rec["dispense_no"]}
    if steps == "void_rollback":
        return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"],
                "dispense_no": rec["dispense_no"], "record": rec["id"]}
    return {"visit": vid, "visit_no": visit["visit_no"], "rx": rx["id"], "rx_no": rx["prescription_no"]}


FOUR_LIVER = {"inquiry_cold_heat": "无明显寒热", "inquiry_sweat": "偶有自汗", "inquiry_head_body": "头胀",
              "inquiry_diet": "纳差", "inquiry_sleep": "入睡困难", "inquiry_excretion": "大便偏干",
              "inquiry_emotion": "情志抑郁易怒", "inspection_face": "面色少华", "inspection_shape": "形体偏瘦",
              "tongue_body": "PALE_RED", "tongue_coating": "THIN_WHITE", "auscultation_voice": "语声正常",
              "pulse_code": "WIRY", "pulse_detail": "左关弦", "four_diagnosis_summary": "肝郁脾虚，脉弦细",
              "present_illness": "情志不畅后出现胁肋胀痛，善太息，纳差乏力", "past_history": "否认高血压、糖尿病史"}
FOUR_DAMP = {"inquiry_cold_heat": "身热不扬", "inquiry_sweat": "汗出黏腻", "inquiry_head_body": "头重如裹",
             "inquiry_diet": "口苦口黏", "inquiry_sleep": "睡眠尚可", "inquiry_excretion": "大便黏滞不爽",
             "inquiry_emotion": "平", "inspection_face": "面色油光", "inspection_shape": "形体偏胖",
             "tongue_body": "RED", "tongue_coating": "YELLOW_GREASY", "auscultation_voice": "语声重浊",
             "pulse_code": "SLIPPERY", "pulse_detail": "右关滑", "four_diagnosis_summary": "湿热中阻，苔黄腻",
             "present_illness": "脘腹胀满两周，口苦口黏，食欲不振", "past_history": "慢性胃炎 3 年"}
FOUR_QI = {"inquiry_cold_heat": "畏寒肢冷", "inquiry_sweat": "动则汗出", "inquiry_head_body": "头晕乏力",
           "inquiry_diet": "食少便溏", "inquiry_sleep": "夜寐多梦", "inquiry_excretion": "小便清长",
           "inquiry_emotion": "精神不振", "inspection_face": "面色苍白", "inspection_shape": "形体偏瘦",
           "tongue_body": "PALE_WHITE", "tongue_coating": "THIN_WHITE", "auscultation_voice": "语声低微",
           "pulse_code": "VACUOUS", "pulse_detail": "沉细无力", "four_diagnosis_summary": "气血两虚，脉沉细",
           "present_illness": "半年来气短乏力，心悸失眠，面色苍白", "past_history": "产后失血较多"}


def main():
    force = "--force" in sys.argv
    conn = db.connect()
    try:
        if not db.query_one("SELECT COUNT(*) AS c FROM patient", (), conn)["c"]:
            print("（未发现批次 1 演示数据，先自动灌入）")
            import seed_demo_data
            conn.close()
            seed_demo_data.main()
            conn = db.connect()
        n = db.query_one("SELECT COUNT(*) AS c FROM visit", (), conn)["c"]
        if n and not force:
            print("已有 %d 条就诊数据，跳过（如需重灌加 --force）" % n)
            return 0
    finally:
        conn.close()

    daozhen, yishi, yaoshi, keshi = _user("daozhen"), _user("yishi"), _user("yaoshi"), _user("keshi")
    print("=== 场景 1：张伟 · 今日挂号（待接诊，UI-03 待办） ===")
    v1 = visit_service.register_visit({"patient_id": _patient("张伟"), "visit_type": "FIRST", "dept_code": DEPT,
                                       "register_time": TODAY + " 08:15:00", "remark": "窗口挂号"}, daozhen)
    print("  %s 张伟 %s" % (v1["visit_no"], v1["visit_status"]))

    print("=== 场景 2：李静 · 接诊中（四诊+辨证已确认，可开方 → UI-04/05/06） ===")
    r2 = chain(daozhen, yishi, yaoshi, keshi, patient="李静", register_time=TODAY + " 08:40:00",
               complaint="胁肋胀痛 3 天，善太息，纳差", four=dict(FOUR_LIVER), syndrome="肝气郁结证",
               treat="疏肝解郁、健脾和胃", items=_items([("柴胡", 6, "NONE")]), steps="receive")
    print("  %s 李静 接诊中（四诊 1 份 + 辨证已确认）" % r2["visit_no"])

    print("=== 场景 3：王秀英 · 逍遥散加减（含毒性饮片与超量理由）→ 待审核（UI-07） ===")
    rx3 = chain(daozhen, yishi, yaoshi, keshi, patient="王秀英", register_time=TODAY + " 09:10:00",
                complaint="脘腹胀满，口苦口黏，胁痛", four=dict(FOUR_DAMP), syndrome="脾胃湿热证",
                treat="清热化湿、疏肝和胃", steps="submitted", doses=7,
                items=_items([("柴胡", 13, "NONE"), ("白芍", 15, "NONE"), ("半夏", 9, "PRE_DECOCT"),
                              ("茯苓", 12, "NONE"), ("陈皮", 6, "NONE"), ("甘草", 3, "NONE")]),
                over_reason="患者形体壮实、邪气较盛，依《伤寒论》法短期加量，已告知并嘱中病即止")
    print("  %s 王秀英 → 处方 %s（待审核；柴胡 13g 超常用量 10g，已填超量理由）" % (rx3["visit_no"], rx3["rx_no"]))

    print("=== 场景 4：张伟 · 四君子汤加减 → 已调剂待发药（UI-08） ===")
    r4 = chain(daozhen, yishi, yaoshi, keshi, patient="张伟", register_time=TODAY + " 09:30:00",
               complaint="神疲乏力，食少便溏", four=dict(FOUR_QI), syndrome="气血两虚证",
               treat="益气健脾、养血安神", steps="dispensing", doses=7,
               items=_items([("党参", 12, "NONE"), ("白术", 10, "NONE"), ("茯苓", 12, "NONE"),
                             ("甘草", 3, "NONE"), ("陈皮", 6, "NONE"), ("当归", 10, "NONE")]))
    print("  %s 张伟 → 处方 %s → 调剂单 %s（已调剂，待发药）" % (r4["visit_no"], r4["rx_no"], r4["dispense_no"]))

    print("=== 场景 5：李静 · 逍遥散 → 已发药（完整闭环 + 库存流水） ===")
    r5 = chain(daozhen, yishi, yaoshi, keshi, patient="李静", register_time=TODAY + " 09:50:00",
               complaint="复诊：胁痛减轻，仍夜寐欠安", four=dict(FOUR_LIVER), syndrome="肝气郁结证",
               treat="疏肝解郁、养血安神", steps="issued", doses=7,
               items=_items([("当归", 10, "NONE"), ("白芍", 12, "NONE"), ("柴胡", 6, "NONE"),
                             ("茯苓", 12, "NONE"), ("白术", 10, "NONE"), ("甘草", 3, "NONE")]))
    print("  %s 李静 → 处方 %s → 调剂单 %s（已发药）" % (r5["visit_no"], r5["rx_no"], r5["dispense_no"]))

    print("=== 场景 6：王秀英 · 已调剂后作废（R-04 回冲库存） ===")
    r6 = chain(daozhen, yishi, yaoshi, keshi, patient="王秀英", register_time=TODAY + " 10:20:00",
               complaint="腰膝酸软，畏寒肢冷，夜尿频多", four=dict(FOUR_QI), syndrome="肾阳虚证",
               treat="温补肾阳、健脾益气", steps="void_rollback", doses=7,
               items=_items([("党参", 12, "NONE"), ("白术", 10, "NONE"), ("茯苓", 12, "NONE"),
                             ("黄芪", 15, "NONE"), ("陈皮", 6, "NONE"), ("甘草", 3, "NONE")]))
    out = prescription_service.cancel_prescription(r6["rx"], {"cancel_reason": "患者要求改用中成药，处方作废"},
                                                   keshi)
    print("  %s 王秀英 → 处方 %s 已作废（%s，库存已回冲）" % (r6["visit_no"], r6["rx_no"], out.get("dispatch")))

    print("=== 场景 7/8：历史就诊（2026-06）→ 随访失访 与 随访已完成 ===")
    hist1 = chain(daozhen, yishi, yaoshi, keshi, patient="王秀英", register_time="2026-06-08 09:00:00",
                  complaint="脘腹痞满，食后腹胀", four=dict(FOUR_DAMP), syndrome="痰湿内蕴证",
                  treat="燥湿化痰、理气和中", steps="submitted", doses=7,
                  items=_items([("陈皮", 6, "NONE"), ("半夏", 6, "PRE_DECOCT"), ("茯苓", 12, "NONE"),
                                ("白术", 10, "NONE"), ("甘草", 3, "NONE")]))
    f1 = [x for x in followup_service.list_followups(1, 200, {})["list"]
          if x.get("source_visit_id") == hist1["visit"]]
    if f1:
        followup_service.mark_lost(f1[0]["id"], {"remark": "电话三次未接通，家属称已赴外院就诊"}, daozhen)
        print("  %s → 随访 %s 已失访（计划 %s 已超期）" % (hist1["visit_no"], f1[0]["follow_up_no"],
                                                        f1[0]["planned_follow_up_date"]))
    hist2 = chain(daozhen, yishi, yaoshi, keshi, patient="张伟", register_time="2026-06-15 09:00:00",
                  complaint="神疲乏力，心悸失眠", four=dict(FOUR_QI), syndrome="气血两虚证",
                  treat="益气养血、健脾安神", steps="submitted", doses=7,
                  items=_items([("党参", 12, "NONE"), ("白术", 10, "NONE"), ("茯苓", 12, "NONE"),
                                ("甘草", 3, "NONE")]))
    f2 = [x for x in followup_service.list_followups(1, 200, {})["list"]
          if x.get("source_visit_id") == hist2["visit"]]
    if f2:
        revisit = visit_service.register_visit({"patient_id": _patient("张伟"), "visit_type": "FOLLOW_UP",
                                                "previous_visit_id": hist2["visit"], "dept_code": DEPT,
                                                "register_time": TODAY + " 11:00:00",
                                                "remark": "随访复诊挂号"}, daozhen)
        followup_service.complete_followup(f2[0]["id"], {
            "actual_visit_id": revisit["id"], "actual_follow_up_date": "2026-09-28",
            "efficacy_level": "MARKED_EFFECT", "symptom_change": "乏力明显改善，睡眠好转",
            "continue_medication": 1, "remark": "嘱继续服 7 剂巩固"}, daozhen)
        print("  %s → 随访 %s 已完成（本次就诊 %s 为今日待接诊的复诊号）"
              % (hist2["visit_no"], f2[0]["follow_up_no"], revisit["visit_no"]))

    print("\n=== 演示库汇总 ===")
    conn = db.connect()
    try:
        for label, sql in (
                ("就诊记录", "SELECT visit_status, COUNT(*) c FROM visit WHERE flag=1 GROUP BY visit_status"),
                ("处方", "SELECT prescription_status, COUNT(*) c FROM prescription WHERE flag=1 GROUP BY prescription_status"),
                ("调剂发药记录", "SELECT record_status, COUNT(*) c FROM dispense_record WHERE flag=1 GROUP BY record_status"),
                ("随访记录", "SELECT record_status, COUNT(*) c FROM follow_up WHERE flag=1 GROUP BY record_status"),
                ("出入库流水", "SELECT biz_type, COUNT(*) c, SUM(quantity) q FROM herb_stock_flow WHERE flag=1 GROUP BY biz_type")):
            print("  %s：" % label, "，".join("%s=%s%s" % (r[0], r[1], ("(%sg)" % round(r[2], 1)) if len(r) > 2 and r[2] is not None else "")
                                            for r in conn.execute(sql).fetchall()) or "无")
    finally:
        conn.close()
    print("\n批次 2 演示数据写入完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
