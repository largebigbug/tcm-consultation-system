# -*- coding: utf-8 -*-
"""批次 5（AI 对话框）规格机械抽取：从本体注册表 + 运行库生成工具清单文档。

产物（禁手改，改模型/注册表后重跑本脚本）：
  code-app/docs/批次5-工具清单（注册表抽取）.md
用法：code-app/backend/.venv/Scripts/python.exe tools/gen_batch5_spec.py
"""
import io
import os
import re
import sqlite3
import sys

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BE))
sys.path.insert(0, BE)
os.chdir(BE)
os.environ.setdefault("APP_DB_PATH", os.path.join(BE, "data", "app.db"))

from ontology import registry  # noqa: E402

OUT = os.path.join(PROJECT, "code-app", "docs", "批次5-工具清单（注册表抽取）.md")


def permission_codes():
    """权限码以**运行库**为准（`sys_permission`，按 `target_ref`=行为 id 键），并与 seed 派生规则交叉核对。

    注：`sys_permission` 的列是 `code` / `target_ref`（无 `permission_id` 列）——用 PRAGMA 核实过再用。
    """
    db = os.environ["APP_DB_PATH"]
    conn = sqlite3.connect(db)
    mapping = {r[0]: r[1] for r in conn.execute("SELECT target_ref, code FROM sys_permission")}
    conn.close()
    derived = None
    derived, err = None, None
    try:
        from seed import permission_code                          # seed.permission_code(target_ref)
        derived = {pid: permission_code(p.get("targetRef"))
                   for pid, p in registry.load_ontology()["permissions"].items()}
    except Exception as exc:                                          # noqa: BLE001
        err = exc                                                  # 不静默：把原因带出去打印
    if err is not None:
        print("  [警告] seed 派生交叉核对未执行：%r" % (err,))
    return mapping, derived


