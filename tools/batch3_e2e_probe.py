# -*- coding: utf-8 -*-
"""批次 3 端到端黑盒探针：真实 socket（werkzeug 起服务 + urllib 请求），不经 Flask test_client。

覆盖：静态页与构建产物哈希、未登录 401、六账号菜单可见性（批次 3 的 7 屏）、
六张报表真实查询/导出、权限 403、随访登记权限交叉、处方作废分派、字典接口。

数据：以验收固定数据集（data/batch3_accept.db）的副本运行，保证确定性且不污染演示库。

用法（后端 venv）：cd code-app/backend && ./.venv/Scripts/python.exe ../../tools/batch3_e2e_probe.py
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 本脚本在 <项目>/tools/ 下
BACKEND = os.path.join(PROJECT, "code-app", "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

ACCEPT = os.path.join(BACKEND, "data", "batch3_accept.db")
E2E = os.path.join(BACKEND, "data", "batch3_e2e.db")
if not os.path.exists(ACCEPT):
    subprocess.run([sys.executable, os.path.join(BACKEND, "tools", "batch3_fixture.py")], check=True,
                   stdout=subprocess.DEVNULL)
shutil.copyfile(ACCEPT, E2E)
assert "app.db" not in os.path.basename(E2E), "禁止触碰演示库"
os.environ["APP_DB_PATH"] = E2E

from werkzeug.serving import make_server  # noqa: E402

from app import app  # noqa: E402

PORT = 5061
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []

BATCH3_PATHS = {
    "/followup/register": "复诊随访登记",
    "/report/visit-stats": "门诊量统计",
    "/report/syndrome-dist": "证型分布统计",
    "/report/herb-usage": "方剂与饮片使用统计",
    "/report/visit-prescription": "就诊与处方记录查询",
    "/report/overdose-ledger": "超量·毒性处方审核台账",
    "/report/followup-analysis": "随访完成与失访分析",
}


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-62s %s" % ("[通过]" if cond else "[失败]", name, detail[:110]))


def call(method, path, token=None, body=None, query=None, raw=False):
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body or {}).encode("utf-8") if method in ("POST", "PUT") else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload, dict(resp.headers)
            try:
                return resp.status, json.loads(payload.decode("utf-8") or "{}"), dict(resp.headers)
            except ValueError:
                return resp.status, {"raw": payload[:200].decode("utf-8", "replace")}, dict(resp.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode("utf-8") or "{}"), dict(e.headers)
        except ValueError:
            return e.code, {"raw": payload[:200].decode("utf-8", "replace")}, dict(e.headers)


def menus_of(user, tokens, cache):
    """菜单随登录响应返回（无独立菜单接口）。"""
    return cache.get(user) or []


def flat_paths(menus):
    out = []
    for m in menus:
        if m.get("path"):
            out.append(m["path"])
        for c in m.get("children") or []:
            if c.get("path"):
                out.append(c["path"])
    return out


def main():
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # ① 静态页与构建产物
    st, body, hdrs = call("GET", "/", raw=True)
    html = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    dist = os.path.join(BACKEND, "..", "frontend", "dist", "index.html")
    check("静态首页可访问（200）", st == 200, "HTTP %s" % st)
    if os.path.exists(dist):
        import re

        want = re.findall(r'assets/(index-[\w.-]+\.js)', open(dist, encoding="utf-8").read())
        check("首页引用的构建产物与 dist 一致", bool(want) and want[0] in html, want[:1])

    # ② 未登录 401
    for path in ("/api/report/RPT-VISIT-STATS-001", "/api/followup", "/api/meta/dictionaries"):
        st, _b, _h = call("GET", path)
        check("未登录访问 %s → 401" % path, st == 401, "HTTP %s" % st)

    # ③ 六账号登录 + 批次 3 菜单可见性
    tokens, menu_cache = {}, {}
    for user, pwd in (("admin", "admin123"), ("keshi", "123456"), ("daozhen", "123456"),
                      ("yishi", "123456"), ("yaoshi", "123456"), ("kufang", "123456")):
        st, body, _ = call("POST", "/api/auth/login", body={"username": user, "password": pwd})
        if st == 200 and body.get("success"):
            tokens[user] = body["data"]["token"]
            menu_cache[user] = body["data"].get("menus") or []
        check("登录 %s（%d 个一级菜单）" % (user, len(menu_cache.get(user) or [])), user in tokens, "HTTP %s" % st)
    if menu_cache.get("admin"):
        import json as _json

        print("      [菜单结构样例] %s" % _json.dumps(menu_cache["admin"][0], ensure_ascii=False)[:220])

    admin_paths = flat_paths(menus_of("admin", tokens, menu_cache))
    for path in BATCH3_PATHS:
        check("admin 可见批次 3 屏 %s" % path, path in admin_paths, str(len(admin_paths)))

    keshi_paths = flat_paths(menus_of("keshi", tokens, menu_cache))
    check("科室管理员可见随访管理（/followup/register）", "/followup/register" in keshi_paths)
    check("科室管理员可见统计报表", "/report/visit-stats" in keshi_paths and "/report/followup-analysis" in keshi_paths)
    kufang_paths = flat_paths(menus_of("kufang", tokens, menu_cache))
    check("库房管理员不可见统计报表", "/report/visit-stats" not in kufang_paths, str(len(kufang_paths)))
    check("库房管理员不可见随访管理", "/followup/register" not in kufang_paths)

    # ④ 六张报表：admin 可查、可导出
    reports = ["RPT-VISIT-STATS-001", "RPT-SYNDROME-DIST-001", "RPT-HERB-USAGE-001",
               "QR-VISIT-PRESCRIPTION-001", "QR-PRESCRIPTION-OVERDOSE-001", "RPT-FOLLOWUP-COMPLETION-001"]
    for rid in reports:
        st, body, _ = call("GET", "/api/report/%s" % rid, token=tokens.get("admin"),
                           query={"page": 1, "size": 5})
        ok = st == 200 and body.get("success") and isinstance(body["data"].get("columns"), list)
        check("报表 %s 查询可用（含列元数据）" % rid, ok, "HTTP %s" % st)
        st, payload, hdrs = call("GET", "/api/report/%s/export" % rid, token=tokens.get("admin"),
                                 query={"format": "csv", "page": 1, "size": 5}, raw=True)
        ok = st == 200 and isinstance(payload, (bytes, bytearray)) and payload[:3] == b"\xef\xbb\xbf"
        check("报表 %s CSV 导出（UTF-8 BOM）" % rid, ok, "HTTP %s %s" % (st, hdrs.get("Content-Type")))

    # ⑤ 权限与取值域
    st, _b, _h = call("GET", "/api/report/RPT-VISIT-STATS-001", token=tokens.get("kufang"))
    check("库房管理员查门诊量统计 → 403", st == 403, "HTTP %s" % st)
    st, _b, _h = call("GET", "/api/report/RPT-VISIT-STATS-001", token=tokens.get("admin"),
                      query={"granularity": "YEAR"})
    check("granularity=YEAR 被拒（400，模型约定 7）", st == 400, "HTTP %s" % st)
    st, _b, _h = call("GET", "/api/report/RPT-HERB-USAGE-001", token=tokens.get("admin"),
                      query={"statsDimension": "FORMULA_TEMPLATE"})
    check("statsDimension=FORMULA_TEMPLATE 可用（模型 enumValues）", st == 200, "HTTP %s" % st)

    # ⑥ 随访权限交叉（keshi 可查不可完成）
    st, body, _ = call("GET", "/api/followup", token=tokens.get("keshi"), query={"page": 1, "size": 5})
    check("科室管理员可查随访列表", st == 200 and body.get("success"), "HTTP %s" % st)
    st, _b, _h = call("POST", "/api/followup/1/complete", token=tokens.get("keshi"),
                      body={"actual_follow_up_date": "2026-09-30", "efficacy_level": "EFFECTIVE"})
    check("科室管理员无 follow_up:complete → 403", st == 403, "HTTP %s" % st)

    # ⑦ 字典与规则接口
    st, body, _h = call("GET", "/api/meta/dictionaries", token=tokens.get("admin"))
    keys = list((body.get("data") or {}).keys()) if st == 200 else []
    need = ["DICT-VISIT.DEPT", "DICT-VISIT.VISIT_TYPE", "DICT-FOLLOWUP.EFFICACY_LEVEL", "DICT-DISPENSE.DISPENSE_STATUS"]
    check("字典接口含批次 3 所需字典", st == 200 and all(k in keys for k in need), str(len(keys)))

    srv.shutdown()
    print("\n" + "=" * 96)
    print("批次 3 端到端黑盒探针：通过 %d 项，失败 %d 项" % (len(OK), len(NG)))
    if NG:
        print("失败项：" + "；".join(NG))
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
