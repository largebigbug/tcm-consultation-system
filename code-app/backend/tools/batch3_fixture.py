# -*- coding: utf-8 -*-
"""批次 3 独立验收的**隔离固定数据集**（绝不触碰演示库 data/app.db）。

做法：
  1) 删除并重建 data/batch3_accept.db，建表 + ensure_seed（角色/权限/菜单，供登录鉴权）；
  2) 以子进程方式灌入批次 1 基础数据（seed_demo_data）与批次 2 业务数据（seed_batch2_demo）；
  3) 追加批次 3 报表所需的分布型数据：跨 3 个月的挂号、不同科室/医师、已发药处方、
     超量药味、毒性饮片药味、跨月随访（含已失访/各疗效等级）；
  4) 打印数据摘要供人工核对。

用法（后端 venv）：
  code-app/backend/.venv/Scripts/python.exe tools/batch3_fixture.py
"""
import io
import os
import subprocess
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

DB = os.path.join(BACKEND, "data", "batch3_accept.db")
os.environ["APP_DB_PATH"] = DB

import db  # noqa: E402
from config import settings  # noqa: E402
from ontology import registry as registry_module  # noqa: E402

settings_db = settings.resolve_db_path()
assert os.path.abspath(settings_db) == os.path.abspath(DB), "APP_DB_PATH 未生效：%s" % settings_db
assert "app.db" not in os.path.basename(DB), "禁止触碰演示库"


