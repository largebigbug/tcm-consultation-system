# -*- coding: utf-8 -*-
"""批次 2 独立验收脚本（主代编写，与开发者自测脚本相互独立）。

覆盖 docs/批次2-实现契约.md §9 必测清单。状态码与字典取值一律采用 M1 字典真实 code
（DICT-VISIT.VISIT_STATUS: REGISTERED/IN_PROGRESS/COMPLETED/CANCELLED；
 DICT-PRESCRIPTION.PRESCRIPTION_STATUS: DRAFT/PENDING_REVIEW/APPROVED/REJECTED/DISPENSING/ISSUED/VOIDED；
 DICT-DISPENSE.DISPENSE_STATUS: PENDING/DISPENSED/ISSUED/CANCELLED）。

用法：D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/batch2_api_test.py
"""
import os
import random
import sys
from datetime import date, timedelta

BACKEND = r"D:\hermes\workspace\中医问诊系统\code-app\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

# 自测/验收库必须隔离：绝不读写演示库 data/app.db（本脚本会写入业务数据）
DB_PATH = os.path.join(BACKEND, "data", "batch2_main.db")
for _sfx in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + _sfx):
        os.remove(DB_PATH + _sfx)
os.environ["APP_DB_PATH"] = DB_PATH

OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-58s %s" % ("[通过]" if cond else "[失败]", name, detail))


