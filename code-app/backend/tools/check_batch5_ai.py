# -*- coding: utf-8 -*-
"""批次 5 AI 编排层自测（实现方自测，非主代验收）。

真实起服务器（隔离库副本 + `AI_PROVIDER=mock` 离线驱动），断言：
  ① SSE 事件序列与顺序（含分片格式与响应头）
  ② 工具 schema 条数 59 与抽取文档逐条一致
  ③ 权限过滤（未授权工具不在 schema；强行调用 → ok=false + 中文）
  ④ SQL 只读负例矩阵（写 SQL / 白名单外表 / 白名单外列 / 多语句 / 注释 / SELECT * 等）
     与正例（正常查询成功、LIMIT 强制补全与超限截断、超时中断）
  ⑤ 审计逐条落库（AI_CHAT / AI_TOOL_CALL / AI_SQL_QUERY）
  ⑥ 未启用降级（503 + 中文 hint）
  ⑦ 未登录 401

隔离纪律：`APP_DB_PATH` 指向**演示库副本**（`data/app.db` → `data/b5_ai.db`，原生路径），
跑完删除副本；演示库 `data/app.db` 全程只读（`mode=ro`）。会写库的自测一律走副本。

用法：code-app/backend/.venv/Scripts/python.exe tools/check_batch5_ai.py
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(BE))
DEMO_DB = os.path.join(BE, "data", "app.db")
ISO_DB = os.path.join(BE, "data", "b5_ai.db")
KILLER = os.path.join(PROJECT, "tools", "kill_app_servers.py")
PYTHON = sys.executable
PORT_MOCK = 5735
PORT_DEFAULT = 5736

sys.path.insert(0, BE)
os.chdir(BE)
os.environ["APP_DB_PATH"] = ISO_DB.replace("\\", "/")

RESULTS = []
NOTES = []
EXPECTED_TOOL_CALLS = {"count": 0}   # 本次自测实际发起的工具调用数（含被拒）
CHATS = {"count": 0}                 # 本次自测实际进入 SSE 的对话数
SQL_CALLS = {"count": 0}             # 本次自测实际发起的只读 SQL 调用数（含被拒）
# 审计行数基线：隔离库副本来自演示库，**可能已含真实用户的历史 AI 审计**（如接了真 key 后的人工对话），
# 故一律断言「增量」，不能断言绝对条数。
AUDIT_BASE = {"chats": 0, "tools": 0, "sql": 0}


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("｜" + detail) if detail else ""))
    return bool(ok)


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------- HTTP 工具

def http(method, path, token=None, body=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (CURRENT_PORT, path), data=data,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read().decode("utf-8", "replace")


def login(username, password):
    status, _h, text = http("POST", "/api/auth/login", body={"username": username,
                                                             "password": password})
    payload = json.loads(text)
    token = (payload.get("data") or {}).get("token")
    return status, payload, token


def chat_events(token, message, extra=None):
    """POST /api/ai/chat 并解析原始 SSE 分片，返回 (status, headers, raw, [(type, data, block)])。"""
    body = {"message": message}
    if extra:
        body.update(extra)
    status, headers, raw = http("POST", "/api/ai/chat", token=token, body=body, timeout=120)
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        m = re.match(r"^event: ([a-z_]+)\ndata: (.*)$", block, re.S)
        if not m:
            events.append(("<malformed>", {"raw": block}, block))
            continue
        events.append((m.group(1), json.loads(m.group(2)), block))
    if status == 200 and events:
        CHATS["count"] += 1                # 每次成功进入 SSE 的对话都会写一条 AI_CHAT
    return status, headers, raw, events


def event_types(events):
    return [e[0] for e in events]


def tool_call_event(events):
    for etype, data, _block in events:
        if etype == "tool_call":
            return data
    return None


def tool_result_event(events):
    for etype, data, _block in events:
        if etype == "tool_result":
            return data
    return None


def sql_chat(token, sql, label=""):
    """用 mock 指令强制调用 sql_readonly，返回 (ok, error, rowCount)。"""
    message = '#tool=sql_readonly #args=' + json.dumps({"sql": sql}, ensure_ascii=False)
    status, _h, _raw, events = chat_events(token, message)
    EXPECTED_TOOL_CALLS["count"] += 1
    SQL_CALLS["count"] += 1
    result = tool_result_event(events) or {}
    return status, result.get("ok"), result.get("error"), result.get("rowsCount"), events


def forced_tool(token, name, args=None):
    message = "#tool=%s" % name
    if args is not None:
        message += " #args=" + json.dumps(args, ensure_ascii=False)
    status, _h, _raw, events = chat_events(token, message)
    EXPECTED_TOOL_CALLS["count"] += 1
    return status, events


# ---------------------------------------------------------------- 服务器

CURRENT_PORT = PORT_MOCK
PROCS = []
DEGRADED_BASE = {"chats": 0}


def kill_ports(*ports):
    for port in ports:
        subprocess.run([PYTHON, KILLER, "--port", str(port)], capture_output=True, text=True)


def start_server(port, env_extra):
    global CURRENT_PORT
    CURRENT_PORT = port
    env = dict(os.environ)
    env.update(env_extra)
    code = ("import sys; sys.path.insert(0, %r); from app import app; "
            "app.run(host='127.0.0.1', port=%d, debug=False, use_reloader=False)"
            % (BE.rstrip("\\").replace("\\", "/"), port))
    proc = subprocess.Popen([PYTHON, "-c", code], cwd=BE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace")
    PROCS.append(proc)
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError("服务器启动即退出（端口 %d）：\n%s" % (port, out[-2000:]))
        try:
            status, _h, text = http("GET", "/api/health", timeout=3)
            if status == 200:
                return proc
        except Exception:                              # noqa: BLE001 - 未就绪继续等
            pass
        time.sleep(0.4)
    raise RuntimeError("服务器未在 40 秒内就绪（端口 %d）" % port)


def stop_servers():
    for proc in PROCS:
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:                              # noqa: BLE001
            pass
    PROCS.clear()


# ---------------------------------------------------------------- 隔离库

def prepare_db():
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(ISO_DB + suffix):
            os.remove(ISO_DB + suffix)
    src = sqlite3.connect("file:%s?mode=ro" % DEMO_DB.replace("\\", "/"), uri=True)
    dst = sqlite3.connect(ISO_DB)
    try:
        src.backup(dst)                                # 含 WAL 中已提交内容
    finally:
        dst.close()
        src.close()


def cleanup_db():
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(ISO_DB + suffix)
        except OSError:
            pass


def iso_query(sql, params=()):
    conn = sqlite3.connect("file:%s?mode=ro" % ISO_DB.replace("\\", "/"), uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def audit_rows(action):
    return iso_query("SELECT * FROM audit_logs WHERE action = ? ORDER BY id", (action,))


BUSINESS_BEFORE = {}

BUSINESS_TABLES = ("patient", "visit", "four_diagnosis", "syndrome_diagnosis", "syndrome_type",
                   "formula_template", "formula_item", "herb", "herb_stock_flow", "prescription",
                   "prescription_item", "dispense_record", "follow_up", "sys_user", "sys_role",
                   "sys_permission", "sys_resource")


def business_counts():
    """隔离库业务表行数指纹（证明 AI 编排层未写任何业务数据）。"""
    conn = sqlite3.connect("file:%s?mode=ro" % ISO_DB.replace("\\", "/"), uri=True)
    try:
        out = {}
        for table in BUSINESS_TABLES:
            out[table] = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        return out
    finally:
        conn.close()


def demo_fingerprint():
    """演示库只读指纹（证明全程未写演示库）。"""
    conn = sqlite3.connect("file:%s?mode=ro" % DEMO_DB.replace("\\", "/"), uri=True)
    try:
        rows = conn.execute("SELECT COUNT(*) AS c, SUM(LENGTH(COALESCE(patient_name,''))) AS s "
                            "FROM patient").fetchone()
        audit = conn.execute("SELECT COUNT(*) AS c FROM audit_logs").fetchone()
        return {"patient_rows": rows[0], "patient_name_len": rows[1], "audit_rows": audit[0]}
    finally:
        conn.close()


# ================================================================ ① ①②③④⑤⑦

def _env_key_present():
    """真实凭据是否存在：进程环境 AI_API_KEY/DEEPSEEK_API_KEY，或 backend/.env（settings 会 load_dotenv）。"""
    for name in ("AI_API_KEY", "DEEPSEEK_API_KEY"):
        value = os.environ.get(name)
        if value and str(value).strip():
            return True
    env_file = os.path.join(BACKEND, ".env")
    if os.path.exists(env_file):
        for line in io.open(env_file, encoding="utf-8", errors="replace").read().splitlines():
            if line.startswith(("DEEPSEEK_API_KEY=", "AI_API_KEY=")) and line.split("=", 1)[1].strip():
                return True
    return False


def phase_mock():
    section("① 启动 mock 服务器（隔离库副本 + AI_PROVIDER=mock 离线驱动）")
    start_server(PORT_MOCK, {"APP_DB_PATH": ISO_DB.replace("\\", "/"),
                             "AI_PROVIDER": "mock",
                             "AI_API_KEY": "",
                             "AI_BASE_URL": ""})
    status, _h, text = http("GET", "/api/health")
    check("服务器就绪 /api/health", status == 200, text.strip()[:120])

    section("⑦ 未登录 401")
    st, _h, text = http("GET", "/api/ai/status")
    check("GET /api/ai/status 未登录 → 401", st == 401,
          "HTTP %s｜%s" % (st, json.loads(text).get("message") if text else ""))
    st, _h, text = http("POST", "/api/ai/chat", body={"message": "你好"})
    check("POST /api/ai/chat 未登录 → 401", st == 401,
          "HTTP %s｜%s" % (st, json.loads(text).get("message") if text else ""))
    st, _h, text = http("POST", "/api/ai/chat", body={})
    check("POST /api/ai/chat 无 token（空体）→ 401", st == 401, "HTTP %s" % st)

    section("登录与 /api/ai/status")
    st, payload, admin_token = login("admin", "admin123")
    check("admin 登录成功", st == 200 and bool(admin_token), "HTTP %s" % st)
    st, _h, text = http("GET", "/api/ai/status", token=admin_token)
    data = json.loads(text).get("data") or {}
    check("status 返回五字段且 provider=mock（env 覆盖生效）",
          st == 200 and set(data) == {"enabled", "provider", "model", "configured", "hint"}
          and data.get("provider") == "mock" and data.get("configured") is True
          and data.get("enabled") is True,
          json.dumps(data, ensure_ascii=False))
    st, payload, yaoshi_token = login("yaoshi", "123456")
    check("yaoshi（中药师）登录成功", st == 200 and bool(yaoshi_token), "HTTP %s" % st)

    section("① SSE 事件序列与顺序（mock 全链路）")
    st, _h, text = http("POST", "/api/ai/chat", token=admin_token, body={"message": "   "})
    check("chat 空消息 → 400 + 中文（参数类）",
          st == 400 and "不能为空" in (json.loads(text).get("message") or ""),
          "HTTP %s｜%s" % (st, json.loads(text).get("message")))
    st, _h, text = http("POST", "/api/ai/chat", token=admin_token,
                        body={"message": "你好", "history": "not-a-list"})
    check("chat history 非数组 → 400 + 中文（参数类）",
          st == 400 and "history" in (json.loads(text).get("message") or ""),
          "HTTP %s｜%s" % (st, json.loads(text).get("message")))
    st, headers, raw, events = chat_events(admin_token, "本月门诊量多少",
                                           extra={"history": [
                                               {"role": "user", "content": "你好"},
                                               {"role": "assistant", "content": "你好，请问需要什么"}],
                                               "context": {"screenId": "frmVisitStats"}})
    EXPECTED_TOOL_CALLS["count"] += 1
    check("HTTP 200", st == 200, "HTTP %s" % st)
    check("Content-Type = text/event-stream; charset=utf-8",
          headers.get("Content-Type") == "text/event-stream; charset=utf-8",
          str(headers.get("Content-Type")))
    check("Cache-Control = no-cache", headers.get("Cache-Control") == "no-cache",
          str(headers.get("Cache-Control")))
    check("X-Accel-Buffering = no", headers.get("X-Accel-Buffering") == "no",
          str(headers.get("X-Accel-Buffering")))
    check("事件序列 == 契约 §3.3 顺序",
          event_types(events) == ["message_start", "delta", "tool_call", "tool_result",
                                  "render_payload", "message_end"],
          " → ".join(event_types(events)))
    check("每个分片均为 `event: <type>\\ndata: <json>\\n\\n` 格式",
          all(re.match(r"^event: [a-z_]+\ndata: \{.*\}$", b, re.S) for _t, _d, b in events)
          and raw.endswith("\n\n"),
          "首片=%r" % events[0][2][:60])
    start = events[0][1]
    check("message_start 含 messageId(32位 hex) 与 ts(YYYY-MM-DD HH:MM:SS)",
          re.fullmatch(r"[0-9a-f]{32}", start.get("messageId") or "")
          and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", start.get("ts") or ""),
          json.dumps(start, ensure_ascii=False))
    call = tool_call_event(events)
    result = tool_result_event(events)
    check("tool_call 含 toolCallId/name/arguments",
          bool(call) and call.get("toolCallId") and call.get("name")
          and isinstance(call.get("arguments"), dict),
          json.dumps(call, ensure_ascii=False)[:160])
    check("tool_result 与 tool_call 的 toolCallId 成对一致",
          bool(result) and result.get("toolCallId") == call.get("toolCallId"),
          "%s / %s" % (call.get("toolCallId"), result.get("toolCallId")))
    check("tool_result.ok = true 且带 summary", result.get("ok") is True
          and bool(result.get("summary")), json.dumps(result, ensure_ascii=False)[:160])
    render = [d for t, d, _b in events if t == "render_payload"][0]
    check("render_payload 为 table（columns/rows/total/truncated 齐备）",
          render.get("renderType") == "table"
          and set(render.get("payload") or {}) >= {"columns", "rows", "total", "truncated"}
          and (render["payload"]["columns"]),
          json.dumps({"renderType": render.get("renderType"),
                      "columns": len(render["payload"]["columns"]),
                      "rows": len(render["payload"]["rows"]),
                      "total": render["payload"]["total"]}, ensure_ascii=False))
    end = events[-1][1]
    check("message_end.finishReason=stop 且 toolCallCount=1",
          end.get("finishReason") == "stop" and end.get("toolCallCount") == 1,
          json.dumps(end, ensure_ascii=False))

    section("① 其它渲染类型（chart / action）与未知工具")
    st, _h, _raw, events = chat_events(admin_token, "用图表展示门诊量趋势")
    EXPECTED_TOOL_CALLS["count"] += 1
    render = [d for t, d, _b in events if t == "render_payload"][0]
    check("chart 意图 → renderType=chart（bar/line/pie + xField/yField）",
          render.get("renderType") == "chart"
          and render["payload"].get("chartType") in ("bar", "line", "pie")
          and render["payload"].get("xField") and render["payload"].get("yField"),
          json.dumps({k: v for k, v in render["payload"].items() if k != "rows"},
                     ensure_ascii=False))
    st, _h, _raw, events = chat_events(admin_token, "我要给新患者建档")
    EXPECTED_TOOL_CALLS["count"] += 1
    render = [d for t, d, _b in events if t == "render_payload"][0]
    payload = render["payload"]
    check("行为工具 → renderType=action（navigate + screenId/behaviorId/permissionCode）",
          render.get("renderType") == "action" and payload.get("type") == "navigate"
          and payload.get("screenId") == "frmPatientCreate"
          and payload.get("behaviorId") == "Patient_Save"
          and payload.get("permissionCode") == "patient:save",
          json.dumps(payload, ensure_ascii=False))
    check("action 事件序列仍合法（tool_result 后紧跟 render_payload）",
          event_types(events) == ["message_start", "delta", "tool_call", "tool_result",
                                  "render_payload", "message_end"],
          " → ".join(event_types(events)))
    st, events = forced_tool(admin_token, "not_exists.Tool")
    result = tool_result_event(events)
    check("未知工具 → tool_result.ok=false + 中文原因",
          result.get("ok") is False and "未知的工具" in (result.get("error") or ""),
          json.dumps(result, ensure_ascii=False)[:160])
    check("失败工具后以 delta 中文说明收尾（不产生 render_payload）",
          event_types(events) == ["message_start", "delta", "tool_call", "tool_result", "delta",
                                  "message_end"],
          " → ".join(event_types(events)))

    section("③ 权限过滤（黑盒：强行调用未授权工具）")
    st, events = forced_tool(yaoshi_token, "action_Patient_Save")
    result = tool_result_event(events)
    check("yaoshi 强行调用 action_Patient_Save → ok=false + 无权限执行该操作",
          result.get("ok") is False and result.get("error") == "无权限执行该操作",
          json.dumps(result, ensure_ascii=False)[:200])
    st, events = forced_tool(yaoshi_token, "nav_frmPatientCreate")
    result = tool_result_event(events)
    check("yaoshi 强行调用未授权导航 nav_frmPatientCreate → ok=false",
          result.get("ok") is False, json.dumps(result, ensure_ascii=False)[:200])
    st, events = forced_tool(yaoshi_token, "query_Visit_QueryStats")
    result = tool_result_event(events)
    check("yaoshi 强行调用未授权查询 query_Visit_QueryStats → ok=false",
          result.get("ok") is False, json.dumps(result, ensure_ascii=False)[:200])
    st, events = forced_tool(yaoshi_token, "query_Herb_QueryStockAndAlert")
    result = tool_result_event(events)
    check("yaoshi 调用已授权查询 query_Herb_QueryStockAndAlert → ok=true（对照组）",
          result.get("ok") is True, json.dumps(result, ensure_ascii=False)[:200])

    section("④ SQL 只读负例矩阵（黑盒强制调用 sql_readonly）")
    negatives = [
        ("写 SQL-INSERT", "INSERT INTO patient (patient_no) VALUES ('X')", "仅允许 SELECT"),
        ("写 SQL-UPDATE", "UPDATE patient SET patient_name = 'X'", "仅允许 SELECT"),
        ("写 SQL-DELETE", "DELETE FROM patient", "仅允许 SELECT"),
        ("写 SQL-DROP", "DROP TABLE patient", "仅允许 SELECT"),
        ("写 SQL-ALTER", "ALTER TABLE patient ADD COLUMN x TEXT", "仅允许 SELECT"),
        ("管理 SQL-PRAGMA", "PRAGMA table_info(patient)", "仅允许 SELECT"),
        ("白名单外表 sys_user", "SELECT username FROM sys_user", "不在白名单内"),
        ("白名单外表 audit_logs", "SELECT * FROM audit_logs", "不允许 SELECT *"),
        ("白名单外表(子查询)", "SELECT patient_no FROM patient WHERE id IN "
                              "(SELECT id FROM sys_user)", "不在白名单内"),
        ("UNION 拼接外部表", "SELECT patient_no FROM patient UNION SELECT code FROM sys_role",
         "禁止"),
        ("白名单外列", "SELECT patient_no, created_at FROM patient", "不在白名单内"),
        ("白名单外列(主键)", "SELECT id FROM patient", "不在白名单内"),
        ("多语句", "SELECT patient_no FROM patient; DROP TABLE patient", "禁止多语句"),
        ("注释 --", "SELECT patient_no FROM patient -- drop", "禁止出现注释"),
        ("注释 /* */", "SELECT patient_no FROM patient /* x */", "禁止出现注释"),
        ("SELECT *", "SELECT * FROM patient", "不允许 SELECT *"),
        ("别名 SELECT *", "SELECT p.* FROM patient p", "不允许 SELECT *"),
        ("sqlite_master 系统表", "SELECT name FROM sqlite_master", "禁止访问 SQLite 系统表"),
        ("函数越权 load_extension", "SELECT load_extension('x') FROM patient",
         "禁止的 SQL 关键字"),
        ("空语句", "   ", "不能为空"),
    ]
    for label, sql, expect in negatives:
        st, ok, err, rows, _events = sql_chat(admin_token, sql, label)
        check("负例·%s → 被拒" % label,
              st == 200 and ok is False and expect in (err or ""),
              "HTTP %s｜ok=%s｜error=%s" % (st, ok, err))

    section("④ SQL 正例（正常查询 + LIMIT 强制生效）")
    st, ok, err, rows, events = sql_chat(
        admin_token, "SELECT patient_no, patient_name, gender FROM patient")
    render = [d for t, d, _b in events if t == "render_payload"]
    check("正例·无 LIMIT 的 SELECT 成功且自动补 LIMIT（≤100 行）",
          ok is True and rows is not None and rows <= 100 and bool(render)
          and render[0]["renderType"] == "table",
          "ok=%s｜rowsCount=%s｜columns=%s" % (
              ok, rows, [c["name"] for c in render[0]["payload"]["columns"]] if render else []))
    st, ok, err, rows, _e = sql_chat(admin_token, "SELECT patient_no FROM patient LIMIT 3")
    check("正例·显式 LIMIT 3 → 返回 ≤3 行", ok is True and rows is not None and rows <= 3,
          "ok=%s｜rowsCount=%s" % (ok, rows))
    st, ok, err, rows, _e = sql_chat(admin_token, "SELECT patientNo FROM patient LIMIT 3")
    check("正例·M1 驼峰字段名（patientNo）被归一化为物理列", ok is True,
          "ok=%s｜rowsCount=%s｜error=%s" % (ok, rows, err))
    st, ok, err, rows, _e = sql_chat(
        admin_token, "SELECT visit_no, COUNT(*) AS c FROM visit GROUP BY visit_no LIMIT 10")
    check("正例·聚合 + COUNT(*) 允许（行数 ≤10）", ok is True and rows is not None and rows <= 10,
          "ok=%s｜rowsCount=%s｜error=%s" % (ok, rows, err))
    st, ok, err, rows, _e = sql_chat(admin_token, "SELECT patient_no FROM patient LIMIT 9999")
    check("正例·超上限 LIMIT 9999 → 成功且行数 ≤ max_limit(500)", ok is True
          and rows is not None and rows <= 500, "ok=%s｜rowsCount=%s" % (ok, rows))

    section("⑤ 审计逐条落库")
    chats = audit_rows("AI_CHAT")
    tool_rows = audit_rows("AI_TOOL_CALL")
    sql_rows = audit_rows("AI_SQL_QUERY")
    print("    审计行数：AI_CHAT=%d｜AI_TOOL_CALL=%d｜AI_SQL_QUERY=%d"
          % (len(chats), len(tool_rows), len(sql_rows)))
    d_chats = len(chats) - AUDIT_BASE["chats"]
    d_tools = len(tool_rows) - AUDIT_BASE["tools"]
    d_sql = len(sql_rows) - AUDIT_BASE["sql"]
    check("AI_CHAT 增量 == 本次自测对话数", d_chats == CHATS["count"],
          "增量 %d / 期望 %d（基线 %d）" % (d_chats, CHATS["count"], AUDIT_BASE["chats"]))
    check("AI_TOOL_CALL 增量 == 本次自测工具调用数（含被拒）",
          d_tools == EXPECTED_TOOL_CALLS["count"],
          "增量 %d / 期望 %d（基线 %d）" % (d_tools, EXPECTED_TOOL_CALLS["count"], AUDIT_BASE["tools"]))
    check("AI_SQL_QUERY 增量 == SQL 调用数（含被拒）",
          d_sql == SQL_CALLS["count"],
          "增量 %d / 期望 %d（基线 %d）" % (d_sql, SQL_CALLS["count"], AUDIT_BASE["sql"]))
    # 取**本次自测产生的最后一条**（chats[0] 可能是历史行，曾用它导致 provider 断言假失败）
    sample = json.loads(chats[-1]["detail"])
    check("AI_CHAT detail 字段齐备（messageId/questionLen/toolCallCount/provider）",
          set(sample) == {"messageId", "questionLen", "toolCallCount", "provider"}
          and sample["provider"] == "mock",
          json.dumps(sample, ensure_ascii=False))
    rejected = [json.loads(r["detail"]) for r in sql_rows if not json.loads(r["detail"])["ok"]]
    check("被拒 SQL 同样落审计（含 rejectedReason）",
          len(rejected) >= len(negatives) and all(r.get("rejectedReason") for r in rejected),
          "被拒 %d 条，样例 %s" % (len(rejected), json.dumps(rejected[0], ensure_ascii=False)[:160]))
    denied = [json.loads(r["detail"]) for r in tool_rows
              if "无权限执行该操作" == (json.loads(r["detail"]).get("error") or "")]
    check("被拒的工具调用落审计（ok=false + error）",
          len(denied) >= 1 and all(r.get("ok") is False for r in denied),
          "样例 %s" % json.dumps(denied[0], ensure_ascii=False)[:200])
    username = {r["username"] for r in tool_rows}
    check("审计记录了触发用户（username）", "admin" in username and "yaoshi" in username,
          "users=%s" % sorted(username))
    # 只读边界硬证据：整轮对话前后，隔离库 17 张业务/系统表的行数指纹不变
    after = business_counts()
    diff = {k: (BUSINESS_BEFORE.get(k), v) for k, v in after.items()
            if BUSINESS_BEFORE.get(k) != v}
    check("整轮对话前后业务表行数指纹完全一致（AI 未写任何业务数据）", not diff,
          "比对 %d 张表｜差异=%s" % (len(after), diff or "无"))


# ================================================================ ② ③ ④（进程内）

def phase_inprocess():
    global CHATS, SQL_CALLS
    section("② 工具 schema 条数与抽取文档逐条一致（进程内断言，隔离库）")
    # 进程内断言需要运行库与本体装载（APP_DB_PATH 已在模块导入前指向隔离库副本）
    import db as db_module
    from config import settings as settings_module
    from ontology import registry as ontology_registry
    db_module.init_db_path(settings_module.resolve_db_path())
    ontology_registry.load_ontology()
    from ai import prompt_builder, tool_registry
    from ai.providers import load_ai_config, status_payload
    from sql_readonly import SqlRejected, SqlTimeout, guard_sql, execute_readonly

    verify = tool_registry.verify_against_spec_doc()
    check("与抽取文档逐条对账 OK（无缺失/无多余/计数一致）", verify["ok"],
          json.dumps({"doc_total": verify.get("doc_total"),
                      "generated_total": verify.get("generated_total"),
                      "missing": verify["missing_in_generated"],
                      "extra": verify["extra_in_generated"],
                      "count_mismatch": verify["count_mismatch"]}, ensure_ascii=False))
    counts = tool_registry.counts()
    check("分类计数 = 导航19/查询7/报表7/行为24/图表1/SQL1，总 59",
          counts == {"nav": 19, "query": 7, "report": 7, "action": 24, "chart": 1, "sql": 1,
                     "total": 59}, json.dumps(counts, ensure_ascii=False))

    section("③ 权限过滤（进程内：schema 层面）")
    admin_id = db_module.query_one("SELECT id FROM sys_user WHERE username='admin'")["id"]
    yaoshi_id = db_module.query_one("SELECT id FROM sys_user WHERE username='yaoshi'")["id"]
    admin_tools = {t["function"]["name"] for t in tool_registry.build_tools(admin_id)}
    yaoshi_tools = {t["function"]["name"] for t in tool_registry.build_tools(yaoshi_id)}
    check("admin（*）→ 全部 59 个工具", len(admin_tools) == 59,
          "count=%d" % len(admin_tools))
    unauthorized = {n for n in admin_tools if n.startswith(("action_Patient_Save", "nav_frmPatientCreate",
                                                            "query_Visit_QueryStats"))}
    check("未授权工具不进入 yaoshi 的 schema",
          len(yaoshi_tools) < 59 and not (unauthorized & yaoshi_tools),
          "yaoshi=%d 个｜排除 %s｜样例 yaoshi 工具：%s"
          % (len(yaoshi_tools), sorted(unauthorized),
             sorted(yaoshi_tools)[:4]))
    check("yaoshi 授权工具与角色权限一致（含库存/审核/发药相关）",
          {"action_Dispense_Confirm", "action_Prescription_Review",
           "query_Herb_QueryStockAndAlert", "nav_frmHerbStock"} <= yaoshi_tools,
          "%d 个：%s" % (len(yaoshi_tools), sorted(yaoshi_tools)))
    text, elements = prompt_builder.prompt_elements(admin_id)
    check("system prompt 五要素齐备（契约 §6）", all(elements.values()),
          json.dumps(elements, ensure_ascii=False))
    yaoshi_text, _e = prompt_builder.prompt_elements(yaoshi_id)
    check("system prompt 中不含未授权工具（按权限过滤）",
          "action_Patient_Save" not in yaoshi_text and "query_Visit_QueryStats" not in yaoshi_text
          and "action_Dispense_Confirm" in yaoshi_text,
          "prompt 长度 admin=%d / yaoshi=%d" % (len(text), len(yaoshi_text)))
    check("system prompt 含 59 工具清单中的管理域工具（admin）",
          "sql_readonly" in text and "nav_frmVisitStats" in text and "chart" in text, "")
    section("⑤ 生效配置：环境变量 > config.yaml（§5 + 主代补充要求）")
    saved = {k: os.environ.get(k) for k in ("AI_PROVIDER", "AI_API_KEY", "AI_BASE_URL", "AI_MODEL")}
    try:
        os.environ["AI_PROVIDER"] = "mock"
        os.environ["AI_API_KEY"] = "env-override-test-value"
        os.environ["AI_BASE_URL"] = "https://env.example.invalid/v1"
        os.environ["AI_MODEL"] = "mock-env-model"
        cfg = load_ai_config()
        check("AI_PROVIDER=mock 覆盖 ai.provider（config.yaml 未改）→ enabled/configured 为真",
              cfg["provider"] == "mock" and cfg["enabled"] and cfg["configured"],
              json.dumps({k: cfg[k] for k in ("provider", "model", "enabled", "configured",
                                              "base_url")}, ensure_ascii=False))
        check("AI_API_KEY / AI_BASE_URL / AI_MODEL 覆盖生效（来源标记也随之变化）",
              cfg["api_key"] == "env-override-test-value"
              and cfg["base_url"] == "https://env.example.invalid/v1"
              and cfg["model"] == "mock-env-model"
              and cfg["sources"] == {"provider": "AI_PROVIDER", "api_key": "AI_API_KEY",
                                     "base_url": "AI_BASE_URL", "model": "AI_MODEL"},
              json.dumps(cfg["sources"], ensure_ascii=False))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    cfg = load_ai_config()
    check("撤除环境变量后回落 config.yaml（provider=deepseek；configured 取决于 .env 是否有真 key）",
          cfg["provider"] == "deepseek" and cfg["configured"] is _env_key_present()
          and cfg["base_url"] == "https://api.deepseek.com",
          json.dumps({k: cfg[k] for k in ("provider", "configured", "base_url")},
                     ensure_ascii=False))

    section("④ SQL 守卫进程内矩阵（LIMIT 补全/截断、超时中断）")
    g = guard_sql("SELECT patient_no FROM patient")
    check("无 LIMIT → 自动补 LIMIT 100", g.sql.endswith("LIMIT 100") and g.limit == 100, g.sql)
    g = guard_sql("SELECT patient_no FROM patient LIMIT 9999")
    check("LIMIT 超上限 → 截断为 500", g.sql.endswith("LIMIT 500") and g.limit == 500, g.sql)
    g = guard_sql("SELECT patient_no FROM patient LIMIT 7")
    check("LIMIT 未超限 → 原样保留", g.sql.endswith("LIMIT 7"), g.sql)
    g = guard_sql("select patient_no from Patient limit 5;")
    check("小写 + 尾分号 + 表名大小写 → 正常放行（尾分号已去掉）",
          g.sql.lower().endswith("limit 5") and ";" not in g.sql and g.tables == ["patient"], g.sql)
    try:
        guard_sql("SELECT patient_name AS nm FROM patient LIMIT 1")
        alias_ok = True
    except SqlRejected as exc:
        alias_ok = False
        NOTES.append("列别名（AS nm）被拒：%s" % exc.message)
    check("列别名 AS 可用（不引入越权字段）", alias_ok, "见 NOTES" if not alias_ok else "")
    _g, result = execute_readonly("SELECT patient_no, patient_name FROM patient LIMIT 3")
    check("受限执行返回列名与行数据", result["rowCount"] >= 0 and result["columns"] == [
        "patient_no", "patient_name"],
        "rowCount=%d｜columns=%s｜elapsedMs=%d"
        % (result["rowCount"], result["columns"], result["elapsedMs"]))
    # 超时中断必须用**足够大的数据量**做确定性验证：小表（几行）查询在 progress handler
    # 触发前就跑完，会得到"时快时慢"的假失败。故自建 20 万行的临时库（表/字段名取白名单内，
    # 保证 guard 放行），用聚合查询逼出超时。
    import sqlite3
    import tempfile
    big_db = os.path.join(tempfile.gettempdir(), "b5_timeout_probe.db")
    for _suf in ("", "-wal", "-shm"):
        if os.path.exists(big_db + _suf):
            os.remove(big_db + _suf)
    _conn = sqlite3.connect(big_db)
    _conn.execute("CREATE TABLE patient (patient_no TEXT, patient_name TEXT)")
    _conn.executemany("INSERT INTO patient VALUES (?, ?)",
                      [("PA%06d" % i, "患者%d" % i) for i in range(200000)])
    _conn.commit()
    _conn.close()
    try:
        _g, _big = execute_readonly("SELECT COUNT(1) AS cnt FROM patient", db_path=big_db,
                                    timeout_seconds=0.0, progress_steps=1)
        timeout_raised = False
        NOTES.append("大表聚合未被中断（rows=%s elapsed=%sms）" % (_big.get("rowCount"), _big.get("elapsedMs")))
    except SqlTimeout as exc:
        timeout_raised = True
        NOTES.append("超时中断实测（20 万行聚合，timeout_seconds=0）：%s" % exc)
    except Exception as exc:                           # noqa: BLE001
        timeout_raised = False
        NOTES.append("超时未按预期抛出 SqlTimeout，实际：%r" % exc)
    finally:
        for _suf in ("", "-wal", "-shm"):
            if os.path.exists(big_db + _suf):
                os.remove(big_db + _suf)
    check("超时中断（20 万行聚合 + timeout_seconds=0 → progress handler 中断查询）", timeout_raised,
          NOTES[-1] if NOTES else "")

    section("⑥ 与主代验收装置的接口兼容（复刻其名称启发式发现逻辑）")
    import sql_readonly.guard as guard_module
    entry = None
    for name in dir(guard_module):
        fn = getattr(guard_module, name)
        if callable(fn) and not name.startswith("_") and re.search(
                r"run|execute|query|guard|check|safe", name, re.I):
            entry = (name, fn)
            break
    check("验收装置按名称启发式发现的只读入口 = execute_readonly（而非类/异常）",
          bool(entry) and entry[0] == "execute_readonly", "发现：%s" % (entry[0] if entry else None))

    def run_sql(sql_text):
        """复刻 batch5_api_test.py §5 的签名嗅探。"""
        fn = entry[1]
        for args in (("dummy-actor-token", sql_text), (admin_id, sql_text), (sql_text,),
                     (sql_text, "dummy-actor-token")):
            try:
                res = fn(*args)
            except TypeError:
                continue
            except Exception as exc:                   # noqa: BLE001
                return False, repr(exc)
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool):
                return res
            if isinstance(res, dict):
                return bool(res.get("ok", True)), res
            return True, res
        return None, "签名不匹配"

    ok_g, det_g = run_sql("SELECT herb_code, herb_name, stock_quantity FROM herb LIMIT 10")
    check("(actor, sql) 形式调用下白名单 SQL 通过", ok_g is True, str(det_g)[:120])
    for label, bad in (
            ("INSERT", "INSERT INTO herb (herb_code) VALUES ('X')"),
            ("UPDATE", "UPDATE herb SET stock_quantity = 0 WHERE id = 1"),
            ("DELETE", "DELETE FROM herb WHERE id = 1"),
            ("DROP", "DROP TABLE herb"),
            ("PRAGMA", "PRAGMA table_info(herb)"),
            ("白名单外表 sys_user", "SELECT id, code FROM sys_user"),
            ("白名单外字段", "SELECT herb_code, secret_col FROM herb"),
            ("多语句", "SELECT herb_code FROM herb; DROP TABLE herb"),
            ("注释绕过", "SELECT herb_code FROM herb -- WHERE flag=1"),
            ("SELECT *", "SELECT * FROM herb"),
            ("sqlite_master", "SELECT name FROM sqlite_master")):
        ok_n, det_n = run_sql(bad)
        check("验收入口·%s 被拒" % label, ok_n is False, str(det_n)[:90])
    ok_l, det_l = run_sql("SELECT herb_code FROM herb")
    check("验收入口·缺 LIMIT 自动追加（默认 100）", ok_l is True, str(det_l)[:120])
    ok_cap, det_cap = run_sql("SELECT herb_code FROM herb LIMIT 9999")
    check("验收入口·超上限 LIMIT 截断为 500 仍成功", ok_cap is True, str(det_cap)[:120])

    flat = [str(t.get("name")) for t in tool_registry.build_tools(admin_id)]
    pre = {k: sum(1 for n in flat if n.startswith(k)) for k in ("nav", "query", "report", "action")}
    check("验收装置按扁平 name 枚举：59 个工具、前缀分类计数与抽取文档一致",
          len(flat) == 59 and pre == {"nav": 19, "query": 7, "report": 7, "action": 24}
          and "chart" in flat and "sql_readonly" in flat,
          "total=%d｜%s" % (len(flat), pre))
    offenders = []
    for root, dirs, files in os.walk(BE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "data", "tools")]
        if os.path.relpath(root, BE).split(os.sep)[0] not in ("ai", "sql_readonly", "sse"):
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            text = open(os.path.join(root, name), encoding="utf-8", errors="replace").read()
            for pat in (r"requests\.post", r"urlopen\([^)]*method\s*=\s*[\"']POST",
                        r"session\.post"):
                if re.search(pat, text):
                    offenders.append((name, pat))
    check("验收装置静态守卫：ai/ sql_readonly/ sse/ 内无写请求调用",
          not offenders, str(offenders[:3]))

    section("② 计数汇总")
    print("    " + json.dumps({"doc_ok": verify["ok"], "counts": counts},
                               ensure_ascii=False))


# ================================================================ ⑥ 降级

def phase_degraded():
    section("⑥ 未启用降级（默认 provider=deepseek 且无凭据）")
    stop_servers()
    kill_ports(PORT_DEFAULT)
    start_server(PORT_DEFAULT, {"APP_DB_PATH": ISO_DB.replace("\\", "/"),
                                "AI_PROVIDER": "", "AI_API_KEY": "", "AI_BASE_URL": "", "DEEPSEEK_API_KEY": ""})
    st, _h, text = http("GET", "/api/health")
    check("降级态服务器就绪", st == 200, "HTTP %s" % st)
    st, payload, token = login("admin", "admin123")
    check("降级态 admin 登录成功", st == 200 and bool(token), "HTTP %s" % st)
    st, _h, text = http("GET", "/api/ai/status", token=token)
    data = json.loads(text).get("data") or {}
    check("status：enabled=false + configured=false + provider=deepseek + 中文 hint",
          st == 200 and data.get("enabled") is False and data.get("configured") is False
          and data.get("provider") == "deepseek" and data.get("hint")
          and ("未启用" in data["hint"]),
          json.dumps(data, ensure_ascii=False))
    st, headers, text = http("POST", "/api/ai/chat", token=token, body={"message": "你好"})
    body = json.loads(text)
    check("chat → 503 + success:false + 中文提示（不进入 SSE）",
          st == 503 and body.get("success") is False and "未启用" in (body.get("message") or "")
          and "event-stream" not in str(headers.get("Content-Type")),
          "HTTP %s｜%s｜Content-Type=%s" % (st, body.get("message"), headers.get("Content-Type")))
    st, _h, text = http("POST", "/api/ai/chat", token=token, body={"message": "你好"})
    check("降级态 chat 不进入编排层：无 SSE、无新增 AI_CHAT 审计",
          st == 503 and len(audit_rows("AI_CHAT")) == DEGRADED_BASE["chats"],
          "HTTP %s｜AI_CHAT 行数 %d（基线 %d）"
          % (st, len(audit_rows("AI_CHAT")), DEGRADED_BASE["chats"]))


# ================================================================ main

def main():
    global BUSINESS_BEFORE, DEGRADED_BASE
    print("批次 5 AI 编排层自测（实现方自测）：隔离库副本 %s" % ISO_DB)
    print("演示库 data/app.db（全程只读）指纹｜开始：%s"
          % json.dumps(demo_fingerprint(), ensure_ascii=False))
    try:
        kill_ports(PORT_MOCK, PORT_DEFAULT)
        prepare_db()
        BUSINESS_BEFORE = business_counts()
        global AUDIT_BASE
        AUDIT_BASE = {"chats": len(audit_rows("AI_CHAT")), "tools": len(audit_rows("AI_TOOL_CALL")),
                      "sql": len(audit_rows("AI_SQL_QUERY"))}
        print("隔离库审计基线（继承自演示库的历史行）：%s" % json.dumps(AUDIT_BASE))
        print("隔离库业务表行数基线：%s" % json.dumps(BUSINESS_BEFORE, ensure_ascii=False))
        phase_mock()
        DEGRADED_BASE = {"chats": len(audit_rows("AI_CHAT"))}
        phase_inprocess()
        phase_degraded()
    finally:
        stop_servers()
        if os.path.exists(ISO_DB):
            print("\n隔离库业务表行数终值：%s" % json.dumps(business_counts(),
                                                           ensure_ascii=False))
        print("演示库 data/app.db（全程只读）指纹｜结束：%s"
              % json.dumps(demo_fingerprint(), ensure_ascii=False))
        cleanup_db()
        print("已删除隔离库副本：%s（含 -wal/-shm）" % ISO_DB)

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = [n for n, ok, _d in RESULTS if not ok]
    section("自测汇总")
    print("  断言 %d 项：PASS %d / FAIL %d" % (len(RESULTS), passed, len(failed)))
    if failed:
        for name in failed:
            print("  FAIL：%s" % name)
    if NOTES:
        print("  备注：")
        for note in NOTES:
            print("    - %s" % note)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