def main():
    reg = registry.load_ontology()
    beh = reg["behaviors"]
    codes, derived = permission_codes()

    nav = reg["screens"]
    menus = reg["menus"]
    queries = {k: v for k, v in beh.items() if v.get("behaviorType") == "QUERY"}
    commands = {k: v for k, v in beh.items()
                if v.get("behaviorType") == "COMMAND" and v.get("triggerType") == "USER_ACTION"}
    reports = reg["query_reports"]
    wl = reg["db_whitelist"]

    menu_of = {}
    for m in menus:
        for c in m.get("children", []):
            if c.get("screenRef"):
                menu_of[c["screenRef"]] = (m["name"], c["name"])

    def code_of(behavior_id):
        """按行为 id 取权限码（库内真值优先）。"""
        if not behavior_id:
            return "—"
        return codes.get(behavior_id, "（库中无）")

    lines = []
    add = lines.append
    add("# 批次 5 工具清单（注册表机械抽取）\n")
    add("> 本文件由 `code-app/backend/tools/gen_batch5_spec.py` 从本体注册表 + 运行库自动生成，**禁止手改**；")
    add("> 改模型或改权限后重跑该脚本。AI 编排层的工具 schema 一律以本文件为唯一口径。\n")
    add("生成时依据：`registry` 的 behaviors / query.reports / screens / menus / permissions / "
        "`db_whitelist`；权限码取自运行库 `sys_permission.code`。\n")

    add("## 0. 计数汇总\n")
    add("| 类别 | 工具名规则 | 数量 |")
    add("|---|---|---|")
    add("| 导航工具 | `nav_<screenId>` | %d |" % len(nav))
    add("| 查询工具（M2 QUERY） | `query_<BehaviorId>` | %d |" % len(queries))
    add("| 查询工具（M7 报表） | `report_<reportCode>` | %d |" % len(reports))
    add("| 行为工具（只读边界：仅生成跳转，不执行写操作） | `action_<BehaviorId>` | %d |" % len(commands))
    add("| 图表工具 | `chart` | 1 |")
    add("| SQL 只读工具 | `sql_readonly` | 1（白名单 %d 表） |" % len(wl))
    add("")

    add("## 1. 导航工具（来源：MU `screens`，权限随登录用户菜单可见性）\n")
    add("| # | 工具名 | 屏 id | 屏名称 | 类型 | 菜单路径 |")
    add("|---|---|---|---|---|---|")
    for i, (sid, s) in enumerate(nav.items(), 1):
        path = " / ".join(menu_of.get(sid, ("（无菜单）", "")))
        add("| %d | `nav_%s` | `%s` | %s | %s | %s |" % (i, sid, sid, s.get("name", ""), s.get("screenType", ""), path))
    add("")

    add("## 2. 查询工具（来源：M2 `behaviorType=QUERY` + M7 报表）\n")
    add("### 2.1 M2 QUERY 行为\n")
    add("| # | 工具名 | 行为 id | 名称 | 报表 | 权限码 |")
    add("|---|---|---|---|---|---|")
    for i, (bid, b) in enumerate(queries.items(), 1):
        add("| %d | `query_%s` | `%s` | %s | `%s` | `%s` |" % (i, bid, bid, b.get("name", ""),
                                                             b.get("queryReportRef", "-"), code_of(bid)))
    add("\n### 2.2 M7 报表（可带参数查询/导出）\n")
    add("| # | 工具名 | 报表码 | 名称 | behaviorRef | 权限码 | 参数数 | 列数 |")
    add("|---|---|---|---|---|---|---|---|")
    for i, (rid, r) in enumerate(reports.items(), 1):
        add("| %d | `report_%s` | `%s` | %s | `%s` | `%s` | %d | %d |" % (
            i, rid, rid, r.get("name", ""), r.get("behaviorRef", "-"), code_of(r.get("behaviorRef", "")),
            len(r.get("parameters", [])), len(r.get("resultColumns", []))))
    add("")

    add("## 3. 行为工具清单（**只读边界**）\n")
    add("> 按用户确认：AI 默认只读，**不执行任何写操作**。本节的 24 条行为仅供 AI 生成 `action` 渲染")
    add("> （跳转到固定页面并可预填），真正提交由用户在页面上确认。因此每条都**不需要**调用后端写接口。\n")
    add("| # | 工具名 | 行为 id | 名称 | 所属聚合 | 权限码（用户须具备才提示可操作） |")
    add("|---|---|---|---|---|---|")
    for i, (bid, b) in enumerate(commands.items(), 1):
        add("| %d | `action_%s` | `%s` | %s | `%s` | `%s` |" % (i, bid, bid, b.get("name", ""),
                                                              b.get("ownerEntity", ""), code_of(bid)))
    add("")

    add("## 4. 图表工具\n")
    add("| 工具名 | 入参 | 出参 | 说明 |")
    add("|---|---|---|---|")
    add("| `chart` | `{rows, chartType: bar\\|line\\|pie, xField, yField}` | "
        "`render_payload{renderType:'chart', payload:{...}}` | 由查询结果转 ECharts option，前端用已装 `echarts` 渲染 |")
    add("")

    add("## 5. SQL 只读白名单（来源：`registry.db_whitelist`，共 %d 表）\n" % len(wl))
    add("| # | 物理表 | M1 别名 | 允许字段（%d 类） |")
    add("|---|---|---|---|")
    total_cols = 0
    for i, (tbl, meta) in enumerate(wl.items(), 1):
        attrs = meta.get("attributes", [])
        total_cols += len(attrs)
        add("| %d | `%s` | `%s` | %s |" % (i, meta.get("table", tbl), meta.get("alias", ""), ", ".join(attrs)))
    add("")
    add("> 白名单字段合计 **%d** 个。SQL 只读工具**只允许**上述表与字段；任何未列出的表/列一律拒绝。\n" % total_cols)

    add("## 6. 权限码对照（库内真值 ↔ seed 派生规则）\n")
    mismatch = []
    if derived:
        for pid, code in derived.items():
            target = reg["permissions"][pid].get("targetRef")
            if codes.get(target) != code:
                mismatch.append((pid, code, codes.get(target)))
    add("| # | permissionId | 权限码（库内） | 目标行为 | 名称 |")
    add("|---|---|---|---|---|")
    for i, (pid, p) in enumerate(reg["permissions"].items(), 1):
        add("| %d | `%s` | `%s` | `%s` | %s |" % (i, pid, codes.get(pid, "（库中无）"),
                                                 p.get("targetRef", ""), p.get("name", "")))
    add("")
    add("派生一致性：%s\n" % ("✅ seed 派生规则与库内 code 完全一致（%d 条）" % len(derived) if derived and not mismatch
                            else ("⚠️ 不一致项：%s" % mismatch if mismatch else "（未取到 seed 派生函数，仅列库内真值）")))
    add("")
    add("## 7. 全局兜底条数\n")
    add("计数：导航 %d / 查询 %d / 报表 %d / 行为(只读) %d / 白名单表 %d / 白名单字段 %d\n"
        % (len(nav), len(queries), len(reports), len(commands), len(wl), total_cols))
    add("- 可生成工具总数：**%d**（导航 %d + 查询 %d + 报表 %d + 行为(只读) %d + 图表 1 + SQL 1）" % (
        len(nav) + len(queries) + len(reports) + len(commands) + 2,
        len(nav), len(queries), len(reports), len(commands)))
    add("- 行为全部带 `requiredPermissions`：**%s**" % ("是" if all(v.get("requiredPermissions") for v in beh.values()) else "否"))

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("已生成 %s（%d 行）" % (OUT, len(lines) + 1))
    print("计数：导航 %d / 查询 %d / 报表 %d / 行为(只读) %d / 白名单表 %d / 白名单字段 %d" % (
        len(nav), len(queries), len(reports), len(commands), len(wl), total_cols))


if __name__ == "__main__":
    main()
