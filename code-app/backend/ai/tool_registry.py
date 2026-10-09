# -*- coding: utf-8 -*-
"""工具注册表（契约 §4）：**逐条**从注册表/抽取文档生成 59 个工具的 function-calling schema。

单一语义来源（不手写任何业务清单）：
  * 导航 19 = MU `screens`（权限随登录用户的菜单可见性，取运行库 `sys_resource.permission_code`）
  * 查询 7  = M2 `behaviorType=QUERY`（报表取 `queryReportRef`）
  * 报表 7  = M7 `query_reports`（入参取报表 `parameters`）
  * 行为 24 = M2 `behaviorType=COMMAND & triggerType=USER_ACTION`（只读边界：仅生成跳转 action）
  * 图表 1 / SQL 1 = 平台工具（SQL 由 `sql_readonly.guard` 强制白名单）

权限码取运行库 `sys_permission`（`target_ref` = 行为 id）的真值，缺失时回落到
`seed.permission_code(targetRef)` 派生规则（与库内真值一致，抽取文档 §6 已核对）。

`verify_against_spec_doc()` 把生成结果与 `docs/批次5-工具清单（注册表抽取）.md` 逐条对账
（工具名集合 + 分类计数 + 总数），供自测与验收断言。
"""
import hashlib
import os
import re

import db
from config import settings
from ontology.registry import load_ontology, registry

from sql_readonly import SqlFailed, SqlRejected, SqlTimeout, execute_readonly

CATEGORY_ORDER = ("nav", "query", "report", "action", "chart", "sql")
CATEGORY_LABEL = {
    "nav": "导航", "query": "查询", "report": "报表", "action": "行为（只读跳转）",
    "chart": "图表", "sql": "SQL 只读",
}
EXPECTED_TOTAL = 59

SPEC_DOC = os.path.join(settings.BASE_DIR, os.pardir, "docs", "批次5-工具清单（注册表抽取）.md")

_SPEC_TOOL_RE = re.compile(r"`((?:nav|query|report|action)_[A-Za-z0-9_.\-]+)`")
_SPEC_COUNT_RE = {
    "nav": re.compile(r"\|\s*导航工具\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|"),
    "query": re.compile(r"\|\s*查询工具（M2 QUERY）\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|"),
    "report": re.compile(r"\|\s*查询工具（M7 报表）\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|"),
    "action": re.compile(r"\|\s*行为工具（只读边界[^|]*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|"),
}


# ---------------------------------------------------------------- 基础工具

def ensure_ontology():
    if not registry.get("screens"):
        load_ontology()


def _snake(name):
    out = []
    for i, ch in enumerate(name or ""):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _kebab(name):
    return _snake(name).replace("_", "-")


# OpenAI/DeepSeek 函数名约束：^[a-zA-Z0-9_-]{1,64}$（含 `.` 会被 400 拒绝）
TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_ILLEGAL_IN_NAME = re.compile(r"[^A-Za-z0-9_-]")


def tool_name(prefix, ident):
    """构造 API 合法的工具名：`<prefix>_<净化后的 id>`；超长则截断并加短哈希。

    模型里的 id 可能含 `.` 等非法字符（旧口径为 `nav.frmXxx`），或日后新增奇怪 id；
    统一净化，保证任何模型内容都不会让函数名越界。中文标签走 description，不进函数名。
    """
    raw = "%s_%s" % (prefix, _ILLEGAL_IN_NAME.sub("_", str(ident or "")))
    if len(raw) > 64:
        raw = "%s_%s" % (raw[:55], hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8])
    return raw


def validate_tool_names(tools):
    """硬校验：工具名必须符合 API 约束且唯一；违规抛错（宁可启动失败，也不要线上 400）。"""
    seen, bad, dup = set(), [], []
    for t in tools:
        name = (t.get("function") or {}).get("name", "")
        if not TOOL_NAME_RE.match(name):
            bad.append(name)
        if name in seen:
            dup.append(name)
        seen.add(name)
    if bad or dup:
        raise RuntimeError("工具名不符合 API 约束：非法=%s 重复=%s" % (bad[:5], dup[:5]))
    return True