def build_schema_and_seed():
    from seed import ensure_seed

    db.init_db_path(DB)
    conn = db.connect()
    try:
        with io.open(os.path.join(BACKEND, "schema.sql"), "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        ensure_seed(conn)
        conn.commit()
    finally:
        conn.close()


def run_script(name):
    p = subprocess.run([sys.executable, os.path.join(BACKEND, "tools", name)],
                       env=dict(os.environ, APP_DB_PATH=DB), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (p.stdout or "")[-300:].strip()
    print("  [%s] exit=%d %s" % (name, p.returncode, tail.replace("\n", " | ")))
    if p.returncode != 0:
        print((p.stderr or "")[-800:])
        raise SystemExit("灌数失败：%s" % name)


def columns(conn, table):
    return [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def extras():
    """报表分布型数据（复制既有行再改写，保证列完整、外键有效）。"""
    conn = db.connect()
    try:
        for t in ("visit", "prescription", "prescription_item", "follow_up", "herb", "syndrome_diagnosis"):
            cols = columns(conn, t)
            assert cols, "表不存在：%s" % t
        need = {
            "visit": ["register_time", "dept_code", "doctor_id", "visit_type", "visit_status", "flag", "patient_id"],
            "prescription": ["prescription_status", "reviewer_id", "review_time", "prescribe_time", "flag"],
            "prescription_item": ["prescription_id", "herb_id", "single_dose", "over_dose_reason", "flag"],
            "follow_up": ["planned_follow_up_date", "actual_follow_up_date", "record_status", "efficacy_level",
                          "actual_visit_id", "flag"],
            "herb": ["max_common_dose", "toxicity_level", "flag"],
        }
        for t, req in need.items():
            miss = [c for c in req if c not in columns(conn, t)]
            assert not miss, "%s 缺列：%s" % (t, miss)

        import re as _re
        import sqlite3 as _sq

        _UPDATED = {}  # 用于生成唯一业务编号的全局序号

        def _bump_no(value, n):
            """把业务编号尾号 +n（如 ZC000001 → ZC900001），无尾号则补后缀。"""
            if value is None:
                return None
            text = str(value)
            m = _re.search(r"(\d+)$", text)
            if m:
                width = len(m.group(1))
                return text[:m.start(1)] + str(int(m.group(1)) + n).zfill(width)
            return "%s-B3%d" % (text, n)

        def copy_row(table, where, updates):
            """复制一行（列名不变）→ 改字段 → 插入，返回新 id。

            业务编号列（*_no）带 UNIQUE 约束，插入冲突时自动改写尾号重试。
            """
            cols = columns(conn, table)
            src = conn.execute("SELECT %s FROM %s WHERE %s LIMIT 1" % (", ".join(cols), table, where)).fetchone()
            assert src, "未找到源行：%s %s" % (table, where)
            base = {c: src[c] for c in cols}
            base.pop("id", None)
            no_cols = [c for c in cols if c.endswith("_no")]
            for attempt in range(1, 12):
                data = dict(base)
                data.update(updates)
                if attempt > 1:
                    key = (table, attempt)
                    _UPDATED[key] = _UPDATED.get(key, 0) + 7
                    for c in no_cols:
                        data[c] = _bump_no(base.get(c), 900000 // (attempt + 1) + _UPDATED[key])
                keys = list(data.keys())
                sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(keys), ", ".join("?" for _ in keys))
                try:
                    return conn.execute(sql, [data[k] for k in keys]).lastrowid
                except _sq.IntegrityError:
                    if attempt >= 11:
                        raise
            raise AssertionError("unreachable")

        # ① 跨月/跨科室/跨医师的就诊分布（报表按「日期粒度 + 科室 + 医师 + 就诊类型」分组）
        plans = [("2026-07-15 09:00:00", "TCM_GYN"), ("2026-07-15 10:30:00", "TCM_GYN"),
                 ("2026-07-28 14:00:00", "ACUPUNCTURE"), ("2026-08-20 08:40:00", "TCM_INTERNAL"),
                 ("2026-08-20 09:10:00", "TCM_PEDIATRIC"), ("2026-09-05 15:20:00", "ACUPUNCTURE")]
        new_visit_ids = []
        for ts, dept in plans:
            vid = copy_row("visit", "flag = 1", {"register_time": ts, "dept_code": dept,
                                                "visit_status": "COMPLETED", "visit_type": "FIRST"})
            new_visit_ids.append(vid)

        # ② 已发药处方（R-04 阻断分支 + 台账 reviewResult 列需要）
        #    注意：必须同步复制其明细，并挂到方剂模板上——否则会产生「无明细处方」，
        #    使饮片维度多出一行空饮片数据、方剂维度被打成一行空值（固定数据集质量要求）
        rx_src = conn.execute("SELECT id FROM prescription WHERE flag = 1 ORDER BY id LIMIT 1").fetchone()
        formula = conn.execute("SELECT id FROM formula_template WHERE flag = 1 ORDER BY id LIMIT 1").fetchone()
        assert rx_src, "缺少可用处方"
        assert formula, "缺少方剂模板（方剂维度需要）"
        issued = copy_row("prescription", "flag = 1",
                          {"prescription_status": "ISSUED", "reviewer_id": 1, "review_time": "2026-08-20 11:00:00",
                           "prescribe_time": "2026-08-20 10:30:00", "formula_template_id": formula["id"]})
        item_cols = [c for c in columns(conn, "prescription_item") if c != "id"]
        for src in conn.execute("SELECT %s FROM prescription_item WHERE prescription_id = ? AND flag = 1"
                                % ", ".join(item_cols), (rx_src["id"],)).fetchall():
            data = {c: src[c] for c in item_cols}
            data["prescription_id"] = issued
            data["flag"] = 1
            conn.execute("INSERT INTO prescription_item (%s) VALUES (%s)"
                         % (", ".join(item_cols), ", ".join("?" for _ in item_cols)),
                         [data[c] for c in item_cols])

        # ③ 超量药味（single_dose > herb.max_common_dose → 触发 OVERDOSE）
        base_herb = conn.execute(
            "SELECT id, max_common_dose FROM herb WHERE flag = 1 AND max_common_dose IS NOT NULL "
            "AND toxicity_level = 'NONE' LIMIT 1").fetchone()
        assert base_herb, "缺少可用饮片（max_common_dose 非空）"
        item_src = conn.execute("SELECT prescription_id FROM prescription_item WHERE flag = 1 LIMIT 1").fetchone()
        copy_row("prescription_item", "flag = 1",
                 {"prescription_id": item_src["prescription_id"], "herb_id": base_herb["id"],
                  "single_dose": float(base_herb["max_common_dose"]) * 2.5,
                  "over_dose_reason": "患者体质壮实，遵师承经验加量，已双签字确认"})

        # ④ 毒性饮片药味（触发 TOXIC 分支；毒性分级取 M1 字典真实 code）
        tox = conn.execute("SELECT id FROM herb WHERE flag = 1 AND toxicity_level IN ('TOXIC','HIGHLY_TOXIC','SLIGHT') "
                           "ORDER BY CASE toxicity_level WHEN 'HIGHLY_TOXIC' THEN 0 WHEN 'TOXIC' THEN 1 ELSE 2 END "
                           "LIMIT 1").fetchone()
        if tox:
            copy_row("prescription_item", "flag = 1",
                     {"prescription_id": item_src["prescription_id"], "herb_id": tox["id"],
                      "single_dose": 3.0, "over_dose_reason": "毒性饮片，按药典上限内使用"})

        # ⑤ 跨月随访分布（计划随访日期分属 8/9 月，含已完成/已失访与各疗效等级）
        fu_src = conn.execute("SELECT id, patient_id, source_visit_id FROM follow_up WHERE flag = 1 LIMIT 1").fetchone()
        assert fu_src, "缺少随访记录"
        fu_plans = [("2026-08-05", "COMPLETED", "CURED"), ("2026-08-25", "COMPLETED", "MARKED_EFFECT"),
                    ("2026-08-25", "COMPLETED", "EFFECTIVE"), ("2026-09-10", "LOST", None),
                    ("2026-09-10", "LOST", None)]
        for d, st, eff in fu_plans:
            v = new_visit_ids.pop() if new_visit_ids else None
            copy_row("follow_up", "flag = 1",
                     {"patient_id": fu_src["patient_id"], "planned_follow_up_date": d,
                      "record_status": st,
                      "actual_follow_up_date": d if st == "COMPLETED" else None,
                      "efficacy_level": eff,
                      "actual_visit_id": v if st == "COMPLETED" else None})
        conn.commit()
    finally:
        conn.close()


def summary():
    conn = db.connect()
    try:
        rows = []
        for t in ("patient", "visit", "syndrome_diagnosis", "prescription", "prescription_item",
                  "dispense_record", "follow_up", "herb", "herb_stock_flow"):
            n = conn.execute("SELECT COUNT(*) c FROM %s WHERE flag = 1" % t).fetchone()["c"]
            rows.append("%s=%d" % (t, n))
        print("  实际数据量：" + "，".join(rows))
        print("  就诊按月：" + str([tuple(r) for r in conn.execute(
            "SELECT substr(register_time,1,7) m, COUNT(*) c FROM visit WHERE flag=1 GROUP BY m ORDER BY m")]))
        print("  就诊按科室：" + str([tuple(r) for r in conn.execute(
            "SELECT dept_code, COUNT(*) c FROM visit WHERE flag=1 GROUP BY dept_code ORDER BY dept_code")]))
        print("  随访按状态：" + str([tuple(r) for r in conn.execute(
            "SELECT record_status, COUNT(*) c FROM follow_up WHERE flag=1 GROUP BY record_status")]))
        print("  超量明细数：" + str(conn.execute(
            "SELECT COUNT(*) c FROM prescription_item i JOIN herb h ON h.id=i.herb_id "
            "WHERE i.flag=1 AND h.flag=1 AND i.single_dose > h.max_common_dose").fetchone()["c"]))
        print("  毒性明细数：" + str(conn.execute(
            "SELECT COUNT(*) c FROM prescription_item i JOIN herb h ON h.id=i.herb_id "
            "WHERE i.flag=1 AND h.flag=1 AND h.toxicity_level IN ('TOXIC','HIGHLY_TOXIC','SLIGHT')").fetchone()["c"]))
    finally:
        conn.close()


def main():
    registry_module.load_ontology()
    if os.path.exists(DB):
        os.remove(DB)
        for suffix in ("-wal", "-shm"):
            if os.path.exists(DB + suffix):
                os.remove(DB + suffix)
    print("① 建库 + 角色/权限/菜单种子（%s）" % os.path.basename(DB))
    build_schema_and_seed()
    print("② 灌入批次 1 基础数据 + 批次 2 业务数据")
    run_script("seed_demo_data.py")
    run_script("seed_batch2_demo.py")
    print("③ 追加批次 3 报表分布数据（跨月/科室/已发药/超量/毒性/跨月随访）")
    extras()
    print("④ 摘要：")
    summary()
    print("✅ 固定数据集就绪：%s" % DB)


if __name__ == "__main__":
    main()
