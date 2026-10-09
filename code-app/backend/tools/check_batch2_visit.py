# -*- coding: utf-8 -*-
"""批次 2 门诊侧（就诊 + 四诊 + 辨证）接口自测 —— 真实 HTTP，走 Flask test_client。

覆盖 docs/批次2-实现契约.md §4.1 / §4.2 / §8.6 / §9（1、8 项的门诊侧部分）：
  挂号正例与复诊/主诉/患者状态负例 → 待接诊列表 → 接诊正例与非 REGISTERED/REF-05 负例 →
  四诊录入（脉象缺失、非接诊中负例；重复录入为更新且不新增第二条）→ 辨证保存（依据不足 10 字、
  无四诊负例）→ 确认（INV-02 第二条主证、重复确认、就诊非接诊中负例）→
  撤销就诊（有处方负例、原因缺失负例、状态不符负例）→ complete_visit 直调（状态前置、同事务
  提交与回滚、幂等开关）→ 越权负例。

用法：
  D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/check_batch2_visit.py
说明：使用独立临时库 data/check_batch2_visit.db（运行前删除重建），不污染 data/app.db。
"""
import os
import random
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DB_PATH = os.path.join(BACKEND, "data", "check_batch2_visit.db")
for _suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + _suffix):
        os.remove(DB_PATH + _suffix)
os.environ["APP_DB_PATH"] = DB_PATH

from app import app  # noqa: E402

import db  # noqa: E402
from ontology.registry import get_dictionary_items  # noqa: E402
from services import visit_service, diagnosis_service  # noqa: E402

client = app.test_client()
OK, NG = [], []
SFX = random.randint(1000, 9999)


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-58s %s" % ("[通过]" if cond else "[失败]", name, detail))
    return bool(cond)


def sec(title):
    print("\n=== %s ===" % title)


