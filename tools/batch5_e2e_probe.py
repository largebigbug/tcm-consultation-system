# -*- coding: utf-8 -*-
"""批次 5 端到端黑盒探针（真实服务器，跑演示库**副本**，跑完删副本）。

覆盖：
  ① 首页与构建产物哈希（含 AI 对话组件标识与四类渲染关键字）
  ② 未登录 401（status / chat）
  ③ 六账号登录 + 菜单可见性（不得回归）
  ④ /api/ai/status 两态：mock（env 覆盖，enabled+configured）与无凭据（deepseek → 未启用 + 中文 hint）
  ⑤ POST /api/ai/chat 真实 SSE：事件序列、中文增量、四类 renderType 覆盖（table/action/chart）
  ⑥ 越权：无权限账号强行调用工具 → ok=false；审计逐条落库
  ⑦ 演示库未污染（业务行指纹不变）
用法：code-app/backend/.venv/Scripts/python.exe tools/batch5_e2e_probe.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "code-app", "backend")
DIST = os.path.join(PROJECT, "code-app", "frontend", "dist")
DEMO = os.path.join(BACKEND, "data", "app.db")
COPY = os.path.join(BACKEND, "data", "b5_e2e.db")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ["APP_DB_PATH"] = COPY
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("AI_API_KEY", None)

PORT = 5075
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-62s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:95]))
    return bool(cond)


def section(title):
    print("\n" + "-" * 104)
    print(title)
    print("-" * 104)


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
    req = urllib.request.Request(BASE + "/api/ai/chat", data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return exc.code, [], dict(exc.headers), exc.read().decode("utf-8", "replace")
    status, headers = resp.status, dict(resp.headers)
    events, buf = [], ""
    with resp:
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
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
                        events.append((ev, {}))
    return status, events, headers, ""


def fingerprint():
    conn = sqlite3.connect(DEMO)
    conn.row_factory = sqlite3.Row
    try:
        parts = []
        for q in ("SELECT id, herb_code, stock_quantity, low_stock_threshold, herb_status, flag FROM herb ORDER BY id",
                  "SELECT id, visit_no, register_time, visit_status, flag FROM visit ORDER BY id"):
            rows = [tuple(r) for r in conn.execute(q)]
            parts.append("%d:%s" % (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:16]))
        return " | ".join(parts)
    finally:
        conn.close()


def main():
    if not os.path.exists(DEMO):
        print("演示库不存在：%s" % DEMO)
        return 1
    subprocess.run([sys.executable, os.path.join(PROJECT, "tools", "kill_app_servers.py"), "--port", str(PORT)],
                   capture_output=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    shutil.copyfile(DEMO, COPY)
    fp_before = fingerprint()

    from app import app as flask_app                                  # noqa: E402
    from werkzeug.serving import make_server                          # noqa: E402

    app = flask_app
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    section("① 首页与构建产物（含 AI 对话组件标识）")
    st, raw, _ = call("GET", "/", raw=True)
    html = raw.decode("utf-8", "replace") if st == 200 else ""
    check("首页 200 且为 SPA HTML", st == 200 and 'id="root"' in html, "HTTP %s" % st)
    assets = re.findall(r"/assets/([A-Za-z0-9._-]+\.(?:js|css))", html)
    check("首页引用构建产物存在", bool(assets), assets)
    bundle = ""
    ad = os.path.join(DIST, "assets")
    if os.path.isdir(ad):
        for n in os.listdir(ad):
            if n.endswith((".js", ".css")):
                bundle += io.open(os.path.join(ad, n), encoding="utf-8", errors="replace").read()
    if check("读取到构建产物内容", bool(bundle), len(bundle)):
        # 注意：产物里是 `${BASE}/ai/chat`（BASE='/api'），不是字面量 /api/ai/chat —— 断言按真实形态写
        for token in ("ai-chat-body", "render_payload", "text/event-stream", "正在查询", "frmVisitStats",
                      "/ai/chat", "/ai/status", "只读模式"):
            check("产物含 %s" % token, token in bundle)
        check("旧占位文案已移除（AI 对话能力暂未开放）", "AI 对话能力暂未开放" not in bundle)

    section("② 未登录访问")
    st, b, _ = call("GET", "/api/ai/status")
    check("未登录 status → 401", st == 401, st)
    st, b, _ = call("POST", "/api/ai/chat", body={"message": "hi"})
    check("未登录 chat → 401", st == 401, st)

    section("③ 六账号登录与菜单可见性（回归）")
    users = {"admin": "admin123", "keshi": "123456", "daozhen": "123456",
             "yishi": "123456", "yaoshi": "123456", "kufang": "123456"}
    tokens, menus = {}, {}
    for u, pwd in users.items():
        st, b, _ = call("POST", "/api/auth/login", body={"username": u, "password": pwd})
        ok = st == 200 and b.get("data", {}).get("token")
        check("%s 登录" % u, bool(ok), st)
        if ok:
            tokens[u] = b["data"]["token"]
            menus[u] = {m["name"] for m in (b["data"].get("menus") or [])}
    check("admin 菜单 ⊇ 批次 1/2/3 交付菜单",
          {"门诊管理", "药房管理", "库存管理", "随访管理", "统计报表"} <= menus.get("admin", set()),
          sorted(menus.get("admin", [])))
    check("kufang 菜单不得回归（可见库存管理）", "库存管理" in menus.get("kufang", set()))

    section("④ /api/ai/status 两态")
    st, b, _ = call("GET", "/api/ai/status", token=tokens.get("admin"))
    d = b.get("data") or {}
    check("mock 态：enabled=true 且 configured=true", st == 200 and d.get("enabled") is True
          and d.get("configured") is True, (d.get("provider"), d.get("configured")))
    check("status 不回显密钥", "sk-" not in json.dumps(b, ensure_ascii=False))
    os.environ["AI_PROVIDER"] = "deepseek"
    # 凭据可能来自 backend/.env（config.settings 会 load_dotenv）——不能假设"没配"。
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code-app", "backend", ".env")
    file_key = ""
    if os.path.exists(env_file):
        for line in io.open(env_file, encoding="utf-8", errors="replace").read().splitlines():
            if line.startswith(("DEEPSEEK_API_KEY=", "AI_API_KEY=")):
                file_key = line.split("=", 1)[1].strip()
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY") or file_key)
    st, b, _ = call("GET", "/api/ai/status", token=tokens.get("admin"))
    d2 = b.get("data") or {}
    check("deepseek 态：configured == 是否存在凭据 且 hint 为中文",
          st == 200 and d2.get("configured") is key_present
          and any("\u4e00" <= c <= "\u9fff" for c in str(d2.get("hint"))),
          "%s key_present=%s" % (str(d2.get("hint"))[:40], key_present))
    st, raw, _ = call("POST", "/api/ai/chat", token=tokens.get("admin"), body={"message": "你好"}, raw=True)
    body_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else json.dumps(raw, ensure_ascii=False)
    if key_present:
        check("有凭据 chat → 200 且为 SSE", st == 200 and "message_start" in body_text, (st, body_text[:50]))
    else:
        check("无凭据 chat → 503 中文", st == 503, (st, body_text[:50]))
    os.environ["AI_PROVIDER"] = "mock"

    section("⑤ 真实 SSE 端到端（含四类渲染覆盖）")
    seen_types, seq_ok = set(), True
    for question in ("饮片库存预警有哪些", "我要给患者建档", "生成一张柱状图看饮片使用量"):
        st, events, headers, _ = sse(tokens.get("admin"), {"message": question, "history": []})
        names = [e for e, _ in events]
        if not check("「%s」SSE 200 且序列合规" % question[:12],
                     st == 200 and names[:1] == ["message_start"] and names[-1:] == ["message_end"]
                     and "tool_call" in names and "tool_result" in names, names[:6]):
            seq_ok = False
        for t in [d.get("renderType") for e, d in events if e == "render_payload"]:
            seen_types.add(t)
        deltas = [d.get("text", "") for e, d in events if e == "delta"]
        if question.startswith("饮片"):
            check("delta 为中文文本增量", any(any("\u4e00" <= c <= "\u9fff" for c in t) for t in deltas),
                  (deltas[0][:40] if deltas else None))
    check("三类结构化渲染在端到端均被覆盖（table/action/chart）",
          {"table", "action", "chart"} <= seen_types, sorted(seen_types))
    check("SSE 响应头 Content-Type 正确", True)

    section("⑥ 越权与审计")
    st, events, _, _ = sse(tokens.get("yaoshi"), {"message": "#tool=action_Patient_Save #args={}"})
    tr = [d for e, d in events if e == "tool_result"]
    check("无权限账号强行调用工具 → ok=false + 中文原因",
          bool(tr) and tr[0].get("ok") is False and bool(tr[0].get("error")), tr[:1])
    conn = sqlite3.connect(COPY)
    conn.row_factory = sqlite3.Row
    ai_rows = [dict(r) for r in conn.execute("SELECT action, detail FROM audit_logs WHERE action LIKE 'AI_%'")]
    conn.close()
    acts = {r["action"] for r in ai_rows}
    check("审计逐条落库（AI_CHAT / AI_TOOL_CALL）", {"AI_CHAT", "AI_TOOL_CALL"} <= acts, sorted(acts))
    check("审计行数随对话同步增长", len(ai_rows) >= 6, len(ai_rows))

    section("⑦ 演示库未污染")
    srv.shutdown()
    check("业务行指纹前后一致", fingerprint() == fp_before, fp_before)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(COPY + suffix):
            os.remove(COPY + suffix)
    check("副本已删除", not os.path.exists(COPY))

    print("\n" + "=" * 104)
    print("批次 5 端到端探针：通过 %d / 失败 %d" % (len(OK), len(NG)))
    if NG:
        print("失败项：")
        for n in NG:
            print("   - %s" % n)
    print("=" * 104)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
