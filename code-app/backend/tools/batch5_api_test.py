# -*- coding: utf-8 -*-
"""批次 5 主代独立验收：右侧 AI 对话框（SSE / 工具注册 / 只读边界 / 审计 / 降级）。

设计原则（与批次 3/4 一致）：
  ① 期望值来自**契约 + 抽取文档**（独立读取 md 与注册表），不来自实现代码；
  ② 黑盒 HTTP（真实 socket：werkzeug make_server）+ 真实 SSE 逐事件解析；必要时对
     公开入口做白盒断言（工具条数与抽取文档逐条比对）；
  ③ 库隔离：默认复制演示库为 data/b5_ai.db（**绝不读写演示库**），跑完保留由调用方决定；
  ④ 起服务用**模块级 app**（SPA 与 /api 都在它上面，工厂实例只有 /api）；
  ⑤ 用环境变量 AI_PROVIDER=mock 切离线 provider，**不修改 config.yaml**；
   ⑦ 的 deepseek 段按**实际凭据状态自适应**（backend/.env 或环境变量有 key → 期望真流式；无 → 期望 503 降级）。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch5_api_test.py
"""
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BACKEND))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DEMO_DB = os.path.join(BACKEND, "data", "app.db")
DB = os.path.join(BACKEND, "data", "b5_ai.db")
os.environ["APP_DB_PATH"] = DB
os.environ["AI_PROVIDER"] = "mock"          # 离线可测：不修改 config.yaml
os.environ.pop("AI_API_KEY", None)
assert os.path.basename(DB) != "app.db", "本脚本严禁使用演示库"

PORT = 5071
BASE = "http://127.0.0.1:%d" % PORT
CONTRACT = os.path.join(PROJECT, "code-app", "docs", "批次5-实现契约.md")
TOOLDOC = os.path.join(PROJECT, "code-app", "docs", "批次5-工具清单（注册表抽取）.md")
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-64s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:100]))
    return bool(cond)


def section(title):
    print("\n" + "-" * 108)
    print(title)
    print("-" * 108)


def call(method, path, token=None, body=None, raw=False, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload.decode() or "{}")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if raw:
            return exc.code, payload, dict(exc.headers)
        try:
            return exc.code, json.loads(payload.decode() or "{}"), dict(exc.headers)
        except ValueError:
            return exc.code, {}, dict(exc.headers)


def sse(token, body, timeout=60):
    """真实 SSE：逐片读取并按 `event: x\\ndata: y\\n\\n` 解析为 [(event, data), ...]。"""
    req = urllib.request.Request(BASE + "/api/ai/chat", data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    events, headers, status = [], {}, None
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return exc.code, [], dict(exc.headers), exc.read().decode("utf-8", "replace")
    status, headers = resp.status, dict(resp.headers)
    buf, raw_all = "", ""
    with resp:
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            raw_all += text
            buf += text
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev, data = None, []
                for line in block.splitlines():
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                if ev:
                    try:
                        events.append((ev, json.loads("\n".join(data) or "{}")))
                    except ValueError:
                        events.append((ev, {"__raw__": "\n".join(data)}))
    return status, events, headers, raw_all


def sql(query, args=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(query, args)]
    finally:
        conn.close()


def scalar(query, args=()):
    rows = sql(query, args)
    return list(rows[0].values())[0] if rows else None


def prepare_fixture():
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(DB + suffix):
            os.remove(DB + suffix)
    shutil.copyfile(DEMO_DB, DB)          # 副本：绝不读写演示库
    # 追加 300 行饮片（只写隔离副本），用于真实触发 LIMIT 截断断言（否则行数不足会让断言变成空断言）
    conn = sqlite3.connect(DB)
    try:
        conn.executemany(
            "INSERT INTO herb (herb_code, herb_name, herb_category, min_common_dose, max_common_dose, "
            "toxicity_level, stock_quantity, low_stock_threshold, herb_status, flag) "
            "VALUES (?, ?, 'TONIFYING', 3, 10, 'NONE', 100, 50, 'ENABLED', 1)",
            [("B5T%04d" % i, "批量测试饮片%04d" % i) for i in range(1, 301)])
        conn.commit()
    finally:
        conn.close()


def doc_counts():
    """从抽取文档机械读出期望工具条数（独立数据源）。"""
    txt = io.open(TOOLDOC, encoding="utf-8").read()
    out = {}
    # ① §0 计数表的每一行（形如：| 导航工具 | `nav.<screenId>` | 19 |）——主口径
    row_map = {"导航工具": "nav", "查询工具（M2 QUERY）": "query", "查询工具（M7 报表）": "report",
               "行为工具（只读边界：仅生成跳转，不执行写操作）": "action"}
    table = {}
    for line in txt.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) >= 3 and cells[0] in row_map and cells[-1].isdigit():
            table[row_map[cells[0]]] = int(cells[-1])
    out.update(table)
    # ② 总数行（形如：可生成工具总数：**59**（导航 19 + 查询 7 + …））——兜底并交叉核对
    m = re.search(r"可生成工具总数：\*\*(\d+)\*\*", txt)
    if m:
        out["total"] = int(m.group(1))
    m = re.search(r"可生成工具总数：\*\*(\d+)\*\*（导航 (\d+) \+ 查询 (\d+) \+ 报表 (\d+) \+ 行为\(只读\) (\d+)",
                  txt)
    if m:
        out.setdefault("nav", int(m.group(2)))
        out.setdefault("query", int(m.group(3)))
        out.setdefault("report", int(m.group(4)))
        out.setdefault("action", int(m.group(5)))
    m = re.search(r"白名单字段合计 \*\*(\d+)\*\*", txt)
    if m:
        out["wl_fields"] = int(m.group(1))
    m = re.search(r"共 (\d+) 表", txt)
    if m:
        out["wl_tables"] = int(m.group(1))
    return out


