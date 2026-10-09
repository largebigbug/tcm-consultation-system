# -*- coding: utf-8 -*-
"""批次 1 演示库只读体检（不改数据）：核对演示数据与预警菜单在真实服务上的表现。"""
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5000"
OK, NG = [], []


def req(path, method="GET", body=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, json.dumps(body).encode() if body is not None else None, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-44s %s" % ("[通过]" if cond else "[失败]", name, detail))


def login(u, p):
    return req("/api/auth/login", "POST", {"username": u, "password": p})["data"]["token"]


h_dao, h_ke, h_ku = login("daozhen", "123456"), login("keshi", "123456"), login("kufang", "123456")

print("=== 演示数据齐备性 ===")
for name, path, token, want in [
    ("患者", "/api/patient?page=1&size=20", h_dao, 3),
    ("证型字典", "/api/syndrome?page=1&size=20", h_ke, 6),
    ("饮片品目", "/api/herb?page=1&size=20", h_ku, 10),
    ("方剂模板", "/api/formula?page=1&size=20", h_ke, 2),
]:
    d = req(path, token=token)["data"]
    rows = d.get("list", [])
    check("%s %d 条" % (name, want), d.get("total") == want, "total=%s" % d.get("total"))
    if name == "方剂模板":
        detail = "、".join("%s(%s)" % (r["formula_name"], r["formula_code"]) for r in rows)
        check("方剂编码与名称", all(r.get("formula_code") for r in rows), detail)

print("\n=== 预警（UI-10） ===")
d = req("/api/herb/stock?page=1&size=20&alert_only=true", token=h_ku)["data"]
alerts = [(r["herb_name"], r["stock_quantity"], r["low_stock_threshold"], r.get("alert_status")) for r in d.get("list", [])]
check("预警项仅半夏（200g < 300g）", len(alerts) == 1 and alerts[0][0] == "半夏", str(alerts))

d = req("/api/herb/stock?page=1&size=20", token=h_ku)["data"]
check("库存列表 10 行含预警列", d.get("total") == 10 and all("alert_status" in r for r in d.get("list", [])),
      "total=%s" % d.get("total"))

print("\n=== 方剂明细跳选框（饮片引用） ===")
opts = req("/api/herb/options", token=h_ke)["data"]
check("饮片跳选框返回 10 项", len(opts) == 10, "首项：%s" % (opts[0] if opts else "无"))
rows = req("/api/formula?page=1&size=5", token=h_ke)["data"]["list"]
for fname, want in (("逍遥散", 6), ("四君子汤", 4)):
    fid = [r["id"] for r in rows if r["formula_name"] == fname]
    items = req("/api/formula/%s" % fid[0], token=h_ke)["data"]["items"] if fid else []
    check("%s 明细 %d 味含药味名称" % (fname, want), len(items) == want and all(i.get("herb_name") for i in items),
          "、".join("%s%sg" % (i["herb_name"], i["common_dose"]) for i in items))

print("\n" + "=" * 62)
print("演示库体检：通过 %d，失败 %d" % (len(OK), len(NG)))
for n in NG:
    print("  - " + n)
sys.exit(1 if NG else 0)
