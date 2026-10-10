# -*- coding: utf-8 -*-
"""批次 4 开工侦察：机械枚举「已实现 vs 模型要求」的真实缺口，供批次范围决策。

只读，不写任何文件/库。输出四张清单：
  ① MU 屏幕（19 屏）→ 是否已进后端 SCREEN_META（未进 = 未实现屏）
  ② M7 查询报表 → 是否有对应接口/前端页面
  ③ M5 权限 → 权限码在代库里是否有落地证据（接口装饰器/菜单）
  ④ M2 行为 → 在 services/api 代码里是否有同名落地痕迹
用法：D:/hermes/workspace/docx-venv/Scripts/python.exe tools/recon_batch4.py
"""
import io
import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML = os.path.join(ROOT, "yaml")
BACKEND = os.path.join(ROOT, "code-app", "backend")
FRONT = os.path.join(ROOT, "code-app", "frontend", "src")


def load(name):
    with io.open(os.path.join(YAML, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def walk(d, key):
    """递归收集所有同名 key 的值（模型各层嵌套不一，硬编码层级易漏）。"""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k == key:
                out.append(v)
            out.extend(walk(v, key))
    elif isinstance(d, list):
        for v in d:
            out.extend(walk(v, key))
    return out


def read(path):
    try:
        return io.open(path, encoding="utf-8").read()
    except OSError:
        return ""


def main():
    mu = load("mu-ui-model.yaml")
    m7 = load("m7-report-model.yaml")
    m2 = load("m2-behavior-model.yaml")
    m5 = load("m5-actor-model.yaml")

    seed = read(os.path.join(BACKEND, "seed.py"))
    screen_meta = set(re.findall(r'"(scr[A-Za-z0-9_]+)"\s*:', seed))
    backend_code = "\n".join(read(os.path.join(BACKEND, d, f))
                           for d in ("api", "services", "utils", "tools")
                           for f in (os.listdir(os.path.join(BACKEND, d)) if os.path.isdir(os.path.join(BACKEND, d)) else [])
                           if f.endswith(".py"))
    front_files = []
    for dirpath, _dirs, files in os.walk(FRONT):
        front_files += [os.path.join(dirpath, f) for f in files if f.endswith((".tsx", ".ts"))]
    front_code = "\n".join(read(p) for p in front_files)

    print("=" * 100)
    print("① MU 屏幕 → 是否已实现（后端 SCREEN_META 有无该 screenRef）")
    print("=" * 100)
    screens = []
    for block in re.finditer(r"- id:\s*(scr[A-Za-z0-9_]+)(.*?)(?=\n  - id:|\Z)", read(os.path.join(YAML, "mu-ui-model.yaml")),
                             re.S):
        sid, body = block.group(1), block.group(2)
        name = (re.search(r"name:\s*(.+)", body) or [None, "?"])[1]
        screens.append((sid, name.strip()))
    if not screens:                      # 结构不同则退回通用遍历
        for s in walk(mu, "screens") if isinstance(mu, dict) else []:
            for item in (s or []):
                if isinstance(item, dict) and "id" in item:
                    screens.append((item["id"], str(item.get("name", ""))))
    done = [(s, n) for s, n in screens if s in screen_meta]
    todo = [(s, n) for s, n in screens if s not in screen_meta]
    print("已实现（%d 屏）：%s" % (len(done), "、".join(s for s, _ in done)))
    print("未实现（%d 屏）：" % len(todo))
    for s, n in todo:
        print("   - %-32s %s" % (s, n))

    print()
    print("=" * 100)
    print("② M7 查询报表 → 是否有接口落地")
    print("=" * 100)
    reports = []
    for r in (m7.get("query_reports") or []):
        reports.append((r.get("id"), r.get("name") or r.get("reportName"), r.get("reportType"),
                        [(p or {}).get("name") for p in (r.get("parameters") or r.get("queryParameters") or [])]))
    for rid, rname, rtype, params in reports:
        in_backend = rid in backend_code
        in_front = "RPT-" in front_code or rid in front_code
        print("   %-28s %-22s %-12s 后端:%s 前端:%s 参数:%d" %
              (rid, rname, rtype, "有" if in_backend else "无", "有" if in_front else "无", len(params)))

    print()
    print("=" * 100)
    print("③ M5 权限 → 代码里有落地证据（装饰器/引用）吗")
    print("=" * 100)
    perms = []
    def collect_perms(node):
        if isinstance(node, dict):
            if "permissionId" in node or "code" in node and "permissionCode" in node:
                pid = node.get("permissionId") or node.get("permissionCode")
                perms.append((pid, node.get("name") or node.get("permissionName"), node.get("targetRef")))
            for v in node.values():
                collect_perms(v)
        elif isinstance(node, list):
            for v in node:
                collect_perms(v)
    collect_perms(m5.get("roles") or [])
    collect_perms(m5.get("permissions") or [])
    seen = {}
    for pid, name, tref in perms:
        if pid and pid not in seen:
            seen[pid] = (name, tref)
    missing = []
    for pid, (name, tref) in sorted(seen.items()):
        if pid not in backend_code and pid not in front_code:
            missing.append((pid, name, tref))
    print("权限总数：%d；代码中无引用：%d" % (len(seen), len(missing)))
    for pid, name, tref in missing:
        print("   - %-46s %-18s targetRef=%s" % (pid, name, tref))

    print()
    print("=" * 100)
    print("④ M2 行为 → 代码里有同名痕迹吗（仅提示，非门禁）")
    print("=" * 100)
    behaviors = []
    for b in (m2.get("behaviors") or []):
        behaviors.append((b.get("id"), b.get("name"), b.get("behaviorType") or b.get("type"), b.get("ownerEntity")))
    ghost = [b for b in behaviors if b[0] and b[0] not in backend_code]
    print("行为总数：%d；代码中无同名痕迹：%d" % (len(behaviors), len(ghost)))
    for bid, name, btype, owner in ghost:
        print("   - %-34s %-22s %-14s %s" % (bid, name, btype, owner))
    return 0


if __name__ == "__main__":
    sys.exit(main())
