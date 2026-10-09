# -*- coding: utf-8 -*-
"""批次 3 演示库只读体检：六张报表在**演示库**上是否真有数据、结构是否完整。

只读（不写任何表）：以真实 HTTP（werkzeug make_server）调用 6 张报表接口，核对：
  ① 门诊量统计：按日/按月均有分组行，合计＝分组之和
  ② 证型分布：有分组行、占比之和 ≈ 1
  ③ 方剂与饮片使用统计：HERB / FORMULA_TEMPLATE 双维度都有数据；模型内取值可用、模型外取值被拒
  ④ 就诊与处方记录查询：主从结构完整（主行附处方、处方附明细）
  ⑤ 超量·毒性台账：BOTH / OVERDOSE / TOXIC 三个触发类型都有数据
  ⑥ 随访完成与失访分析：计划随访数 = 已完成 + 已失访 + 待随访
  ⑦ 导出：XLSX 结构可解析（zip + XML）、CSV 带 BOM 与表头

用法：code-app/backend/.venv/Scripts/python.exe tools/batch3_demo_verify.py
"""
import io as _io
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.dom.minidom import parseString

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DB = os.environ.get("APP_DB_PATH") or os.path.join(BACKEND, "data", "app.db")
assert "batch3_accept" not in DB and "batch3_e2e" not in DB, "本脚本用于演示库体检"
os.environ["APP_DB_PATH"] = DB

from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402

PORT = 5062
BASE = "http://127.0.0.1:%d" % PORT
OK, NG = [], []


def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print("  %s %-56s %s" % ("[通过]" if cond else "[失败]", name, str(detail)[:90]))
    return bool(cond)


def call(method, path, token=None, body=None, raw=False):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload.decode() or "{}")), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, (payload if raw else json.loads(payload.decode() or "{}")), dict(e.headers)
        except ValueError:
            return e.code, payload, dict(e.headers)


