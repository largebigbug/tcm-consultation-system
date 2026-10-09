# -*- coding: utf-8 -*-
"""批次 1 端到端联调探针：对真实运行中的 Flask 服务（默认 http://127.0.0.1:5000）做黑盒检查。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5000"
OK, NG = [], []


def req(path, method="GET", body=None, token=None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(r, data, timeout=20) as resp:
        payload = resp.read()
        return resp.status, payload if raw else json.loads(payload.decode("utf-8"))


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-46s %s" % ("[通过]" if cond else "[失败]", name, detail))


def post(path, body, token=None):
    return req(path, "POST", body, token)


print("=== ① 前端产物由 Flask 托管 ===")
status, html = req("/", raw=True)
text = html.decode("utf-8", errors="replace")
check("GET / 返回 200 且为 HTML", status == 200 and "<div id=\"root\">" in text, "%d B" % len(html))
asset = text.split('src="')[1].split('"')[0] if 'src="' in text else ""
check("index.html 引用构建产物", asset.endswith(".js"), asset)
status, js = req(asset, raw=True)
check("JS 产物可下载", status == 200 and len(js) > 100000, "%d B" % len(js))

print("\n=== ② 健康检查与字典 ===")
s, body = req("/api/health")
check("健康检查", body.get("success"), body.get("data", {}))
s, body = post("/api/auth/login", {"username": "admin", "password": "admin123"})
admin = body["data"]["token"]
s, body = req("/api/meta/dictionaries", token=admin)
keys = sorted(body["data"].keys())
check("字典接口 24 个类型键", len(keys) == 24, keys[0] + " … " + keys[-1])

print("\n=== ③ 六个账号的菜单可见性（种子修复后） ===")
expect = {
    "admin": {"门诊管理", "库存管理", "基础数据", "审批中心", "流程管理", "系统管理"},
    "daozhen": {"门诊管理", "审批中心"},
    "yishi": {"审批中心"},
    "yaoshi": {"库存管理", "审批中心"},
    "kufang": {"库存管理", "审批中心"},
    "keshi": {"基础数据", "库存管理", "审批中心"},  # ROLE-05 按 M5 持有 herb:query-stock-and-alert
}
pw = {"admin": "admin123"}
for user, want in expect.items():
    s, body = post("/api/auth/login", {"username": user, "password": pw.get(user, "123456")})
    d = body["data"]
    got = {m["name"] for m in d["menus"]}
    # 超集语义：批次 1 交付的菜单必须仍在（后续批次会新增菜单，故不做等值断言）
    check("%-8s 菜单 ⊇ %s" % (user, "、".join(sorted(want))), want <= got,
          "实得：%s" % ("、".join(sorted(got)) or "无"))
    if user == "kufang":
        check("kufang 不可见「统计报表 / 随访管理」（M5 未授予）",
              not ({"统计报表", "随访管理"} & got), "实得：%s" % "、".join(sorted(got)))
        stock = [m for m in d["menus"] if m["name"] == "库存管理"]
        check("库房管理员可见「饮片库存与预警」菜单（种子修复验证）",
              bool(stock) and any(c["name"] == "饮片库存与预警" for c in stock[0]["children"]),
              str([c["path"] for c in stock[0]["children"]]) if stock else "无库存管理菜单")
        kufang_token = d["token"]

print("\n=== ④ 库房管理员真实接口往返 ===")
import time as _time
_suffix = _time.strftime("%H%M%S")
s, body = post("/api/herb", {"herb_name": "端到端探针饮片" + _suffix, "herb_category": "TONIFYING",
                             "min_common_dose": 6, "max_common_dose": 12, "toxicity_level": "NONE",
                             "low_stock_threshold": 200}, token=kufang_token)
probe_hid = (body.get("data") or {}).get("id")
check("库房管理员可经 HTTP 建档饮片", body.get("success"), str(body.get("message")))
s, body = post("/api/herb/%s/inbound" % probe_hid, {"quantity": 800, "biz_date": "2026-09-30 15:00:00",
                                                    "inbound_no": "RK-E2E-" + _suffix}, token=kufang_token)
check("经 HTTP 入库 800g 成功", body.get("success") and float((body.get("data") or {}).get("stock_quantity") or 0) == 800,
      "stock=%s" % (body.get("data") or {}).get("stock_quantity"))
s, body = req("/api/herb/stock?page=1&size=3", token=kufang_token)
rows = (body.get("data") or {}).get("list", [])
check("库存查询返回数据", body.get("success") and len(rows) >= 1, "total=%s" % (body.get("data") or {}).get("total"))
if rows:
    r0 = rows[0]
    check("结果列含预警与最近入库日期", "alert_status" in r0 and "latest_inbound_date" in r0,
          "%s 库存=%s 预警=%s" % (r0.get("herb_name"), r0.get("stock_quantity"), r0.get("alert_status")))

print("\n=== ⑤ 越权与未登录 ===")
try:
    req("/api/herb/stock?page=1&size=1")
    check("未登录访问被拒", False, "竟然成功了")
except urllib.error.HTTPError as e:
    check("未登录访问返回 401", e.code == 401, "HTTP %d" % e.code)
try:
    post("/api/herb", {"herb_name": "越权探针" + _suffix, "min_common_dose": 1, "max_common_dose": 2},
         token=post("/api/auth/login", {"username": "daozhen", "password": "123456"})[1]["data"]["token"])
    check("导诊员建饮片被拒", False, "竟然成功了")
except urllib.error.HTTPError as e:
    check("导诊员建饮片返回 403", e.code == 403, "HTTP %d" % e.code)

print("\n" + "=" * 70)
print("端到端结果：通过 %d，失败 %d" % (len(OK), len(NG)))
for n in NG:
    print("  - " + n)
sys.exit(1 if NG else 0)