def api(method, path, token=None, payload=None, query=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    resp = getattr(client, method)(path, json=payload, headers=headers, query_string=query or {})
    try:
        body = resp.get_json()
    except Exception:
        body = None
    return resp, body or {}


def login(username, password="123456"):
    _, body = api("post", "/api/auth/login", payload={"username": username, "password": password})
    assert body.get("success"), (username, body)
    return body["data"]["token"], body["data"]


def data(body):
    return body.get("data") or {}


def msg(body):
    return body.get("message")


def ok(body):
    return bool(body.get("success"))


def expect_fail(body, keyword):
    return (not ok(body)) and (keyword in str(msg(body)))


def make_patient(token, name, phone_suffix=1):
    r, b = api("post", "/api/patient", token, {
        "patient_name": name, "gender": "MALE", "birth_date": "1980-05-20",
        "phone": "138%08d" % (SFX * 10 + phone_suffix)})
    assert ok(b), msg(b)
    return data(b)["id"]


def main():
    sec("0. 字典码自检（不猜码：以 registry 的 data_dictionaries 为准）")
    status_codes = [i["code"] for i in get_dictionary_items("DICT-VISIT", "VISIT_STATUS")]
    type_codes = [i["code"] for i in get_dictionary_items("DICT-VISIT", "VISIT_TYPE")]
    dept_codes = [i["code"] for i in get_dictionary_items("DICT-VISIT", "DEPT")]
    conclusion_codes = [i["code"] for i in get_dictionary_items("DICT-SYNDROME", "CONCLUSION_STATUS")]
    nature_codes = [i["code"] for i in get_dictionary_items("DICT-SYNDROME", "SYNDROME_NATURE")]
    print("  DICT-VISIT.VISIT_STATUS      :", status_codes)
    print("  DICT-VISIT.VISIT_TYPE        :", type_codes)
    print("  DICT-VISIT.DEPT              :", dept_codes)
    print("  DICT-SYNDROME.CONCLUSION_STATUS:", conclusion_codes)
    print("  DICT-SYNDROME.SYNDROME_NATURE  :", nature_codes)
    print("  受控状态口径                 : REGISTERED / %s / COMPLETED / CANCELLED（IN_PROGRESS 为别名）"
          % visit_service.STATUS_IN_CONSULT)
    check("就诊状态字典含 REGISTERED/COMPLETED/CANCELLED", {"REGISTERED", "COMPLETED", "CANCELLED"} <= set(status_codes))
    check("辨证结论状态字典含 DRAFT/CONFIRMED", {"DRAFT", "CONFIRMED"} <= set(conclusion_codes))

    tk_dao, _ = login("daozhen")   # ROLE-01 导诊员
    tk_yi, info_yi = login("yishi")  # ROLE-02 中医师
    tk_yao, _ = login("yaoshi")    # ROLE-03 中药师
    tk_ke, _ = login("keshi")      # ROLE-05 科室管理员（持 syndrome:save，用于取证型）
    yi_uid = str(info_yi["user"]["id"])
    dept = "TCM_INTERNAL"
    check("四账号登录成功（导诊员/中医师/中药师/科室管理员）",
          bool(tk_dao and tk_yi and tk_yao and tk_ke), "中医师 user_id=%s" % yi_uid)

    pid = make_patient(tk_dao, "门诊侧自测患者%d" % SFX)
    pid2 = make_patient(tk_dao, "门诊侧自测患者B%d" % SFX, 2)

    # ---------------------------------------------------------------- 挂号
    sec("1. Visit_Register（UI-02）")
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FOLLOW_UP",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "chief_complaint": "复诊未选上次就诊，应被拒"})
    check("负例：复诊未选上次就诊 → 拒", expect_fail(b, "上次就诊"), str(msg(b)))

    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid2, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "chief_complaint": "跨患者的上次就诊"})
    other_visit = data(b).get("id")
    r2, b2 = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FOLLOW_UP",
                                                "previous_visit_id": other_visit, "dept_code": dept,
                                                "doctor_id": yi_uid, "chief_complaint": "跨患者复诊"})
    check("负例：上次就诊不属于该患者 → 拒", expect_fail(b2, "不属于"), str(msg(b2)))

    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "register_time": "2026-09-30 07:50:00"})
    check("正例：挂号不填主诉（M1 v1.5：主诉归属接诊环节）",
          ok(b) and not data(b).get("chief_complaint"), str(msg(b)))
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "chief_complaint": "主" * 201})
    check("负例：主诉超过 200 字 → 拒", expect_fail(b, "200"), str(msg(b)))

    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "register_time": "2026-09-30 08:00:00",
                                              "chief_complaint": "胁肋胀痛 3 天，善太息"})
    v1 = data(b)
    visit1 = v1.get("id")
    check("正例：初诊挂号成功", ok(b) and visit1, str(msg(b)))
    check("就诊号 ZC+6", str(v1.get("visit_no", "")).startswith("ZC") and len(str(v1.get("visit_no"))) == 8,
          str(v1.get("visit_no")))
    check("挂号后状态=REGISTERED", v1.get("visit_status") == "REGISTERED", str(v1.get("visit_status")))
    check("挂号后未接诊（receive_time 为空、无四诊）",
          not v1.get("receive_time") and not v1.get("four_diagnosis"), "")
    check("列表含患者姓名（patient_name）", v1.get("patient_name") == "门诊侧自测患者%d" % SFX,
          str(v1.get("patient_name")))

    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FOLLOW_UP",
                                              "previous_visit_id": visit1, "dept_code": dept,
                                              "doctor_id": yi_uid, "chief_complaint": "复诊：胁痛减轻",
                                              "register_time": "2026-09-28 10:00:00"})
    visit2 = data(b).get("id")
    check("正例：复诊挂号成功（带上次就诊）", ok(b) and visit2, str(msg(b)))
    check("复诊记录保留 previous_visit_id", data(b).get("previous_visit_id") == visit1,
          str(data(b).get("previous_visit_id")))

    # 字典外取值必须被拒（不静默落库）
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST_VISIT",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "register_time": "2026-09-30 08:05:00"})
    check("负例：就诊类型字典外取值 → 拒", expect_fail(b, "字典"), str(msg(b)))
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST",
                                              "dept_code": "INTERNAL", "doctor_id": yi_uid,
                                              "register_time": "2026-09-30 08:05:00"})
    check("负例：科室字典外取值 → 拒", expect_fail(b, "字典"), str(msg(b)))
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "初诊",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "register_time": "2026-09-30 08:06:00"})
    check("兼容：字典 label（初诊）归一化为 code 后可挂号", ok(b) and data(b).get("visit_type") == "FIRST",
          str(msg(b)))

    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "chief_complaint": "带处方的就诊（用于撤销前置负例）"})
    visit_extra = data(b).get("id")
    _, sb = api("post", "/api/patient/%s/status" % pid2, tk_dao, {"patient_status": "INACTIVE"})
    r, b = api("post", "/api/visit", tk_dao, {"patient_id": pid2, "visit_type": "FIRST",
                                              "dept_code": dept, "doctor_id": yi_uid,
                                              "chief_complaint": "停用患者挂号"})
    check("负例：患者已停用 → 拒", expect_fail(b, "停用"), str(msg(b)))
    api("post", "/api/patient/%s/status" % pid2, tk_dao, {"patient_status": "ACTIVE"})

    r, b = api("get", "/api/visit", tk_dao, query={"page": 1, "size": 20, "patient_name": "门诊侧自测患者%d" % SFX})
    check("列表按患者姓名过滤命中", ok(b) and data(b).get("total", 0) >= 3, "共 %s 行" % data(b).get("total"))
    r, b = api("get", "/api/visit", tk_dao, query={"visit_status": "IN_CONSULT"})
    check("列表按状态过滤可执行（此时无接诊中记录）", ok(b) and data(b).get("total") == 0,
          "共 %s 行" % data(b).get("total"))
    r, b = api("get", "/api/visit/options", tk_dao, query={"patient_id": pid})
    check("复诊跳选框 options 返回该患者历史就诊",
          ok(b) and any(x.get("id") == visit1 for x in data(b)), "%d 条" % len(data(b) or []))
    r, b = api("get", "/api/visit", tk_dao, query={"page": "abc"})
    check("负例：分页参数非法 → 中文提示（不透出英文异常）", expect_fail(b, "必须为整数"), str(msg(b)))
    r, b = api("get", "/api/visit/options", tk_dao, query={"patient_id": "abc"})
    check("负例：options 患者标识非法 → 中文提示", expect_fail(b, "非法"), str(msg(b)))

    # ---------------------------------------------------------------- 接诊
    sec("2. Visit_Receive（UI-03）")
    r, b = api("get", "/api/visit/pending", tk_yi, query={"page": 1, "size": 50})
    check("待接诊列表可查（中医师）且含本次挂号",
          ok(b) and any(x.get("id") == visit1 for x in data(b).get("list", [])),
          "共 %s 行" % data(b).get("total"))
    check("待接诊列表全部为 REGISTERED",
          all(x.get("visit_status") == "REGISTERED" for x in data(b).get("list", [])), "")

    r, b = api("get", "/api/visit/%s" % visit1, tk_yi)
    check("详情可被中医师读取（接口级权限交叉）", ok(b) and data(b).get("id") == visit1, str(msg(b)))

    r, b = api("post", "/api/visit/%s/receive" % visit1, tk_yi,
               {"receive_time": "2026-09-30 09:00:00", "doctor_id": "999", "dept_code": dept,
                "vital_signs": "T36.6 P78 BP118/76", "chief_complaint": "胁肋胀痛 3 天，善太息",
                "present_illness": "情志不畅后出现胁肋胀痛", "past_history": "无"})
    check("正例：接诊成功", ok(b), str(msg(b)))
    r, b = api("get", "/api/visit/%s" % visit1, tk_yi)
    d1 = data(b)
    check("接诊后状态=接诊中（M1 字典码 IN_PROGRESS）",
          d1.get("visit_status") == visit_service.STATUS_IN_CONSULT, str(d1.get("visit_status")))
    check("接诊时间已写入", str(d1.get("receive_time")) == "2026-09-30 09:00:00", str(d1.get("receive_time")))
    check("接诊医师=当前登录用户（M2 后置条件）", str(d1.get("doctor_id")) == yi_uid,
          "doctor_id=%s 期望=%s" % (d1.get("doctor_id"), yi_uid))

    r, b = api("post", "/api/visit/%s/receive" % visit1, tk_yi, {"receive_time": "2026-09-30 09:30:00"})
    check("负例：非 REGISTERED 接诊 → 拒", expect_fail(b, "已挂号"), str(msg(b)))

    r, b = api("post", "/api/visit/%s/receive" % visit2, tk_yi, {"receive_time": "2026-09-27 09:00:00"})
    check("负例 REF-05：接诊时间早于挂号时间 → 拒", expect_fail(b, "不得早于"), str(msg(b)))
    r, b = api("post", "/api/visit/%s/receive" % visit2, tk_yi, {"receive_time": "2026-09-28 11:00:00"})
    check("正例：同日且晚于挂号时间可接诊", ok(b), str(msg(b)))

    # ---------------------------------------------------------------- 四诊
    sec("3. Visit_SaveFourDiagnosis（UI-04）")
    r, b = api("post", "/api/visit/%s/four-diagnosis" % visit2, tk_yi,
               {"inquiry_cold_heat": "无明显寒热", "inquiry_sweat": "偶有自汗"})
    check("负例：脉象缺失 → 拒", expect_fail(b, "脉象"), str(msg(b)))

    four = {"inquiry_cold_heat": "无明显寒热", "inquiry_sweat": "偶有自汗", "inquiry_head_body": "头胀",
            "inquiry_diet": "纳差", "inquiry_sleep": "入睡困难", "inquiry_excretion": "大便偏干",
            "inquiry_emotion": "情志抑郁", "inspection_face": "面色少华", "inspection_shape": "形体偏瘦",
            "tongue_body": "淡红", "tongue_coating": "THIN_WHITE", "auscultation_voice": "语声正常",
            "auscultation_smell": "无异常", "pulse_code": "弦", "pulse_detail": "左关弦",
            "four_diagnosis_summary": "肝郁气滞，脉弦"}
    r, b = api("post", "/api/visit/%s/four-diagnosis" % visit1, tk_yi, four)
    check("正例：四诊录入成功", ok(b), str(msg(b)))
    check("字典 label 归一化为 code（tongue_body 淡红→PALE_RED）",
          data(b).get("tongue_body") == "PALE_RED", str(data(b).get("tongue_body")))
    check("字典 label 归一化为 code（pulse_code 弦→WIRY）",
          data(b).get("pulse_code") == "WIRY", str(data(b).get("pulse_code")))
    check("四诊号按 FD+6 生成", str(data(b).get("four_diagnosis_id", "")).startswith("FD"),
          str(data(b).get("four_diagnosis_id")))

    r, b = api("post", "/api/visit/%s/four-diagnosis" % visit1, tk_yi, dict(four, pulse_detail="脉弦细",
                                                                          tongue_body="PALE_WHITE"))
    check("重复录入为更新（不新增第二条）", ok(b) and data(b).get("pulse_detail") == "脉弦细", str(msg(b)))
    r, b = api("get", "/api/visit/%s/four-diagnosis" % visit1, tk_yi)
    check("四诊详情为更新后的值", data(b).get("pulse_detail") == "脉弦细", str(data(b).get("pulse_detail")))
    conn = db.connect()
    cnt = conn.execute("SELECT COUNT(*) c FROM four_diagnosis WHERE visit_id = ? AND flag = 1",
                       (visit1,)).fetchone()["c"]
    conn.close()
    check("库中该就诊四诊仅有 1 条（ux_four_diagnosis_visit）", cnt == 1, "条数=%s" % cnt)

    r, b = api("get", "/api/visit/%s/four-diagnosis" % visit2, tk_yi)
    check("四诊详情不存在时 data=null", ok(b) and b.get("data") is None, str(b.get("data")))

    r, b = api("post", "/api/visit/%s/four-diagnosis" % visit_extra, tk_yi, four)
    check("负例：非「接诊中」就诊录四诊 → 拒", expect_fail(b, "接诊中"), str(msg(b)))

    # ---------------------------------------------------------------- 辨证
    sec("4. Diagnosis_Save / Diagnosis_Confirm（UI-05）")
    r, b = api("get", "/api/syndrome", tk_ke, query={"page": 1, "size": 5})
    syn = (data(b).get("list") or [])
    if not syn:
        r, b = api("post", "/api/syndrome", tk_ke, {"syndrome_name": "自测肝郁%d证" % SFX,
                                                    "diagnosis_method": "ZANGFU"})
        syn = [data(b)]
    syndrome_id = syn[0]["id"]
    print("  证型：%s %s" % (syn[0].get("syndrome_code"), syn[0].get("syndrome_name")))

    base_diag = {"visit_id": visit1, "diagnosis_method": "ZANGFU", "syndrome_id": syndrome_id,
                 "syndrome_nature": "PRIMARY", "treatment_principle": "疏肝理气、健脾和胃"}
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, diagnosis_basis="太短"))
    check("负例：辨证依据不足 10 字 → 拒", expect_fail(b, "10"), str(msg(b)))
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, diagnosis_basis="          胁痛"))
    check("负例：依据不足 10 字（去空白后判定）→ 拒", expect_fail(b, "10"), str(msg(b)))
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, visit_id=visit2,
                                                     diagnosis_basis="该就诊尚未录入四诊信息，应被拒"))
    check("负例：就诊无四诊信息 → 拒", expect_fail(b, "四诊"), str(msg(b)))
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, diagnosis_method="NOT_A_METHOD",
                                                     diagnosis_basis="辨证方法越界，应被拒的用例"))
    check("负例：辨证方法不在字典范围 → 拒", expect_fail(b, "字典"), str(msg(b)))
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, treatment_principle=" ",
                                                     diagnosis_basis="治法为空，应被拒绝的用例"))
    check("负例：治法为空 → 拒", expect_fail(b, "治法"), str(msg(b)))

    r, b = api("post", "/api/diagnosis", tk_yi, dict(
        base_diag, diagnosis_basis="胁肋胀痛、善太息、脉弦，情志不畅后加重，符合肝气郁结"))
    diag1 = data(b).get("id")
    check("正例：辨证保存草稿成功", ok(b) and diag1, str(msg(b)))
    check("辨证号 BZ+6", str(data(b).get("diagnosis_no", "")).startswith("BZ")
          and len(str(data(b).get("diagnosis_no"))) == 8, str(data(b).get("diagnosis_no")))
    check("初始状态=DRAFT", data(b).get("conclusion_status") == "DRAFT", str(data(b).get("conclusion_status")))
    check("返回带证型名称", bool(data(b).get("syndrome_name")), str(data(b).get("syndrome_name")))

    r, b = api("get", "/api/diagnosis", tk_yi, query={"visit_id": visit1})
    check("按就诊查询辨证结论列表", ok(b) and any(x.get("id") == diag1 for x in data(b)), "")
    r, b = api("get", "/api/diagnosis", tk_yi, query={"visit_id": "abc"})
    check("负例：visit_id 非法 → 拒", expect_fail(b, "非法"), str(msg(b)))
    r, b = api("get", "/api/diagnosis", tk_yi)
    check("负例：缺 visit_id → 拒", expect_fail(b, "就诊记录必填"), str(msg(b)))

    r, b = api("put", "/api/diagnosis/%s" % diag1, tk_yi, dict(
        base_diag, diagnosis_basis="胁肋胀痛、善太息、脉弦，情志不畅后加重，肝气郁结（修改）",
        treatment_principle="疏肝理气"))
    check("正例：草稿可修改", ok(b) and data(b).get("treatment_principle") == "疏肝理气", str(msg(b)))

    r, b = api("post", "/api/diagnosis", tk_yi, dict(
        base_diag, diagnosis_basis="同一就诊第二条主证，应被 INV-02 拒绝的用例", treatment_principle="疏肝"))
    second = data(b).get("id")
    check("负例 INV-02：同就诊第二条主证保存被拒（唯一索引兜底 + 预检）",
          (not ok(b)) and ("主证" in str(msg(b))), str(msg(b)))

    r, b = api("post", "/api/diagnosis/%s/confirm" % diag1, tk_yi, {})
    check("正例：辨证确认成功", ok(b) and data(b).get("conclusion_status") == "CONFIRMED", str(msg(b)))
    r, b = api("post", "/api/diagnosis/%s/confirm" % diag1, tk_yi, {})
    check("负例：重复确认 → 拒", expect_fail(b, "已确认"), str(msg(b)))
    r, b = api("put", "/api/diagnosis/%s" % diag1, tk_yi, dict(base_diag, diagnosis_basis="已确认不可修改的用例"))
    check("负例：已确认结论不可修改", expect_fail(b, "草稿"), str(msg(b)))

    # 兼证（SECONDARY）可再存一条，用于验证「主证唯一」只约束 PRIMARY
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, syndrome_nature="SECONDARY",
                                                     diagnosis_basis="兼见脾虚湿盛，纳差便溏舌淡",
                                                     treatment_principle="健脾化湿"))
    diag2 = data(b).get("id")
    check("正例：兼证（SECONDARY）可另存一条", ok(b) and diag2, str(msg(b)))
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, syndrome_nature="PRIMARY",
                                                     diagnosis_basis="第三条主证（仍应被拒）的用例"))
    check("负例 INV-02：第三条主证仍被拒", not ok(b), str(msg(b)))

    # 确认级别 INV-02：临时摘除唯一索引后直插第二条主证，验证服务层确认前置
    conn = db.connect()
    conn.execute("DROP INDEX IF EXISTS ux_diagnosis_primary")
    conn.execute(
        "INSERT INTO syndrome_diagnosis (diagnosis_no, visit_id, diagnosis_method, syndrome_id, "
        "syndrome_nature, diagnosis_basis, treatment_principle, conclusion_status, flag) "
        "VALUES (?, ?, ?, ?, 'PRIMARY', ?, ?, 'DRAFT', 1)",
        ("BZ9999%02d" % (SFX % 100), visit1, "ZANGFU", syndrome_id,
         "绕过唯一索引直插的第二条主证，用于验证确认前置", "疏肝"))
    conn.commit()
    raw_id = conn.execute("SELECT MAX(id) i FROM syndrome_diagnosis").fetchone()["i"]
    conn.close()
    r, b = api("post", "/api/diagnosis/%s/confirm" % raw_id, tk_yi, {})
    check("负例 INV-02：确认阶段校验主证唯一（服务层前置）", expect_fail(b, "主证"), str(msg(b)))
    conn = db.connect()
    conn.execute("DELETE FROM syndrome_diagnosis WHERE id = ?", (raw_id,))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_diagnosis_primary ON syndrome_diagnosis "
                 "(visit_id) WHERE syndrome_nature = 'PRIMARY' AND flag = 1")
    conn.commit()
    conn.close()
    conn = db.connect()
    idx = conn.execute("SELECT COUNT(*) c FROM sqlite_master WHERE type='index' "
                       "AND name='ux_diagnosis_primary'").fetchone()["c"]
    conn.close()
    check("（已还原唯一索引 ux_diagnosis_primary）", idx == 1, "index=%s" % idx)

    # 确认前置：就诊非「接诊中」
    r, b = api("post", "/api/visit/%s/four-diagnosis" % visit2, tk_yi, four)
    check("（准备）visit2 四诊录入成功", ok(b), str(msg(b)))
    conn = db.connect()
    conn.execute("UPDATE visit SET visit_status = 'REGISTERED' WHERE id = ?", (visit2,))
    conn.commit()
    conn.close()
    r, b = api("post", "/api/diagnosis", tk_yi, dict(base_diag, visit_id=visit2,
                                                     diagnosis_basis="将在已挂号状态下确认的用例",
                                                     syndrome_nature="SECONDARY"))
    diag_v2 = data(b).get("id")
    check("（准备）visit2 兼证保存成功", ok(b) and diag_v2, str(msg(b)))
    r, b = api("post", "/api/diagnosis/%s/confirm" % diag_v2, tk_yi, {})
    check("负例：就诊非「接诊中」时确认 → 拒", expect_fail(b, "接诊中"), str(msg(b)))
    conn = db.connect()
    conn.execute("UPDATE visit SET visit_status = 'IN_PROGRESS' WHERE id = ?", (visit2,))
    conn.commit()
    conn.close()

    # ---------------------------------------------------------------- 撤销就诊
    sec("5. Visit_Cancel（UI-02 撤销按钮）")
    r, b = api("post", "/api/visit/%s/cancel" % visit_extra, tk_dao, {})
    check("负例：撤销原因缺失 → 拒", expect_fail(b, "撤销原因"), str(msg(b)))

    # 建一条处方记录（处方模块属后端 B；此处直插以验证 Visit_Cancel 的「无处方」前置）
    conn = db.connect()
    conn.execute(
        "INSERT INTO prescription (prescription_no, visit_id, patient_id, doctor_id, "
        "prescription_type, doses, usage_method, prescribe_time, prescription_status, flag) "
        "VALUES (?, ?, ?, ?, 'HERBAL_DECOCTION', 7, 'DAILY_1_2', '2026-09-30 10:00:00', 'DRAFT', 1)",
        ("CF9999%02d" % (SFX % 100), visit_extra, pid, yi_uid))
    conn.commit()
    conn.close()
    r, b = api("post", "/api/visit/%s/cancel" % visit_extra, tk_dao, {"cancel_reason": "已开方仍尝试撤销"})
    check("负例：该就诊下已存在处方 → 拒", expect_fail(b, "处方"), str(msg(b)))

    r, b = api("post", "/api/visit/%s/cancel" % visit1, tk_yi, {"cancel_reason": "患者临时离开，退号"})
    check("正例：接诊中就诊可撤销（中医师持 visit:cancel）", ok(b), str(msg(b)))
    check("撤销后状态=CANCELLED", data(b).get("visit_status") == "CANCELLED", str(data(b).get("visit_status")))
    check("撤销原因追加到 remark", "撤销原因：患者临时离开，退号" in str(data(b).get("remark")),
          str(data(b).get("remark")))
    r, b = api("post", "/api/visit/%s/cancel" % visit1, tk_yi, {"cancel_reason": "重复撤销"})
    check("负例：重复撤销（状态不符）→ 拒", expect_fail(b, "已挂号"), str(msg(b)))

    # ---------------------------------------------------------------- 越权
    sec("6. 越权负例（§9-9 门诊侧部分）")
    r, b = api("post", "/api/visit/%s/receive" % visit2, tk_dao, {"receive_time": "2026-09-28 12:00:00"})
    check("导诊员接诊被拒（visit:receive）", (not ok(b)) and r.status_code == 403,
          "HTTP %s %s" % (r.status_code, msg(b)))
    r, b = api("get", "/api/visit", tk_yao)
    check("中药师查就诊列表被拒（visit:register）", (not ok(b)) and r.status_code == 403,
          "HTTP %s %s" % (r.status_code, msg(b)))
    r, b = api("post", "/api/diagnosis", tk_dao, dict(base_diag, visit_id=visit2,
                                                      diagnosis_basis="导诊员无 diagnosis:save，应被拒"))
    check("导诊员保存辨证被拒（diagnosis:save）", (not ok(b)) and r.status_code == 403,
          "HTTP %s %s" % (r.status_code, msg(b)))
    r, b = api("post", "/api/diagnosis/%s/confirm" % diag1, tk_yao, {})
    check("中药师确认辨证被拒（diagnosis:confirm）", (not ok(b)) and r.status_code == 403,
          "HTTP %s %s" % (r.status_code, msg(b)))

    # ---------------------------------------------------------------- complete_visit
    sec("7. complete_visit（系统行为 Visit_Complete）直调验证")
    check("函数签名可被药房模块按契约调用",
          callable(getattr(visit_service, "complete_visit", None))
          and callable(getattr(visit_service, "get_visit", None)), "")

    try:
        visit_service.complete_visit(visit2, None)
        check("负例：未传 conn → 拒", False, "未抛异常")
    except ValueError as e:
        check("负例：未传 conn → 拒（必须同事务）", "事务" in str(e), str(e))

    try:
        db.transaction(lambda conn: visit_service.complete_visit(999999, conn))
        check("负例：就诊不存在 → 拒", False, "未抛异常")
    except ValueError as e:
        check("负例：就诊不存在 → 拒", "不存在" in str(e), str(e))

    try:
        db.transaction(lambda conn: visit_service.complete_visit(visit_extra, conn))
        check("负例：REGISTERED 状态 → 拒", False, "未抛异常")
    except ValueError as e:
        check("负例：REGISTERED 状态 → 拒（中文提示）", "接诊中" in str(e), str(e))

    # 同事务回滚：事务内完成就诊后抛错 → 状态必须回滚为「接诊中」
    def _rollback(conn):
        visit_service.complete_visit(visit2, conn)
        raise RuntimeError("force rollback")

    try:
        db.transaction(_rollback)
    except RuntimeError:
        pass
    after = visit_service.get_visit(visit2)
    check("同事务回滚：回滚后仍为接诊中", after["visit_status"] == visit_service.STATUS_IN_CONSULT,
          str(after["visit_status"]))

    def _commit(conn):
        return visit_service.complete_visit(visit2, conn)

    row = db.transaction(_commit)
    check("正例：接诊中 → COMPLETED（返回就诊记录）",
          row and row.get("visit_status") == "COMPLETED", str(row.get("visit_status")))
    check("get_visit 读到 COMPLETED 与 label",
          visit_service.get_visit(visit2)["visit_status_label"] == "已完成",
          str(visit_service.get_visit(visit2)["visit_status_label"]))
    r, b = api("get", "/api/visit/%s" % visit2, tk_yi)
    check("HTTP 详情同步可见 COMPLETED", data(b).get("visit_status") == "COMPLETED",
          str(data(b).get("visit_status")))

    try:
        db.transaction(lambda conn: visit_service.complete_visit(visit2, conn))
        check("负例：已完成就诊重复完成 → 拒", False, "未抛异常")
    except ValueError as e:
        check("负例：已完成就诊重复完成 → 拒（中文提示）", "已完成" in str(e), str(e))
    again = db.transaction(lambda conn: visit_service.complete_visit(visit2, conn, allow_idempotent=True))
    check("allow_idempotent=True 时幂等返回", again and again.get("visit_status") == "COMPLETED",
          str(again.get("visit_status")))

    # ---------------------------------------------------------------- 详情聚合
    sec("8. 详情聚合（GET /api/visit/{id}：患者 + 四诊 + 辨证 + 处方摘要）")
    r, b = api("get", "/api/visit/%s" % visit1, tk_yi)
    d = data(b)
    check("详情含患者姓名/就诊号/状态 label",
          d.get("patient_name") and d.get("visit_no") and d.get("visit_status_label"),
          "%s / %s" % (d.get("visit_no"), d.get("visit_status_label")))
    check("详情含 four_diagnosis（含脉象）",
          (d.get("four_diagnosis") or {}).get("pulse_code") == "WIRY", str(d.get("has_four_diagnosis")))
    check("详情含 syndrome_diagnoses[]（带证型名称）",
          any(x.get("syndrome_name") for x in d.get("syndrome_diagnoses") or []),
          str([(x.get("diagnosis_no"), x.get("conclusion_status")) for x in d.get("syndrome_diagnoses") or []]))
    r, b = api("get", "/api/visit/%s" % visit_extra, tk_yi)
    de = data(b)
    check("详情含 prescriptions[] 摘要与处方数",
          de.get("prescription_count") == 1 and str((de.get("prescriptions") or [{}])[0]
                                                    .get("prescription_no", "")).startswith("CF"),
          str(de.get("prescription_count")))
    r, b = api("get", "/api/visit/999999", tk_yi)
    check("不存在的就诊 → data=null", ok(b) and b.get("data") is None, str(b.get("data")))

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 86)
    print("批次 2 门诊侧自测：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
    for n in NG:
        print("  - " + n)
    print("数据库：%s" % DB_PATH)
    print("=" * 86)
    return 1 if NG else 0


if __name__ == "__main__":
    sys.exit(main())
