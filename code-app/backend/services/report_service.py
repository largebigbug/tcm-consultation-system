# -*- coding: utf-8 -*-
"""批次 3 报表引擎（**完全由 M7 元数据驱动**）。

契约：docs/批次3-实现契约.md §2 全局约定、§3 报表引擎规范、§4 六张报表口径、§8 验收。
模型：ontology.registry.load_ontology() → registry["query_reports"]（7 个报表对象）、
      registry["db_whitelist"]（13 张物理表白名单，含 table 与 attributes）。

设计要点（不写任何 per-report 分支；下列规则对全部报表一视同仁）
  1. 别名 → 物理表：sourceObjects[].alias 的 snake_case，若不在 db_whitelist 内，回落到
     M1 聚合别名（ObjectRef 聚合的 alias，entityPath 存在时取该子实体 alias）的 snake_case，
     仍不在白名单内即抛中文异常。
  2. 列 `别名.属性名` → 物理表别名 + 属性 snake_case；属性必须在白名单 attributes 内。
     预聚合别名（itemAgg / visitPrescriptionAgg / flowAgg…）以 CTE 实现，CTE 列名 =
     preAggregation.columns[].name（聚合列）与 groupBy 键（分组键）原样命名，CTE 内同样 flag = 1。
  3. Join：模型写 `别名.外键 == 别名.<被引用对象业务键>`（v1.6 前）或 `== 别名.id`（v1.6 起），
     引擎一律按契约 §3.2 生成 `外键列 = 被引用表主键 id`（被引用方是预聚合别名时取其分组键）。
  4. 表达式翻译：DATE_TRUNC(x, MONTH) → strftime('%Y-%m', x)、DAY → date(x)、YEAR → strftime('%Y', x)、
     第二参数为查询参数（granularity）时取参数值（DAY/MONTH/YEAR，非法值抛中文异常）；
     COUNT/COUNT_DISTINCT/SUM/AVG/MIN/MAX → 对应 SQL；SUM(CASE WHEN…) 原样保留；
     比率列不做百分比化（返回 0~1 小数），除法一律 `* 1.0` 强制浮点 + NULLIF 保护除零。
  5. SUBTOTAL(x)（跨全部分组的总计）→ 窗口聚合 SUM(x) OVER ()：整张报表退化为
     「分组子查询 + 外层窗口」两段式，分母与分子同条件且不受分页影响（契约 §3.3、M7 约定 7）。
  6. 条件：group=BASE 恒参与（仅受 skipWhenParameterEmpty 控制）；非 BASE 组为可选条件组，
     由同报表的开关参数（Enum，默认值 BOTH 或该组 triggerKind 之一）控制：
     BOTH=组内成员按连接符全部参与，否则仅 triggerKind 匹配的成员参与；组与组之间用 AND 连接，
     每组外层加括号。常量条件（无 parameterRef 而有 fixedValue）恒参与：`别名.属性` 作列引用、
     `[A, B, C]` 配 IN 展开、其余为字面量。LIKE → LIKE '%值%'；IN 支持重复参数与逗号分隔。
  7. 字典参数只接受 M1 字典 code（字典由该列 M1 属性的 dictionaryRef 决定），非法值抛中文异常；
     引用型参数（AggregateRootRef，如 herbId/formulaTemplateId）允许主键 id 或 M1 聚合的业务编号，
     由引擎解析为目标主键（模型参数 sourceField 与条件左表达式口径不一致时的兼容，见交付报告）。
  8. 维度参数（如 statsDimension=HERB|FORMULA_TEMPLATE，取值域取模型 enumValues，M7 约定 10/11）：
     可选维度 = 具有「仅引用自身的一组非聚合结果列」
     的非主别名；取值决定分组列与置空列（其他维度列及其预聚合列置 NULL）。
  9. 主从报表：从主表出发按 Join 关系算层级（被连接表持外键且为普通表 → 层级 +1；引用型 Join 与
     预聚合别名不升级），实体层级 ≥ 2 即为主从结构（本批仅 QR-VISIT-PRESCRIPTION-001）。
 10. 全部 SQL 使用 ? 参数化绑定（查询参数值一律不拼进 SQL）；排序字段走结果列白名单。
 11. 分页 page 自 1 起，size 默认 pagination.defaultPageSize、上限 pagination.maxPageSize（超出截断）；
     summary 仅在 reportOptions.totalFields 非空时返回，取**全量分组行**逐列求和（不受分页影响）。
"""

import datetime
import re

import db
from ontology.registry import get_dictionary_items, load_ontology, registry
from utils.tabular import write_csv, write_xlsx

# ---------------------------------------------------------------- 常量

MAX_EXPORT_ROWS = 10000
GRANULARITY = ("DAY", "MONTH")            # 内置回退值（M7 约定 7）；模型给 enumValues 时以模型为准
GRANULARITY_SQL = {
    "DAY": "date(%s)",
    "MONTH": "strftime('%%Y-%%m', %s)",
    "YEAR": "strftime('%%Y', %s)",
}
def _enum_values(spec):
    """M7 约定 10：Enum 型参数的合法取值来自该参数的 `enumValues` 字段（统一大写，供比对）。"""
    if not isinstance(spec, dict):
        return []
    raw = spec.get("enumValues")
    if not isinstance(raw, (list, tuple)):
        return []
    return [_text(v).upper() for v in raw if _text(v)]


OPERATOR_SQL = {
    "EQ": "=", "NE": "<>", "GT": ">", "GE": ">=", "LT": "<", "LE": "<=",
    "LIKE": "LIKE", "IN": "IN", "BETWEEN": "BETWEEN",
}
AGGREGATE_SQL = {
    "COUNT": "COUNT(%s)", "COUNT_DISTINCT": "COUNT(DISTINCT %s)", "SUM": "SUM(%s)",
    "AVG": "AVG(%s)", "MIN": "MIN(%s)", "MAX": "MAX(%s)",
}
DATE_OPERATORS = ("GE", "LE", "GT", "LT", "BETWEEN")
BARE_KEYWORDS = {"CASE", "WHEN", "THEN", "ELSE", "END", "NULL", "IS", "NOT", "AND", "OR",
                 "TRUE", "FALSE", "CAST", "AS", "IN"}
SWITCH_ALL = "BOTH"
BOOL_TRUE = ("true", "1", "yes", "y")
BOOL_FALSE = ("false", "0", "no", "n")
CHILD_KEY = "prescriptions"
GRANDCHILD_KEY = "items"
ROW_KEY = "id"
LEVEL_PREFIX = "__lvl"
LEVEL_EXTRA_ATTRS = ("cancelReason",)   # 契约 §4.4：从表行须返回作废相关字段
MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}

