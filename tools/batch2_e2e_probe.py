# -*- coding: utf-8 -*-
"""批次 2 端到端黑盒探针：真实 socket（werkzeug 起服务 + urllib 请求），不经 Flask test_client。

验证：静态页可访问、六个账号真实登录取菜单、全链路（挂号→接诊→四诊→辨证→开方→提交→审核→调剂→发药）
在真实 HTTP 上跑通、越权 403、未登录 401、库存与流水一致性。

用法（后端 venv）：cd code-app/backend && ./.venv/Scripts/python.exe ../../tools/batch2_e2e_probe.py
"""
import json
import os
import random
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

BACKEND = r"D:\hermes\workspace\中医问诊系统\code-app\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ["APP_DB_PATH"] = "data/batch2_e2e.db"
_db = os.path.join(BACKEND, "data", "batch2_e2e.db")
if os.path.exists(_db):
    os.remove(_db)

from werkzeug.serving import make_server  # noqa: E402

from app import app  # noqa: E402

PORT = 5011
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-58s %s" % ("[通过]" if cond else "[失败]", name, detail))


def call(method, path, token=None, body=None, query=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body or {}).encode("utf-8") if method in ("POST", "PUT") else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw or "{}")
            except ValueError:
                return resp.status, {"raw": raw[:200]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw or "{}")
        except ValueError:
            return e.code, {"raw": raw[:200]}


