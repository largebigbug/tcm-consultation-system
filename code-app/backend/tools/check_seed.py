# -*- coding: utf-8 -*-
"""建库 + 种子自检（不依赖 Flask，直接调 registry / schema.sql / seed.py）。

用法：D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe tools/check_seed.py
"""
import json
import os
import sys

BACKEND = r"D:\hermes\workspace\中医问诊系统\code-app\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402
from ontology.registry import registry  # noqa: E402
from seed import ensure_seed  # noqa: E402

db.init_db_path(settings.resolve_db_path())
registry_module.load_ontology()

print("模型装载：", {k: len(v) for k, v in registry.items() if isinstance(v, dict)})

conn = db.connect()
try:
    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    ensure_seed(conn)
    conn.commit()

    tables = ["sys_user", "sys_role", "sys_permission", "sys_resource", "sys_role_permission",
              "sys_user_role", "flow_definition", "patient", "syndrome_type", "formula_template",
              "formula_item", "herb", "herb_stock_flow"]
    print("\n=== 表计数 ===")
    for t in tables:
        print("  %-20s %s" % (t, db.query_one(f"SELECT COUNT(*) AS c FROM {t}", (), conn)["c"]))

    print("\n=== 角色 ===")
    for r in db.query("SELECT code, name FROM sys_role ORDER BY id", (), conn):
        print("  %-10s %s" % (r["code"], r["name"]))

    print("\n=== 权限码（%d） ===" % db.query_one("SELECT COUNT(*) c FROM sys_permission", (), conn)["c"])
    print("  " + ", ".join(r["code"] for r in db.query("SELECT code FROM sys_permission ORDER BY id", (), conn)))

    print("\n=== 角色授权 ===")
    for r in db.query("SELECT code FROM sys_role ORDER BY id", (), conn):
        codes = [x["code"] for x in db.query(
            "SELECT p.code FROM sys_permission p JOIN sys_role_permission rp ON rp.permission_id = p.id "
            "JOIN sys_role ro ON ro.id = rp.role_id WHERE ro.code = ? ORDER BY p.id", (r["code"],), conn)]
        print("  %-10s %s" % (r["code"], ", ".join(codes) or "（无）"))

    print("\n=== 菜单资源 ===")
    rows = db.query("SELECT id, parent_id, name, code, permission_code, type, path, icon, sort_order "
                    "FROM sys_resource ORDER BY sort_order", (), conn)
    for r in rows:
        print("  %-3s p=%-3s %-8s %-26s perm=%-24s %-10s %s" % (
            r["id"], r["parent_id"], r["name"], r["code"], r["permission_code"] or "-", r["type"], r["path"] or "-"))

    print("\n=== 流程定义 ===")
    for r in db.query("SELECT code, name, flow_type, trigger_type, trigger_behavior, node_graph FROM flow_definition", (), conn):
        g = json.loads(r["node_graph"] or "{}")
        print("  %-32s %-8s %-10s 节点 %d 边 %d" % (
            r["code"], r["flow_type"], r["trigger_type"], len(g.get("nodes", [])), len(g.get("edges", []))))
        for n in g.get("nodes", []):
            print("      %-6s %-14s %-28s %s" % (n["id"], n["type"], (n.get("name") or "")[:26],
                                                 n.get("role_ref") or n.get("behavior_ref") or ""))

    print("\n=== 登录自检（auth_service） ===")
    from services import auth_service
    for u, pw in [("admin", "admin123"), ("kufang", "123456"), ("keshi", "123456")]:
        user, err = auth_service.login(u, pw)
        if err:
            print("  %-8s 失败：%s" % (u, err))
            continue
        payload = auth_service.build_login_payload(user)
        print("  %-8s 角色=%s 权限数=%d 一级菜单=%s" % (
            u, payload["user"]["roles"], len(payload["permissions"]),
            [m["name"] for m in payload["menus"]]))
finally:
    conn.close()