def main():
    from app import app
    c = app.test_client()
    sfx = random.randint(1000, 9999)

    def login(u, p):
        body = c.post("/api/auth/login", json={"username": u, "password": p}).get_json()
        assert body.get("success"), (u, body)
        return {"Authorization": "Bearer " + body["data"]["token"]}

    def data(r):
        return (r.get_json() or {}).get("data") or {}

    def msg(r):
        return (r.get_json() or {}).get("message")

    def ok(r):
        return bool((r.get_json() or {}).get("success"))

    H = {u: login(u, "123456") for u in ("daozhen", "yishi", "yaoshi", "kufang", "keshi")}
    DAY = "2026-09-30"

    print("=== 0. 登录与菜单可见性（M5 授权） ===")

    def menus_of(u):
        return {m["name"]: [ch["name"] for ch in m.get("children", [])]
                for m in c.post("/api/auth/login", json={"username": u, "password": "123456"}
                                ).get_json()["data"]["menus"]}

    m_dao, m_yi, m_yao, m_ke = menus_of("daozhen"), menus_of("yishi"), menus_of("yaoshi"), menus_of("keshi")
    check("导诊员见「门诊管理 › 门诊挂号」", "门诊挂号" in m_dao.get("门诊管理", []), str(m_dao.get("门诊管理")))
    check("中医师见接诊/四诊/辨证/开方四屏",
          set(["接诊开单", "四诊录入", "辨证判定", "开具处方"]).issubset(m_yi.get("门诊管理", [])),
          str(m_yi.get("门诊管理")))
    check("中药师见「药房管理 › 处方审核 + 调剂发药」",
          set(["处方审核", "调剂发药"]).issubset(m_yao.get("药房管理", [])), str(m_yao.get("药房管理")))
    check("科室管理员不含「调剂发药」与「开具处方」",
          "调剂发药" not in m_ke.get("药房管理", []) and "开具处方" not in m_ke.get("门诊管理", []), str(m_ke))

    print("\n=== 1. 基础数据 ===")
    r = c.post("/api/patient", json={"patient_name": "批次二验收患者%d" % sfx, "gender": "MALE",
                                     "birth_date": "1978-06-15", "phone": "1380013%04d" % sfx},
               headers=H["daozhen"])
    patient_id = data(r).get("id")
    check("患者建档", ok(r) and patient_id, str(msg(r)))
    r = c.post("/api/patient", json={"patient_name": "批次二患者%d" % sfx, "gender": "FEMALE",
                                     "birth_date": "1985-02-20", "phone": "1380013%04d" % (sfx + 1)},
               headers=H["daozhen"])
    patient2 = data(r).get("id")
    check("第二位患者建档", ok(r) and patient2, str(msg(r)))

    herbs = {}
    for key, name, cat, mn, mx, tox, limit in (
            ("a", "验收当归%d" % sfx, "TONIFYING", 6, 12, "NONE", None),
            ("b", "验收附子%d" % sfx, "WARMING_INTERIOR", 3, 9, "SLIGHT", 30),
            ("c", "验收细辛%d" % sfx, "RELIEVING_EXTERIOR", 1, 9, "SLIGHT", 5)):
        body = {"herb_name": name, "herb_category": cat, "min_common_dose": mn, "max_common_dose": mx,
                "toxicity_level": tox, "low_stock_threshold": 100}
        if limit is not None:
            body["toxic_dose_limit"] = limit
        r = c.post("/api/herb", json=body, headers=H["kufang"])
        herbs[key] = data(r).get("id")
        check("饮片建档 %s（max=%sg%s）" % (key, mx, "，毒性上限=%sg" % limit if limit else ""),
              ok(r) and herbs[key], str(msg(r)))
    for key, qty, no in (("a", 500, "A"), ("b", 300, "B"), ("c", 100, "C")):
        r = c.post("/api/herb/%s/inbound" % herbs[key],
                   json={"quantity": qty, "biz_date": DAY + " 08:01:00", "inbound_no": "RK2%s0%d" % (no, sfx)},
                   headers=H["kufang"])
        check("饮片 %s 入库 %sg" % (key, qty), ok(r), str(msg(r)))

    print("\n=== 2. 挂号 UI-02 ===")
    r = c.post("/api/visit", json={"patient_id": patient_id, "visit_type": "FOLLOW_UP", "dept_code": "TCM_INTERNAL",
                                   "register_time": DAY + " 08:20:00"}, headers=H["daozhen"])
    check("复诊未选上次就诊被拒", not ok(r), str(msg(r)))
    r = c.post("/api/visit", json={"patient_id": patient_id, "visit_type": "NOT_A_TYPE",
                                   "register_time": DAY + " 08:20:00"}, headers=H["daozhen"])
    check("就诊类型不在字典内被拒", not ok(r), str(msg(r)))
    r = c.post("/api/visit", json={"patient_id": patient_id, "visit_type": "FIRST", "dept_code": "NO_SUCH_DEPT",
                                   "register_time": DAY + " 08:20:00"}, headers=H["daozhen"])
    check("科室不在字典内被拒", not ok(r), str(msg(r)))

    r = c.get("/api/syndrome", query_string={"page": 1, "size": 5}, headers=H["keshi"])
    syn = data(r).get("list") or []
    if not syn:
        r = c.post("/api/syndrome", json={"syndrome_name": "验收肝郁%d证" % sfx, "diagnosis_method": "ZANGFU"},
                   headers=H["keshi"])
        syn = [data(r)]
    syndrome_id = syn[0]["id"]
    check("取得可用证型", bool(syndrome_id), "%s %s" % (syn[0].get("syndrome_code"), syn[0].get("syndrome_name")))

    def new_visit(register_time, patient, dept="TCM_INTERNAL", complaint="胁肋胀痛 3 天，善太息"):
        """挂号 → 接诊 → 四诊 → 辨证保存+确认；返回 (visit_id, diagnosis_id, 最后响应)。"""
        r = c.post("/api/visit", json={"patient_id": patient, "visit_type": "FIRST", "dept_code": dept,
                                       "register_time": register_time, "remark": "验收用就诊"},
                   headers=H["daozhen"])
        vid = data(r).get("id")
        if not vid:
            return None, None, r
        r = c.post("/api/visit/%s/receive" % vid,
                   json={"receive_time": register_time[:11] + "23:00:00", "dept_code": dept,
                         "chief_complaint": complaint, "vital_signs": "T36.6 P78 BP118/76",
                         "present_illness": "情志不畅后出现胁肋胀痛", "past_history": "无"},
                   headers=H["yishi"])
        if not ok(r):
            return vid, None, r
        four = {"inquiry_cold_heat": "无明显寒热", "inquiry_sweat": "偶有自汗", "inquiry_head_body": "头胀",
                "inquiry_diet": "纳差", "inquiry_sleep": "入睡困难", "inquiry_excretion": "大便偏干",
                "inquiry_emotion": "情志抑郁", "inspection_face": "面色少华", "inspection_shape": "形体偏瘦",
                "tongue_body": "PALE_RED", "tongue_coating": "THIN_WHITE", "auscultation_voice": "语声正常",
                "pulse_code": "WIRY", "pulse_detail": "左关弦", "four_diagnosis_summary": "肝郁气滞，脉弦"}
        r = c.post("/api/visit/%s/four-diagnosis" % vid, json=four, headers=H["yishi"])
        if not ok(r):
            return vid, None, r
        r = c.post("/api/diagnosis", json={"visit_id": vid, "diagnosis_method": "ZANGFU",
                                           "syndrome_id": syndrome_id, "syndrome_nature": "PRIMARY",
                                           "diagnosis_basis": "胁肋胀痛、善太息、脉弦，情志不畅后加重，符合肝气郁结",
                                           "treatment_principle": "疏肝理气、健脾和胃"}, headers=H["yishi"])
        did = data(r).get("id")
        if not did:
            return vid, None, r
        r = c.post("/api/diagnosis/%s/confirm" % did, json={}, headers=H["yishi"])
        if not ok(r):
            return vid, did, r
        return vid, did, r

    r = c.post("/api/visit", json={"patient_id": patient_id, "visit_type": "FIRST", "dept_code": "TCM_INTERNAL",
                                   "register_time": DAY + " 08:30:00", "remark": "挂号不填主诉（M1 v1.5）"},
               headers=H["daozhen"])
    v0 = data(r)
    visit0 = v0.get("id")
    check("挂号成功（主诉可为空）", ok(r) and visit0, str(msg(r)))
    check("就诊号按 ZC+6 生成", str(v0.get("visit_no")).startswith("ZC") and len(str(v0.get("visit_no"))) == 8,
          str(v0.get("visit_no")))
    check("挂号后状态=REGISTERED（M1 字典码）", v0.get("visit_status") == "REGISTERED", str(v0.get("visit_status")))

    print("\n=== 3. 接诊 UI-03（REF-05 与主诉前置） ===")
    r = c.post("/api/visit/%s/receive" % visit0, json={"receive_time": DAY + " 08:00:00", "dept_code": "TCM_INTERNAL",
                                                       "chief_complaint": "胁肋胀痛 3 天"}, headers=H["yishi"])
    check("REF-05 接诊时间早于挂号时间被拒", not ok(r), str(msg(r)))
    r = c.post("/api/visit/%s/receive" % visit0, json={"receive_time": DAY + " 09:00:00",
                                                       "dept_code": "TCM_INTERNAL"}, headers=H["yishi"])
    check("主诉缺失被拒（M2 Visit_Receive 前置）", not ok(r), str(msg(r)))
    r = c.post("/api/visit/%s/receive" % visit0, json={"receive_time": DAY + " 09:00:00", "dept_code": "TCM_INTERNAL",
                                                       "chief_complaint": "胁肋胀痛 3 天，善太息"}, headers=H["yishi"])
    check("接诊成功", ok(r), str(msg(r)))
    r = c.get("/api/visit/%s" % visit0, headers=H["yishi"])
    check("接诊后状态=IN_PROGRESS（M1 字典码）", data(r).get("visit_status") == "IN_PROGRESS",
          str(data(r).get("visit_status")))

    print("\n=== 4. 四诊 UI-04 ===")
    r = c.post("/api/visit/%s/four-diagnosis" % visit0, json={"inquiry_cold_heat": "无明显寒热"}, headers=H["yishi"])
    check("脉象缺失被拒", not ok(r), str(msg(r)))
    four = {"tongue_body": "PALE_RED", "tongue_coating": "THIN_WHITE", "pulse_code": "WIRY",
            "inquiry_cold_heat": "无明显寒热", "inquiry_emotion": "情志抑郁", "four_diagnosis_summary": "肝郁气滞"}
    r = c.post("/api/visit/%s/four-diagnosis" % visit0, json=dict(four, pulse_code="NOT_A_PULSE"), headers=H["yishi"])
    check("脉象字典外取值被拒", not ok(r), str(msg(r)))
    r = c.post("/api/visit/%s/four-diagnosis" % visit0, json=four, headers=H["yishi"])
    check("四诊录入成功", ok(r), str(msg(r)))
    r = c.post("/api/visit/%s/four-diagnosis" % visit0, json=dict(four, pulse_detail="脉弦细"), headers=H["yishi"])
    check("重复录入为更新语义", ok(r), str(msg(r)))
    r = c.get("/api/visit/%s/four-diagnosis" % visit0, headers=H["yishi"])
    check("四诊详情为更新后的值", (data(r) or {}).get("pulse_detail") == "脉弦细",
          str((data(r) or {}).get("pulse_detail")))

    print("\n=== 5. 辨证 UI-05 ===")
    r = c.post("/api/diagnosis", json={"visit_id": visit0, "diagnosis_method": "ZANGFU", "syndrome_id": syndrome_id,
                                       "syndrome_nature": "PRIMARY", "diagnosis_basis": "太短",
                                       "treatment_principle": "疏肝"}, headers=H["yishi"])
    check("辨证依据不足 10 字被拒", not ok(r), str(msg(r)))
    r = c.post("/api/diagnosis", json={"visit_id": visit0, "diagnosis_method": "ZANGFU", "syndrome_id": syndrome_id,
                                       "syndrome_nature": "PRIMARY",
                                       "diagnosis_basis": "胁肋胀痛、善太息、脉弦，情志不畅后加重，符合肝气郁结",
                                       "treatment_principle": "疏肝理气、健脾和胃"}, headers=H["yishi"])
    d0 = data(r)
    check("辨证保存草稿成功", ok(r) and d0.get("id"), str(msg(r)))
    check("辨证号按 BZ+6 生成", str(d0.get("diagnosis_no")).startswith("BZ"), str(d0.get("diagnosis_no")))
    r = c.post("/api/diagnosis/%s/confirm" % d0.get("id"), json={}, headers=H["yishi"])
    check("辨证确认成功", ok(r), str(msg(r)))
    r = c.post("/api/diagnosis", json={"visit_id": visit0, "diagnosis_method": "ZANGFU", "syndrome_id": syndrome_id,
                                       "syndrome_nature": "PRIMARY", "diagnosis_basis": "第二条主证应被 INV-02 拒绝",
                                       "treatment_principle": "疏肝"}, headers=H["yishi"])
    second = data(r).get("id")
    if ok(r) and second:
        r2 = c.post("/api/diagnosis/%s/confirm" % second, json={}, headers=H["yishi"])
        check("INV-02 同就诊第二条主证被拒", not ok(r2), str(msg(r2)))
    else:
        check("INV-02 同就诊第二条主证被拒", True, "保存阶段即被拒：" + str(msg(r)))

    print("\n=== 6. 处方校验与 R-01/R-03（UI-06） ===")
    RX = {"prescription_type": "HERBAL_DECOCTION", "doses": 7, "usage_method": "DAILY_1_2",
          "decoction_instruction": "水煎服，日一剂分两次温服", "medical_advice": "忌辛辣"}

    def rx_body(visit_id, items, **kw):
        b = dict(RX, visit_id=visit_id, items=items)
        b.update(kw)
        return b

    it_a10 = {"seq_no": 1, "herb_id": herbs["a"], "single_dose": 10, "decoction_method": "NONE"}
    it_b6 = {"seq_no": 2, "herb_id": herbs["b"], "single_dose": 6, "decoction_method": "PRE_DECOCT"}
    r = c.post("/api/prescription", json=rx_body(visit0, []), headers=H["yishi"])
    check("处方明细为空被拒", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [it_a10], doses=0), headers=H["yishi"])
    check("剂数 0 越界被拒（REF-10）", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [it_a10], doses=31), headers=H["yishi"])
    check("剂数 31 越界被拒（REF-10）", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [it_a10, dict(it_a10, seq_no=2)]), headers=H["yishi"])
    check("同一处方饮片重复被拒", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [dict(it_a10, single_dose=0)]), headers=H["yishi"])
    check("单剂剂量 0 被拒（REF-12）", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [dict(it_a10, single_dose=25)]), headers=H["yishi"])
    check("R-01 超 2 倍阻断（25g > 12g×2）", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [dict(it_a10, single_dose=18)]), headers=H["yishi"])
    check("R-01 超量未填理由被拒（18g ≤ 2 倍）", not ok(r), str(msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit0, [dict(it_a10, single_dose=18,
                                                             over_dose_reason="患者体质壮实，医师经验加量")]),
               headers=H["yishi"])
    check("R-01 超量填理由后通过", ok(r), str(msg(r)))
    rx_od = data(r).get("id")
    if rx_od:
        items = data(c.get("/api/prescription/%s" % rx_od, headers=H["yishi"])).get("items") or []
        check("超量理由已落库",
              any(str(i.get("over_dose_reason") or "").startswith("患者体质壮实") for i in items),
              str(items)[:90])
        c.post("/api/prescription/%s/cancel" % rx_od, json={"cancel_reason": "验收清理"}, headers=H["yishi"])
    r = c.post("/api/prescription", json=rx_body(visit0, [dict(it_b6, single_dose=8)]), headers=H["yishi"])
    check("R-03 毒性单剂 8g ≤ 上限 30g 通过", ok(r), str(msg(r)))
    if ok(r):
        c.post("/api/prescription/%s/cancel" % data(r).get("id"), json={"cancel_reason": "验收清理"}, headers=H["yishi"])
    r = c.post("/api/prescription", json=rx_body(visit0, [{"seq_no": 1, "herb_id": herbs["c"], "single_dose": 8}]),
               headers=H["yishi"])
    rx_tox = data(r).get("id")
    check("R-03 保存草稿阶段不阻断（M3 reusedBy=提交）", ok(r) and rx_tox, str(msg(r)))
    if rx_tox:
        r = c.post("/api/prescription/%s/submit" % rx_tox, json={}, headers=H["yishi"])
        check("R-03 毒性单剂 8g > 上限 5g 提交时阻断（R-01 本身通过）", not ok(r), str(msg(r)))
        c.post("/api/prescription/%s/cancel" % rx_tox, json={"cancel_reason": "验收清理"}, headers=H["yishi"])
    r = c.post("/api/prescription", json=rx_body(visit0, [{"seq_no": 1, "herb_id": herbs["c"], "single_dose": 4}]),
               headers=H["yishi"])
    check("R-03 毒性单剂 4g ≤ 上限 5g 通过", ok(r), str(msg(r)))
    if ok(r):
        c.post("/api/prescription/%s/cancel" % data(r).get("id"), json={"cancel_reason": "验收清理"}, headers=H["yishi"])

    print("\n=== 7. 全链路：提交 → 审核 → 调剂 → 发药（+ 三条联动） ===")
    r = c.post("/api/prescription", json=rx_body(visit0, [it_a10, it_b6]), headers=H["yishi"])
    rx1 = data(r).get("id")
    check("处方保存草稿成功", ok(r) and rx1, str(msg(r)))
    check("处方号按 CF+6 生成", str(data(r).get("prescription_no")).startswith("CF"),
          str(data(r).get("prescription_no")))
    check("草稿状态=DRAFT", data(r).get("prescription_status") == "DRAFT", str(data(r).get("prescription_status")))

    r = c.post("/api/prescription/%s/submit" % rx1, json={}, headers=H["yishi"])
    check("提交送审成功", ok(r), str(msg(r)))
    r = c.get("/api/prescription/%s" % rx1, headers=H["yishi"])
    check("提交后状态=PENDING_REVIEW（M1 字典码）", data(r).get("prescription_status") == "PENDING_REVIEW",
          str(data(r).get("prescription_status")))
    r = c.get("/api/visit/%s" % visit0, headers=H["yishi"])
    check("联动 Visit_Complete：就诊=COMPLETED", data(r).get("visit_status") == "COMPLETED",
          str(data(r).get("visit_status")))
    r = c.get("/api/followup", query_string={"page": 1, "size": 50}, headers=H["daozhen"])
    plans = [x for x in data(r).get("list", []) if x.get("source_visit_id") == visit0]
    check("联动 FollowUp_CreatePlan：生成 1 条随访", len(plans) == 1, "共 %d 条" % len(plans))
    follow_id = plans[0]["id"] if plans else None
    if plans:
        want = (date.fromisoformat(DAY) + timedelta(days=7)).isoformat()
        check("计划随访日期 = 挂号日期 + 剂数天", str(plans[0].get("planned_follow_up_date"))[:10] == want,
              "实得 %s / 期望 %s" % (plans[0].get("planned_follow_up_date"), want))
    r = c.post("/api/prescription/%s/submit" % rx1, json={}, headers=H["yishi"])
    check("重复提交被拒（状态不符）", not ok(r), str(msg(r)))
    r = c.get("/api/followup", query_string={"page": 1, "size": 50}, headers=H["daozhen"])
    check("重复提交未生成第二条随访",
          len([x for x in data(r).get("list", []) if x.get("source_visit_id") == visit0]) == 1, "")

    r = c.get("/api/prescription/pending-review", query_string={"page": 1, "size": 20}, headers=H["yaoshi"])
    check("待审核列表含该处方", any(x.get("id") == rx1 for x in data(r).get("list", [])), "%s 行" % data(r).get("total"))
    r = c.get("/api/flow/tasks", query_string={"page": 1, "size": 20}, headers=H["yaoshi"])
    check("审批流生成中药师待办任务", data(r).get("total", 0) >= 1, "%s 条" % data(r).get("total"))
    r = c.post("/api/prescription/%s/review" % rx1, json={"action": "REJECT"}, headers=H["yaoshi"])
    check("审核驳回未填理由被拒", not ok(r), str(msg(r)))
    r = c.post("/api/prescription/%s/review" % rx1, json={"action": "APPROVE", "comment": "用法用量合理，同意调剂"},
               headers=H["yaoshi"])
    check("审核通过成功", ok(r), str(msg(r)))
    rx = data(c.get("/api/prescription/%s" % rx1, headers=H["yaoshi"]))
    check("状态=APPROVED 且写入审核人/审核时间",
          rx.get("prescription_status") == "APPROVED" and rx.get("reviewer_id") and rx.get("review_time"), "")
    disp = rx.get("dispense_record") or {}
    disp_id = disp.get("id")
    check("联动 Dispense_CreatePending：生成待调剂记录",
          bool(disp_id) and disp.get("record_status") == "PENDING", str(disp)[:120])
    check("发药单号按 FY+6 生成", str(disp.get("dispense_no", "")).startswith("FY"), str(disp.get("dispense_no")))

    r = c.get("/api/dispense/%s/stock-check" % disp_id, headers=H["yaoshi"])
    rows = data(r) if isinstance(data(r), list) else (data(r).get("list") or [])
    check("库存校验返回逐味结果", bool(rows) and all("enough" in x for x in rows), str(rows)[:110])
    r = c.post("/api/dispense/%s/confirm" % disp_id, json={}, headers=H["yaoshi"])
    check("调剂确认成功（R-02 充足）", ok(r), str(msg(r)))
    ha = data(c.get("/api/herb/%s" % herbs["a"], headers=H["kufang"]))
    check("Herb_DeductStock：当归 500→430g", abs(float(ha.get("stock_quantity") or 0) - 430) < 1e-6,
          "stock=%s" % ha.get("stock_quantity"))
    flows = ha.get("stock_flows") or []
    check("生成 DISPENSE_OUT 负数量流水",
          any(f.get("biz_type") == "DISPENSE_OUT" and float(f.get("quantity")) < 0 for f in flows),
          str([(f.get("flow_no"), f.get("biz_type"), f.get("quantity")) for f in flows])[:140])
    check("INV-03 库存=流水净和",
          abs(float(ha.get("stock_quantity")) - sum(float(f.get("quantity") or 0) for f in flows)) < 1e-6, "")
    r = c.get("/api/prescription/%s" % rx1, headers=H["yaoshi"])
    check("调剂后处方状态=DISPENSING（M1 字典码）", data(r).get("prescription_status") == "DISPENSING",
          str(data(r).get("prescription_status")))
    r = c.post("/api/dispense/%s/issue" % disp_id, json={}, headers=H["yaoshi"])
    check("发药确认成功", ok(r), str(msg(r)))
    r = c.get("/api/prescription/%s" % rx1, headers=H["yaoshi"])
    check("发药后处方状态=ISSUED", data(r).get("prescription_status") == "ISSUED",
          str(data(r).get("prescription_status")))
    r = c.post("/api/prescription/%s/cancel" % rx1, json={"cancel_reason": "已发药尝试作废"}, headers=H["keshi"])
    check("R-04 BLOCK：已发药处方作废被阻断", not ok(r), str(msg(r)))

    print("\n=== 8. R-02 库存不足阻断 + R-04 回冲（新就诊） ===")
    visit1, _, _ = new_visit(DAY + " 10:10:00", patient_id)
    r = c.post("/api/prescription", json=rx_body(visit1, [{"seq_no": 1, "herb_id": herbs["c"], "single_dose": 4}],
                                                 doses=30), headers=H["yishi"])
    rx2 = data(r).get("id")
    check("（回冲场景）处方开具成功", bool(rx2), str(msg(r)))
    r = c.post("/api/prescription/%s/submit" % rx2, json={}, headers=H["yishi"])
    check("（回冲场景）提交成功", ok(r), str(msg(r)))
    r = c.post("/api/prescription/%s/review" % rx2, json={"action": "APPROVE", "comment": "同意"}, headers=H["yaoshi"])
    check("（回冲场景）审核通过", ok(r), str(msg(r)))
    d2 = (data(c.get("/api/prescription/%s" % rx2, headers=H["yaoshi"])).get("dispense_record") or {})
    r = c.post("/api/dispense/%s/confirm" % d2.get("id"), json={}, headers=H["yaoshi"])
    check("R-02 需求 120g > 库存 100g 阻断调剂", not ok(r), str(msg(r)))
    r = c.post("/api/herb/%s/inbound" % herbs["c"], json={"quantity": 200, "biz_date": DAY + " 11:00:00",
                                                          "inbound_no": "RK2C1%d" % sfx}, headers=H["kufang"])
    check("R-02 补货入库 200g", ok(r), str(msg(r)))
    r = c.post("/api/dispense/%s/confirm" % d2.get("id"), json={}, headers=H["yaoshi"])
    check("补货后调剂成功", ok(r), str(msg(r)))
    before = float(data(c.get("/api/herb/%s" % herbs["c"], headers=H["kufang"])).get("stock_quantity") or 0)
    r = c.post("/api/prescription/%s/cancel" % rx2, json={"cancel_reason": "患者要求停药，作废处方"}, headers=H["keshi"])
    check("R-04 VOID_WITH_ROLLBACK：已调剂处方可作废", ok(r), str(msg(r)))
    check("作废响应含分派结果 VOID_WITH_ROLLBACK",
          str((data(r) or {}).get("dispatch")) == "VOID_WITH_ROLLBACK", str(data(r))[:110])
    hc = data(c.get("/api/herb/%s" % herbs["c"], headers=H["kufang"]))
    flows = hc.get("stock_flows") or []
    check("Herb_ReturnStock：库存回冲 +120g",
          abs(float(hc.get("stock_quantity")) - before - 120) < 1e-6,
          "before=%s after=%s" % (before, hc.get("stock_quantity")))
    check("生成 VOID_ROLLBACK 正数量流水",
          any(f.get("biz_type") == "VOID_ROLLBACK" and float(f.get("quantity")) > 0 for f in flows), "")
    check("INV-03 回冲后成立",
          abs(float(hc.get("stock_quantity")) - sum(float(f.get("quantity") or 0) for f in flows)) < 1e-6, "")
    r = c.get("/api/prescription/%s" % rx2, headers=H["yaoshi"])
    check("回冲后处方状态=VOIDED", data(r).get("prescription_status") == "VOIDED",
          str(data(r).get("prescription_status")))

    print("\n=== 9. R-04 VOID_ONLY（草稿 / 待审核 / 审核通过三态） ===")
    visit2, _, _ = new_visit(DAY + " 10:20:00", patient2)
    ids = {}
    for tag in ("draft", "submitted", "approved"):
        r = c.post("/api/prescription", json=rx_body(visit2, [dict(it_a10)]), headers=H["yishi"])
        ids[tag] = data(r).get("id")
    check("（VOID_ONLY 场景）三张处方开具成功", all(ids.values()), str(ids))
    c.post("/api/prescription/%s/submit" % ids["submitted"], json={}, headers=H["yishi"])
    c.post("/api/prescription/%s/submit" % ids["approved"], json={}, headers=H["yishi"])
    c.post("/api/prescription/%s/review" % ids["approved"], json={"action": "APPROVE", "comment": "同意"},
           headers=H["yaoshi"])
    for tag in ("draft", "submitted", "approved"):
        r = c.post("/api/prescription/%s/cancel" % ids[tag], json={"cancel_reason": "验收作废（%s 态）" % tag},
                   headers=H["yishi"])
        check("作废（%s 态）成功且分派=VOID_ONLY" % tag,
              ok(r) and str((data(r) or {}).get("dispatch")) == "VOID_ONLY", str(data(r))[:100])
    if ids["approved"]:
        d3 = (data(c.get("/api/prescription/%s" % ids["approved"], headers=H["yaoshi"])).get("dispense_record") or {})
        check("VOID_ONLY 已取消其待调剂记录", str(d3.get("record_status")) == "CANCELLED", str(d3)[:110])
    flows_a = [f for f in (data(c.get("/api/herb/%s" % herbs["a"], headers=H["kufang"])).get("stock_flows") or [])
               if f.get("biz_type") == "VOID_ROLLBACK"]
    check("VOID_ONLY 未产生回冲流水", not flows_a, str(flows_a)[:80])

    print("\n=== 10. R-05 随访日期顺序 + MarkLost 超期前置 ===")
    if follow_id:
        r = c.post("/api/followup/%s/mark-lost" % follow_id, json={"remark": "联系不上"}, headers=H["daozhen"])
        check("计划未超期不得标记失访（M2 前置）", not ok(r), str(msg(r)))
        r = c.post("/api/followup/%s/mark-lost" % follow_id, json={}, headers=H["daozhen"])
        check("失访原因必填被拒", not ok(r), str(msg(r)))
    visit3, _, _ = new_visit("2026-01-05 09:00:00", patient_id)
    r = c.post("/api/prescription", json=rx_body(visit3, [dict(it_a10)]), headers=H["yishi"])
    rx3 = data(r).get("id")
    r = c.post("/api/prescription/%s/submit" % rx3, json={}, headers=H["yishi"])
    check("（R-05 场景）过期就诊开具处方并提交成功", ok(r), str(msg(r)))
    r = c.get("/api/followup", query_string={"page": 1, "size": 50}, headers=H["daozhen"])
    old_plans = [x for x in data(r).get("list", []) if x.get("source_visit_id") == visit3]
    check("（R-05 场景）生成超期随访记录（2026-01-12）", bool(old_plans),
          str(old_plans[0].get("planned_follow_up_date")) if old_plans else "无")
    if old_plans:
        fid = old_plans[0]["id"]
        r = c.post("/api/followup/%s/complete" % fid,
                   json={"actual_visit_id": visit3, "actual_follow_up_date": "2025-12-01",
                         "efficacy_level": "EFFECTIVE"}, headers=H["daozhen"])
        check("R-05 实际随访日期早于上次挂号被拒", not ok(r), str(msg(r)))
        r = c.post("/api/followup/%s/complete" % fid,
                   json={"actual_visit_id": visit3, "actual_follow_up_date": "2026-01-20",
                         "efficacy_level": "EFFECTIVE", "symptom_change": "胁痛减轻"}, headers=H["daozhen"])
        check("本次就诊缺失被拒（M2 前置）",
              not ok(c.post("/api/followup/%s/complete" % fid,
                            json={"actual_follow_up_date": "2026-01-20"}, headers=H["daozhen"])), "")
        check("R-05 合规日期随访登记成功", ok(r), str(msg(r)))

    print("\n=== 11. 越权负例 ===")
    r = c.post("/api/visit/%s/receive" % visit3, json={"receive_time": DAY + " 12:00:00",
                                                       "chief_complaint": "越权"}, headers=H["daozhen"])
    check("导诊员接诊被拒（visit:receive）", not ok(r), "HTTP %s %s" % (r.status_code, msg(r)))
    r = c.post("/api/prescription/%s/review" % ids.get("approved"), json={"action": "APPROVE", "comment": "越权"},
               headers=H["yishi"])
    check("中医师审核被拒（prescription:review）", not ok(r), "HTTP %s %s" % (r.status_code, msg(r)))
    r = c.post("/api/dispense/%s/confirm" % disp_id, json={}, headers=H["yishi"])
    check("中医师调剂被拒（dispense:confirm）", not ok(r), "HTTP %s %s" % (r.status_code, msg(r)))
    r = c.post("/api/prescription", json=rx_body(visit2, [dict(it_a10)]), headers=H["yaoshi"])
    check("中药师开方被拒（prescription:save）", not ok(r), "HTTP %s %s" % (r.status_code, msg(r)))
    r = c.get("/api/visit", query_string={"page": 1, "size": 5})
    check("未登录访问被拒（401）", r.status_code == 401, "HTTP %s" % r.status_code)

    print("\n=== 12. 库存一致性总检 ===")
    for key in ("a", "b", "c"):
        h = data(c.get("/api/herb/%s" % herbs[key], headers=H["kufang"]))
        flows = h.get("stock_flows") or []
        net = sum(float(f.get("quantity") or 0) for f in flows)
        check("INV-03 饮片 %s：库存 == 流水净和" % key, abs(float(h.get("stock_quantity")) - net) < 1e-6,
              "库存=%s 净和=%s" % (h.get("stock_quantity"), net))

    print("\n" + "=" * 84)
    print("批次 2 独立验收：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
    for n in NG:
        print("  ✗ " + n)
    print("=" * 84)
    return 1 if NG else 0


if __name__ == "__main__":
    sys.exit(main())
