# -*- coding: utf-8 -*-
"""打印全部字典类型与字典项 code（裁决契约与模型口径差异时用）。"""
import io
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
m1 = yaml.safe_load(io.open(os.path.join(D, "m1-object-model.yaml"), encoding="utf-8").read())
for dic in m1["data_dictionaries"]:
    print("== %s %s" % (dic.get("id"), dic.get("name", "")))
    for t in dic.get("types", []) or []:
        codes = ["%s=%s" % (it["code"], it.get("label")) for it in t.get("items", []) or []]
        print("   %-22s %s" % (t.get("typeCode"), " | ".join(codes)))
