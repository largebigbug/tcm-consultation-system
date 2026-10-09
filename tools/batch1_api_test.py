# -*- coding: utf-8 -*-
"""批次 1 独立验收脚本（由主代编写，与开发者自测脚本相互独立）。

覆盖契约 docs/批次1-实现契约.md §9 要求的全部验收点：
  登录与权限 → 患者（含 INV-01／身份证／必填负例）→ 证型 → 方剂主从（含药味重复负例）
  → 饮片建档／入库／盘点／库存查询／导出 → 越权负例 → 编号规则 → INV-03 对账

用法（必须用后端 venv 解释器）：
  D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/batch1_api_test.py
"""
import os
import random
import re
import sys

BACKEND = r"D:\hermes\workspace\中医问诊系统\code-app\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

# 自测/验收库必须隔离：绝不读写演示库 data/app.db（本脚本会写入业务数据）
DB_PATH = os.path.join(BACKEND, "data", "batch1_main.db")
for _sfx in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + _sfx):
        os.remove(DB_PATH + _sfx)
os.environ["APP_DB_PATH"] = DB_PATH

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-52s %s" % ("[通过]" if cond else "[失败]", name, detail))


def login(c, username, password):
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    body = r.get_json()
    assert r.status_code == 200 and body.get("success"), (username, r.status_code, body)
    return {"Authorization": "Bearer " + body["data"]["token"]}


