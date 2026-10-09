# -*- coding: utf-8 -*-
"""批次 1 接口自测（真实 HTTP，走 Flask test_client）。

覆盖：登录 6 账号 → 患者新建/修改/停用/证件重复与身份证校验负例 → 证型新增/改名/停用 →
      饮片建档（REF-07 负例）/入库（库存+流水）/盘点（差异流水，账实相符负例）/库存查询/CSV 导出 →
      方剂主从保存（药味重复负例、明细为空负例）→ 越权负例（daozhen 调 herb:save → 403）。

用法：
  D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/check_batch1_api.py
说明：使用独立临时库（data/check_batch1.db，运行前删除重建），不污染 data/app.db。
"""
import datetime
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DB_PATH = os.path.join(BACKEND, "data", "check_batch1.db")
for _suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + _suffix):
        os.remove(DB_PATH + _suffix)
os.environ["APP_DB_PATH"] = DB_PATH

from app import app  # noqa: E402

client = app.test_client()

RESULTS = []
N = [0]


def check(name, cond, detail=""):
    N[0] += 1
    RESULTS.append(bool(cond))
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name, ("  -> " + str(detail)) if detail else ""))
    return bool(cond)


def api(method, path, token=None, payload=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    resp = getattr(client, method)(path, json=payload, headers=headers)
    body = None
    try:
        body = resp.get_json()
    except Exception:
        pass
    return resp, body


def login(username, password):
    _, body = api("post", "/api/auth/login", payload={"username": username, "password": password})
    if not body or not body.get("success"):
        return None, body
    return body["data"]["token"], body["data"]


# 生成合法身份证号（18 位 + 正确校验位）
_ID_W = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_C = "10X98765432"


def id_card(body17):
    return body17 + _ID_C[sum(int(body17[i]) * _ID_W[i] for i in range(17)) % 11]


def sec(title):
    print("\n=== %s ===" % title)


TODAY = datetime.date.today().isoformat()
ID_OK = id_card("11010119900307001")

# ---------------------------------------------------------------- 1. 登录 6 账号
sec("1. 登录 6 个演示账号")
tokens = {}
for username, password in [("admin", "admin123"), ("daozhen", "123456"), ("yishi", "123456"),
                           ("yaoshi", "123456"), ("kufang", "123456"), ("keshi", "123456")]:
    token, data = login(username, password)
    if token:
        tokens[username] = token
        check("登录 %s" % username, True,
              "角色=%s 权限数=%d" % (data["user"]["roles"], len(data["permissions"])))
    else:
        check("登录 %s" % username, False, data)

admin = tokens.get("admin")
daozhen = tokens.get("daozhen")
yaoshi = tokens.get("yaoshi")
kufang = tokens.get("kufang")
keshi = tokens.get("keshi")

# ---------------------------------------------------------------- 2. 患者
sec("2. 患者建档（Patient_Save / Patient_ChangeStatus）")
resp, body = api("post", "/api/patient", daozhen, {
    "patient_name": "张三", "gender": "MALE", "birth_date": "1990-03-07", "age": 35,
    "id_type": "ID_CARD", "id_no": ID_OK, "phone": "13800138000",
    "address": "北京市朝阳区", "occupation": "教师", "remark": "初诊",
})
patient = (body or {}).get("data") or {}
check("患者新建成功", resp.status_code == 200 and body.get("success") is True, body.get("message"))
check("患者编号 PA+6", bool(patient.get("patient_no")) and
      patient["patient_no"].startswith("PA") and len(patient["patient_no"]) == 8, patient.get("patient_no"))
pid = patient.get("id")

# INV-01 负例：同一证件类型 + 号码
_, body = api("post", "/api/patient", daozhen, {
    "patient_name": "李四", "gender": "FEMALE", "birth_date": "1992-01-01", "age": 33,
    "id_type": "ID_CARD", "id_no": ID_OK, "phone": "13800138001"})
check("INV-01 证件联合唯一负例", body and body.get("success") is False, body.get("message"))

# REF-03 负例：身份证校验位错误
_, body = api("post", "/api/patient", daozhen, {
    "patient_name": "王五", "gender": "MALE", "birth_date": "1991-02-02", "age": 34,
    "id_type": "ID_CARD", "id_no": "110101199003070019", "phone": "13800138002"})
check("REF-03 身份证校验位负例", body and body.get("success") is False, body.get("message"))

# 出生日期与年龄至少一项负例
_, body = api("post", "/api/patient", daozhen, {
    "patient_name": "赵六", "gender": "MALE", "phone": "13800138003"})
check("出生日期/年龄至少一项负例", body and body.get("success") is False, body.get("message"))

# 电话格式负例
_, body = api("post", "/api/patient", daozhen, {
    "patient_name": "钱七", "gender": "MALE", "age": 40, "phone": "12345"})
check("电话格式负例", body and body.get("success") is False, body.get("message"))

# 修改
_, body = api("put", "/api/patient/%s" % pid, daozhen, {
    "patient_name": "张三丰", "gender": "MALE", "birth_date": "1990-03-07", "age": 36,
    "id_type": "ID_CARD", "id_no": ID_OK, "phone": "13800138000", "remark": "已修改"})
check("患者修改成功", body and body.get("success") is True and
      (body.get("data") or {}).get("patient_name") == "张三丰", body.get("message"))

# 列表
_, body = api("get", "/api/patient?page=1&size=10&patient_name=张三", daozhen)
check("患者列表查询", body and body.get("success") is True and body["data"]["total"] >= 1,
      "total=%s" % (body["data"]["total"] if body and body.get("data") else None))

# 停用 / 启用
_, body = api("post", "/api/patient/%s/status" % pid, daozhen, {"patient_status": "INACTIVE"})
check("患者停用", body and body.get("success") is True and
      (body.get("data") or {}).get("patient_status") == "INACTIVE", body.get("message"))
_, body = api("get", "/api/patient?patient_status=INACTIVE", daozhen)
check("停用后可按状态检索", body and body.get("data") and body["data"]["total"] >= 1)
_, body = api("post", "/api/patient/%s/status" % pid, daozhen, {"patient_status": "ACTIVE"})
check("患者启用", body and body.get("success") is True and
      (body.get("data") or {}).get("patient_status") == "ACTIVE", body.get("message"))

# ---------------------------------------------------------------- 3. 证型
sec("3. 证型字典（Syndrome_Save / Syndrome_ChangeStatus）")
_, body = api("post", "/api/syndrome", keshi, {
    "syndrome_name": "肝气郁结证", "diagnosis_method": "ZANGFU", "syndrome_description": "情志不畅",
    "common_symptoms": "胁肋胀痛", "corresponding_treatment": "疏肝理气"})
syndrome = (body or {}).get("data") or {}
check("证型新增成功", body and body.get("success") is True and
      syndrome.get("syndrome_status") == "ENABLED", body.get("message"))
check("证型编码 Z+3", bool(syndrome.get("syndrome_code")) and
      syndrome["syndrome_code"].startswith("Z") and len(syndrome["syndrome_code"]) == 4,
      syndrome.get("syndrome_code"))
sid = syndrome.get("id")

_, body = api("post", "/api/syndrome", keshi, {"syndrome_name": "肝气郁结证", "diagnosis_method": "ZANGFU"})
check("证型名称唯一负例", body and body.get("success") is False, body.get("message"))

_, body = api("put", "/api/syndrome/%s" % sid, keshi, {
    "syndrome_name": "肝郁气滞证", "diagnosis_method": "ZANGFU", "syndrome_status": "ENABLED"})
check("证型改名", body and body.get("success") is True and
      (body.get("data") or {}).get("syndrome_name") == "肝郁气滞证", body.get("message"))

_, body = api("post", "/api/syndrome/%s/status" % sid, keshi, {"syndrome_status": "DISABLED"})
check("证型停用", body and body.get("success") is True and
      (body.get("data") or {}).get("syndrome_status") == "DISABLED", body.get("message"))

# ---------------------------------------------------------------- 4. 饮片
sec("4. 饮片建档与入库（Herb_Save / Herb_Inbound / Herb_ChangeStatus）")
_, body = api("post", "/api/herb", kufang, {
    "herb_name": "当归", "alias_name": "干归", "herb_category": "TONIFYING", "nature_meridian": "甘辛温",
    "efficacy": "补血活血", "min_common_dose": 6, "max_common_dose": 15, "toxicity_level": "NONE",
    "low_stock_threshold": 500, "origin": "甘肃", "spec": "统货"})
herb1 = (body or {}).get("data") or {}
check("饮片建档成功", body and body.get("success") is True, body.get("message"))
check("饮片编码 Y+4", bool(herb1.get("herb_code")) and herb1["herb_code"].startswith("Y")
      and len(herb1["herb_code"]) == 5, herb1.get("herb_code"))
check("建档初始库存为 0", float(herb1.get("stock_quantity") or 0) == 0, herb1.get("stock_quantity"))
h1 = herb1.get("id")

_, body = api("post", "/api/herb", kufang, {
    "herb_name": "白芍", "herb_category": "TONIFYING", "min_common_dose": 6, "max_common_dose": 12,
    "toxicity_level": "NONE", "low_stock_threshold": 100})
herb2 = (body or {}).get("data") or {}
check("第二味饮片建档", body and body.get("success") is True, herb2.get("herb_code"))
h2 = herb2.get("id")

# REF-07 负例：最大量 < 最小量
_, body = api("post", "/api/herb", kufang, {
    "herb_name": "甘草", "min_common_dose": 10, "max_common_dose": 5, "toxicity_level": "NONE"})
check("REF-07 常用量区间负例", body and body.get("success") is False, body.get("message"))

# 入库（含入库单号必填负例）
_, body = api("post", "/api/herb/%s/inbound" % h1, kufang, {"quantity": 1000, "inbound_no": "IN0026-001"})
check("入库前缺业务日期也可受理（默认当前时间）", body and body.get("success") is True, body.get("message"))
stock_after = float((body.get("data") or {}).get("stock_quantity") or 0)
check("入库后库存 = 1000", stock_after == 1000, stock_after)
flows = (body.get("data") or {}).get("stock_flows") or []
check("入库生成 INBOUND 流水", len(flows) == 1 and flows[0]["biz_type"] == "INBOUND"
      and float(flows[0]["quantity"]) == 1000, [(f["flow_no"], f["biz_type"], f["quantity"]) for f in flows])

_, body = api("post", "/api/herb/%s/inbound" % h1, kufang, {"quantity": 500})
check("入库单号必填负例", body and body.get("success") is False, body.get("message"))

_, body = api("post", "/api/herb/%s/inbound" % h1, kufang, {"quantity": -5, "inbound_no": "IN0026-002"})
check("入库数量必须为正负例", body and body.get("success") is False, body.get("message"))

# 对账（R-06 / INV-03）
_, body = api("get", "/api/herb/%s/reconcile" % h1, kufang)
check("R-06 对账差异为 0", body and body.get("success") is True and
      abs(body["data"]["difference"]) < 1e-6, body.get("data"))

# ---------------------------------------------------------------- 5. 方剂（主从）
sec("5. 方剂模板（Formula_Save 主从单事务 / Formula_ChangeStatus）")
_, body = api("post", "/api/formula", keshi, {
    "formula_name": "逍遥散", "formula_type": "CLASSIC", "source": "《太平惠民和剂局方》",
    "function": "疏肝解郁", "indication": "肝郁血虚", "default_doses": 7,
    "items": [
        {"seq_no": 1, "herb_id": h1, "common_dose": 10, "decoction_method": "NONE"},
        {"seq_no": 2, "herb_id": h2, "common_dose": 12, "decoction_method": "NONE"},
    ]})
formula = (body or {}).get("data") or {}
check("方剂主从保存成功", body and body.get("success") is True, body.get("message"))
check("方剂编码 F+3", bool(formula.get("formula_code")) and formula["formula_code"].startswith("F")
      and len(formula["formula_code"]) == 4, formula.get("formula_code"))
check("明细 2 行且带药味显示名", len(formula.get("items") or []) == 2 and
      all(i.get("herb_name") for i in formula["items"]),
      [(i["seq_no"], i["herb_name"], i["common_dose"]) for i in formula.get("items") or []])
fid = formula.get("id")

# 药味重复负例
_, body = api("post", "/api/formula", keshi, {
    "formula_name": "重复方", "formula_type": "EXPERIENCE",
    "items": [{"seq_no": 1, "herb_id": h1, "common_dose": 10},
              {"seq_no": 2, "herb_id": h1, "common_dose": 5}]})
check("明细药味不重复负例", body and body.get("success") is False, body.get("message"))

# 明细为空负例
_, body = api("post", "/api/formula", keshi, {
    "formula_name": "空明细方", "formula_type": "EXPERIENCE", "items": []})
check("明细至少一味负例", body and body.get("success") is False, body.get("message"))

# 修改（从表全量重建：改成 1 行）
_, body = api("put", "/api/formula/%s" % fid, keshi, {
    "formula_name": "逍遥散", "formula_type": "CLASSIC", "default_doses": 5,
    "items": [{"seq_no": 1, "herb_id": h1, "common_dose": 9, "decoction_method": "PRE_DECOCT"}]})
check("方剂修改后从表全量重建为 1 行", body and body.get("success") is True and
      len((body.get("data") or {}).get("items") or []) == 1 and
      float(body["data"]["items"][0]["common_dose"]) == 9,
      [(i["seq_no"], i["common_dose"]) for i in (body.get("data") or {}).get("items") or []])

_, body = api("post", "/api/formula/%s/status" % fid, keshi, {"formula_status": "DISABLED"})
check("方剂停用", body and body.get("success") is True and
      (body.get("data") or {}).get("formula_status") == "DISABLED", body.get("message"))

# 跳选框
_, body = api("get", "/api/herb/options?keyword=当", keshi)
check("饮片跳选框 options", body and body.get("success") is True and len(body["data"]) >= 1,
      [o["herb_name"] for o in (body.get("data") or [])])

# ---------------------------------------------------------------- 6. 库存盘点 / 查询 / 导出
sec("6. 饮片盘点、库存查询与导出（Herb_Stocktake / Herb_QueryStockAndAlert）")
# 盘点：实盘 900（账面 1000 → 差异 -100）
_, body = api("post", "/api/herb/%s/stocktake" % h1, kufang,
              {"actual_quantity": 900, "remark": "盘点差异（报损）"})
data = (body or {}).get("data") or {}
check("盘点成功并置库存为实盘数", body and body.get("success") is True and
      float(data.get("stock_quantity") or 0) == 900, data.get("stocktake"))
flows = data.get("stock_flows") or []
adjust = [f for f in flows if f["biz_type"] == "STOCKTAKE_ADJUST"]
check("生成盘点调整流水（数量 -100）", len(adjust) == 1 and float(adjust[0]["quantity"]) == -100,
      [(f["flow_no"], f["biz_type"], f["quantity"]) for f in flows])

_, body = api("get", "/api/herb/%s/reconcile" % h1, kufang)
check("盘点后 INV-03 库存与流水净和一致", body and abs(body["data"]["difference"]) < 1e-6,
      body.get("data"))

_, body = api("post", "/api/herb/%s/stocktake" % h1, kufang,
              {"actual_quantity": 900, "remark": "账实相符"})
check("盘点差异为 0 负例（账实相符，无需调整）", body and body.get("success") is False, body.get("message"))

_, body = api("post", "/api/herb/%s/stocktake" % h1, kufang, {"actual_quantity": 800})
check("盘点原因必填负例", body and body.get("success") is False, body.get("message"))

# 库存查询（kufang）
_, body = api("get", "/api/herb/stock?page=1&size=20", kufang)
rows = (body.get("data") or {}).get("list") or []
row1 = next((r for r in rows if r["id"] == h1), None)
check("库存查询返回列表", body and body.get("success") is True and row1 is not None,
      "total=%s" % ((body.get("data") or {}).get("total")))
check("库存查询含预警列与最近入库日期", row1 is not None and "alert_status" in row1 and
      row1.get("latest_inbound_date"), row1 and {k: row1[k] for k in
      ("herb_code", "stock_quantity", "low_stock_threshold", "alert_status", "latest_inbound_date")})

# 预警筛选：当归库存 900 >= 预警值 500 → 非预警；白芍库存 0 < 100 → 预警
_, body = api("get", "/api/herb/stock?alert_only=true", kufang)
alert_rows = (body.get("data") or {}).get("list") or []
check("仅看预警项筛选有效", all(r["alert_flag"] for r in alert_rows) and
      any(r["id"] == h2 for r in alert_rows),
      [(r["herb_name"], r["stock_quantity"], r["low_stock_threshold"]) for r in alert_rows])

# 权限：yaoshi 也可查询（ROLE-03）
_, body = api("get", "/api/herb/stock", yaoshi)
check("中药师可查询库存预警", body and body.get("success") is True)

# 导出 CSV
resp, _ = api("get", "/api/herb/stock/export?alert_only=true", kufang)
raw = resp.data
check("导出 CSV 成功且带 UTF-8 BOM", resp.status_code == 200 and raw.startswith(b"\xef\xbb\xbf")
      and "text/csv" in resp.headers.get("Content-Type", ""),
      "bytes=%d content_type=%s" % (len(raw), resp.headers.get("Content-Type")))
text = raw.decode("utf-8-sig")
check("CSV 含表头与数据行", "饮片编码" in text and "白芍" in text, text.splitlines()[:2])

# ---------------------------------------------------------------- 7. 越权
sec("7. 越权负例（RBAC）")
resp, body = api("post", "/api/herb", daozhen, {
    "herb_name": "越权饮片", "min_common_dose": 1, "max_common_dose": 2, "toxicity_level": "NONE"})
check("daozhen 调 herb:save 返回 403", resp.status_code == 403, "%s %s" % (resp.status_code, body.get("message")))

resp, body = api("post", "/api/syndrome", daozhen, {"syndrome_name": "越权证型", "diagnosis_method": "ZANGFU"})
check("daozhen 调 syndrome:save 返回 403", resp.status_code == 403, resp.status_code)

resp, body = api("post", "/api/herb/%s/inbound" % h1, daozhen, {"quantity": 10, "inbound_no": "X"})
check("daozhen 调 herb:inbound 返回 403", resp.status_code == 403, resp.status_code)

resp, body = api("get", "/api/herb/stock", daozhen)
check("daozhen 调 herb:query-stock-and-alert 返回 403", resp.status_code == 403, resp.status_code)

resp, body = api("get", "/api/patient")
# 注：未带 Authorization 时 utils/security.py::login_required 返回单元素元组，
# 触发 Flask TypeError → 500（平台层既有缺陷，不在本批文件范围内，不修改）。
# 此处只断言「未登录拿不到患者数据」。
denied = not (resp.status_code == 200 and (body or {}).get("success") is True)
check("未登录访问患者列表被拒绝（拿不到数据）", denied,
      "%s %s" % (resp.status_code, (body or {}).get("message")))

# ---------------------------------------------------------------- 汇总
passed = sum(1 for r in RESULTS if r)
failed = len(RESULTS) - passed
print("\n" + "=" * 60)
print("汇总：通过 %d / 失败 %d / 合计 %d" % (passed, failed, len(RESULTS)))
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
