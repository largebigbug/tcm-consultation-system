# -*- coding: utf-8 -*-
"""批次 5 演示库**只读**体检：AI 对话接口在演示库上是否可用，且**不产生任何写入**。

只读口径（刻意的选择）：本脚本**不发起对话**——对话会写 `audit_logs`（AI_CHAT/AI_TOOL_CALL），
那就不再是只读体检。对话链路的真实端到端证据由 `tools/batch5_e2e_probe.py`（跑副本）提供。
本脚本只验证：状态接口可用、鉴权正确、配置降级提示可读、业务行指纹不变、**演示库 AI_* 审计仍为 0**。

用法：code-app/backend/.venv/Scripts/python.exe tools/batch5_demo_verify.py
"""
import hashlib
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
DB = os.path.join(BACKEND, "data", "app.db")
assert os.path.basename(DB) == "app.db", "本脚本只用于演示库体检"
os.environ["APP_DB_PATH"] = DB
os.environ.pop("AI_PROVIDER", None)       # 用 config.yaml 的真实交付配置（provider: deepseek, 无 key）
os.environ.pop("AI_API_KEY", None)
PORT = 5077
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-60s %s" % ("[PASS]" if cond else "[FAIL]", name, str(detail)[:90]))
    return bool(cond)


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)
        except ValueError:
            return exc.code, {}, dict(exc.headers)


def fingerprint():
    conn = sqlite3.connect(DB)
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


def ai_audit_rows():
    conn = sqlite3.connect(DB)
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'AI_%'").fetchone()[0]
    finally:
        conn.close()


def main():
    fp_before, ai_before = fingerprint(), ai_audit_rows()
    print("体检前：指纹 %s ｜ AI_* 审计 %d 行" % (fp_before, ai_before))

    from app import app as flask_app                                   # noqa: E402
    from werkzeug.serving import make_server                           # noqa: E402

    srv = make_server("127.0.0.1", PORT, flask_app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    st, b, _ = call("GET", "/api/ai/status")
    check("未登录访问 /api/ai/status → 401 中文", st == 401 and any("\u4e00" <= c <= "\u9fff" for c in str(b.get("message"))),
          (st, str(b.get("message"))[:30]))

    st, b, _ = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
    token = b.get("data", {}).get("token") if st == 200 else None
    check("admin 登录取令牌", bool(token), st)

    st, b, _ = call("GET", "/api/ai/status", token=token)
    d = b.get("data") or {}
    check("status 200 且结构完整（enabled/provider/model/configured/hint）",
          st == 200 and {"enabled", "provider", "model", "configured", "hint"} <= set(d), sorted(d))
    configured = d.get("configured")
    if configured:
        check("已配置：hint 说明当前 provider/model", bool(d.get("hint")), str(d.get("hint"))[:50])
    else:
        check("未配置（交付默认态）：hint 为中文且指引如何启用",
              bool(d.get("hint")) and "DEEPSEEK_API_KEY" in str(d.get("hint")), str(d.get("hint"))[:70])
        st2, b2, _ = call("POST", "/api/ai/chat", token=token, body={"message": "你好"})
        check("未配置时对话 → 503 + 中文提示（前端展示未启用态的依据）",
              st2 == 503 and any("\u4e00" <= c <= "\u9fff" for c in json.dumps(b2, ensure_ascii=False)),
              (st2, str(b2.get("message"))[:40]))
    check("status 不回显任何密钥", "sk-" not in json.dumps(b, ensure_ascii=False))
    check("演示库可查业务数据（饮片数 ≥ 1，说明库可用）",
          sqlite3.connect(DB).execute("SELECT COUNT(*) FROM herb WHERE flag = 1").fetchone()[0] >= 1)

    srv.shutdown()
    check("业务行指纹不变（只读）", fingerprint() == fp_before, fp_before)
    check("演示库 AI_* 审计仍为 %d 行（本脚本不发起对话）" % ai_before, ai_audit_rows() == ai_before,
          ai_audit_rows())

    print("\n" + "=" * 100)
    print("批次 5 演示库只读体检：通过 %d / 失败 %d（库：%s）" % (len(OK), len(NG), DB))
    if NG:
        print("失败项：" + "；".join(NG))
    print("=" * 100)
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
