# -*- coding: utf-8 -*-
"""批次 4 抽取脚本：从 M7 / MU 机械生成「报表规格」与「屏幕规格」两份文档。

批次 4 范围＝第 7 张报表 QR-HERB-STOCK-001（饮片库存与预警查询）+ frmHerbStock 屏改造。
产物（禁手改，改模型后重跑本脚本）：
  code-app/docs/批次4-报表规格（M7抽取）.md
  code-app/docs/批次4-屏幕规格（MU抽取）.md
用法：D:/hermes/tools/docx-venv/Scripts/python.exe tools/gen_batch4_spec.py
"""
import io
import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML = os.path.join(ROOT, "yaml")
DOCS = os.path.join(ROOT, "code-app", "docs")
REPORT_ID = "QR-HERB-STOCK-001"
SCREEN_ID = "frmHerbStock"


def load(name):
    with io.open(os.path.join(YAML, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    m7 = load("m7-report-model.yaml")
    mu = load("mu-ui-model.yaml")
    rep = [r for r in m7["query_reports"] if r["id"] == REPORT_ID][0]
    scr = [s for s in mu["screens"] if s["screenId"] == SCREEN_ID][0]

    out = []
    add = out.append
    add("# 批次 4 · 报表规格（从 M7 机械抽取，禁手改）")
    add("")
    add("> 来源：`yaml/m7-report-model.yaml`（v%s）｜报表 `%s` ｜由 `tools/gen_batch4_spec.py` 生成。"
        % (m7.get("version"), REPORT_ID))
    add("> **实现与验收一律以本文件为准**；与模型不一致时以模型为准并重跑本脚本。")
    add("")
    add("## 1. 报表定义")
    add("")
    add("| 字段 | 值 |")
    add("|---|---|")
    for key in ("id", "name", "alias", "objectType", "behaviorRef", "version"):
        add("| `%s` | %s |" % (key, rep.get(key)))
    add("| `description` | %s |" % (rep.get("description") or "").strip().replace("\n", " "))
    add("")
    add("## 2. 来源对象（sourceObjects）")
    add("")
    add("| 别名 | 对象引用 | 主来源 | 子实体路径 | 预聚合 |")
    add("|---|---|---|---|---|")
    for so in rep.get("sourceObjects") or []:
        pre = so.get("preAggregation") or {}
        pre_txt = ("groupBy=%s；列=%s" % (pre.get("groupBy"), [c.get("name") for c in (pre.get("columns") or [])])
                   if pre else "—")
        add("| `%s` | `%s` | %s | %s | %s |" % (so.get("alias"), so.get("objectRef"),
                                                "**是**" if so.get("primary") else "否",
                                                so.get("entityPath") or "—", pre_txt))
    add("")
    add("## 3. Join（口径：`别名.外键 == 对方主键 id`）")
    add("")
    add("| # | 左右 | 条件 | 连接类型 |")
    add("|---|---|---|---|")
    for i, j in enumerate(rep.get("joins") or [], 1):
        add("| %d | `%s` ↔ `%s` | `%s` | %s |" % (i, j.get("leftSource"), j.get("rightSource"),
                                                   j.get("conditionExpression"), j.get("joinType")))
    add("")
    add("## 4. 查询参数（`parameters`）")
    add("")
    add("| 名称 | 标签 | 类型 | 必填 | 默认值 | 字典/枚举 | 角色 |")
    add("|---|---|---|---|---|---|---|")
    switch_names = {c.get("switchParameterRef") for c in (rep.get("conditions") or []) if c.get("switchParameterRef")}
    for p in rep.get("parameters") or []:
        dref = p.get("dictionaryRef") or p.get("dictRef") or ""
        ev = p.get("enumValues")
        role = "**条件组开关（约定 13）**" if p.get("name") in switch_names else "普通筛选"
        add("| `%s` | %s | %s | %s | %s | %s | %s |" % (
            p.get("name"), p.get("label"), p.get("dataType"), "是" if p.get("required") else "否",
            p.get("defaultValue"), ("enumValues=%s" % ev) if ev else (dref or "—"), role))
    add("")
    add("## 5. 查询条件（含条件组与开关，约定 13）")
    add("")
    add("| 条件 | 左表达式 | 运算符 | 参数/常量 | 连接符 | 组 | 空值跳过 | 开关参数 | 开关激活值 | triggerKind |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for c in rep.get("conditions") or []:
        rhs = c.get("parameterRef") or ("常量 `%s`" % c.get("fixedValue"))
        add("| %s | `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            c.get("conditionId"), c.get("leftExpression"), c.get("operator"), rhs,
            c.get("logicalConnector"), c.get("group") or "BASE",
            "是" if c.get("skipWhenParameterEmpty") else "否",
            c.get("switchParameterRef") or "—",
            c.get("switchActivateValue") if c.get("switchActivateValue") is not None else "—",
            c.get("triggerKind") or "—"))
    add("")
    add("**组语义（约定 6 + 约定 13）**：")
    add("")
    add("- `BASE` 恒参与（仅受 `skipWhenParameterEmpty` 控制）；组内按 `logicalConnector` 连接，**组间一律 AND**。")
    add("- `ALERT_FILTER`（预警筛选）：开关 `onlyAlert`；**true → 组参与；false / 未传 → 整组跳过**（未传取 `defaultValue=false`）。")
    add("- 布尔开关取值非法（非 true/false/1/0/yes/no/y/n）→ **400 中文提示**，不得静默当 false。")
    add("")
    add("## 6. 结果列（`resultColumns`，列与列序一律以后端返回为准）")
    add("")
    add("| # | 名称 | 标签 | 类型 | 表达式 | 可见 | 可排序 | 可空 | 格式 |")
    add("|---|---|---|---|---|---|---|---|---|")
    for i, col in enumerate(rep.get("resultColumns") or [], 1):
        add("| %d | `%s` | %s | %s | `%s` | %s | %s | %s | %s |" % (
            i, col.get("name"), col.get("label"), col.get("dataType"),
            (col.get("sourceExpression") or "").strip(), "是" if col.get("visible") else "否",
            "是" if col.get("sortable") else "否", "是" if col.get("nullable") else "否", col.get("format") or "—"))
    add("")
    add("## 7. 分组 / 排序 / 分页 / 报表选项")
    add("")
    add("- `groupBy`：%s" % (rep.get("groupBy") or "（无）"))
    add("- `having`：%s" % (rep.get("having") or "（无）"))
    add("- `orderBy`：%s" % (rep.get("orderBy") or "（无）"))
    add("- `pagination`：%s" % (rep.get("pagination") or "（无）"))
    add("- `reportOptions`：")
    for k, v in (rep.get("reportOptions") or {}).items():
        add("  - `%s` = %s" % (k, v))
    add("")
    add("## 8. 预警状态口径（实现须知）")
    add("")
    for col in rep.get("resultColumns") or []:
        if col.get("name") in ("alertStatus", "alertGap"):
            add("- `%s`（%s）：`%s`" % (col.get("name"), col.get("label"),
                                        " ".join(x.strip() for x in (col.get("sourceExpression") or "").split("\n"))))
    add("")
    add("> 注意：`alertStatus` 返回**中文标签**「预警 / 正常」（模型为计算列，不是字典字典值）；"
        "前端展示与验收断言都必须按此口径，不得自行映射为 `ALERT`/`NORMAL`。")

    report_md = "\n".join(out) + "\n"
    io.open(os.path.join(DOCS, "批次4-报表规格（M7抽取）.md"), "w", encoding="utf-8", newline="\n").write(report_md)

    # ---------------- 屏幕规格 ----------------
    o2 = []
    a2 = o2.append
    a2("# 批次 4 · 屏幕规格（从 MU 机械抽取，禁手改）")
    a2("")
    a2("> 来源：`yaml/mu-ui-model.yaml`（v%s）｜屏幕 `%s`（%s）｜由 `tools/gen_batch4_spec.py` 生成。"
       % (mu.get("version"), scr.get("screenId"), scr.get("name")))
    a2("")
    a2("## 1. 屏幕定义")
    a2("")
    a2("| 字段 | 值 |")
    a2("|---|---|")
    a2("| `screenId` | `%s` |" % scr.get("screenId"))
    a2("| `name` | %s |" % scr.get("name"))
    a2("| `screenType` | %s |" % scr.get("screenType"))
    a2("")
    a2("## 2. 控件元素（%d 个，控件 id 原样落地）" % len(scr.get("elements") or []))
    a2("")
    a2("| # | 控件 id | 类型 | 标签 | io | dataBinding |")
    a2("|---|---|---|---|---|---|")
    for i, e in enumerate(scr.get("elements") or [], 1):
        a2("| %d | `%s` | %s | %s | %s | %s |" % (i, e.get("id"), e.get("type"), e.get("label"),
                                                  e.get("io") or "—", e.get("dataBinding") or "—"))
    a2("")
    a2("## 3. 功能点/动作（%d 个）" % len(scr.get("actions") or []))
    a2("")
    a2("| # | actionId | 名称 | 类型 | behaviorRef | permissionRef |")
    a2("|---|---|---|---|---|---|")
    for i, act in enumerate(scr.get("actions") or [], 1):
        a2("| %d | `%s` | %s | %s | `%s` | `%s` |" % (i, act.get("actionId"), act.get("name"),
                                                      act.get("actionType"), act.get("behaviorRef"),
                                                      "、".join(act.get("permissionRef") or [])))
    a2("")
    a2("## 4. 布局原样（ASCII 原型）")
    a2("")
    a2("```text")
    a2(scr.get("layout") or "")
    a2("```")
    a2("")
    a2("## 5. 权限码（由 M5 permissionId 的 targetRef 机械派生）")
    a2("")
    a2("| 权限 id | 派生权限码 | 说明 |")
    a2("|---|---|---|")
    for act in scr.get("actions") or []:
        for pid in (act.get("permissionRef") or []):
            alias, _, action = (act.get("behaviorRef") or "_").partition("_")
            kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", action).lower()
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", alias).lower()
            a2("| `%s` | `%s:%s` | %s |" % (pid, snake, kebab, act.get("name")))
    screen_md = "\n".join(o2) + "\n"
    io.open(os.path.join(DOCS, "批次4-屏幕规格（MU抽取）.md"), "w", encoding="utf-8", newline="\n").write(screen_md)

    print("报表规格：%d 行 / 屏幕规格：%d 行" % (report_md.count("\n"), screen_md.count("\n")))
    print("参数 %d 个，条件 %d 条，结果列 %d 列，元素 %d 个，动作 %d 个"
          % (len(rep.get("parameters") or []), len(rep.get("conditions") or []),
             len(rep.get("resultColumns") or []), len(scr.get("elements") or []), len(scr.get("actions") or [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
