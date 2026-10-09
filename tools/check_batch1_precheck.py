# -*- coding: utf-8 -*-
"""核对字典码与真实路由表（批次 1 验收前置检查）。"""
import io
import os
import sys

import yaml

D = r"D:\hermes\workspace\中医问诊系统\code-app"
sys.path.insert(0, os.path.join(D, "backend"))
os.chdir(os.path.join(D, "backend"))

m1 = yaml.safe_load(io.open(os.path.join(D, "models/m1-object-model.yaml"), encoding="utf-8").read())
print("=== M1 字典类型与字典项码 ===")
for dic in m1["data_dictionaries"]:
    for t in dic.get("types", []) or []:
        codes = [it["code"] for it in t.get("items", []) or []]
        print("  %-18s %-26s %s" % (dic["id"], t.get("typeCode"), ", ".join(codes)))

print("\n=== 真实路由表（本批相关） ===")
from app import app
rules = sorted([(str(r), sorted(r.methods - {"HEAD", "OPTIONS"})) for r in app.url_map.iter_rules()])
for path, methods in rules:
    if path.startswith(("/api/patient", "/api/syndrome", "/api/formula", "/api/herb", "/api/meta")):
        print("  %-42s %s" % (path, ",".join(methods)))