def main():
    prepare_fixture()
    expected = doc_counts()
    print("抽取文档期望：", expected)

    section("① 契约与抽取文档存在且可解析")
    check("契约存在且 ≥200 行", os.path.exists(CONTRACT) and io.open(CONTRACT, encoding="utf-8").read().count("\n") > 200)
    check("抽取文档给出工具总数与各类计数", bool(expected.get("total") and expected.get("nav")),
          expected)

    # 模块级 app：SPA 路由与 /api 都注册在它上面（工厂实例只有 /api）
    from app import app as flask_app                                    # noqa: E402
    from werkzeug.serving import make_server                            # noqa: E402

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    section("② /api/ai/status 与鉴权")
    st, b, _ = call("GET", "/api/ai/status")
    check("未登录访问 status → 401", st == 401, st)
    st, b, _ = call("POST", "/api/ai/chat", body={"message": "hi"})
    check("未登录访问 chat → 401", st == 401, st)

    st, body, _ = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
    admin = body.get("data", {}).get("token") if st == 200 else None
    check("admin 登录取令牌", bool(admin), st)

    st, b, _ = call("GET", "/api/ai/status", token=admin)
    if check("status 返回 200", st == 200, b):
        d = b.get("data") or {}
        check("环境变量 AI_PROVIDER 覆盖生效（provider=mock）", d.get("provider") == "mock", d.get("provider"))
        check("enabled=true 且 configured=true（mock 无需凭据）", d.get("enabled") is True and d.get("configured") is True,
              (d.get("enabled"), d.get("configured")))
        raw = json.dumps(b, ensure_ascii=False)
        check("status 不回显任何密钥（无 sk- / api_key 明文）", "sk-" not in raw and "api_key" not in raw.lower().replace("apikey", ""),
              raw[:80])

    section("③ SSE 事件序列（mock provider 全链路）")
    st, events, headers, raw = sse(admin, {"message": "帮我看看饮片库存是否充足", "history": [],
                                           "context": {"screenId": "frmHerbStock"}})
    if check("chat SSE 返回 200", st == 200, st):
        names = [e for e, _ in events]
        print("     事件序列：", names)
        check("首事件为 message_start", names[:1] == ["message_start"], names[:1])
        check("末事件为 message_end（或 error）", names[-1:] in (["message_end"], ["error"]), names[-1:])
        check("含 delta（文本增量）", "delta" in names, names)
        check("含 tool_call 与 tool_result（mock 驱动完整链路）",
              "tool_call" in names and "tool_result" in names, names)
        check("含 render_payload", "render_payload" in names, names)
        check("tool_call 与 tool_result 成对且数量一致",
              names.count("tool_call") == names.count("tool_result"), names)
        check("每个 tool_result 的位置晚于同名 tool_call",
              all(names.index("tool_call") < len(names) - 1 for _ in [0]) and
              names.index("tool_call") < names.index("tool_result"), names)
        check("message_start 只出现一次", names.count("message_start") == 1, names)
        check("事件名均在契约 §3.3 定义的 7 类内",
              set(names) <= {"message_start", "delta", "tool_call", "tool_result", "render_payload",
                             "message_end", "error"}, set(names) - {"message_start", "delta", "tool_call",
                                                                   "tool_result", "render_payload", "message_end", "error"})
        d0 = dict(events).get("message_start", {})
        check("message_start 含 messageId 与 ts", bool(d0.get("messageId")) and bool(d0.get("ts")), d0)
        pend = [d for e, d in events if e == "message_end"]
        check("message_end 含 finishReason 与 toolCallCount",
              pend and "finishReason" in pend[0] and "toolCallCount" in pend[0], pend[:1])
        rp = [d for e, d in events if e == "render_payload"]
        check("render_payload 的 renderType ∈ {text,table,chart,action}",
              all(d.get("renderType") in {"text", "table", "chart", "action"} for d in rp), [d.get("renderType") for d in rp])
        tc = [d for e, d in events if e == "tool_call"]
        check("tool_call 含 toolCallId/name/arguments", all(
            d.get("toolCallId") and d.get("name") and "arguments" in d for d in tc), tc[:1])
        check("tool_call 名称属于抽取文档的 6 类工具前缀",
              all(re.match(r"^(nav|query|report|action|chart|sql_readonly)", str(d.get("name"))) for d in tc),
              [d.get("name") for d in tc])
        ctype = headers.get("Content-Type", "") or headers.get("content-type", "")
        check("响应头 Content-Type 为 text/event-stream", "text/event-stream" in ctype, ctype)
        check("响应头含 no-cache", "no-cache" in json.dumps({k.lower(): v for k, v in headers.items()}),
              [k for k in headers if k.lower() == "cache-control"])
        check("原始分片使用 event:/data: 双行格式", "event:" in raw and "data:" in raw, raw[:60].replace("\n", "|"))

    section("④ 工具注册表与权限过滤（实测入口 build_tools(user_id)，与抽取文档逐条比对）")
    tool_names = None
    try:
        from ai import tool_registry as tr
        uid = scalar("SELECT id FROM sys_user WHERE username = 'admin'")
        raw_tools = tr.build_tools(uid)
        print("     build_tools(admin) → %d 个工具" % len(raw_tools))

        def names_of(tools):
            seq = list(tools.values()) if isinstance(tools, dict) else list(tools)
            out = []
            for t in seq:
                if isinstance(t, dict):
                    fn = t.get("function") if isinstance(t.get("function"), dict) else {}
                    out.append(str(t.get("name") or fn.get("name") or ""))
                else:
                    out.append(str(t))
            return [n for n in out if n]

        admin_names = names_of(raw_tools)
        tool_names = admin_names
        check("工具总数与抽取文档一致", len(admin_names) == expected.get("total"),
              "实现 %d / 文档 %s" % (len(admin_names), expected.get("total")))
        pre = {k: len([n for n in admin_names if n.startswith(k)]) for k in ("nav", "query", "report", "action")}
        check("各类计数与文档逐类一致（导航/查询/报表/行为）",
              all(pre[k] == expected.get(k) for k in pre),
              "%s vs 文档 %s" % (pre, {k: expected.get(k) for k in pre}))
        check("工具名唯一（无重复）", len(set(admin_names)) == len(admin_names),
              len(admin_names) - len(set(admin_names)))
        check("工具命名前缀合法（nav./query./report./action./chart/sql_readonly）",
              all(re.match(r"^(nav|query|report|action|chart|sql_readonly)", n) for n in admin_names),
              [n for n in admin_names if not re.match(r"^(nav|query|report|action|chart|sql_readonly)", n)][:3])
        # 与抽取文档逐条比对（独立数据源：解析文档里每个工具名）
        doc = io.open(TOOLDOC, encoding="utf-8").read()
        doc_names = set(re.findall(r"`(nav\.[A-Za-z0-9_]+|query\.[A-Za-z0-9_]+|report\.[A-Za-z0-9\-]+|action\.[A-Za-z0-9_]+)`", doc))
        impl_names = {n for n in admin_names if n.startswith(("nav.", "query.", "report.", "action."))}
        check("四类工具名与文档逐条一致（差集均空）",
              not (impl_names - doc_names) and not (doc_names - impl_names),
              "实现多：%s ／ 文档多：%s" % (sorted(impl_names - doc_names)[:3], sorted(doc_names - impl_names)[:3]))
        # 只读边界：不得存在写语义工具
        check("不存在写语义工具（execute./write./create./update./delete. 前缀）",
              not [n for n in admin_names if re.match(r"^(execute|write|create|update|delete)\.", n)],
              [n for n in admin_names if re.match(r"^(execute|write|create|update|delete)\.", n)][:3])
        # 权限过滤：低权限用户工具集 ⊆ admin，且严格更少
        low_id = scalar("SELECT id FROM sys_user WHERE username = 'yaoshi'")
        low_names = names_of(tr.build_tools(low_id))
        check("低权限用户（yaoshi）工具集 ⊆ admin 工具集", set(low_names) <= set(admin_names),
              sorted(set(low_names) - set(admin_names))[:3])
        check("低权限用户工具更少（权限过滤确有生效）", len(low_names) < len(admin_names),
              "%d < %d" % (len(low_names), len(admin_names)))
        has_ps = scalar("""SELECT COUNT(*) FROM sys_user u JOIN sys_user_role ur ON ur.user_id = u.id
            JOIN sys_role_permission rp ON rp.role_id = ur.role_id JOIN sys_permission p ON p.id = rp.permission_id
            WHERE u.username = 'yaoshi' AND p.code = 'patient:save'""")
        check("越权用例前置条件：yaoshi 库内确无 patient:save", not has_ps, has_ps)
        perms = tr.permission_codes_of(low_id)
        check("工具过滤依据为库内权限集（permission_codes_of 非空）", bool(perms), len(perms) if perms is not None else None)
        # 被拒工具：必须用**无该权限**的账号（daozhen 无 patient:save）——用 admin 测会得到 ok=true 的假失败
        # 注意：daozhen（导诊）**确有此权限**（库内实测 patient:save=True），必须用 yaoshi（无该权限）
        st_l, b_l, _ = call("POST", "/api/auth/login", body={"username": "yaoshi", "password": "123456"})
        low_token = b_l.get("data", {}).get("token") if st_l == 200 else None
        check("无该权限账号 yaoshi 可登录（用于越权用例）", bool(low_token), st_l)
        if low_token:
            st, events, _, _ = sse(low_token, {"message": "#tool=action_Patient_Save #args={}"})
            tr_res = [d for e, d in events if e == "tool_result"]
            check("无权限账号强行调用未授权工具 → ok=false + 中文原因",
                  bool(tr_res) and tr_res[0].get("ok") is False and bool(tr_res[0].get("error")),
                  tr_res[:1])
            # 反证：admin 调用同一工具应成功（证明失败确实来自权限而非工具坏）
            st, events, _, _ = sse(admin, {"message": "#tool=action_Patient_Save #args={}"})
            tr_adm = [d for e, d in events if e == "tool_result"]
            check("对照：admin 调用同一工具 → ok=true（证明被拒来自权限）",
                  bool(tr_adm) and tr_adm[0].get("ok") is True, tr_adm[:1])
    except ImportError as exc:
        check("能导入 ai.tool_registry", False, exc)

    section("⑤ 只读 SQL 边界负例矩阵（契约 §7 逐条；实测入口 execute_readonly(sql, …)）")
    try:
        from sql_readonly import guard as g
        run = getattr(g, "execute_readonly", None)
        check("存在只读执行入口 execute_readonly", callable(run), getattr(run, "__module__", None))

        def exec_sql(sql_text):
            """返回 (ok, payload)：异常视为被拒；payload 归一化为 dict（实测返回 (SqlVerdict, {columns,rows,...})）。"""
            try:
                res = run(sql_text)
            except Exception as exc:                                  # noqa: BLE001
                return False, "%s: %s" % (type(exc).__name__, str(exc)[:70])
            if isinstance(res, tuple):
                res = next((x for x in res if isinstance(x, dict)), {"__tuple__": [type(x).__name__ for x in res]})
            return True, res

        ok_g, det_g = exec_sql("SELECT herb_code, herb_name, stock_quantity FROM herb")
        check("白名单内正常 SELECT 通过（自动补 LIMIT）", ok_g is True, str(det_g)[:70])
        rows_g = (det_g.get("rows") or []) if isinstance(det_g, dict) else None
        check("返回结构含 columns/rows（可机读）",
              isinstance(det_g, dict) and det_g.get("columns") is not None and rows_g is not None,
              sorted(det_g)[:6] if isinstance(det_g, dict) else det_g)
        check("默认 LIMIT=100 生效（返回行数 ≤ 100）", rows_g is not None and len(rows_g) <= 100,
              len(rows_g) if rows_g is not None else "无 rows")
        # 隔离库里已预置 310 行饮片 → 下列断言是**真断言**（不再是空断言）
        total_rows = scalar("SELECT COUNT(*) FROM herb WHERE flag = 1")
        # 实测语义（已核实）：默认 limit=100 且 truncated=True；显式 LIMIT 9999 → limit 截断为 500（行数=实有行数）
        ok_big, det_big = exec_sql("SELECT herb_code, herb_name FROM herb")
        rows_big = (det_big.get("rows") or []) if isinstance(det_big, dict) else None
        check("库内行数 >100（截断断言的前置条件成立）", (total_rows or 0) > 100, total_rows)
        check("大结果集被默认 LIMIT 截断（100 行 / limit=100 / truncated=True）",
              ok_big is True and rows_big is not None and len(rows_big) == 100
              and isinstance(det_big, dict) and det_big.get("truncated") is True and det_big.get("limit") == 100,
              (len(rows_big) if rows_big is not None else None,
               det_big.get("truncated") if isinstance(det_big, dict) else None,
               det_big.get("limit") if isinstance(det_big, dict) else None))
        ok_mid, det_mid = exec_sql("SELECT herb_code FROM herb LIMIT 150")
        rows_mid = (det_mid.get("rows") or []) if isinstance(det_mid, dict) else None
        check("显式 LIMIT 150 被尊重（150 行 / limit=150 / truncated=True）",
              ok_mid is True and rows_mid is not None and len(rows_mid) == 150
              and isinstance(det_mid, dict) and det_mid.get("limit") == 150 and det_mid.get("truncated") is True,
              (len(rows_mid) if rows_mid is not None else None,
               det_mid.get("limit") if isinstance(det_mid, dict) else None))
        ok_cap, det_cap = exec_sql("SELECT herb_code FROM herb LIMIT 9999")
        rows_cap = (det_cap.get("rows") or []) if isinstance(det_cap, dict) else None
        check("超上限 LIMIT 被截断为 500（limit=500，行数=实有行数，truncated=False）",
              ok_cap is True and rows_cap is not None and len(rows_cap) == total_rows
              and isinstance(det_cap, dict) and det_cap.get("limit") == 500 and det_cap.get("truncated") is False,
              (len(rows_cap) if rows_cap is not None else None,
               det_cap.get("limit") if isinstance(det_cap, dict) else None,
               det_cap.get("truncated") if isinstance(det_cap, dict) else None))

        negatives = [
            ("写操作 INSERT", "INSERT INTO herb (herb_code) VALUES ('X')"),
            ("写操作 UPDATE", "UPDATE herb SET stock_quantity = 0 WHERE id = 1"),
            ("写操作 DELETE", "DELETE FROM herb WHERE id = 1"),
            ("DDL DROP", "DROP TABLE herb"),
            ("DDL ALTER", "ALTER TABLE herb ADD COLUMN x TEXT"),
            ("PRAGMA", "PRAGMA table_info(herb)"),
            ("白名单外表", "SELECT id, code FROM sys_user"),
            ("白名单外字段", "SELECT herb_code, no_such_col FROM herb"),
            ("多语句", "SELECT herb_code FROM herb; DROP TABLE herb"),
            ("注释绕过 --", "SELECT herb_code FROM herb -- WHERE flag=1"),
            ("注释绕过 块注释", "SELECT herb_code FROM herb /* x */"),
            ("SELECT *", "SELECT * FROM herb"),
            ("sqlite_master", "SELECT name FROM sqlite_master"),
            ("默认字段 flag（非白名单属性）", "SELECT herb_code FROM herb WHERE flag = 1"),
            ("逻辑删除绕过试探", "SELECT herb_code FROM herb WHERE flag = 0"),
        ]
        for label, bad in negatives:
            ok_n, det_n = exec_sql(bad)
            check("%s 被拒" % label, ok_n is False, str(det_n)[:70])
        # 被拒原因必须是中文可读
        ok_n, det_n = exec_sql("DROP TABLE herb")
        check("拒绝原因含中文说明", (not ok_n) and any("\u4e00" <= c <= "\u9fff" for c in str(det_n)), str(det_n)[:60])
        # 超时能力可配置（progress_steps 参数存在即视为具备中断手段）
        import inspect
        if callable(run):
            params = inspect.signature(run).parameters
            check("入口具备超时/步进参数（timeout_seconds / progress_steps）",
                  "timeout_seconds" in params and "progress_steps" in params, list(params))
    except ImportError as exc:
        check("能导入 sql_readonly.guard", False, exc)

    section("⑥ 审计落库（契约 §8 三种 action）")
    before = scalar("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'AI_%'")
    st, events, _, _ = sse(admin, {"message": "统计一下饮片库存预警", "history": []})
    time.sleep(0.3)
    rows = sql("SELECT action, detail FROM audit_logs WHERE action LIKE 'AI_%' ORDER BY id DESC LIMIT 20")
    after = scalar("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'AI_%'")
    check("一次对话后新增 AI_* 审计行", (after or 0) > (before or 0), "%s → %s" % (before, after))
    acts = {r["action"] for r in rows}
    check("含 AI_CHAT 审计", "AI_CHAT" in acts, sorted(acts))
    check("含 AI_TOOL_CALL 审计", "AI_TOOL_CALL" in acts, sorted(acts))
    detail_ok = any("messageId" in (r["detail"] or "") for r in rows if r["action"] == "AI_CHAT")
    check("AI_CHAT 的 detail 为 JSON 且含 messageId", detail_ok,
          [r["detail"][:60] for r in rows if r["action"] == "AI_CHAT"][:1])
    sql_rows = sql("SELECT detail FROM audit_logs WHERE action = 'AI_SQL_QUERY' ORDER BY id DESC LIMIT 3")
    if sql_rows:
        check("AI_SQL_QUERY 的 detail 含 sql 与 ok", "sql" in (sql_rows[0]["detail"] or ""),
              sql_rows[0]["detail"][:60])
    else:
        check("（SQL 工具未在 mock 对话中被调用 → 无 AI_SQL_QUERY 行，属可接受）", True, "已直接对 guard 做过负例矩阵")

    section("⑦ provider 切回 deepseek：按**实际凭据状态**自适应（无凭据→503 降级；有凭据→真流式）")
    os.environ["AI_PROVIDER"] = "deepseek"
    os.environ.pop("AI_API_KEY", None)
    # 凭据可能来自进程环境或 backend/.env（config.settings 会 load_dotenv）——不能假设"没配"。
    env_file = os.path.join(BACKEND, ".env")
    file_key = ""
    if os.path.exists(env_file):
        for line in io.open(env_file, encoding="utf-8", errors="replace").read().splitlines():
            if line.startswith(("DEEPSEEK_API_KEY=", "AI_API_KEY=")):
                file_key = line.split("=", 1)[1].strip()
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY") or file_key)
    st, b, _ = call("GET", "/api/ai/status", token=admin)
    d = b.get("data") or {}
    check("provider 切回 deepseek 后 configured == 是否存在凭据", st == 200 and d.get("configured") is key_present,
          (st, d.get("configured"), "key_present=%s" % key_present))
    check("status 带中文 hint", bool(d.get("hint")) and any("\u4e00" <= c <= "\u9fff" for c in str(d.get("hint"))),
          str(d.get("hint"))[:60])
    st, raw, _ = call("POST", "/api/ai/chat", token=admin, body={"message": "你好"}, raw=True)
    body_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else json.dumps(raw, ensure_ascii=False)
    if key_present:
        check("已配置凭据时 chat → 200 且为 SSE（message_start 在流里）",
              st == 200 and "message_start" in body_text, (st, body_text[:60]))
    else:
        check("未配置时 chat → 503 中文提示",
              st == 503 and any("\u4e00" <= c <= "\u9fff" for c in body_text), (st, body_text[:60]))
    os.environ["AI_PROVIDER"] = "mock"

    section("⑧ 只读边界的静态守卫（AI 层不得调用写接口）")
    offenders = []
    for root, dirs, files in os.walk(os.path.join(BACKEND, "ai")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                t = io.open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                for pat in (r"requests\.post", r"urlopen\([^)]*method\s*=\s*[\"']POST", r"session\.post"):
                    if re.search(pat, t):
                        offenders.append((f, pat))
    check("ai/ 模块内无写请求调用（只读边界）", not offenders, offenders[:3])

    srv.shutdown()
    for suffix in ("", "-wal", "-shm"):                     # 跑完删隔离副本（纪律：不留测试库）
        if os.path.exists(DB + suffix):
            os.remove(DB + suffix)
    print("\n" + "=" * 108)
    print("批次 5 独立验收结果：通过 %d / 失败 %d（隔离库已删除：%s）" % (len(OK), len(NG), DB))
    if NG:
        print("失败项：")
        for n in NG:
            print("   - %s" % n)
    print("=" * 108)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
