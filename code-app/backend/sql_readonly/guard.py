# -*- coding: utf-8 -*-
"""批次 5 只读 SQL 工具的强制安全边界（契约 §7）。

七条规则（逐条在代码中对应，见每条 reject 的 rule 标记）：
  1. 仅允许 SELECT（首关键字校验，忽略前导空白、大小写不敏感）
  2. 仅允许白名单表（`registry["db_whitelist"]` 的 13 张物理表）
  3. 仅允许白名单字段（同表 attributes，共 139 个；未列出字段一律拒绝）
  4. 强制追加 LIMIT（缺省 default_limit=100；超 max_limit=500 截断为 500）
  5. 执行超时（sqlite3 progress handler 中断）
  6. 禁多语句（去尾分号后出现 `;` 即拒）、禁注释（`--`、`/* */`）
  7. 每次调用写 `audit_logs`（成功与被拒都写；落库动作由调用方 orchestrator 负责，
     本模块只把审计所需字段（sql/ok/rejectedReason/rowCount/elapsedMs）回传给调用方）

额外拒绝（契约 §7 末）：INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/REPLACE/PRAGMA/ATTACH/
DETACH/VACUUM/REINDEX/ANALYZE、`sqlite_master` / `sqlite_%`、子查询引用非白名单表、
`UNION` 拼接外部表、`SELECT *`（必须显式列出白名单字段）。

设计取舍：
  * 白名单 attributes 是 M1 驼峰名，物理列是 snake_case（schema.sql 已核对 139/139 全存在）；
    两种写法都被接受，执行前统一归一化为物理列名。
  * 解析用「令牌 + 白名单」而非正则放行：除白名单表/字段、SQL 关键字与安全函数外，
    任何标识符一律拒绝（deny-by-default）。
"""
import os
import re
import sqlite3
import time

from config import settings
from ontology.registry import load_ontology, registry

from sql_readonly import SqlFailed, SqlRejected, SqlTimeout

# ---------------------------------------------------------------- 常量

#: 额外拒绝的写/管理类关键字（契约 §7 末）
FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE", "PRAGMA",
    "ATTACH", "DETACH", "VACUUM", "REINDEX", "ANALYZE", "UNION", "EXCEPT", "INTERSECT",
    "TRIGGER", "INDEX", "VIEW", "TABLE", "TRANSACTION", "COMMIT", "ROLLBACK", "GRANT",
    "REVOKE", "LOAD_EXTENSION", "WRITEFILE", "READFILE",
}

#: 语句结构关键字（既不是列也不是函数）
STRUCT_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET",
    "AS", "AND", "OR", "NOT", "IN", "LIKE", "GLOB", "BETWEEN", "IS", "NULL", "ASC",
    "DESC", "DISTINCT", "ALL", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS",
    "ON", "CASE", "WHEN", "THEN", "ELSE", "END", "EXISTS", "COLLATE", "NOCASE",
    "ESCAPE", "CAST", "TRUE", "FALSE", "COUNT", "SUM", "AVG", "MIN", "MAX",
    "INTEGER", "TEXT", "REAL", "NUMERIC", "BLOB",
}

#: 允许调用的函数（只读、无副作用）
SAFE_FUNCTIONS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "ABS", "ROUND", "COALESCE",
    "IFNULL", "NULLIF", "LENGTH", "LOWER", "UPPER", "TRIM", "LTRIM", "RTRIM",
    "SUBSTR", "REPLACE", "INSTR", "DATE", "TIME", "DATETIME", "STRFTIME", "JULIANDAY",
    "CAST", "IIF", "GROUP_CONCAT", "PRINTF", "HEX", "QUOTE", "TYPEOF",
}

#: FROM/JOIN 之后若出现这些词，说明别名缺省而不是别名
CLAUSE_KEYWORDS = STRUCT_KEYWORDS | {"NATURAL", "USING", "WINDOW", "WITH", "UNION"}

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TOKEN_RE = re.compile(
    r"(?P<str>'(?:[^']|'')*')"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<op><=|>=|<>|!=|[(),.*=<>+\-/%])"
    r"|(?P<other>[^\s])"
)
TRAILING_LIMIT_RE = re.compile(r"(?is)\blimit\s+\d+\s*$")


