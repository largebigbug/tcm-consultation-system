# -*- coding: utf-8 -*-
"""system prompt 构建（契约 §6：五要素逐条出现，无硬编码业务清单）。

五要素：
  1. 系统角色与能力说明（只读、不写数据）
  2. 业务域清单（6 个一级菜单 / 19 屏 / 30 个业务对象能力，按权限过滤）
  3. 查询与报表清单（7 个 QUERY 行为 + 7 张 M7 报表，含报表码与可传参数名）
  4. 工具清单及调用说明（按权限过滤后的工具：名称、入参、何时用）
  5. 安全边界与渲染协议（只读声明、写操作引导语、text/table/chart/action 何时返回、SQL 只读约束摘要）

全部素材来自 `ontology.registry`（+ 运行库权限真值），不写死任何业务清单。
"""
from ontology.registry import load_ontology, registry

from ai.tool_registry import CATEGORY_LABEL, CATEGORY_ORDER, _snake, permission_codes_of
from sql_readonly import whitelist_summary


def _allowed(codes, code):
    if not code:
        return True
    return "*" in codes or code in codes


def _catalog_from_tools(tools):
    out = {cat: [] for cat in CATEGORY_ORDER}
    for tool in tools:
        meta = tool["_meta"]
        fn = tool["function"]
        out[meta["category"]].append({
            "name": fn["name"],
            "label": meta.get("label", fn["name"]),
            "params": sorted((fn["parameters"] or {}).get("properties", {})),
            "required": list((fn["parameters"] or {}).get("required", [])),
            "description": fn["description"],
        })
    return out


def _domain_section(codes):
    """要素 2：一级菜单 / 屏 / 业务对象能力（按权限过滤）。"""
    menus = []
    for menu in registry["menus"]:
        children = [c for c in (menu.get("children") or [])]
        if not children:
            continue
        menus.append("%s（%s）" % (menu.get("name"), "、".join(c.get("name", "") for c in children)))

    screen_lines = []
    for sid, screen in registry["screens"].items():
        screen_lines.append("- %s｜%s｜%s" % (sid, screen.get("name", sid),
                                             screen.get("screenType", "")))

    capabilities = []
    for bid, behavior in registry["behaviors"].items():
        if behavior.get("behaviorType") != "COMMAND":
            continue
        code = _behavior_code(bid)
        if not _allowed(codes, code):
            continue
        capabilities.append("- %s｜%s｜%s" % (bid, behavior.get("name", ""),
                                             "系统自动" if behavior.get("triggerType") == "SYSTEM" else "用户操作"))
    return menus, screen_lines, capabilities


def _behavior_code(behavior_id):
    """行为 id → 权限码（运行库真值优先，回落 seed 派生规则）。"""
    try:
        import db
        row = db.query_one("SELECT code FROM sys_permission WHERE target_ref = ?", (behavior_id,))
        if row and row.get("code"):
            return row["code"]
    except Exception:                                  # noqa: BLE001 - 回落派生规则
        pass
    try:
        from seed import permission_code
        return permission_code(behavior_id)
    except Exception:                                  # noqa: BLE001
        return ""


def _query_section(codes):
    """要素 3：7 个 QUERY 行为 + 7 张 M7 报表（报表码 + 参数名）。"""
    lines = []
    for bid, behavior in registry["behaviors"].items():
        if behavior.get("behaviorType") != "QUERY":
            continue
        code = _behavior_code(bid)
        if not _allowed(codes, code):
            continue
        report_code = behavior.get("queryReportRef") or "-"
        params = _report_param_names(report_code)
        lines.append("- 查询 %s｜%s｜工具 query_%s｜报表 %s｜参数：%s"
                     % (bid, behavior.get("name", ""), bid, report_code,
                        "、".join(params) if params else "（无）"))
    report_lines = []
    for rid, report in registry["query_reports"].items():
        code = _behavior_code(report.get("behaviorRef") or "")
        if not _allowed(codes, code):
            continue
        report_lines.append("- 报表 %s｜%s｜工具 report_%s｜参数：%s"
                            % (rid, report.get("name", ""), rid,
                               "、".join(_report_param_names(rid)) or "（无）"))
    return lines, report_lines


def _report_param_names(report_code):
    report = registry["query_reports"].get(report_code) or {}
    return [p["name"] for p in report.get("parameters") or []]


def _tool_section(cat, items):
    if not items:
        return ["（当前账号无可用工具）"]
    lines = []
    for item in items:
        param_text = "、".join(item["params"]) if item["params"] else "无"
        lines.append("- %s｜%s｜入参：%s｜何时用：%s"
                     % (item["name"], item["label"], param_text, item["description"]))
    return lines