def _allowed(codes, code):
    """与 `services.auth_service.has_permission` 同一语义（`*` 为超级权限）。"""
    if not code:
        return True
    return "*" in codes or code in codes


def permission_codes_of(user_id):
    from services.auth_service import get_permission_codes
    return get_permission_codes(user_id)


def _db_behavior_codes():
    """运行库真值：行为 id → 权限码（`sys_permission.target_ref` → `code`）。"""
    rows = db.query("SELECT code, target_ref FROM sys_permission WHERE target_ref IS NOT NULL")
    return {r["target_ref"]: r["code"] for r in rows if r["target_ref"]}


def _derived_code(target_ref):
    """回落：`seed.permission_code` 派生规则（与库内真值一致，抽取文档 §6 已核对）。"""
    try:
        from seed import permission_code
        return permission_code(target_ref)
    except Exception:                                  # noqa: BLE001 - 派生失败只影响提示文案
        return ""


def _menu_permission_map():
    """屏 id → 菜单权限码（运行库 `sys_resource`，即登录用户的菜单可见性口径）。

    运行库不可用时回落：该屏第一条带 `behaviorRef` 的 action 的权限码。
    """
    out = {}
    by_code = {}
    try:
        rows = db.query("SELECT code, permission_code FROM sys_resource WHERE type = 'MENU'")
        by_code = {r["code"]: (r["permission_code"] or "") for r in rows}
    except Exception:                                  # noqa: BLE001 - 回落见下
        by_code = {}
    ensure_ontology()
    for menu in registry["menus"]:
        for child in menu.get("children") or []:
            sid = child.get("screenRef")
            if not sid:
                continue
            code = by_code.get(child.get("menuId"), "")
            if not code and by_code:
                continue
            if not code:
                screen = registry["screens"].get(sid) or {}
                for action in screen.get("actions") or []:
                    ref = action.get("behaviorRef")
                    if ref:
                        code = _derived_code(ref)
                        break
            out[sid] = code or ""
    return out


# ---------------------------------------------------------------- 参数 schema

def _param_schema(spec):
    dtype = (spec.get("dataType") or "String").strip()
    desc = spec.get("label") or spec.get("name")
    prop = {"description": "%s（%s）" % (desc, dtype)}
    if dtype in ("Integer", "Long"):
        prop["type"] = "integer"
    elif dtype in ("Decimal", "Number", "Float", "Double"):
        prop["type"] = "number"
    elif dtype == "Boolean":
        prop["type"] = "boolean"
    else:
        prop["type"] = "string"
        if dtype == "Date":
            prop["description"] += "，格式 yyyy-MM-dd"
    if spec.get("enumValues"):
        prop["enum"] = [str(v) for v in spec["enumValues"]]
    if spec.get("defaultValue") is not None:
        prop["description"] += "，缺省 %s" % spec["defaultValue"]
    return prop


def _report_parameters(report_code, with_paging=False):
    report = registry["query_reports"].get(report_code) or {}
    props, required = {}, []
    for spec in report.get("parameters") or []:
        props[spec["name"]] = _param_schema(spec)
        if spec.get("required"):
            required.append(spec["name"])
    if with_paging:
        props["page"] = {"type": "integer", "description": "页码（自 1 起）"}
        props["size"] = {"type": "integer", "description": "每页条数（上限以模型 pagination 为准）"}
    return props, required


def _schema(name, description, props=None, required=None):
    """工具定义：OpenAI function-calling 形状 + 顶层 `name` 便捷别名。

    顶层 `name` 是**冗余别名**，便于工具枚举/验收脚本 `tool["name"]` 直接取名字；
    发给模型前由 provider 归一化为 {type, function}（见 `providers.deepseek._payload`）。
    """
    return {
        "type": "function",
        "name": name,
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": list(required or []),
            },
        },
    }