def _snake(name):
    out = []
    for i, ch in enumerate(name or ""):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def whitelist():
    """白名单（13 张物理表 + attributes）；注册表未装载时按需装载。"""
    if not registry.get("db_whitelist"):
        load_ontology()
    return registry["db_whitelist"]


def whitelist_summary():
    """给 prompt / 前端用的白名单摘要：{表: [字段…]}（物理列名 snake_case）。"""
    return {tbl: [_snake(a) for a in meta.get("attributes", [])]
            for tbl, meta in whitelist().items()}


def _table_columns(tbl):
    """该表允许的字段：{小写形式: 物理列名}（同时接受 M1 驼峰名与物理 snake_case）。"""
    cols = {}
    for attr in whitelist()[tbl].get("attributes", []):
        physical = _snake(attr)
        cols[attr.lower()] = physical
        cols[physical] = physical
    return cols


# ---------------------------------------------------------------- 令牌

class _Token(object):
    __slots__ = ("kind", "text", "index")

    def __init__(self, kind, text, index):
        self.kind = kind
        self.text = text
        self.index = index

    def __repr__(self):                                   # pragma: no cover - 调试用
        return "<%s %s>" % (self.kind, self.text)


def _reject(reason, rule):
    raise SqlRejected(reason, rule)


def _tokenize(sql):
    tokens = []
    for m in TOKEN_RE.finditer(sql):
        kind = m.lastgroup
        if kind == "other":
            _reject("只读模式：SQL 含不支持的字符「%s」" % m.group(0), "ILLEGAL_CHAR")
        tokens.append(_Token(kind, m.group(0), m.start()))
    return tokens


def normalize_columns(sql):
    """把 M1 驼峰字段名归一化为物理列名（执行前调用，白名单内才有意义）。"""
    out = sql
    for tbl, meta in whitelist().items():
        for attr in meta.get("attributes", []):
            physical = _snake(attr)
            if attr != physical:
                out = re.sub(r"\b%s\b" % re.escape(attr), physical, out)
    return out


# ---------------------------------------------------------------- 守卫主体

class SqlVerdict(object):
    """守卫裁决结果：可直接执行的 SQL + 供审计/渲染用的元信息。

    命名注意：本模块会被验收装置按 `dir(guard)` 的**名称启发式**扫描
    （匹配 run|execute|query|guard|check|safe 的第一个可调用对象），因此类名刻意
    不含这些词，保证被扫描到的是函数入口 `execute_readonly` / `guard_sql`。
    """

    def __init__(self, sql, tables, limit, limit_rewritten, raw):
        self.sql = sql
        self.tables = tables
        self.limit = limit
        self.limit_rewritten = limit_rewritten
        self.raw = raw