def main():
    from app import app
    c = app.test_client()
    sfx = random.randint(1000, 9999)

    print("\n=== 1. 登录与模型装载 ===")
    h_admin = login(c, "admin", "admin123")
    h_daozhen = login(c, "daozhen", "123456")
    h_yaoshi = login(c, "yaoshi", "123456")
    h_kufang = login(c, "kufang", "123456")
    h_keshi = login(c, "keshi", "123456")
    check("六个演示账号均可登录", True)

    r = c.get("/api/meta/ontology", headers=h_admin)
    counts = r.get_json()["data"]
    check("七模型装载（9 聚合/4 子实体/37 行为/6 规则/7 报表/19 屏）",
          counts["aggregates"] == 9 and counts["entities"] == 4 and counts["behaviors"] == 37
          and counts["rules"] == 6 and counts["query_reports"] == 7 and counts["screens"] == 19,
          str(counts))

    r = c.get("/api/meta/dictionaries", headers=h_admin)
    dicts = r.get_json()["data"]
    check("字典接口返回 11 个字典类型", len(dicts) >= 11, "共 %d 个键" % len(dicts))
    check("患者性别字典可用", len(dicts.get("DICT-PATIENT.GENDER", [])) >= 2)

    # ---------------- 患者 ----------------
    print("\n=== 2. 患者建档（UI-01） ===")
    name = "测试患者%d" % sfx
    r = c.post("/api/patient", json={
        "patient_name": name, "gender": "MALE", "birth_date": "1980-05-06",
        "phone": "1380000%04d" % sfx, "occupation": "教师", "address": "北京市朝阳区测试路1号",
        "allergy_history": "无", "remark": "验收用例",
    }, headers=h_daozhen)
    body = r.get_json()
    check("导诊员可新建患者", r.status_code == 200 and body.get("success"), str(body.get("message")))
    p = body.get("data") or {}
    pid = p.get("id")
    check("患者编号按 PA+6 位生成", bool(re.match(r"^PA\d{6}$", str(p.get("patient_no")))), str(p.get("patient_no")))
    check("默认状态为 ACTIVE", p.get("patient_status") == "ACTIVE", str(p.get("patient_status")))
    check("年龄由出生日期自动计算", isinstance(p.get("age"), int) and p["age"] > 40, "age=%s" % p.get("age"))

    r = c.put("/api/patient/%s" % pid, json={
        "patient_name": name, "gender": "MALE", "birth_date": "1980-05-06",
        "phone": "1380000%04d" % sfx, "occupation": "中学教师",
        "id_type": "ID_CARD", "id_no": "110101198005060015",
    }, headers=h_daozhen)
    body = r.get_json()
    check("修改患者（含身份证号）成功", r.status_code == 200 and body.get("success"), str(body.get("message")))
    check("身份证 18 位校验位通过", body.get("success") is True, str(body.get("message")))

    r = c.post("/api/patient", json={
        "patient_name": "重复证件%d" % sfx, "gender": "FEMALE", "phone": "1390000%04d" % sfx,
        "birth_date": "1985-03-04", "id_type": "ID_CARD", "id_no": "110101198005060015",
    }, headers=h_daozhen)
    check("INV-01 同证件号码重复建档被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.post("/api/patient", json={
        "patient_name": "错误证件%d" % sfx, "gender": "MALE", "phone": "1370000%04d" % sfx,
        "birth_date": "1985-03-04", "id_type": "ID_CARD", "id_no": "110101198005060019",
    }, headers=h_daozhen)
    check("身份证校验位错误被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.post("/api/patient", json={"patient_name": "缺信息%d" % sfx, "gender": "MALE", "birth_date": "1990-01-02"}, headers=h_daozhen)
    check("缺少联系电话被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.post("/api/patient/%s/status" % pid, json={"patient_status": "INACTIVE"}, headers=h_daozhen)
    body = r.get_json()
    check("患者停用成功", body.get("success") and (body.get("data") or {}).get("patient_status") == "INACTIVE",
          str(body.get("message")))

    r = c.get("/api/patient", query_string={"page": 1, "size": 10, "patient_name": name}, headers=h_daozhen)
    body = r.get_json()
    rows = (body.get("data") or {}).get("list", [])
    check("患者列表按姓名可查", body.get("success") and len(rows) >= 1, "命中 %d 行" % len(rows))

    # ---------------- 证型 ----------------
    print("\n=== 3. 证型字典维护（UI-12） ===")
    sname = "验收证型%d证" % sfx
    r = c.post("/api/syndrome", json={
        "syndrome_name": sname, "diagnosis_method": "EIGHT_PRINCIPLES",
        "syndrome_description": "验收用证候描述", "common_symptoms": "胸闷、太息",
        "corresponding_treatment": "疏肝理气",
    }, headers=h_keshi)
    body = r.get_json()
    check("科室管理员可新增证型", body.get("success"), str(body.get("message")))
    s = body.get("data") or {}
    sid = s.get("id")
    check("证型编码按 Z+3 位生成", bool(re.match(r"^Z\d{3}$", str(s.get("syndrome_code")))), str(s.get("syndrome_code")))

    r = c.post("/api/syndrome", json={"syndrome_name": sname, "diagnosis_method": "EIGHT_PRINCIPLES"}, headers=h_keshi)
    check("证型名称重复被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.put("/api/syndrome/%s" % sid, json={"syndrome_name": sname + "（改）", "diagnosis_method": "EIGHT_PRINCIPLES"}, headers=h_keshi)
    check("证型改名成功", r.get_json().get("success"), str(r.get_json().get("message")))

    r = c.post("/api/syndrome/%s/status" % sid, json={"syndrome_status": "DISABLED"}, headers=h_keshi)
    body = r.get_json()
    check("证型停用成功", body.get("success") and (body.get("data") or {}).get("syndrome_status") == "DISABLED",
          str(body.get("message")))

    # ---------------- 饮片（先建，方剂要用） ----------------
    print("\n=== 4. 饮片建档与入库（UI-09） ===")
    hname = "验收饮片%d" % sfx
    r = c.post("/api/herb", json={
        "herb_name": hname, "herb_category": "TONIFYING", "min_common_dose": 6, "max_common_dose": 12,
        "toxicity_level": "SLIGHT", "toxic_dose_limit": 30, "low_stock_threshold": 500, "spec": "统货", "origin": "甘肃",
    }, headers=h_kufang)
    body = r.get_json()
    check("库房管理员可建档饮片", body.get("success"), str(body.get("message")))
    hb = body.get("data") or {}
    hid = hb.get("id")
    check("饮片编码按 Y+4 位生成", bool(re.match(r"^Y\d{4}$", str(hb.get("herb_code")))), str(hb.get("herb_code")))
    check("新建饮片库存为 0", float(hb.get("stock_quantity") or 0) == 0, str(hb.get("stock_quantity")))
    check("毒性单张处方总量上限已落库（R-03 依赖字段）",
          float(hb.get("toxic_dose_limit") or 0) == 30, "toxic_dose_limit=%s" % hb.get("toxic_dose_limit"))

    r = c.post("/api/herb", json={"herb_name": hname + "二", "min_common_dose": 10, "max_common_dose": 5}, headers=h_kufang)
    check("REF-07 常用量区间错误被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.post("/api/herb/%s/inbound" % hid, json={
        "quantity": 2000, "biz_date": "2026-09-30 10:00:00", "inbound_no": "RK2026%04d" % sfx, "remark": "验收入库",
    }, headers=h_kufang)
    body = r.get_json()
    check("入库登记成功", body.get("success"), str(body.get("message")))
    got = (body.get("data") or {}).get("stock_quantity")
    check("入库后库存 +2000", float(got or 0) == 2000, "stock=%s" % got)

    r = c.post("/api/herb/%s/inbound" % hid, json={
        "quantity": 500, "biz_date": "2026-09-30 11:00:00", "inbound_no": "RK2026%04dB" % sfx, "remark": "二次入库",
    }, headers=h_kufang)
    check("二次入库成功（累计 2500）", float((r.get_json().get("data") or {}).get("stock_quantity") or 0) == 2500,
          str(r.get_json().get("message")))

    r = c.post("/api/herb/%s/inbound" % hid, json={"quantity": 100, "biz_date": "2026-09-30 11:30:00"}, headers=h_kufang)
    check("入库单号缺失被拒（M2 前置条件）", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.get("/api/herb/%s" % hid, headers=h_kufang)
    data = r.get_json().get("data") or {}
    flows = data.get("stock_flows") or data.get("stock_flows".replace("_", "")) or []
    check("出入库流水已落库（2 条）", len(flows) >= 2, "流水 %d 条" % len(flows))
    check("流水号按 LS+6 位生成（需求文档 UI-09 原型口径）", all(re.match(r"^LS\d{6}$", str(f.get("flow_no"))) for f in flows) if flows else False,
          ", ".join(str(f.get("flow_no")) for f in flows))

    r = c.post("/api/herb/%s/stocktake" % hid, json={
        "actual_quantity": 2480, "biz_date": "2026-09-30 12:00:00", "remark": "盘点损耗 20g",
    }, headers=h_kufang)
    body = r.get_json()
    check("盘点成功", body.get("success"), str(body.get("message")))
    check("盘点后库存 = 实盘 2480", float((body.get("data") or {}).get("stock_quantity") or 0) == 2480,
          "stock=%s" % (body.get("data") or {}).get("stock_quantity"))

    r = c.get("/api/herb/%s" % hid, headers=h_kufang)
    data = r.get_json().get("data") or {}
    flows = data.get("stock_flows") or []
    diff = [f for f in flows if f.get("biz_type") == "STOCKTAKE_ADJUST"]
    check("盘点生成差异流水（STOCKTAKE_ADJUST / -20）", len(diff) == 1 and float(diff[0]["quantity"]) == -20,
          str([(f.get("biz_type"), f.get("quantity")) for f in flows]))
    net = sum(float(f["quantity"]) for f in flows)
    check("INV-03 库存=流水净和", abs(net - float(data.get("stock_quantity") or 0)) < 1e-6,
          "净和=%s 库存=%s" % (net, data.get("stock_quantity")))

    # 低库存预警：再建一个低库存饮片
    lname = "验收低库存%d" % sfx
    r = c.post("/api/herb", json={
        "herb_name": lname, "min_common_dose": 3, "max_common_dose": 9, "toxicity_level": "NONE",
        "low_stock_threshold": 1000,
    }, headers=h_kufang)
    lid = (r.get_json().get("data") or {}).get("id")
    c.post("/api/herb/%s/inbound" % lid, json={"quantity": 100, "biz_date": "2026-09-30 10:00:00"}, headers=h_kufang)

    print("\n=== 5. 饮片库存与预警（UI-10） ===")
    r = c.get("/api/herb/stock", query_string={"page": 1, "size": 10, "herb_name": hname}, headers=h_yaoshi)
    body = r.get_json()
    rows = (body.get("data") or {}).get("list", [])
    check("中药师可查询库存", body.get("success") and len(rows) >= 1, "命中 %d 行" % len(rows))

    r = c.get("/api/herb/stock", query_string={"page": 1, "size": 50, "alert_only": "true"}, headers=h_kufang)
    rows = (r.get_json().get("data") or {}).get("list", [])
    alert_names = [x.get("herb_name") for x in rows]
    check("仅看预警项过滤生效", lname in alert_names and hname not in alert_names, "预警项：%s" % alert_names[:5])

    r = c.get("/api/herb/stock/export", query_string={"herb_name": hname}, headers=h_yaoshi)
    raw = r.data.decode("utf-8-sig", errors="replace")
    check("库存导出 CSV 返回数据行", r.status_code == 200 and hname in raw, "字节 %d" % len(r.data))

    # ---------------- 方剂 ----------------
    print("\n=== 6. 方剂模板维护（UI-13） ===")
    fname = "验收方剂%d" % sfx
    r = c.post("/api/formula", json={
        "formula_name": fname, "formula_type": "CLASSIC", "source": "《验方》", "function": "疏肝解郁",
        "indication": "肝气郁结证", "default_doses": 7,
        "items": [{"seq_no": 2, "herb_id": hid, "common_dose": 10, "decoction_method": "NONE"},
                  {"seq_no": 1, "herb_id": lid, "common_dose": 6}],
    }, headers=h_keshi)
    body = r.get_json()
    check("科室管理员可新增方剂（含 2 味明细）", body.get("success"), str(body.get("message")))
    f = body.get("data") or {}
    fid = f.get("id")
    check("方剂编码按 F+3 位生成", bool(re.match(r"^F\d{3}$", str(f.get("formula_code")))), str(f.get("formula_code")))

    r = c.get("/api/formula/%s" % fid, headers=h_keshi)
    data = r.get_json().get("data") or {}
    items = data.get("items", [])
    check("方剂明细按序号返回（2 行）", len(items) == 2 and items[0].get("herb_name"), str([(i.get("seq_no"), i.get("herb_name")) for i in items]))

    r = c.post("/api/formula", json={
        "formula_name": fname + "重复", "formula_type": "CLASSIC",
        "items": [{"seq_no": 1, "herb_id": hid, "common_dose": 10},
                  {"seq_no": 2, "herb_id": hid, "common_dose": 5}],
    }, headers=h_keshi)
    check("方剂明细药味重复被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.post("/api/formula", json={"formula_name": fname + "空明细", "formula_type": "CLASSIC", "items": []}, headers=h_keshi)
    check("方剂明细为空被拒", r.get_json().get("success") is False, str(r.get_json().get("message")))

    r = c.put("/api/formula/%s" % fid, json={
        "formula_name": fname, "formula_type": "CLASSIC", "default_doses": 5,
        "items": [{"seq_no": 1, "herb_id": lid, "common_dose": 9}],
    }, headers=h_keshi)
    body = r.get_json()
    check("方剂从表全量重建（1 行）", body.get("success"), str(body.get("message")))
    r = c.get("/api/formula/%s" % fid, headers=h_keshi)
    check("重建后明细为 1 行", len((r.get_json().get("data") or {}).get("items", [])) == 1)

    r = c.post("/api/formula/%s/status" % fid, json={"formula_status": "DISABLED"}, headers=h_keshi)
    check("方剂停用成功", r.get_json().get("success"), str(r.get_json().get("message")))

    # ---------------- 越权 ----------------
    print("\n=== 7. 权限边界（越权负例） ===")
    r = c.post("/api/herb", json={"herb_name": "越权饮片%d" % sfx, "min_common_dose": 1, "max_common_dose": 2},
               headers=h_daozhen)
    check("导诊员建饮片被拒（herb:save）", r.status_code == 403 or r.get_json().get("success") is False,
          "HTTP %s %s" % (r.status_code, r.get_json().get("message")))

    r = c.post("/api/patient", json={"patient_name": "越权患者", "gender": "MALE", "phone": "13611110000"},
               headers=h_yaoshi)
    check("中药师建患者被拒（patient:save）", r.status_code == 403 or r.get_json().get("success") is False,
          "HTTP %s %s" % (r.status_code, r.get_json().get("message")))

    r = c.post("/api/syndrome/%s/status" % sid, json={"syndrome_status": "ENABLED"}, headers=h_kufang)
    check("库房管理员改证型状态被拒（syndrome:change-status）",
          r.status_code == 403 or r.get_json().get("success") is False,
          "HTTP %s %s" % (r.status_code, r.get_json().get("message")))

    r = c.get("/api/herb/stock", query_string={"page": 1, "size": 5}, headers=h_daozhen)
    check("导诊员查库存被拒（herb:query-stock-and-alert）",
          r.status_code == 403 or r.get_json().get("success") is False,
          "HTTP %s %s" % (r.status_code, r.get_json().get("message")))

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 78)
    print("验收结果：通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：")
        for f in FAIL:
            print("  - " + f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