# ---------------------------------------------------------------- 工具生成

def build_all_tools():
    """生成 59 个工具定义（**不**做权限过滤）；每项含 `_meta`（执行与审计所需）。"""
    ensure_ontology()
    codes = _db_behavior_codes()
    menu_perm = _menu_permission_map()
    tools = []

    # ---- 导航 19
    screens = registry["screens"]
    for sid, screen in screens.items():
        perm = menu_perm.get(sid, "")
        tools.append(_schema(
            tool_name("nav", sid),
            "打开/跳转到系统页面「%s」（%s）。当用户想进入某个功能页面时使用；"
            "只返回跳转指令，不执行任何写操作。" % (screen.get("name", sid), sid),
            {}, [],
        ) | {"_meta": {"category": "nav", "screenId": sid, "behaviorId": "",
                       "label": screen.get("name", sid), "permission": perm,
                       "detail": "页面 %s" % screen.get("name", sid)}})

    # ---- 查询 7（M2 QUERY）与报表 7（M7）
    for bid, behavior in registry["behaviors"].items():
        if behavior.get("behaviorType") != "QUERY":
            continue
        report_code = behavior.get("queryReportRef") or ""
        props, required = _report_parameters(report_code, with_paging=True)
        tools.append(_schema(
            tool_name("query", bid),
            "查询「%s」（只读统计查询，返回表格数据）。当用户询问对应统计口径时使用；"
            "参数缺省时按报表模型默认值执行。" % behavior.get("name", bid),
            props, required,
        ) | {"_meta": {"category": "query", "behaviorId": bid, "reportCode": report_code,
                       "label": behavior.get("name", bid),
                       "permission": codes.get(bid) or _derived_code(bid),
                       "screenId": _screen_of_behavior(bid)}})

    for rid, report in registry["query_reports"].items():
        props, required = _report_parameters(rid, with_paging=True)
        ref = report.get("behaviorRef") or ""
        tools.append(_schema(
            tool_name("report", rid),
            "查询 M7 报表「%s」（报表码 %s，只读，返回表格数据，可带分页）。"
            "当用户明确要报表数据时使用。" % (report.get("name", rid), rid),
            props, required,
        ) | {"_meta": {"category": "report", "reportCode": rid, "behaviorId": ref,
                       "label": report.get("name", rid),
                       "permission": codes.get(ref) or _derived_code(ref),
                       "screenId": _screen_of_behavior(ref)}})

    # ---- 行为 24（只读边界：仅生成跳转 action）
    for bid, behavior in registry["behaviors"].items():
        if behavior.get("behaviorType") != "COMMAND" or behavior.get("triggerType") != "USER_ACTION":
            continue
        tools.append(_schema(
            tool_name("action", bid),
            "「%s」：AI 不执行写操作，只生成跳转到对应页面并可预填的按钮，"
            "由用户在页面上确认提交。" % behavior.get("name", bid),
            {"prefill": {"type": "object",
                         "description": "预填字段（键为表单字段名，值为待填内容），可省略"}},
            [],
        ) | {"_meta": {"category": "action", "behaviorId": bid,
                       "label": behavior.get("name", bid), "screenId": _screen_of_behavior(bid),
                       "permission": codes.get(bid) or _derived_code(bid),
                       "detail": "行为 %s" % behavior.get("name", bid)}})

    # ---- 图表 1
    tools.append(_schema(
        "chart",
        "把已有查询结果渲染成图表（bar / line / pie）。当用户要求「用图表展示」时使用。",
        {
            "rows": {"type": "array", "items": {"type": "object"},
                     "description": "数据行（对象数组，键与 xField/yField 对应）"},
            "chartType": {"type": "string", "enum": ["bar", "line", "pie"], "description": "图表类型"},
            "xField": {"type": "string", "description": "X 轴/类目字段名"},
            "yField": {"type": "string", "description": "Y 轴/数值字段名"},
            "title": {"type": "string", "description": "图表标题，可省略"},
        },
        ["rows", "chartType", "xField", "yField"],
    ) | {"_meta": {"category": "chart", "behaviorId": "", "label": "图表渲染",
                   "permission": "", "screenId": ""}})

    # ---- SQL 只读 1
    tables = "、".join(sorted(registry["db_whitelist"]))
    tools.append(_schema(
        "sql_readonly",
        "对白名单表执行只读 SELECT 查询（仅 SELECT、仅白名单表 %s 及其白名单字段，"
        "强制 LIMIT、3 秒超时、禁注释/多语句/SELECT *）。其它工具无法满足的取数需求才使用。"
        % tables,
        {"sql": {"type": "string", "description": "单条 SELECT 语句（需要显式列出字段）"}},
        ["sql"],
    ) | {"_meta": {"category": "sql", "behaviorId": "", "label": "只读 SQL 查询",
                   "permission": "", "screenId": ""}})

    validate_tool_names(tools)   # 硬校验：非法/重复的工具名直接抛错，禁止进 schema
    return tools