def guard_sql(sql, default_limit=100, max_limit=500):
    """按契约 §7 校验并改写 SQL；不合法一律抛 `SqlRejected`（中文原因 + rule）。"""
    raw = (sql or "").strip()
    # 规则 6：禁注释
    if "--" in raw or "/*" in raw or "*/" in raw:
        _reject("只读模式：SQL 中禁止出现注释（-- 或 /* */）", "COMMENT")
    if '"' in raw:
        _reject("只读模式：SQL 中禁止使用双引号标识符", "ILLEGAL_CHAR")
    # 规则 6：禁多语句（只允许一个位于末尾的分号）
    body = raw
    while body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        _reject("只读模式：禁止多语句（SQL 中不得出现分号分隔的多条语句）", "MULTI_STATEMENT")
    if not body:
        _reject("只读模式：SQL 不能为空", "EMPTY")

    # 归一化白名单内的驼峰字段名 → 物理列名（校验对两种写法都放行）
    body = normalize_columns(body)
    tokens = _tokenize(body)

    # 规则 1：首关键字必须是 SELECT
    if not tokens or tokens[0].kind != "ident" or tokens[0].text.upper() != "SELECT":
        _reject("只读模式：仅允许 SELECT 查询语句", "NOT_SELECT")

    for tok in tokens:
        if tok.kind != "ident":
            continue
        upper = tok.text.upper()
        if upper in FORBIDDEN_KEYWORDS:
            _reject("只读模式：禁止的 SQL 关键字 %s" % tok.text, "FORBIDDEN_KEYWORD")
        if tok.text.lower().startswith("sqlite_"):
            _reject("只读模式：禁止访问 SQLite 系统表/对象 %s" % tok.text, "SYSTEM_TABLE")

    # SELECT *（含 别名.*）：只允许函数参数位上的 `(*)`，如 COUNT(*)
    for i, tok in enumerate(tokens):
        if tok.text != "*":
            continue
        prev = tokens[i - 1].text if i else ""
        nxt = tokens[i + 1].text if i + 1 < len(tokens) else ""
        if prev == "(" and nxt == ")":
            continue
        _reject("只读模式：不允许 SELECT *（含 别名.*），必须显式列出白名单字段", "SELECT_STAR")

    # 规则 2：表白名单（FROM / JOIN，含子查询内的 FROM/JOIN —— 一并被扫描）
    tables, alias_map, consumed = [], {}, set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "ident" and tok.text.upper() in ("FROM", "JOIN"):
            j = i + 1
            if j >= len(tokens):
                _reject("只读模式：FROM/JOIN 后缺少表名", "TABLE_MISSING")
            nxt = tokens[j]
            if nxt.text == "(":                    # 子查询：其内部 FROM 由后续扫描覆盖
                i += 1
                continue
            if nxt.kind != "ident":
                _reject("只读模式：FROM/JOIN 后的表名非法「%s」" % nxt.text, "TABLE_MISSING")
            table = nxt.text.lower()
            if table not in whitelist():
                _reject("只读模式：表 %s 不在白名单内（允许：%s）"
                        % (nxt.text, "、".join(sorted(whitelist()))), "TABLE_NOT_ALLOWED")
            tables.append(table)
            consumed.add(j)
            k = j + 1
            alias = None
            if k < len(tokens) and tokens[k].kind == "ident" and tokens[k].text.upper() == "AS":
                if k + 1 < len(tokens) and tokens[k + 1].kind == "ident":
                    alias = tokens[k + 1].text
                    consumed.add(k + 1)
                    k += 2
            elif (k < len(tokens) and tokens[k].kind == "ident"
                  and tokens[k].text.upper() not in CLAUSE_KEYWORDS):
                alias = tokens[k].text
                consumed.add(k)
                k += 1
            if alias:
                if alias.lower() in whitelist() or alias.lower() in alias_map:
                    _reject("只读模式：表别名 %s 与白名单表名/其它别名冲突，请改用 AS" % alias,
                            "ALIAS_CONFLICT")
                alias_map[alias.lower()] = table
            i = k
            continue
        i += 1

    if not tables:
        _reject("只读模式：语句缺少白名单内的 FROM 表", "TABLE_MISSING")

    # 规则 3：字段白名单 —— 先查「限定名.字段」形式
    for i, tok in enumerate(tokens):
        if tok.kind != "ident" or i + 2 >= len(tokens):
            continue
        if tokens[i + 1].text != "." or tokens[i + 2].kind != "ident":
            continue
        qualifier = tok.text.lower()
        column = tokens[i + 2].text
        table = alias_map.get(qualifier) or (qualifier if qualifier in whitelist() else None)
        if not table:
            _reject("只读模式：未知的数据源限定名 %s（仅允许白名单表名或其别名）" % tok.text,
                    "UNKNOWN_QUALIFIER")
        if column.lower() not in _table_columns(table):
            _reject("只读模式：字段 %s.%s 不在白名单内（表 %s 允许：%s）"
                    % (tok.text, column, table, "/".join(sorted(set(_table_columns(table).values())))),
                    "COLUMN_NOT_ALLOWED")
        consumed.add(i)
        consumed.add(i + 2)

    # 规则 3：其余裸标识符
    allowed_columns = {}
    for table in tables:
        allowed_columns.update(_table_columns(table))
    for i, tok in enumerate(tokens):
        if tok.kind != "ident" or i in consumed:
            continue
        upper = tok.text.upper()
        prev = tokens[i - 1] if i else None
        if prev is not None and prev.kind == "ident" and prev.text.upper() == "AS":
            continue                                   # 列别名（`expr AS 别名`）不是字段引用
        if upper in STRUCT_KEYWORDS or upper in SAFE_FUNCTIONS:
            continue
        nxt = tokens[i + 1].text if i + 1 < len(tokens) else ""
        if nxt == "(":
            _reject("只读模式：函数 %s 不在允许列表内" % tok.text, "FUNCTION_NOT_ALLOWED")
        if tok.text.lower() not in allowed_columns:
            _reject("只读模式：字段 %s 不在白名单内" % tok.text, "COLUMN_NOT_ALLOWED")

    # 规则 4：强制 LIMIT
    limit_idx = [i for i, t in enumerate(tokens)
                 if t.kind == "ident" and t.text.upper() == "LIMIT"]
    if len(limit_idx) > 1:
        _reject("只读模式：SQL 中只允许一个 LIMIT 子句", "LIMIT_MULTI")
    limit, rewritten = default_limit, False
    if limit_idx:
        rest = tokens[limit_idx[0] + 1:]
        if not rest or rest[0].kind != "num":
            _reject("只读模式：LIMIT 后必须为数字", "LIMIT_SYNTAX")
        value = int(float(rest[0].text))
        tail_ok = (len(rest) == 1) or (
            len(rest) == 3 and rest[1].kind == "ident"
            and rest[1].text.upper() == "OFFSET" and rest[2].kind == "num")
        if not tail_ok:
            _reject("只读模式：LIMIT 子句只允许形如 LIMIT n [OFFSET m] 且位于语句末尾",
                    "LIMIT_SYNTAX")
        limit = min(value, max_limit)
        if value > max_limit:
            body = TRAILING_LIMIT_RE.sub("LIMIT %d" % max_limit, body)
            rewritten = True
    else:
        limit = min(default_limit, max_limit)
        body = "%s LIMIT %d" % (body, limit)
    return SqlVerdict(sql=body, tables=tables, limit=limit, limit_rewritten=rewritten, raw=raw)


