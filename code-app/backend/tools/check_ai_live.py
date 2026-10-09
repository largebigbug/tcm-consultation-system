# -*- coding: utf-8 -*-
"""AI 联通性实测：登录 → 查 /api/ai/status → 真发一条对话 → 打印结果。

用法（服务需在运行）：
    code-app/backend/.venv/Scripts/python.exe code-app/backend/tools/check_ai_live.py [端口]
默认端口 5000，账号默认 admin/admin123（可用 --user/--password 覆盖）。

只读用途：只做一次对话请求（会在 audit_logs 里留下一条 AI 工具审计，属正常）。
**不打印任何密钥**，只报 enabled/provider/model 与回复正文。
"""
import json
import sys
import urllib.error
import urllib.request

PORT = "5000"
USER, PWD = "admin", "admin123"
for i, a in enumerate(sys.argv[1:], 1):
    if a == "--port" and len(sys.argv) > i + 1:
        PORT = sys.argv[i + 1]
    if a == "--user" and len(sys.argv) > i + 1:
        USER = sys.argv[i + 1]
    if a == "--password" and len(sys.argv) > i + 1:
        PWD = sys.argv[i + 1]
BASE = "http://127.0.0.1:%s" % PORT


def call(method, path, body=None, token=None, stream=False, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (raw if stream else json.loads(raw.decode() or "{}"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode() or "{}")
        except ValueError:
            return exc.code, {"_raw": raw.decode("utf-8", "replace")[:200]}


def main():
    print("=" * 78)
    print("AI 联通性实测 → %s" % BASE)
    print("=" * 78)
    st, b = call("POST", "/api/auth/login", {"username": USER, "password": PWD})
    token = (b.get("data") or {}).get("token") if st == 200 else None
    print("[1] 登录 %s：HTTP %s %s" % (USER, st, "成功" if token else "失败"))
    if not token:
        print("    → 服务未运行，或账号密码不对")
        return 1

    st, b = call("GET", "/api/ai/status", token=token)
    d = b.get("data") or {}
    print("[2] /api/ai/status：HTTP %s" % st)
    print("    enabled   = %s" % d.get("enabled"))
    print("    configured= %s" % d.get("configured"))
    print("    provider  = %s / model = %s" % (d.get("provider"), d.get("model")))
    print("    hint      = %s" % d.get("hint"))
    if not d.get("enabled"):
        print("\n[结论] AI 仍未启用 —— 按上面的 hint 配好凭据后重启服务再跑一次。")
        return 2

    print("\n[3] 真发一条对话（SSE 流式）…")
    st, raw = call("POST", "/api/ai/chat", {"message": "用一句话介绍你能为中医师做什么"}, token=token,
                   stream=True, timeout=120)
    if st != 200:
        print("    HTTP %s：%s" % (st, raw[:300]))
        return 3
    text = raw.decode("utf-8", "replace")
    events, chunks = [], []
    for line in text.splitlines():
        if line.startswith("event:"):
            events.append(line.split(":", 1)[1].strip())
        if line.startswith("data:"):
            payload = line[5:].strip()
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            for k in ("delta", "text", "content"):
                v = obj.get(k)
                if isinstance(v, str):
                    chunks.append(v)
    print("    事件序列：%s" % (" → ".join(events[:12]) or "（无）"))
    reply = "".join(chunks).strip()
    print("    模型回复（前 300 字）：")
    print("      " + (reply[:300].replace("\n", "\n      ") if reply else "（空）"))
    print("\n[结论] %s" % ("✅ AI 已真实联通" if reply else "⚠️ 有响应但没有文本内容，请看事件序列"))
    return 0 if reply else 4


if __name__ == "__main__":
    sys.exit(main())