def _screen_of_behavior(behavior_id):
    """行为 id → 承载该行为的屏 id（MU `screens[].actions[].behaviorRef`，取首个）。"""
    if not behavior_id:
        return ""
    ensure_ontology()
    for sid, screen in registry["screens"].items():
        for action in screen.get("actions") or []:
            if action.get("behaviorRef") == behavior_id:
                return sid
    return ""


# ---------------------------------------------------------------- 权限过滤

def build_tools(user_id):
    """按登录用户权限过滤后的工具定义（未授权工具**不进入** schema）。"""
    codes = permission_codes_of(user_id)
    return [t for t in build_all_tools() if _allowed(codes, t["_meta"].get("permission"))]


def catalog(user_id):
    """给 prompt_builder 的紧凑清单：分类 → [{name, label, params, description}]。"""
    out = {cat: [] for cat in CATEGORY_ORDER}
    for tool in build_tools(user_id):
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


def get_tool(name):
    """按名取工具定义（全量，不做权限过滤）。"""
    for tool in build_all_tools():
        if tool["function"]["name"] == name:
            return tool
    return None


def counts(tools=None):
    tools = build_all_tools() if tools is None else tools
    result = {cat: 0 for cat in CATEGORY_ORDER}
    for tool in tools:
        result[tool["_meta"]["category"]] += 1
    result["total"] = sum(result.values())
    return result


# ---------------------------------------------------------------- 与抽取文档对账

def spec_doc_tools(path=None):
    """解析抽取文档中的工具名与分类计数（文档缺失时返回 (None, None)）。"""
    path = path or SPEC_DOC
    if not os.path.exists(path):
        return None, None
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    names = set(_SPEC_TOOL_RE.findall(text))
    if "`chart`" in text:
        names.add("chart")
    if "`sql_readonly`" in text:
        names.add("sql_readonly")
    expected = {}
    for cat, pattern in _SPEC_COUNT_RE.items():
        match = pattern.search(text)
        if match:
            expected[cat] = int(match.group(1))
    expected["chart"] = 1
    expected["sql"] = 1
    return names, expected


def verify_against_spec_doc(path=None):
    """生成结果 ↔ 抽取文档逐条对账（自测与验收的硬断言）。"""
    doc_names, doc_counts = spec_doc_tools(path)
    generated = {t["function"]["name"] for t in build_all_tools()}
    result = {
        "doc_path": os.path.abspath(path or SPEC_DOC),
        "doc_available": doc_names is not None,
        "generated_total": len(generated),
        "generated_counts": counts(),
        "ok": False,
        "missing_in_generated": [],
        "extra_in_generated": [],
        "count_mismatch": {},
    }
    if doc_names is None:
        result["error"] = "抽取文档不存在，无法对账：%s" % result["doc_path"]
        return result
    result["doc_total"] = len(doc_names)
    result["doc_counts"] = doc_counts
    result["missing_in_generated"] = sorted(doc_names - generated)
    result["extra_in_generated"] = sorted(generated - doc_names)
    for cat, expected in doc_counts.items():
        if result["generated_counts"].get(cat) != expected:
            result["count_mismatch"][cat] = {"doc": expected,
                                             "generated": result["generated_counts"].get(cat)}
    result["ok"] = (not result["missing_in_generated"] and not result["extra_in_generated"]
                    and not result["count_mismatch"]
                    and result["generated_total"] == result["doc_total"])
    return result