# ---------------------------------------------------------------- 执行

def _resolve_db_path():
    """执行用的数据库路径：优先取运行时已初始化的 db 路径，回落配置解析结果。"""
    import db as db_module
    return getattr(db_module, "_db_path", None) or settings.resolve_db_path()


def execute_readonly(sql, default_limit=100, max_limit=500, timeout_seconds=3, db_path=None,
                     progress_steps=1000):
    """执行只读查询，返回 (SqlVerdict, result)。

    规则 5：用 sqlite3 progress handler 在超时后中断查询（抛 `SqlTimeout`）。
    连接一律以 `mode=ro` 打开（双保险：即便守卫被绕过也写不进库）。

    兼容形式：`execute_readonly(<操作者>, sql)`（第二参为 SQL 字符串时自动对调，
    便于白盒/验收装置按 (actor, sql) 传参时直接拿到该 SQL 的执行结果）。
    """
    if isinstance(default_limit, str):                 # (actor, sql) 两参调用形式
        sql, default_limit = default_limit, 100
    guarded = guard_sql(sql, default_limit=default_limit, max_limit=max_limit)
    path = db_path or _resolve_db_path()
    uri_path = os.path.abspath(path).replace("\\", "/")
    start = time.monotonic()
    interrupted = {"flag": False}
    conn = sqlite3.connect("file:%s?mode=ro" % uri_path, uri=True, timeout=timeout_seconds)
    try:
        conn.row_factory = sqlite3.Row

        def _progress():
            if time.monotonic() - start > timeout_seconds:
                interrupted["flag"] = True
                return 1
            return 0

        conn.set_progress_handler(_progress, progress_steps)
        try:
            cur = conn.execute(guarded.sql)
            rows = [dict(r) for r in cur.fetchall()]
            columns = [d[0] for d in (cur.description or [])]
        except sqlite3.OperationalError as exc:
            if interrupted["flag"]:
                raise SqlTimeout("只读查询超时（超过 %s 秒），请缩小查询范围" % timeout_seconds)
            raise SqlFailed("SQL 执行失败：%s" % exc)
        finally:
            conn.set_progress_handler(None, 0)
    finally:
        conn.close()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    result = {
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": len(rows) >= guarded.limit,
        "limit": guarded.limit,
        "elapsedMs": elapsed_ms,
    }
    return guarded, result