def main():
    sfx = random.randint(1000, 9999)
    server = make_server("127.0.0.1", PORT, app)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print("=== 0. 真实 HTTP 服务就绪（%s） ===" % BASE)
    try:
        st, _ = call("GET", "/")
        check("静态页（前端 dist）可访问", st == 200, "HTTP %s" % st)

        def login(u):
            st, body = call("POST", "/api/auth/login", body={"username": u, "password": "123456"})
            assert body.get("success"), (u, body)
            return body["data"]["token"], body["data"]

        print("\n=== 1. 六账号真实登录与菜单 ===")
        tokens, menus = {}, {}
        for u in ("daozhen", "yishi", "yaoshi", "kufang", "keshi"):
            tokens[u], info = login(u)
            menus[u] = {m["name"]: [c["name"] for c in m.get("children", [])] for m in info["menus"]}
            check("账号 %s 登录成功（%d 个一级菜单）" % (u, len(info["menus"])), bool(info.get("token" if False else "menus")))
        st, body = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
        tokens["admin"] = body["data"]["token"]
        menus["admin"] = {m["name"]: [c["name"] for c in m.get("children", [])] for m in body["data"]["menus"]}
        check("admin 可见门诊与药房两套业务菜单",
              "门诊挂号" in menus["admin"].get("门诊管理", []) and "调剂发药" in menus["admin"].get("药房管理", []),
              str(menus["admin"].get("门诊管理")) + str(menus["admin"].get("药房管理")))

        print("\n=== 2. 全链路（真实 HTTP） ===")
        D = "2026-09-30"
        st, body = call("POST", "/api/patient", token=tokens["daozhen"],
                        body={"patient_name": "探针患者%d" % sfx, "gender": "MALE", "birth_date": "1970-01-01",
                              "phone": "1370013%04d" % sfx})
        pid = (body.get("data") or {}).get("id")
        check("患者建档", st == 200 and pid, str(body.get("message")))
        herb = {}
        for key, dose in (("a", (6, 12)), ("b", (3, 9))):
            st, body = call("POST", "/api/herb", token=tokens["kufang"],
                            body={"herb_name": "探针饮片%s%d" % (key, sfx), "herb_category": "TONIFYING",
                                  "min_common_dose": dose[0], "max_common_dose": dose[1],
                                  "toxicity_level": "NONE", "low_stock_threshold": 50})
            herb[key] = (body.get("data") or {}).get("id")
            call("POST", "/api/herb/%s/inbound" % herb[key], token=tokens["kufang"],
                 body={"quantity": 400, "biz_date": D + " 08:00:00", "inbound_no": "RKE2%s%d" % (key, sfx)})
        check("两味饮片建档并入库", all(herb.values()), str(herb))

        st, body = call("POST", "/api/visit", token=tokens["daozhen"],
                        body={"patient_id": pid, "visit_type": "FIRST", "dept_code": "TCM_INTERNAL",
                              "register_time": D + " 08:30:00"})
        vid = (body.get("data") or {}).get("id")
        check("挂号成功（HTTP）", st == 200 and vid, str(body.get("message")))
        st, body = call("POST", "/api/visit/%s/receive" % vid, token=tokens["yishi"],
                        body={"receive_time": D + " 09:00:00", "dept_code": "TCM_INTERNAL",
                              "chief_complaint": "胁肋胀痛 3 天"})
        check("接诊成功（HTTP）", st == 200, str(body.get("message")))
        st, body = call("POST", "/api/visit/%s/four-diagnosis" % vid, token=tokens["yishi"],
                        body={"tongue_body": "PALE_RED", "tongue_coating": "THIN_WHITE", "pulse_code": "WIRY",
                              "inquiry_emotion": "情志抑郁"})
        check("四诊录入成功（HTTP）", st == 200, str(body.get("message")))
        st, body = call("GET", "/api/syndrome", token=tokens["keshi"], query={"page": 1, "size": 1})
        sid = (((body.get("data") or {}).get("list") or [{}])[0] or {}).get("id")
        if not sid:
            st, body = call("POST", "/api/syndrome", token=tokens["keshi"],
                            body={"syndrome_name": "探针肝郁%d证" % sfx, "diagnosis_method": "ZANGFU"})
            sid = (body.get("data") or {}).get("id")
            check("证型建档（空库场景）", bool(sid), str(body.get("message")))
        st, body = call("POST", "/api/diagnosis", token=tokens["yishi"],
                        body={"visit_id": vid, "diagnosis_method": "ZANGFU", "syndrome_id": sid,
                              "syndrome_nature": "PRIMARY",
                              "diagnosis_basis": "胁肋胀痛、善太息、脉弦，情志不畅后加重，符合肝气郁结",
                              "treatment_principle": "疏肝解郁"})
        did = (body.get("data") or {}).get("id")
        check("辨证保存（HTTP）", st == 200 and did, str(body.get("message")))
        st, body = call("POST", "/api/diagnosis/%s/confirm" % did, token=tokens["yishi"], body={})
        check("辨证确认（HTTP）", st == 200, str(body.get("message")))
        st, body = call("POST", "/api/prescription", token=tokens["yishi"],
                        body={"visit_id": vid, "prescription_type": "HERBAL_DECOCTION", "doses": 7,
                              "usage_method": "DAILY_1_2", "decoction_instruction": "水煎服",
                              "items": [{"seq_no": 1, "herb_id": herb["a"], "single_dose": 10},
                                        {"seq_no": 2, "herb_id": herb["b"], "single_dose": 6}]})
        rx = (body.get("data") or {}).get("id")
        check("开方保存草稿（HTTP）", st == 200 and rx, str(body.get("message")))
        st, body = call("POST", "/api/prescription/%s/submit" % rx, token=tokens["yishi"], body={})
        check("提交送审（HTTP）", st == 200, str(body.get("message")))
        st, body = call("GET", "/api/prescription/%s" % rx, token=tokens["yishi"])
        check("提交后状态=PENDING_REVIEW", (body.get("data") or {}).get("prescription_status") == "PENDING_REVIEW",
              str((body.get("data") or {}).get("prescription_status")))
        st, body = call("GET", "/api/followup", token=tokens["daozhen"], query={"page": 1, "size": 50})
        plans = [x for x in ((body.get("data") or {}).get("list") or []) if x.get("source_visit_id") == vid]
        check("联动生成随访计划（HTTP）", len(plans) == 1,
              str((plans[0] or {}).get("planned_follow_up_date")) if plans else "无")
        st, body = call("POST", "/api/prescription/%s/review" % rx, token=tokens["yaoshi"],
                        body={"action": "APPROVE", "comment": "同意调剂"})
        check("药师审核通过（HTTP）", st == 200, str(body.get("message")))
        st, body = call("GET", "/api/prescription/%s" % rx, token=tokens["yaoshi"])
        rec = (body.get("data") or {}).get("dispense_record") or {}
        check("生成待调剂记录（HTTP）", rec.get("record_status") == "PENDING", str(rec.get("dispense_no")))
        st, body = call("POST", "/api/dispense/%s/confirm" % rec.get("id"), token=tokens["yaoshi"], body={})
        check("调剂确认（HTTP）", st == 200, str(body.get("message")))
        st, body = call("POST", "/api/dispense/%s/issue" % rec.get("id"), token=tokens["yaoshi"], body={})
        check("发药确认（HTTP）", st == 200, str(body.get("message")))
        st, body = call("GET", "/api/prescription/%s" % rx, token=tokens["yaoshi"])
        check("全链路终态=ISSUED", (body.get("data") or {}).get("prescription_status") == "ISSUED",
              str((body.get("data") or {}).get("prescription_status")))
        st, body = call("GET", "/api/herb/%s" % herb["a"], token=tokens["kufang"])
        h = body.get("data") or {}
        net = sum(float(f.get("quantity") or 0) for f in (h.get("stock_flows") or []))
        check("库存扣减 400→330g 且 INV-03 成立",
              abs(float(h.get("stock_quantity") or 0) - 330) < 1e-6 and abs(float(h.get("stock_quantity")) - net) < 1e-6,
              "库存=%s 净和=%s" % (h.get("stock_quantity"), net))

        print("\n=== 3. 权限与鉴权（真实 HTTP） ===")
        st, _ = call("GET", "/api/visit", query={"page": 1, "size": 5})
        check("未带 token 访问被拒（401）", st == 401, "HTTP %s" % st)
        st, body = call("POST", "/api/dispense/%s/confirm" % rec.get("id"), token=tokens["yishi"], body={})
        check("中医师调剂被拒（403）", st == 403, "HTTP %s %s" % (st, body.get("message")))
        st, body = call("POST", "/api/prescription/%s/review" % rx, token=tokens["yishi"], body={"action": "APPROVE",
                                                                                                "comment": "越权"})
        check("中医师审核被拒（403）", st == 403, "HTTP %s %s" % (st, body.get("message")))
        st, body = call("POST", "/api/visit/%s/receive" % vid, token=tokens["daozhen"],
                        body={"receive_time": D + " 12:00:00", "chief_complaint": "越权"})
        check("导诊员接诊被拒（403）", st == 403, "HTTP %s %s" % (st, body.get("message")))
    finally:
        server.shutdown()
        th.join(timeout=5)

    print("\n" + "=" * 84)
    print("批次 2 端到端黑盒探针：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
    for n in NG:
        print("  ✗ " + n)
    print("=" * 84)
    return 1 if NG else 0


if __name__ == "__main__":
    sys.exit(main())