# ---------------------------------------------------------------- 执行

def _table_payload(columns, rows, total, truncated):
    return {"columns": columns, "rows": rows, "total": int(total), "truncated": bool(truncated)}


def _report_render(report_code, arguments):
    from services import report_service
    query = {}
    report = registry["query_reports"].get(report_code) or {}
    allowed = {p["name"] for p in report.get("parameters") or []}
    for key, value in (arguments or {}).items():
        if key in allowed or key in ("page", "size"):
            query[key] = value
    payload = report_service.list_report(report_code, query)
    rows = payload.get("list") or []
    columns = [{"name": c["name"], "label": c.get("label") or c["name"]}
               for c in payload.get("columns") or [] if c.get("visible", True)]
    total = int(payload.get("total") or len(rows))
    return {
        "renderType": "table",
        "payload": _table_payload(columns, rows, total, total > len(rows)),
        "rowsCount": len(rows),
        "summary": "「%s」返回 %d 行（共 %d 行）" % (
            (payload.get("report") or {}).get("name") or report_code, len(rows), total),
    }


def _chart_render(arguments):
    rows = arguments.get("rows")
    chart_type = (arguments.get("chartType") or "").strip().lower()
    x_field = arguments.get("xField")
    y_field = arguments.get("yField")
    if not isinstance(rows, list) or not rows:
        raise ValueError("chart 工具需要非空的 rows（对象数组）")
    if chart_type not in ("bar", "line", "pie"):
        raise ValueError("chart 工具 chartType 仅支持 bar / line / pie")
    first = rows[0]
    if not isinstance(first, dict) or x_field not in first or y_field not in first:
        raise ValueError("chart 工具的 xField / yField 必须是 rows 中的字段名")
    payload = {"chartType": chart_type, "xField": x_field, "yField": y_field, "rows": rows}
    if arguments.get("title"):
        payload["title"] = arguments["title"]
    return {"renderType": "chart", "payload": payload, "rowsCount": len(rows),
            "summary": "已生成%s图（%s / %s，%d 行）"
                       % ({"bar": "柱", "line": "折线", "pie": "饼"}[chart_type],
                          x_field, y_field, len(rows))}


def _action_render(meta, arguments):
    payload = {
        "type": "navigate",
        "screenId": meta.get("screenId") or "",
        "behaviorId": meta.get("behaviorId") or "",
        "label": meta.get("label") or "",
        "permissionCode": meta.get("permission") or "",
    }
    prefill = (arguments or {}).get("prefill")
    if isinstance(prefill, dict) and prefill:
        payload["prefill"] = prefill
    return {"renderType": "action", "payload": payload, "rowsCount": None,
            "summary": "只读模式：AI 不执行写操作，已生成跳转「%s」的按钮，请在页面上确认提交"
                       % (meta.get("label") or meta.get("behaviorId") or "目标页面")}


