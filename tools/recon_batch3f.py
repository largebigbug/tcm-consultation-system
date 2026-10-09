# -*- coding: utf-8 -*-
"""批次 3 侦察（六）：MU 屏幕键名与元素结构、M5 权限条目结构。"""
import io
import json
import os

import yaml

D = r"D:\hermes\workspace\中医问诊系统\yaml"
load = lambda f: yaml.safe_load(io.open(os.path.join(D, f), encoding="utf-8").read())
mu = load("mu-ui-model.yaml")
s = [x for x in mu["screens"] if x.get("name") == "门诊量统计"][0]
print("MU 屏幕键：", list(s.keys()))
print(json.dumps({k: v for k, v in s.items() if k not in ("elements", "layout")}, ensure_ascii=False, indent=1)[:900])
print("-- 元素前 3：")
print(json.dumps(s["elements"][:3], ensure_ascii=False, indent=1)[:900])
print("-- layout（前 12 行）：")
lay = s.get("layout") or s.get("asciiLayout") or ""
print("\n".join(str(lay).splitlines()[:12]) if lay else "无")

m5 = load("m5-actor-model.yaml")
print("\nM5 actors 前 1 项键：", list(m5["actors"][0].keys()) if m5.get("actors") else None)
print("M5 roles[0] 键：", list(m5["roles"][0].keys()))
r0 = m5["roles"][0]
print(json.dumps({k: (v[:3] if isinstance(v, list) else v) for k, v in r0.items()}, ensure_ascii=False)[:700])
print("\nM5 permissions[0]：", json.dumps(m5["permissions"][0], ensure_ascii=False)[:400])
codes = sorted({p.get("code") for p in m5["permissions"]})
print("\n权限码（%d 个）：" % len(codes))
print("  " + " | ".join(codes))
