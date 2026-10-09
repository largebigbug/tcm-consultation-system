# -*- coding: utf-8 -*-
"""批次 5（AI 对话框）开工前侦察：注册表可注入素材盘点。

只读：加载本体注册表，打印 AI 编排层要用的键（行为/查询/菜单/白名单），并给出
「可生成的工具条数」估算。用法：code-app/backend/.venv/Scripts/python.exe tools/recon_batch5.py
"""
import os
import sys

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BE)
os.chdir(BE)
os.environ["APP_DB_PATH"] = os.path.join(BE, "data", "app.db")

from ontology import registry  # noqa: E402


def main():
    reg = registry.load_ontology()
    print("=== ① registry 顶层键 ===")
    print(sorted(reg.keys()))

    print("\n=== ② AI 编排层可注入素材 ===")
    for key in ("behaviors", "query_reports", "menus", "screens", "permissions", "db_whitelist",
                "objects", "data_dictionaries", "flows"):
        v = reg.get(key)
        if v is None:
            print("  %-18s （无此键）" % key)
        elif isinstance(v, dict):
            print("  %-18s dict，%d 项：%s" % (key, len(v), sorted(v)[:6]))
        elif isinstance(v, list):
            print("  %-18s list，%d 项" % (key, len(v)))
            if v and isinstance(v[0], dict):
                print("     首项键：%s" % sorted(v[0].keys()))
        else:
            print("  %-18s %s" % (key, type(v).__name__))

    print("\n=== ③ db_whitelist 结构（只读 SQL 工具的边界来源）===")
    wl = reg.get("db_whitelist")
    if wl is None:
        print("  ⚠️ 注册表无 db_whitelist —— 需确认报表引擎用的白名单从哪里来")
    else:
        items = list(wl.items())[:2] if isinstance(wl, dict) else wl[:2]
        print("  类型 %s，样例：%s" % (type(wl).__name__, items))

    print("\n=== ④ 可生成工具条数估算 ===")
    beh = reg.get("behaviors") or []
    qrs = reg.get("query_reports") or []
    menus = reg.get("menus") or []
    print("  导航工具（菜单/屏） : %d" % len(menus))
    print("  查询工具（M2 QUERY）: %d" % len([b for b in beh if isinstance(b, dict)
                                             and b.get("behaviorType") == "QUERY"]))
    print("  行为工具（COMMAND） : %d" % len([b for b in beh if isinstance(b, dict)
                                             and b.get("behaviorType") == "COMMAND"]))
    print("  报表工具（M7）      : %d" % len(qrs))
    print("  SQL 只读工具        : 1（白名单约束）")


if __name__ == "__main__":
    main()