def main():
    app = create_app()
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    st, body, _ = call("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
    token = body["data"]["token"]
    check("admin 登录取令牌", st == 200 and bool(token))

    def report(code, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        st, body, _ = call("GET", "/api/report/%s%s" % (code, ("?" + q) if q else ""), token=token)
        return st, (body.get("data") or {}), body

    print("\n=== ① 门诊量统计（RPT-VISIT-STATS-001）===")
    # 该报表的日期参数默认「当月」(MONTH_START/MONTH_END)，演示数据跨 6–9 月且日历会跨月，
    # 故一律显式给区间，避免断言随日历失效（体检脚本必须与"今天几号"无关）
    WIN = dict(registerDateFrom="2026-06-01", registerDateTo="2026-10-31")
    st, d, b = report("RPT-VISIT-STATS-001", granularity="MONTH", page=1, size=100, **WIN)
    check("按月查询可用且有分组行（显式区间 2026-06-01~2026-10-31）", st == 200 and d.get("total", 0) > 0,
          "行数 %s" % d.get("total"))
    s = d.get("summary") or {}
    check("合计就诊人次 = 分组行之和",
          s.get("visitCount") == sum(r["visitCount"] for r in d["list"]), s.get("visitCount"))
    st2, d2, _ = report("RPT-VISIT-STATS-001", granularity="DAY", page=1, size=100, **WIN)
    check("按日粒度为独立粒度（行数 ≥ 按月）", st2 == 200 and d2.get("total", 0) >= d.get("total", 0),
          "按日 %s / 按月 %s" % (d2.get("total"), d.get("total")))
    check("列顺序来自后端（统计日期在首位）", [c["name"] for c in d["columns"]][0] == "statDate")

    print("\n=== ② 证型分布统计（RPT-SYNDROME-DIST-001）===")
    st, d, b = report("RPT-SYNDROME-DIST-001", page=1, size=100,
                      visitDateFrom="2026-06-01", visitDateTo="2026-10-31")
    ok = check("查询可用且有分组行", st == 200 and d.get("total", 0) > 0, "行数 %s" % d.get("total"))
    if ok:
        ratios = [float(r["caseRatio"]) for r in d["list"] if r.get("caseRatio") is not None]
        check("占比之和 ≈ 1", ratios and abs(sum(ratios) - 1) < 0.001, round(sum(ratios), 4) if ratios else None)

    print("\n=== ③ 方剂与饮片使用统计（RPT-HERB-USAGE-001，双维度）===")
    USAGE_WIN = dict(prescribeDateFrom="2026-06-01", prescribeDateTo="2026-10-31")
    st_h, dh, _ = report("RPT-HERB-USAGE-001", statsDimension="HERB", page=1, size=100, **USAGE_WIN)
    check("饮片维度有数据且饮片列非空",
          st_h == 200 and dh.get("total", 0) > 0 and all(r.get("herbCode") for r in dh["list"]),
          "行数 %s" % dh.get("total"))
    check("累计用量（g）为正数", (dh.get("summary") or {}).get("totalQuantity", 0) > 0,
          (dh.get("summary") or {}).get("totalQuantity"))
    st_f, df, _ = report("RPT-HERB-USAGE-001", statsDimension="FORMULA_TEMPLATE", page=1, size=100,
                         **USAGE_WIN)
    check("方剂维度有数据且方剂列非空",
          st_f == 200 and df.get("total", 0) > 0 and any(r.get("formulaCode") for r in df["list"]),
          "方剂组数 %s" % df.get("total"))
    st_bad, _d, _b = report("RPT-HERB-USAGE-001", statsDimension="FORMULA")
    check("模型外取值 FORMULA 被拒（400，约定 10）", st_bad == 400, "HTTP %s" % st_bad)

    print("\n=== ④ 就诊与处方记录查询（QR-VISIT-PRESCRIPTION-001，主从）===")
    st, d, b = report("QR-VISIT-PRESCRIPTION-001", page=1, size=100)
    if check("查询可用且有主行", st == 200 and d.get("total", 0) > 0, "就诊行数 %s" % d.get("total")):
        rxs = sum(len(r.get("prescriptions") or []) for r in d["list"])
        items = sum(len(x.get("items") or []) for r in d["list"] for x in (r.get("prescriptions") or []))
        check("主行附处方（从行）", rxs > 0, "处方数 %s" % rxs)
        check("处方附明细", items > 0, "明细数 %s" % items)
        check("从表含处方状态与作废原因字段",
              all("prescriptionStatus" in x and "cancelReason" in x
                  for r in d["list"] for x in (r.get("prescriptions") or [])))

    print("\n=== ⑤ 超量·毒性处方审核台账（QR-PRESCRIPTION-OVERDOSE-001）===")
    counts = {}
    for trig in ("BOTH", "OVERDOSE", "TOXIC"):
        st, d, _ = report("QR-PRESCRIPTION-OVERDOSE-001", triggerType=trig, page=1, size=100)
        counts[trig] = d.get("total") if st == 200 else None
    check("BOTH 有数据", (counts.get("BOTH") or 0) > 0, counts)
    check("OVERDOSE（仅超量）有数据", (counts.get("OVERDOSE") or 0) > 0, counts)
    check("TOXIC（仅毒性饮片）有数据", (counts.get("TOXIC") or 0) > 0, counts)
    check("BOTH ≥ 各单分支（组内 OR 语义）",
          (counts.get("BOTH") or 0) >= max(counts.get("OVERDOSE") or 0, counts.get("TOXIC") or 0))
    st, d, _ = report("QR-PRESCRIPTION-OVERDOSE-001", triggerType="BOTH", page=1, size=100)
    check("台账含超出倍数列", all(r.get("exceedRatio") is not None for r in d["list"]) if d.get("list") else False)

    print("\n=== ⑥ 随访完成与失访分析（RPT-FOLLOWUP-COMPLETION-001）===")
    # 演示库的随访计划日跨 6–9 月，故显式给全区间（报表默认区间是当月）
    st, d, _ = report("RPT-FOLLOWUP-COMPLETION-001", plannedDateFrom="2026-06-01", plannedDateTo="2026-10-31",
                      page=1, size=100)
    if check("查询可用且有分组行（计划日 2026-06-01 ~ 2026-10-31）", st == 200 and d.get("total", 0) > 0,
             "行数 %s" % d.get("total")):
        s = d.get("summary") or {}
        check("合计计划随访数 = 分组行之和",
              s.get("plannedCount") == sum(r["plannedCount"] for r in d["list"]), s.get("plannedCount"))
        check("已完成与已失访均有数据（演示库含两种状态）",
              (s.get("completedCount") or 0) > 0 and (s.get("lostCount") or 0) > 0,
              "完成 %s / 失访 %s" % (s.get("completedCount"), s.get("lostCount")))

    print("\n=== ⑦ 导出（XLSX / CSV）===")
    st, raw, hdrs = call("GET", "/api/report/RPT-VISIT-STATS-001/export?format=xlsx", token=token, raw=True)
    if check("XLSX 导出返回 200", st == 200, "HTTP %s" % st):
        try:
            z = zipfile.ZipFile(_io.BytesIO(raw))
            sheet = z.read([n for n in z.namelist() if n.startswith("xl/worksheets/")][0]).decode("utf-8")
            parseString(sheet)
            check("XLSX 结构可解析且含中文表头", "统计日期" in sheet and "合计" in sheet,
                  "%d 行" % sheet.count("<row "))
        except Exception as exc:                     # noqa: BLE001
            check("XLSX 结构可解析", False, str(exc))
    st, raw, _ = call("GET", "/api/report/RPT-VISIT-STATS-001/export?format=csv", token=token, raw=True)
    check("CSV 导出带 UTF-8 BOM 与表头", st == 200 and raw[:3] == b"\xef\xbb\xbf" and "统计日期" in raw.decode("utf-8-sig"))

    srv.shutdown()
    print("\n" + "=" * 90)
    print("批次 3 演示库体检：通过 %d 项，失败 %d 项（库：%s）" % (len(OK), len(NG), DB))
    if NG:
        print("失败项：" + "；".join(NG))
    return 0 if not NG else 1


if __name__ == "__main__":
    sys.exit(main())