def _sql_execute(arguments, limits):
    from sql_readonly import guard_sql
    sql = (arguments or {}).get("sql") or ""
    audit = {"sql": sql, "ok": False, "rejectedReason": None, "rowCount": None, "elapsedMs": 0}
    try:
        _guarded, result = execute_readonly(
            sql,
            default_limit=int(limits.get("default_limit", 100)),
            max_limit=int(limits.get("max_limit", 500)),
            timeout_seconds=float(limits.get("timeout_seconds", 3)),
        )
    except SqlRejected as exc:
        audit["rejectedReason"] = exc.message
        raise
    except SqlTimeout as exc:
        audit["rejectedReason"] = str(exc)
        raise
    except SqlFailed as exc:
        audit["rejectedReason"] = str(exc)
        raise
    audit["ok"] = True
    audit["rowCount"] = result["rowCount"]
    audit["elapsedMs"] = result["elapsedMs"]
    columns = [{"name": name, "label": name} for name in result["columns"]]
    return {
        "renderType": "table",
        "payload": _table_payload(columns, result["rows"], result["rowCount"],
                                  result["truncated"]),
        "rowsCount": result["rowCount"],
        "summary": "只读查询返回 %d 行（%d ms）" % (result["rowCount"], result["elapsedMs"]),
        "sqlAudit": audit,
    }


def execute_tool(name, arguments, user_id, username=None, cfg=None):
    """执行一个工具调用（含权限复检 + 只读边界）。

    返回 dict：`ok / summary / renderType / payload / rowsCount / error / sqlAudit`
    —— 无论成功、被拒还是异常，都**不**抛给上层（由编排层统一转 SSE 事件与审计）。
    """
    from services.auth_service import has_permission

    arguments = arguments if isinstance(arguments, dict) else {}
    tool = get_tool(name)
    if tool is None:
        return {"ok": False, "error": "未知的工具：%s" % name,
                "summary": "调用了不存在的工具「%s」，已拒绝。本次对话未产生任何写操作。" % name,
                "renderType": None, "payload": None, "rowsCount": None}
    meta = tool["_meta"]
    permission = meta.get("permission") or ""
    if permission and not has_permission(user_id, permission):
        return {"ok": False, "error": "无权限执行该操作",
                "summary": "无权限执行该操作：当前账号不具备「%s」所需的权限码 %s，已拒绝。"
                           "本次对话未产生任何写操作。" % (meta.get("label") or name,
                                                          meta.get("permission")),
                "renderType": None, "payload": None, "rowsCount": None}

    limits = (cfg or {}).get("sql_limits") or {"default_limit": 100, "max_limit": 500,
                                              "timeout_seconds": 3}
    try:
        if meta["category"] == "nav":
            out = _action_render(meta, arguments)
            out["summary"] = "已生成跳转「%s」的按钮（AI 不执行写操作）" % meta.get("label")
        elif meta["category"] == "action":
            out = _action_render(meta, arguments)
        elif meta["category"] == "chart":
            out = _chart_render(arguments)
        elif meta["category"] == "sql":
            out = _sql_execute(arguments, limits)
        else:                                          # query / report
            out = _report_render(meta["reportCode"], arguments)
    except (SqlRejected, SqlTimeout, SqlFailed) as exc:
        audit = {"sql": arguments.get("sql") or "", "ok": False,
                 "rejectedReason": getattr(exc, "message", str(exc)),
                 "rowCount": None, "elapsedMs": 0}
        return {"ok": False, "error": getattr(exc, "message", str(exc)),
                "summary": "只读 SQL 被拒绝或执行失败：%s" % getattr(exc, "message", str(exc)),
                "renderType": None, "payload": None, "rowsCount": None, "sqlAudit": audit}
    except ValueError as exc:                          # 报表口径/图表参数等业务校验失败
        return {"ok": False, "error": str(exc), "summary": "工具执行失败：%s" % exc,
                "renderType": None, "payload": None, "rowsCount": None}
    except Exception as exc:                           # noqa: BLE001 - 兜底不外泄堆栈
        return {"ok": False, "error": str(exc), "summary": "工具执行异常：%s" % exc,
                "renderType": None, "payload": None, "rowsCount": None}

    return {
        "ok": True,
        "error": None,
        "summary": out.get("summary") or "",
        "renderType": out.get("renderType"),
        "payload": out.get("payload"),
        "rowsCount": out.get("rowsCount"),
        "sqlAudit": out.get("sqlAudit"),
    }