_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")
_BARE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_DATE_TRUNC_RE = re.compile(r"\bDATE_TRUNC\(\s*([^,()]+?)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_SUBTOTAL_RE = re.compile(r"^(?P<num>.+?)\s*/\s*NULLIF\(\s*SUBTOTAL\(\s*(?P<den>.+?)\s*\)\s*,\s*0\s*\)$")
_LIST_RE = re.compile(r"^\[(.*)\]$")
_CASE_CODE_RE = re.compile(r"=\s*'([A-Za-z0-9_\-]+)'")
_IN_CODE_RE = re.compile(r"IN\s*\(([^)]*)\)")


def _bool_value(raw, label):
    """开关参数取值的严格解析：只接受 true/false/1/0/yes/no/y/n（空串＝未传，返回 None）。

    约定 13：布尔开关取值非法必须中文报错，不得静默当成 False（否则用户传 "TRUE"/"是" 会被
    悄悄忽略，报表返回全量数据而不报错）。
    """
    text = _text(raw).strip().lower()
    if text == "":
        return None
    if text in BOOL_TRUE:
        return True
    if text in BOOL_FALSE:
        return False
    raise ReportError("参数「%s」取值非法（可选 true / false）：%s" % (label, raw))


class ReportError(ValueError):
    """报表业务异常：中文提示 + HTTP 状态码（未知报表 404，其余 400）。"""

    def __init__(self, message, status=400):
        ValueError.__init__(self, message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- 基础工具


def _text(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _snake(name):
    out = []
    for i, ch in enumerate(name or ""):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _kebab(name):
    return _snake(name).replace("_", "-")


def permission_code(target_ref):
    """M2 行为 id → 权限码（与 seed.permission_code 同一规则：`{对象}:{动作}`）。"""
    alias, _, action = _text(target_ref).partition("_")
    if not alias or not action:
        return ""
    return "%s:%s" % (_snake(alias), _kebab(action))


def permission_code_for_report(report):
    return permission_code(report.get("behaviorRef"))


def ensure_ontology():
    if not registry["query_reports"]:
        load_ontology()


def all_report_permission_codes():
    """全部报表权限码（供蓝图级 @require_any_permission 使用）。"""
    ensure_ontology()
    codes = []
    for rep in registry["query_reports"].values():
        code = permission_code_for_report(rep)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def get_report(report_code):
    ensure_ontology()
    rep = registry["query_reports"].get(_text(report_code))
    if not rep:
        raise ReportError("报表不存在：%s" % _text(report_code), 404)
    return rep


def _values(raw):
    """查询参数一律归一为字符串列表（支持重复参数与逗号分隔）。"""
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for item in items:
        for piece in str(item).split(","):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def _resolve_default(value):
    """日期默认值（MONTH_START/MONTH_END/TODAY）→ YYYY-MM-DD；其余原样返回。"""
    token = _text(value)
    if token not in ("MONTH_START", "MONTH_END", "TODAY"):
        return token
    today = datetime.date.today()
    if token == "TODAY":
        return today.strftime("%Y-%m-%d")
    if token == "MONTH_START":
        return today.replace(day=1).strftime("%Y-%m-%d")
    last = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    return last.strftime("%Y-%m-%d")


def _norm_date(value, label):
    text = _text(value)
    raw = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ReportError("参数「%s」日期格式应为 yyyy-MM-dd：%s" % (label, text))


def _split_top_level(expr, token):
    """在括号/引号之外查找分隔符，返回 (左, 右)；找不到返回 None。"""
    depth, quote = 0, ""
    for i, ch in enumerate(expr):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr.startswith(token, i):
            return expr[:i], expr[i + len(token):]
    return None


# ---------------------------------------------------------------- 报表查询编译


class ReportQuery(object):
    """一次报表查询的编译与执行上下文（全部规则由 M7 元数据推导）。"""

    def __init__(self, report, query=None):
        ensure_ontology()
        self.rep = report
        self.code = report["id"]
        self.query = dict(query or {})
        self.wl = registry["db_whitelist"]
        self.result_columns = list(report.get("resultColumns") or [])
        self.col_names = [c["name"] for c in self.result_columns]
        self.col_specs = {c["name"]: c for c in self.result_columns}
        self.specs = {p["name"]: p for p in report.get("parameters") or []}
        self.options = report.get("reportOptions") or {}
        self.empty_display = self.options.get("emptyValueDisplay") or "-"
        self._params = []
        self.aliases = self._build_aliases()
        self.ctes = [a for a, e in self.aliases.items() if e["kind"] == "cte"]
        self.primary = self._primary_alias()
        self.granularity_param = self._granularity_param()
        self.raw_params = self._raw_params()
        self.roles = self._param_roles()
        self.params = self._finalize_params()
        self.granularity = self._resolve_granularity()
        self.candidates = self._dimension_candidates()
        self.dimension = self._resolve_dimension()
        self.trigger = self._resolve_trigger()
        self.group_flags = self._resolve_group_flags()   # 约定 13：布尔开关组的参与判定
        self.levels = self._level_map()
        self.level_aliases = self._level_key_aliases()
        self.master_detail = len(self.level_aliases) >= 3

    # ------------------------------------------------------------ 别名/表

    def _m1_object(self, so):
        """sourceObject → M1 对象（聚合或子实体），用于取属性元数据。"""
        agg = registry["aggregates"].get(so.get("objectRef")) or {}
        path = so.get("entityPath")
        if path:
            for e in agg.get("entities") or []:
                if e.get("alias") == path:
                    return e
        return agg

    def _table_of(self, so, obj):
        for cand in (_snake(so.get("alias")), _snake(obj.get("alias"))):
            if cand and cand in self.wl:
                return cand
        raise ReportError("报表配置引用了未知数据源 %s" % so.get("alias"))

    def _build_aliases(self):
        out = {}
        for so in self.rep.get("sourceObjects") or []:
            alias = so.get("alias")
            if not alias:
                raise ReportError("报表 %s 的数据来源缺少别名" % self.code)
            obj = self._m1_object(so)
            table = self._table_of(so, obj)
            entry = {
                "alias": alias, "table": table, "kind": "table", "primary": bool(so.get("primary")),
                "attrs": list(self.wl[table]["attributes"]),
                "attr_meta": {a["name"]: a for a in (obj.get("attributes") or [])},
                "col_source": {}, "cte_columns": [],
            }
            pre = so.get("preAggregation")
            if pre:
                entry["kind"] = "cte"
                entry["cte_sql"], entry["cte_columns"], entry["col_source"] = self._cte(entry, pre)
            out[alias] = entry
        if not out:
            raise ReportError("报表 %s 未定义数据来源" % self.code)
        if not any(e["primary"] for e in out.values()):
            raise ReportError("报表 %s 未指定主数据来源" % self.code)
        return out

    def _cte(self, entry, pre):
        """预聚合别名 → CTE 定义。列名＝groupBy 键 + preAggregation.columns[].name（原样）。"""
        table, attrs = entry["table"], entry["attrs"]
        group_keys = [_text(k) for k in (pre.get("groupBy") or [])]
        if not group_keys:
            raise ReportError("预聚合数据源 %s 缺少 groupBy" % entry["alias"])
        selects, col_source = [], {}
        for key in group_keys:
            if key not in attrs and not self._join_key_attr(entry, key):
                raise ReportError("预聚合数据源 %s 的分组键 %s 不是 %s 的属性"
                                  % (entry["alias"], key, table))
            selects.append("%s AS %s" % (_snake(key), key))
            col_source[key] = key
        for col in pre.get("columns") or []:
            name = _text(col.get("name"))
            func = _text(col.get("aggregateFunction") or "SUM").upper()
            tpl = AGGREGATE_SQL.get(func)
            if not tpl:
                raise ReportError("预聚合数据源 %s 使用了不支持的聚合函数 %s" % (entry["alias"], func))
            source = _text(col.get("sourceExpression"))
            selects.append("%s AS %s" % (tpl % self._bare_expr(source, attrs, table), name))
            col_source[name] = source.split(".")[-1].strip()
        body = "SELECT %s FROM %s WHERE flag = 1 GROUP BY %s" % (
            ", ".join(selects), table, ", ".join(_snake(k) for k in group_keys))
        return "%s AS (%s)" % (entry["alias"], body), group_keys + [c["name"] for c in pre.get("columns") or []], col_source

    def _bare_expr(self, expr, attrs, table):
        """预聚合表达式（无别名前缀）→ 物理列：属性 snake_case，SQL 关键字原样。"""
        if not expr:
            raise ReportError("预聚合表达式为空（%s）" % table)

        def _sub(m):
            word = m.group(1)
            if word in attrs:
                return _snake(word)
            if word.upper() in BARE_KEYWORDS:
                return word
            raise ReportError("预聚合表达式引用了未知属性 %s（表 %s）" % (word, table))

        return _BARE_RE.sub(_sub, expr)

    def _primary_alias(self):
        for alias, entry in self.aliases.items():
            if entry["primary"]:
                return alias
        return next(iter(self.aliases))

    # ------------------------------------------------------------ 列引用/表达式

    def _all_aliases(self):
        current = getattr(self, "aliases", None)
        if current:
            return list(current.keys())
        return [_text(so.get("alias")) for so in (self.rep.get("sourceObjects") or [])]

    def _join_key_attr(self, entry, attr):
        """聚合归属键/关联外键（M1 以不变式表达，未列入 attributes）：如 PrescriptionItem.prescriptionId。"""
        if not _snake(attr).endswith("_id"):
            return False
        for other in self._all_aliases():
            if other and other != entry.get("alias") and _snake(attr) == _snake(other) + "_id":
                return True
        return False

    def _col_ref(self, alias, attr):
        entry = self.aliases.get(alias)
        if not entry:
            raise ReportError("报表配置引用了未知数据源 %s" % alias)
        if entry["kind"] == "cte":
            if attr not in entry["cte_columns"]:
                raise ReportError("预聚合数据源 %s 不含列 %s" % (alias, attr))
            return "%s.%s" % (alias, attr)
        if attr == ROW_KEY:
            return "%s.id" % alias
        if attr not in entry["attrs"] and not self._join_key_attr(entry, attr):
            raise ReportError("数据源 %s 不存在属性 %s" % (alias, attr))
        return "%s.%s" % (alias, _snake(attr))

    def _translate(self, expr):
        text = _text(expr)
        if not text:
            raise ReportError("报表 %s 的表达式为空" % self.code)
        text = _REF_RE.sub(lambda m: self._col_ref(m.group(1), m.group(2)), text)

        def _dt(m):
            token = m.group(2)
            gran = token if token in GRANULARITY else self.granularity
            if gran not in GRANULARITY:
                raise ReportError("日期粒度取值非法：%s（可选 %s）" % (token, "/".join(GRANULARITY)))
            return GRANULARITY_SQL[gran] % m.group(1)

        return _DATE_TRUNC_RE.sub(_dt, text)

    def _expr_references(self, expr):
        return {m.group(1) for m in _REF_RE.finditer(_text(expr))}

    @staticmethod
    def _force_float(expr):
        """比率列强制浮点除法（SQLite 整数相除会截断）：首个顶层 `/` → `* 1.0 /`。"""
        split = _split_top_level(expr, "/")
        if not split:
            return expr
        left, right = split
        if "*" in right and left.count("(") != left.count(")"):  # 可能是日期格式串等，保守跳过
            return expr
        return "%s* 1.0 /%s" % (left, right)

    def _aggregate(self, expr, agg):
        if not agg or agg == "NONE":
            return self._force_float(expr)
        tpl = AGGREGATE_SQL.get(agg)
        if not tpl:
            raise ReportError("不支持的聚合函数：%s" % agg)
        return tpl % expr

    def _column_sql(self, col, force_null=False):
        if force_null:
            return "NULL"
        expr = _text(col.get("sourceExpression"))
        agg = _text(col.get("aggregateFunction") or "NONE").upper()
        return self._aggregate(self._translate(expr), agg)

    # ------------------------------------------------------------ 参数

    def _granularity_param(self):
        """表达式 DATE_TRUNC(x, <参数名>) 中的粒度参数名（无则 None）。"""
        exprs = [c.get("sourceExpression") for c in self.result_columns]
        exprs += list(self.rep.get("groupBy") or [])
        exprs += [o.get("expression") for o in (self.rep.get("orderBy") or [])]
        for expr in exprs:
            for m in _DATE_TRUNC_RE.finditer(_text(expr)):
                token = m.group(2)
                if token not in GRANULARITY:
                    return token
        return None

    def _raw_params(self):
        out = {}
        for name, spec in self.specs.items():
            values = _values(self.query.get(name))
            if not values:
                default = _resolve_default(spec.get("defaultValue"))
                values = [default] if default else []
            out[name] = values
        return out

    def _is_free_param(self, name):
        """未被任何条件/表达式引用的参数（候选：组开关参数、维度参数）。"""
        for cond in self.rep.get("conditions") or []:
            if cond.get("parameterRef") == name:
                return False
        exprs = [c.get("sourceExpression") for c in self.result_columns]
        exprs += list(self.rep.get("groupBy") or [])
        exprs += [o.get("expression") for o in (self.rep.get("orderBy") or [])]
        for so in self.rep.get("sourceObjects") or []:
            pre = so.get("preAggregation") or {}
            exprs += [c.get("sourceExpression") for c in (pre.get("columns") or [])]
        pattern = re.compile(r"\b%s\b" % re.escape(name))
        return not any(pattern.search(_text(e)) for e in exprs)

    def _groups(self):
        groups = {}
        for cond in self.rep.get("conditions") or []:
            groups.setdefault(cond.get("group") or "BASE", []).append(cond)
        return groups

    def _derive_trigger_kind(self, cond):
        """模型缺 triggerKind 时的派生（模型 v1.7 已显式给出，此处仅为兼容旧模型副本）：
        常量值为列引用 → OVERDOSE（超量比对），否则 → TOXIC（毒性分级限制）。"""
        fixed = _text(cond.get("fixedValue"))
        m = _REF_RE.match(fixed)
        if m and m.group(1) in self.aliases:
            return "OVERDOSE"
        return "TOXIC"

    def _trigger_kinds(self, group_name):
        kinds = []
        for cond in self._groups().get(group_name, []):
            kind = _text(cond.get("triggerKind")) or self._derive_trigger_kind(cond)
            if kind and kind not in kinds:
                kinds.append(kind)
        return kinds

    def _param_roles(self):
        """参数角色：组开关参数（非 BASE 条件组）/ 维度参数（取值＝可选维度别名）。"""
        roles = {}
        free = [n for n in self.specs if self._is_free_param(n)]
        for name in free:
            roles[name] = None
        for group_name in [g for g in self._groups() if g != "BASE"]:
            members = self._groups()[group_name]
            # 约定 13：条件可显式声明开关参数（switchParameterRef），显式优先于启发式推断
            refs = {_text(c.get("switchParameterRef")) for c in members if _text(c.get("switchParameterRef"))}
            if len(refs) == 1:
                ref = next(iter(refs))
                if ref not in self.specs:
                    raise ReportError("条件组 %s 的开关参数 %s 不在本报表参数中（约定 13）" % (group_name, ref))
                acts = [c.get("switchActivateValue") for c in members
                        if _text(c.get("switchParameterRef")) == ref and c.get("switchActivateValue") is not None]
                if acts:
                    roles[ref] = ("group_bool", group_name, acts[0])       # 布尔「相等即参与」
                else:
                    roles[ref] = ("group", group_name, [SWITCH_ALL] + self._trigger_kinds(group_name))
                continue
            allowed = [SWITCH_ALL] + self._trigger_kinds(group_name)
            found = None
            for name in free:
                if _resolve_default(self.specs[name].get("defaultValue")) in allowed:
                    found = name
                    break
            if not found:
                enum_free = [n for n in free
                             if _text(self.specs[n].get("dataType")) == "Enum" and roles.get(n) is None]
                if len(enum_free) == 1:
                    found = enum_free[0]
            if not found:
                # 非 BASE 可选组未声明开关参数：按「整组参与」处理（M7 v1.7 中仅批次 4 的
                # QR-HERB-STOCK-001 ALERT_FILTER 如此），并把该模型问题留给 validate_metadata 报出。
                roles[group_name] = ("group_always",)
            else:
                roles[found] = ("group", group_name, allowed)
        aliases = [c.upper() for c in self._dimension_candidates()]
        for name in free:
            if roles.get(name) is not None:
                continue
            if aliases and _resolve_default(self.specs[name].get("defaultValue")).upper() in aliases:
                roles[name] = ("dimension",)
        return roles

    def _finalize_params(self):
        out = {}
        for name, spec in self.specs.items():
            values = list(self.raw_params.get(name) or [])
            label = _text(spec.get("label")) or name
            dref = self._param_dict_ref(spec)
            if dref:
                values = [self._match_dict_code(v, dref, label) for v in values]
            elif _text(spec.get("dataType")) == "Date":
                values = [_norm_date(v, label) for v in values]
            if values:
                out[name] = values
        return out

    def _param_dict_ref(self, spec):
        for cond in self.rep.get("conditions") or []:
            if cond.get("parameterRef") == spec.get("name"):
                ref = self._attr_dict_ref(cond.get("leftExpression"))
                if ref:
                    return ref
        return self._attr_dict_ref(spec.get("sourceField"))

    def _attr_meta(self, alias, attr):
        entry = self.aliases.get(alias)
        if not entry:
            return None
        meta = entry.get("attr_meta", {}).get(attr)
        if meta:
            return meta
        source = entry.get("col_source", {}).get(attr)
        if source and source != attr:
            return entry.get("attr_meta", {}).get(source)
        return None

    def _attr_dict_ref(self, expr):
        m = _REF_RE.match(_text(expr))
        if not m:
            return None
        meta = self._attr_meta(m.group(1), m.group(2))
        ref = (meta or {}).get("dictionaryRef")
        if ref:
            return (_text(ref.get("dictionaryId")), _text(ref.get("typeCode")))
        return None

    def _match_dict_code(self, value, dref, label):
        codes = [i["code"] for i in get_dictionary_items(dref[0], dref[1])]
        if value in codes:
            return value
        raise ReportError("参数「%s」取值不在字典 %s.%s 范围内：%s" % (label, dref[0], dref[1], value))

    def _fk_target_ids(self, alias, attr, values):
        """引用型参数（AggregateRootRef）值解析：接受目标主键 id 或 M1 聚合业务编号。"""
        meta = self._attr_meta(alias, attr) or {}
        if _text(meta.get("type")) != "AggregateRootRef":
            return values
        target = registry["aggregates"].get(_text(meta.get("targetAggregate"))) or {}
        table = _snake(target.get("alias"))
        if table not in self.wl:
            return values
        code_attr = ""
        for a in target.get("attributes") or []:
            if _text(a.get("type")) == "String" and a.get("unique"):
                code_attr = a["name"]
                break
        if not code_attr:
            return values
        code_col = _snake(code_attr)
        marks = ", ".join("?" for _ in values)
        rows = db.query(
            "SELECT id, %s AS code FROM %s WHERE flag = 1 AND (CAST(id AS TEXT) IN (%s) OR %s IN (%s))"
            % (code_col, table, marks, code_col, marks),
            list(values) + list(values),
        )
        mapping = {}
        for row in rows:
            mapping[str(row["id"])] = row["id"]
            if row["code"] is not None:
                mapping[str(row["code"])] = row["id"]
        return [mapping.get(str(v), v) for v in values]

    def _resolve_granularity(self):
        name = self.granularity_param
        if not name:
            return GRANULARITY[0]
        value = _text((self.params.get(name) or [""])[0]) or GRANULARITY[0]
        value = value.upper()
        allowed = _enum_values(self.specs.get(name)) or list(GRANULARITY)
        if value not in allowed:
            raise ReportError("参数「%s」取值非法（可选 %s）：%s"
                              % (_text(self.specs.get(name, {}).get("label")) or name,
                                 "/".join(allowed), value))
        return value

    def _dimension_candidates(self):
        """可选维度别名：非主表别名，且存在「只引用自身」的非聚合结果列。"""
        cands = []
        for alias, entry in self.aliases.items():
            if entry["primary"] or entry["kind"] != "table":
                continue
            for col in self.result_columns:
                if _text(col.get("aggregateFunction") or "NONE").upper() != "NONE":
                    continue
                if self._expr_references(col.get("sourceExpression")) == {alias}:
                    cands.append(alias)
                    break
        return cands

    def _resolve_dimension(self):
        for name, role in self.roles.items():
            if not isinstance(role, tuple) or role[0] != "dimension":
                continue
            value = _text((self.params.get(name) or [""])[0]).upper()
            allowed = _enum_values(self.specs.get(name)) or [c.upper() for c in self.candidates]
            if value not in allowed:
                raise ReportError("参数「%s」取值非法（可选 %s）：%s"
                                  % (_text(self.specs[name].get("label")) or name,
                                     "/".join(allowed), value))
            target = self._dimension_alias(value)
            if target is None:
                raise ReportError("参数「%s」取值 %s 无法映射到维度别名（可选 %s）"
                                  % (_text(self.specs[name].get("label")) or name, value,
                                     "/".join(c.upper() for c in self.candidates)))
            return target
        return None

    def _dimension_alias(self, value):
        """维度取值 → 维度别名：先精确匹配别名，再按最长前缀匹配（M7 约定 11）。"""
        for cand in self.candidates:
            if cand.upper() == value:
                return cand
        best = None
        for cand in self.candidates:
            alias = cand.upper()
            if len(alias) >= 3 and value.startswith(alias):
                if best is None or len(alias) > len(best[1]):
                    best = (cand, alias)
        return best[0] if best else None

    def _resolve_trigger(self):
        for name, role in self.roles.items():
            if not isinstance(role, tuple) or role[0] != "group":
                continue
            allowed = role[2]
            value = _text((self.params.get(name) or [""])[0]) or SWITCH_ALL
            value = value.upper()
            allowed = _enum_values(self.specs.get(name)) or allowed
            if value not in allowed:
                raise ReportError("参数「%s」取值非法（可选 %s）：%s"
                                  % (_text(self.specs[name].get("label")) or name,
                                     "/".join(allowed), value))
            return value
        return SWITCH_ALL

    def _resolve_group_flags(self):
        """约定 13：布尔开关组的参与判定。值为 true → 参与；false → 整组跳过；未传 → 用参数 defaultValue。"""
        flags = {}
        for name, role in self.roles.items():
            if not isinstance(role, tuple) or role[0] != "group_bool":
                continue
            _role, group_name, activate = role
            spec = self.specs.get(name) or {}
            label = _text(spec.get("label")) or name
            raw = _text((self.raw_params.get(name) or [""])[0])
            parsed = _bool_value(raw, label)
            if parsed is None:                       # 未传 → 模型默认值
                default = _resolve_default(spec.get("defaultValue"))
                if isinstance(default, str):
                    default = _bool_value(default, label)
                parsed = bool(default) if default is not None else False
            flags[group_name] = (parsed == bool(activate))
        return flags

    # ------------------------------------------------------------ 维度/层级

    def _null_aliases(self):
        """当前维度下应置空的别名：其他可选维度 + 以其外键分组的预聚合别名。"""
        out = set()
        if not self.dimension:
            return out
        for cand in self.candidates:
            if cand != self.dimension:
                out.add(cand)
        for alias, entry in self.aliases.items():
            if entry["kind"] != "cte":
                continue
            for key in entry.get("cte_columns") or []:
                for cand in self.candidates:
                    if cand != self.dimension and _snake(key) == _snake(cand) + "_id":
                        out.add(alias)
        return out

    def _dimension_field_aliases(self):
        """reportOptions.groupFields 中引用的维度别名（M7 声明的维度分组字段，如 herb/formula）。"""
        names = set((self.rep.get("reportOptions") or {}).get("groupFields") or [])
        out = set()
        for col in self.result_columns:
            if _text(col.get("name")) in names:
                out |= self._expr_references(col.get("sourceExpression"))
        return out & set(self.candidates)

    def _column_nulled(self, col):
        """契约 §4.3：维度＝HERB 时方剂列置 null，维度＝FORMULA 时饮片列置 null。

        判定：列表达式引用了「非当前维度」的别名/其预聚合别名；或列名以该维度别名开头
        （M7 维度列命名约定，如 formulaRefCount/formulaRefRatio 只引用 prescription，
        但其归属维度由 reportOptions.groupFields 声明为 formula）。
        """
        if not self.dimension:
            return False
        nulls = self._null_aliases()
        if self._expr_references(col.get("sourceExpression")) & nulls:
            return True
        name = _text(col.get("name")).lower()
        field_aliases = self._dimension_field_aliases()
        for alias in sorted(nulls):
            if alias in field_aliases and name.startswith(alias.lower()):
                return True
        return False

    def _join_meta(self, join):
        """Join → (外键侧别名, 外键属性, 被引用别名)。模型条件写法可左右互换，此处归一。"""
        cond = _text(join.get("conditionExpression"))
        if "==" not in cond:
            raise ReportError("Join 条件表达式无法解析：%s" % cond)
        left, right = [p.strip() for p in cond.split("==", 1)]
        lm, rm = _REF_RE.match(left), _REF_RE.match(right)
        if not lm or not rm:
            raise ReportError("Join 条件表达式无法解析：%s" % cond)
        l_alias, l_attr = lm.group(1), lm.group(2)
        r_alias, r_attr = rm.group(1), rm.group(2)
        if l_attr == ROW_KEY and r_attr != ROW_KEY:
            l_alias, l_attr, r_alias = r_alias, r_attr, l_alias
        return l_alias, l_attr, r_alias

    def _level_map(self):
        """别名 → 实体层级：被连接表持外键且为普通表则 +1（明细），引用/预聚合不升级。"""
        joins = self.rep.get("joins") or []
        edges = []
        for join in joins:
            fk_alias, _fk_attr, _ref_alias = self._join_meta(join)
            left, right = join.get("leftSource"), join.get("rightSource")
            for alias in (left, right):
                if alias not in self.aliases:
                    raise ReportError("Join %s 引用了未知数据源 %s" % (join.get("joinId"), alias))
            step = 1 if (fk_alias == right and self.aliases[right]["kind"] == "table") else 0
            edges.append((left, right, step))
        levels = {self.primary: 0}
        for _ in range(len(self.aliases) + 1):
            changed = False
            for left, right, step in edges:
                if left in levels and levels.get(right) != levels[left] + step:
                    levels[right] = levels[left] + step
                    changed = True
                if right in levels and levels.get(left) != levels[right] - step:
                    levels[left] = levels[right] - step
                    changed = True
            if not changed:
                break
        return {a: levels.get(a, 0) for a in self.aliases}

    def _level_key_aliases(self):
        """每一层级的行键别名（主从报表用）：优先取明细链上的普通表别名。"""
        keys = []
        for level in sorted(set(self.levels.values())):
            choices = [a for a, lv in self.levels.items()
                       if lv == level and self.aliases[a]["kind"] == "table"]
            if not choices:
                return []
            chosen = None
            if level == 0:
                chosen = self.primary
            else:
                parents = [a for a, lv in self.levels.items() if lv == level - 1]
                for join in self.rep.get("joins") or []:
                    fk_alias, _fk_attr, _ref_alias = self._join_meta(join)
                    if fk_alias == join.get("rightSource") and fk_alias in choices \
                            and join.get("leftSource") in parents:
                        chosen = fk_alias
                        break
            keys.append(chosen or choices[0])
        return keys

    # ------------------------------------------------------------ 条件

    def _condition_sql(self, cond):
        op = _text(cond.get("operator")).upper()
        if op not in OPERATOR_SQL:
            raise ReportError("不支持的条件算子：%s" % op)
        left_expr = cond.get("leftExpression")
        lsql = self._translate(left_expr)
        pname = cond.get("parameterRef")
        cid = cond.get("conditionId") or ""
        if not pname:
            fixed = cond.get("fixedValue")
            if fixed in (None, ""):
                raise ReportError("报表条件 %s 既无参数也无常量值" % cid)
            return self._const_sql(cid, left_expr, lsql, op, fixed)
        spec = self.specs.get(pname) or {}
        label = _text(spec.get("label")) or pname
        values = list(self.params.get(pname) or [])
        if not values:
            if cond.get("skipWhenParameterEmpty"):
                return None
            raise ReportError("缺少必填查询参数：%s" % label)
        lm = _REF_RE.match(_text(left_expr))
        if lm and op in ("EQ", "IN"):
            values = self._fk_target_ids(lm.group(1), lm.group(2), values)
        if _text(spec.get("dataType")) == "Date" and op in DATE_OPERATORS:
            return self._date_condition(lsql, op, values)
        if op == "IN":
            self._params.extend(values)
            return "%s IN (%s)" % (lsql, ", ".join("?" for _ in values))
        if op == "LIKE":
            self._params.append("%%%s%%" % values[0])
            return "%s LIKE ?" % lsql
        if op == "BETWEEN":
            if len(values) < 2:
                raise ReportError("参数「%s」需要两个取值（起止）" % label)
            self._params.extend(values[:2])
            return "%s BETWEEN ? AND ?" % lsql
        self._params.append(values[0])
        return "%s %s ?" % (lsql, OPERATOR_SQL[op])

    def _date_condition(self, lsql, op, values):
        if op == "BETWEEN":
            if len(values) < 2:
                raise ReportError("日期区间参数需要两个取值（起止）")
            self._params.extend(values[:2])
            return "date(%s) BETWEEN date(?) AND date(?)" % lsql
        self._params.append(values[0])
        return "date(%s) %s date(?)" % (lsql, OPERATOR_SQL[op])

    def _const_sql(self, cid, left_expr, lsql, op, fixed):
        text = _text(fixed)
        m = _LIST_RE.match(text)
        if m:
            if op != "IN":
                raise ReportError("常量取值集合仅支持 IN 算子（条件 %s）" % cid)
            items = [p.strip().strip("'\"") for p in m.group(1).split(",") if p.strip()]
            if not items:
                raise ReportError("常量取值集合为空（条件 %s）" % cid)
            dref = self._attr_dict_ref(left_expr)
            if dref:
                label = _text(left_expr)
                items = [self._match_dict_code(v, dref, label) for v in items]
            self._params.extend(items)
            return "%s IN (%s)" % (lsql, ", ".join("?" for _ in items))
        ref = _REF_RE.match(text)
        if ref and ref.group(1) in self.aliases:
            return "%s %s %s" % (lsql, OPERATOR_SQL[op], self._translate(text))
        literal = text.strip("'\"")
        self._params.append(literal)
        return "%s %s ?" % (lsql, OPERATOR_SQL[op])

    def _active_group(self, group_name, items):
        if self.group_flags.get(group_name) is False:
            return []                            # 约定 13：布尔开关未开启 → 整组跳过（条件不参与 WHERE）
        kinds = self._trigger_kinds(group_name)
        if not kinds:
            return items                      # 无触发类型：常量条件组恒参与
        if self.trigger == SWITCH_ALL:
            return items
        active = [c for c in items
                  if (_text(c.get("triggerKind")) or self._derive_trigger_kind(c)).upper() == self.trigger]
        return active

    def _where_sql(self):
        clauses = ["(%s.flag = 1)" % self.primary]      # 主表 flag=1 写在 WHERE（契约 §3.3）
        for group_name, items in self._groups().items():
            active = items if group_name == "BASE" else self._active_group(group_name, items)
            pieces = []
            for cond in active:
                piece = self._condition_sql(cond)
                if piece is None:
                    continue
                if pieces:
                    pieces.append(_text(cond.get("logicalConnector") or "AND").upper())
                pieces.append("(%s)" % piece)
            if pieces:
                clauses.append("(%s)" % " ".join(pieces))
        return " AND ".join(clauses)          # 组间：AND（契约 §3.3 / M7 约定 6）

    # ------------------------------------------------------------ SQL 组装

    def _from_sql(self):
        parts = ["FROM %s AS %s" % (self.aliases[self.primary]["table"], self.primary)]
        for join in self.rep.get("joins") or []:
            joined = join.get("rightSource")
            entry = self.aliases[joined]
            fk_alias, fk_attr, ref_alias = self._join_meta(join)
            lsql = self._col_ref(fk_alias, fk_attr)
            if self.aliases[ref_alias]["kind"] == "cte":
                rsql = "%s.%s" % (ref_alias, self._cte_key_for(self.aliases[ref_alias], fk_alias))
            else:
                rsql = "%s.id" % ref_alias      # 契约 §3.2：被引用对象主键固定 id
            on = ["(%s = %s)" % (lsql, rsql)]
            if entry["kind"] == "cte":
                relation = joined                                  # 预聚合别名即 CTE 名
            else:
                relation = "%s AS %s" % (entry["table"], joined)
                on.append("(%s.flag = 1)" % joined)                # LEFT JOIN 的 flag 必须写在 ON 里
            parts.append("%s JOIN %s ON %s" % (
                _text(join.get("joinType") or "LEFT").upper(), relation, " AND ".join(on)))
        return " ".join(parts)

    def _cte_key_for(self, entry, other_alias):
        want = _snake(other_alias) + "_id"
        for key in entry.get("cte_columns") or []:
            if _snake(key) == want:
                return key
        keys = [k for k in entry.get("cte_columns") or []]
        if len(keys) == 1:
            return keys[0]
        raise ReportError("预聚合数据源 %s 无法确定与外键 %s 的关联列" % (entry["alias"], other_alias))

    def _group_sql(self):
        keys = list(self.rep.get("groupBy") or [])
        if not self.dimension:
            return [self._translate(k) for k in keys]
        chosen = [k for k in keys if self._expr_references(k) == {self.dimension}]
        for col in self.result_columns:
            if _text(col.get("aggregateFunction") or "NONE").upper() != "NONE":
                continue
            src = _text(col.get("sourceExpression"))
            if self._expr_references(src) == {self.dimension} and src not in chosen:
                chosen.append(src)
        if not chosen:
            raise ReportError("统计维度 %s 没有可用分组列" % self.dimension)
        return [self._translate(k) for k in chosen]

    def _order_sql(self, two_level):
        field = _text((self.query.get("sortField") or [""])[0])
        direction = _text((self.query.get("sortDir") or [""])[0]).upper()
        if direction and direction not in ("ASC", "DESC"):
            raise ReportError("排序方向非法：%s（可选 ASC/DESC）" % direction)
        items = []
        if field:
            if field not in self.col_names:
                raise ReportError("排序字段不可用：%s" % field)
            if not self.col_specs[field].get("sortable"):
                raise ReportError("排序字段不可用（不可排序）：%s" % field)
            items = [(field, direction or "ASC")]
        else:
            for order in self.rep.get("orderBy") or []:
                items.append((_text(order.get("expression")),
                              _text(order.get("direction") or "ASC").upper()))
        parts = []
        for expr, direction in items:
            if direction not in ("ASC", "DESC"):
                raise ReportError("排序方向非法：%s" % direction)
            if expr in self.col_names:
                sql = expr
            elif two_level:
                raise ReportError("排序表达式 %s 不能用于含 SUBTOTAL 的两段式查询" % expr)
            else:
                sql = self._translate(expr)
            parts.append("%s %s" % (sql, direction))
        return " ORDER BY " + ", ".join(parts) if parts else ""

    def _subtotal_columns(self):
        return [c for c in self.result_columns if "SUBTOTAL(" in _text(c.get("sourceExpression"))]

    def build_sql(self):
        """返回 (sql, params)。参数值全部以 ? 绑定，不拼接进 SQL。"""
        self._params = []
        where = self._where_sql()
        group_sql = self._group_sql()
        two_level = bool(self._subtotal_columns())
        with_sql = "WITH %s " % ", ".join(self.aliases[a]["cte_sql"] for a in self.ctes) if self.ctes else ""
        hidden = self._hidden_columns()
        if two_level:
            inner, outer = [], []
            for col in self.result_columns:
                name, expr = col["name"], _text(col.get("sourceExpression"))
                if "SUBTOTAL(" not in expr:
                    inner.append("%s AS %s" % (self._column_sql(col, self._column_nulled(col)), name))
                    outer.append(name)
                    continue
                if self._column_nulled(col):
                    # 维度置空列：整列 NULL（契约 §4.3），不参与窗口分母
                    inner.append("NULL AS %s" % name)
                    outer.append(name)
                    continue
                m = _SUBTOTAL_RE.match(expr)
                if not m:
                    raise ReportError("暂不支持的 SUBTOTAL 表达式：%s" % expr)
                inner.append("%s AS __num_%s" % (self._translate(m.group("num")), name))
                inner.append("%s AS __den_%s" % (self._translate(m.group("den")), name))
                outer.append("__num_%s * 1.0 / NULLIF(SUM(__den_%s) OVER (), 0) AS %s" % (name, name, name))
            inner_sql = "%sSELECT %s %s%s%s" % (
                "WITH %s " % ", ".join(self.aliases[a]["cte_sql"] for a in self.ctes) if self.ctes else "",
                ", ".join(inner), self._from_sql(),
                (" WHERE " + where) if where else "",
                (" GROUP BY " + ", ".join(group_sql)) if group_sql else "")
            sql = "SELECT %s FROM (%s) AS agg%s" % (", ".join(outer), inner_sql, self._order_sql(True))
            return sql, list(self._params)
        select_sql = ["%s AS %s" % (self._column_sql(col, self._column_nulled(col)), col["name"])
                      for col in self.result_columns]
        select_sql.extend(hidden)
        sql = "%sSELECT %s %s%s%s%s" % (
            with_sql, ", ".join(select_sql), self._from_sql(),
            (" WHERE " + where) if where else "",
            (" GROUP BY " + ", ".join(group_sql)) if group_sql else "",
            self._order_sql(False))
        return sql, list(self._params)

    def _hidden_columns(self):
        """主从报表：各层级行键与从表附加列（契约 §4.4）。"""
        if not self.master_detail:
            return []
        out = []
        for level, alias in enumerate(self.level_aliases):
            entry = self.aliases[alias]
            if entry["kind"] != "table":
                raise ReportError("主从报表的行键数据源必须是物理表：%s" % alias)
            out.append("%s.id AS %s%d" % (alias, LEVEL_PREFIX, level))
            if level:
                for attr in LEVEL_EXTRA_ATTRS:
                    if attr in entry["attrs"]:
                        out.append("%s.%s AS %s_%s" % (alias, _snake(attr), LEVEL_PREFIX, attr))
        return out

    # ------------------------------------------------------------ 结果组装

    def _column_meta(self):
        return [{
            "name": c["name"], "label": c.get("label"), "dataType": c.get("dataType"),
            "format": c.get("format"), "sortable": bool(c.get("sortable")),
            "visible": bool(c.get("visible", True)),
        } for c in self.result_columns]

    def _report_meta(self):
        return {"id": self.code, "name": self.rep.get("name"), "alias": self.rep.get("alias"),
                "objectType": self.rep.get("objectType"), "emptyValueDisplay": self.empty_display}

    def _master_detail_meta(self):
        if not self.master_detail:
            return None
        child_cols = self._level_columns(1)
        grand_cols = self._level_columns(2)
        return {
            "level": self.level_aliases[0].upper(),
            "childKey": CHILD_KEY,
            "childColumns": child_cols,
            "grandchildKey": GRANDCHILD_KEY,
            "grandchildColumns": grand_cols,
            "detailRowKey": ROW_KEY,
        }

    def _level_columns(self, level):
        return [c for c in self._column_meta() if self._column_level(c["name"]) == level]

    def _column_level(self, name):
        refs = self._expr_references(self.col_specs[name].get("sourceExpression"))
        if not refs:
            return 0
        return min(self.levels.get(a, 0) for a in refs)

    def _clean(self, row, hidden_keys):
        return {k: v for k, v in row.items() if k not in hidden_keys}

    def _master_rows(self, rows):
        """扁平结果 → 主从结构（主＝就诊，从＝处方，明细＝处方明细）。各层只携带本层列。"""
        keys = ["%s%d" % (LEVEL_PREFIX, i) for i in range(len(self.level_aliases))]
        level_names = {level: [c["name"] for c in self.result_columns
                               if self._column_level(c["name"]) == level]
                       for level in range(len(self.level_aliases))}
        extras = [k for k in (rows[0].keys() if rows else []) if k.startswith(LEVEL_PREFIX + "_")]
        masters, order = {}, []
        for row in rows:
            mkey = row[keys[0]]
            if mkey not in masters:
                masters[mkey] = {
                    "row": {n: row.get(n) for n in level_names.get(0, [])},
                    "children": {}, "child_order": [],
                }
                order.append(mkey)
            master = masters[mkey]
            ckey = row[keys[1]] if len(keys) > 1 else None
            if ckey is None:
                continue
            if ckey not in master["children"]:
                child_row = {n: row.get(n) for n in level_names.get(1, [])}
                child_row[ROW_KEY] = ckey          # 从行主键（处方 id），供前端 keyBy
                for extra in extras:
                    child_row[extra[len(LEVEL_PREFIX) + 1:]] = row.get(extra)
                master["children"][ckey] = {"row": child_row, "items": [], "seen": set()}
                master["child_order"].append(ckey)
            child = master["children"][ckey]
            if len(keys) > 2:
                gkey = row[keys[2]]
                if gkey is None:          # LEFT JOIN 未命中的明细行（如无药味的处方）不算明细
                    continue
                if gkey in child["seen"]:
                    continue
                child["seen"].add(gkey)
                item_row = {n: row.get(n) for n in level_names.get(2, [])}
                item_row[ROW_KEY] = gkey           # 明细行主键（处方明细 id）
                child["items"].append(item_row)
        out = []
        for mkey in order:
            master = masters[mkey]
            children = []
            for ckey in master["child_order"]:
                child = master["children"][ckey]
                child["row"]["items"] = child["items"]
                children.append(child["row"])
            record = dict(master["row"])
            record[ROW_KEY] = mkey
            record[CHILD_KEY] = children
            out.append(record)
        return out

    def _summary(self, rows):
        total_fields = list(self.options.get("totalFields") or [])
        if not total_fields:
            return None
        summary = {}
        for name in total_fields:
            value = 0
            for row in rows:
                item = row.get(name)
                if item is None:
                    continue
                value = value + item
            summary[name] = value
        return summary

    def _pagination(self):
        pagination = self.rep.get("pagination") or {}
        default_size = int(pagination.get("defaultPageSize") or 20)
        max_size = int(pagination.get("maxPageSize") or 100)
        raw_size = self.query.get("size")
        if raw_size:
            try:
                size = int(_values(raw_size)[0])
            except (IndexError, ValueError):
                raise ReportError("分页大小 size 必须为整数：%s" % _text(_values(raw_size)[0]))
            if size <= 0:
                raise ReportError("分页大小 size 必须为不小于 1 的整数：%s" % size, 400)
        else:
            size = default_size
        real_size = min(size, max_size)
        raw_page = self.query.get("page")
        if raw_page:
            try:
                page = int(_values(raw_page)[0])
            except (IndexError, ValueError):
                raise ReportError("页码 page 必须为整数：%s" % _text(_values(raw_page)[0]))
            if page <= 0:
                raise ReportError("页码 page 必须为不小于 1 的整数：%s" % page)
        else:
            page = 1
        return page, real_size

    def fetch(self):
        """执行查询，返回 (payload, 全量数据行)。"""
        sql, params = self.build_sql()
        rows = db.query(sql, params)
        hidden_keys = {k for k in (rows[0].keys() if rows else []) if k.startswith(LEVEL_PREFIX)}
        page, size = self._pagination()
        if self.master_detail:
            records = self._master_rows(rows)
            summary = self._summary(records)
        else:
            records = rows
            summary = self._summary(records)
        total = len(records)
        start = (page - 1) * size
        payload = {
            "report": self._report_meta(),
            "columns": self._column_meta(),
            "list": records[start:start + size],
            "total": total,
            "page": page,
            "size": size,
            "summary": summary,
            "masterDetail": self._master_detail_meta(),
        }
        return payload, records, hidden_keys

    def export_matrix(self):
        """导出矩阵：首行表头（列 label），随后数据行，末尾合计行（首列「合计」）。"""
        payload, records, hidden_keys = self.fetch()
        if not self.master_detail and len(records) > MAX_EXPORT_ROWS:
            raise ReportError("导出数据量过大（超过 %d 行），请缩小查询范围后重试" % MAX_EXPORT_ROWS)
        header = [c["label"] for c in self.result_columns]
        matrix = [header]
        names = [c["name"] for c in self.result_columns]

        def _cell(record, name):
            value = record.get(name)
            return self.empty_display if value is None or value == "" else value

        if self.master_detail:
            for master in records:
                children = master.get(CHILD_KEY) or []
                if not children:
                    matrix.append([_cell(master, n) for n in names])
                    continue
                for child in children:
                    items = child.get(GRANDCHILD_KEY) or []
                    merged = dict(master)
                    merged.update({k: v for k, v in child.items() if k != GRANDCHILD_KEY})
                    if not items:
                        matrix.append([_cell(merged, n) for n in names])
                        continue
                    for item in items:
                        flat = dict(merged)
                        flat.update({k: v for k, v in item.items() if k not in (CHILD_KEY,)})
                        matrix.append([_cell(flat, n) for n in names])
        else:
            for record in records:
                matrix.append([_cell(record, n) for n in names])

        # 主从报表按「展平后」的行数计上限（契约 §5：单次导出 ≤ 10000 行）
        if len(matrix) - 1 > MAX_EXPORT_ROWS:
            raise ReportError("导出数据量过大（超过 %d 行），请缩小查询范围后重试" % MAX_EXPORT_ROWS)
        summary = payload.get("summary")
        if summary is not None:
            row = ["合计"]
            for name in names[1:]:
                row.append(summary.get(name, ""))
            matrix.append(row)
        return matrix


# ---------------------------------------------------------------- 对外接口


def list_report(report_code, query=None):
    """GET /api/report/<reportCode>：分页查询。"""
    rep = get_report(report_code)
    engine = ReportQuery(rep, query)
    payload, _records, _hidden = engine.fetch()
    return payload


def export_report(report_code, query=None, fmt="xlsx"):
    """GET /api/report/<reportCode>/export：返回 (bytes, filename, mimetype)。"""
    fmt = _text(fmt).lower()
    if fmt not in MIME:
        raise ReportError("导出格式不支持：%s（可选 xlsx/csv）" % _text(fmt))
    rep = get_report(report_code)
    engine = ReportQuery(rep, query)
    matrix = engine.export_matrix()
    name = _text(rep.get("name")) or report_code
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
    filename = "%s_%s.%s" % (name, stamp, fmt)
    if fmt == "xlsx":
        return write_xlsx(matrix, name), filename, MIME["xlsx"]
    return write_csv(matrix), filename, MIME["csv"]


def compile_sql(report_code, query=None):
    """（自测/诊断用）编译报表查询 SQL，返回 (sql, params)。"""
    engine = ReportQuery(get_report(report_code), query)
    return engine.build_sql()


def validate_metadata(codes=None):
    """（自测用）逐报表校验模型元数据与物理结构/字典的一致性，返回问题清单（空＝全过）。

    codes：仅校验给定报表码（None＝全部 query_reports）。
    """
    ensure_ontology()
    problems = []
    wanted = set(codes) if codes else None
    for code, rep in registry["query_reports"].items():
        if wanted is not None and code not in wanted:
            continue
        try:
            engine = ReportQuery(rep, {})
        except ReportError as e:
            problems.append("%s：%s" % (code, e.message))
            continue
        for col in engine.result_columns:
            for m in _REF_RE.finditer(_text(col.get("sourceExpression"))):
                try:
                    engine._col_ref(m.group(1), m.group(2))
                except ReportError as e:
                    problems.append("%s 列 %s：%s" % (code, col["name"], e.message))
            # 枚举字面量只与「它紧邻的那个字典列」比对（表达式里可能同时出现多个字典列，
            # 例如有效率列：efficacyLevel IN (...) 与 recordStatus == COMPLETED）。
            expr = _text(col.get("sourceExpression"))
            for m in _REF_RE.finditer(expr):
                dref = engine._attr_dict_ref("%s.%s" % (m.group(1), m.group(2)))
                if not dref:
                    continue
                values = [i["code"] for i in get_dictionary_items(*dref)]
                tail = expr[m.end():]
                box = re.match(r"\s*IN\s*\(([^)]*)\)", tail)
                if box:
                    lits = [p.strip().strip("'\"") for p in box.group(1).split(",") if p.strip()]
                else:
                    cmp = re.match(r"\s*(?:==|!=|<>|>=|<=|>|<)\s*([A-Za-z_][A-Za-z0-9_]*)", tail)
                    lits = [cmp.group(1)] if cmp else []
                for literal in lits:
                    if _REF_RE.match(literal) or literal in values:
                        continue
                    problems.append("%s 列 %s：字面量 %s 不在字典 %s.%s 内（模型与字典不一致）"
                                    % (code, col["name"], literal, dref[0], dref[1]))
        # 约定 13：非 BASE 条件组必须显式声明机读开关（switchParameterRef），否则引擎只能按
        # 「整组恒参与」容错 → 开关参数被静默忽略（QR-HERB-STOCK-001 曾因此恒只返回预警项）。
        group_members = {}
        for cond in rep.get("conditions") or []:
            group_members.setdefault(_text(cond.get("group")) or "BASE", []).append(cond)
        param_names = {_text(pp.get("name")): pp for pp in (rep.get("parameters") or [])}
        for gname, members in group_members.items():
            if gname == "BASE":
                continue
            refs = {_text(c.get("switchParameterRef")) for c in members if _text(c.get("switchParameterRef"))}
            if len(refs) != 1:
                problems.append("%s 条件组 %s：未显式声明 switchParameterRef（约定 13）" % (code, gname))
                continue
            ref = next(iter(refs))
            spec = param_names.get(ref)
            if not spec:
                problems.append("%s 条件组 %s：开关参数 %s 不在报表 parameters 中" % (code, gname, ref))
            elif spec.get("required"):
                problems.append("%s 条件组 %s：开关参数 %s 为必填（约定 13 要求非必填）" % (code, gname, ref))
        for cond in rep.get("conditions") or []:
            left = _text(cond.get("leftExpression"))
            for m in _REF_RE.finditer(left):
                try:
                    engine._col_ref(m.group(1), m.group(2))
                except ReportError as e:
                    problems.append("%s 条件 %s：%s" % (code, cond.get("conditionId"), e.message))
            fixed = _text(cond.get("fixedValue"))
            box = _LIST_RE.match(fixed)
            if box:
                dref = engine._attr_dict_ref(left)
                for value in [p.strip() for p in box.group(1).split(",") if p.strip()]:
                    if dref and value not in [i["code"] for i in get_dictionary_items(*dref)]:
                        problems.append("%s 条件 %s：常量 %s 不在字典 %s.%s 内"
                                        % (code, cond.get("conditionId"), value, dref[0], dref[1]))
            if not cond.get("parameterRef") and not fixed:
                problems.append("%s 条件 %s：既无参数也无常量值" % (code, cond.get("conditionId")))
            if not cond.get("parameterRef") and fixed and not box:
                ref = _REF_RE.match(fixed)
                if ref and ref.group(1) not in engine.aliases:
                    problems.append("%s 条件 %s：常量列引用未知数据源 %s"
                                    % (code, cond.get("conditionId"), ref.group(1)))
        for join in rep.get("joins") or []:
            try:
                engine._join_meta(join)
            except ReportError as e:
                problems.append("%s Join %s：%s" % (code, join.get("joinId"), e.message))
            for side in (join.get("leftSource"), join.get("rightSource")):
                if side not in engine.aliases:
                    problems.append("%s Join %s：未知数据源 %s" % (code, join.get("joinId"), side))
        for order in rep.get("orderBy") or []:
            expr = _text(order.get("expression"))
            if expr in engine.col_names:
                continue
            for m in _REF_RE.finditer(expr):
                try:
                    engine._col_ref(m.group(1), m.group(2))
                except ReportError as e:
                    problems.append("%s 排序 %s：%s" % (code, expr, e.message))
        for key in rep.get("groupBy") or []:
            for m in _REF_RE.finditer(_text(key)):
                try:
                    engine._col_ref(m.group(1), m.group(2))
                except ReportError as e:
                    problems.append("%s 分组 %s：%s" % (code, key, e.message))
    return problems


def _attr_name_for(engine, alias, expr):
    for m in _REF_RE.finditer(_text(expr)):
        if m.group(1) == alias:
            return m.group(2)
    return ""
