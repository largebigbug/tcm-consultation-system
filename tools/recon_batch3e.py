# -*- coding: utf-8 -*-
"""批次 3 侦察（五）：菜单树 / Q-07 角色 / 「对话」相关需求 / REP-04 细节 / 现有 SCREEN_META。"""
import io
import os
import re

R = r"D:\hermes\workspace\中医问诊系统"
doc = io.open(os.path.join(R, "中医问诊系统-需求规格说明书-V9.md"), encoding="utf-8").read()
lines = doc.splitlines()


def show(title, pattern, limit=18):
    print("===== %s" % title)
    n = 0
    for i, l in enumerate(lines, 1):
        if re.search(pattern, l):
            print("%5d| %s" % (i, l.strip()[:160]))
            n += 1
            if n >= limit:
                break
    print()


show("菜单结构/一级菜单", r"一级菜单|菜单结构|菜单树|系统菜单|^\|\s*(门诊管理|药房管理|基础数据|库存管理|统计|报表|查询|随访|审批|系统管理)")
show("Q-07 与角色授权", r"Q-07|Q07|REP-07")
show("「对话」相关（判断 AI 对话框是否属本期）", r"对话|智能助手|问诊助手|大模型|AI 助手|自然语言")
show("REP-04 就诊与处方记录查询 细节", r"REP-04|就诊与处方记录")
show("随访登记屏（复诊随访登记）需求", r"随访登记|复诊随访登记")
print("===== 现有 seed.py SCREEN_META")
s = io.open(os.path.join(R, "code-app", "backend", "seed.py"), encoding="utf-8").read()
m = re.search(r"SCREEN_META\s*=\s*\[(.*?)\n\]", s, re.S)
print((m.group(1)[:2500] if m else "未找到"))