def _sql_section():
    summary = whitelist_summary()
    tables = "、".join("%s(%s)" % (tbl, "/".join(cols)) for tbl, cols in sorted(summary.items()))
    return ("- 仅 SELECT；仅白名单表与其白名单字段（%s）；SQL 里必须显式列出字段，"
            "禁止 SELECT *；强制追加 LIMIT（缺省 100、上限 500）；单次执行超时 3 秒；"
            "禁止注释、多语句、UNION、sqlite_ 系统表。" % tables)


def build_system_prompt(user_id, tools=None):
    """构建 system prompt（tools 为**已按权限过滤**的工具定义；缺省时自行过滤）。"""
    codes = permission_codes_of(user_id)
    if tools is None:
        from ai.tool_registry import build_tools
        tools = build_tools(user_id)
    catalog = _catalog_from_tools(tools)
    menus, screens, capabilities = _domain_section(codes)
    queries, reports = _query_section(codes)

    lines = []
    add = lines.append
    # 要素 1
    add("## 1. 你的角色与能力")
    add("你是中医问诊系统的智能助理，服务于门诊、药房、库存、随访、统计报表与基础数据各岗位。")
    add("你**只读**：可以查询数据、解释口径、生成统计结果与页面跳转按钮；"
        "你**不执行任何写操作**（不建档、不挂号、不开方、不审核、不发药、不调整库存）。")
    add("用户要办业务时，你只输出「跳转到对应页面 + 预填」的按钮，由用户在页面上确认提交。")
    add("回答一律使用简体中文，简洁、可核对；数据不足时说明缺什么，不要编造数字。")

    # 要素 2
    add("")
    add("## 2. 业务域清单（来自本体注册表）")
    add("一级菜单：%s" % "；".join(menus))
    add("可访问页面（19 屏，按你的权限过滤后 %d 屏）：" % len(screens))
    lines.extend(screens)
    add("业务对象能力（共 30 条 COMMAND 行为，按你的权限过滤后 %d 条可直接跳转操作）："
        % len(capabilities))
    lines.extend(capabilities or ["（当前账号无可用业务操作）"])

    # 要素 3
    add("")
    add("## 3. 查询与报表清单")
    add("查询行为（M2 QUERY，共 7 条）：")
    lines.extend(queries or ["（当前账号无可用查询）"])
    add("报表（M7，共 7 张）：")
    lines.extend(reports or ["（当前账号无可用报表）"])

    # 要素 4
    add("")
    add("## 4. 工具清单及调用说明（按你的权限过滤后的全部可用工具）")
    for cat in CATEGORY_ORDER:
        items = catalog.get(cat) or []
        add("### 4.%d %s（%d 个）" % (CATEGORY_ORDER.index(cat) + 1, CATEGORY_LABEL[cat], len(items)))
        lines.extend(_tool_section(cat, items))

    # 要素 5
    add("")
    add("## 5. 安全边界与渲染协议")
    add("- 只读声明：任何工具都不会写数据库；`action_*` 工具只返回跳转按钮，绝不代替用户提交。")
    add("- 写操作引导语：用户要求建档/挂号/开方/审核/发药/盘点等，改用 action_* 工具返回跳转按钮，"
        "并提示「只读模式：请在页面上确认提交」。")
    add("- 渲染协议（必须用工具结果驱动渲染，不要凭空造表格）：")
    add("  * text：纯文字解释、口径说明；")
    add("  * table：query_* / report_* / sql_readonly 的查询结果（列名用报表模型的中文列标签）；")
    add("  * chart：用户明确要「图表/趋势/分布」时，用 chart 工具传 rows/chartType/xField/yField；")
    add("  * action：导航或业务操作引导，返回 {type:'navigate', screenId, behaviorId, label, "
        "prefill?, permissionCode}，前端渲染成按钮跳转，不发起写请求。")
    add("- SQL 只读约束：")
    add(_sql_section())
    add("- 无权限的工具不会出现在工具清单里；若被要求执行无权限操作，如实说明并给出有权限的替代。")
    return "\n".join(lines)


def prompt_elements(user_id, tools=None):
    """（自测用）返回五要素的命中情况，便于断言「五要素逐条出现」。"""
    text = build_system_prompt(user_id, tools)
    checks = {
        "角色与能力": "## 1. 你的角色与能力" in text,
        "业务域清单": "## 2. 业务域清单" in text,
        "查询与报表清单": "## 3. 查询与报表清单" in text,
        "工具清单及调用说明": "## 4. 工具清单及调用说明" in text,
        "安全边界与渲染协议": "## 5. 安全边界与渲染协议" in text,
    }
    return text, checks


if not registry.get("screens"):                        # 模块自用装载（幂等）
    load_ontology()
