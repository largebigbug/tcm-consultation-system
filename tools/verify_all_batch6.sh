#!/usr/bin/env bash
# 批次 6 最终统一取证：模型门禁 + 双副本一致 + 抽取可复现 + 前端构建
#   + 批次 6 三套验收 + 批次 1/2/3/4/5 全量回归 + 演示库未污染复核
set -u
cd /d/hermes/workspace/中医问诊系统
PY="D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe"
DXV="D:/hermes/tools/docx-venv/Scripts/python.exe"
NPM="D:/hermes/.hermes/cache/scratch/npm-fresh/package/bin/npm-cli.js"

echo "########## ① 阶段二模型门禁（含约定 13）##########"
"$DXV" tools/validate_ontology.py yaml 2>&1 | tail -3

echo "########## ② 模型双副本一致性（yaml ↔ code-app/models）##########"
ok=1
for f in m1-object-model.yaml m2-behavior-model.yaml m3-rule-model.yaml m5-actor-model.yaml \
         m6-flow-model.yaml m7-report-model.yaml mu-ui-model.yaml manifest.json CHANGELOG.md; do
  a=$(sha256sum "yaml/$f" | cut -c1-12); b=$(sha256sum "code-app/models/$f" | cut -c1-12)
  if [ "$a" = "$b" ]; then echo "  ✅ $f"; else echo "  ❌ $f ($a vs $b)"; ok=0; fi
done
[ "$ok" = 1 ] && echo "  全部一致" || echo "  存在不一致（见上）"

echo "########## ③ 批次 6 规格抽取（重跑，验证可复现）##########"
(cd code-app/backend && "$PY" tools/gen_batch6_spec.py 2>&1 | tail -2)

echo "########## ④ 前端生产构建（独立 npm）##########"
(cd code-app/frontend && node "$NPM" run build 2>&1 | grep -E "dist/|built in|error")

echo "########## ⑤ 批次 6 主代独立验收（黑盒 HTTP + 库内 oracle + 静态守卫）##########"
(cd code-app/backend && "$PY" tools/batch6_api_test.py 2>&1 | grep -E "独立验收：|失败项|^   -")

echo "########## ⑥ 批次 6 端到端探针（演示库副本）##########"
"$PY" tools/batch6_e2e_probe.py 2>&1 | grep -E "端到端探针：|失败项|^   -"

echo "########## ⑦ 批次 6 演示库只读体检 ##########"
(cd code-app/backend && "$PY" tools/batch6_demo_verify.py 2>&1 | grep -E "只读体检：|失败项|^   -")

echo "########## ⑧ 批次 5 全套（独立 74 / 端到端 37 / 演示库 9）##########"
(cd code-app/backend && "$PY" tools/batch5_api_test.py 2>&1 | grep "独立验收结果")
"$PY" tools/batch5_e2e_probe.py 2>&1 | grep -E "端到端探针：|失败项"
(cd code-app/backend && "$PY" tools/batch5_demo_verify.py 2>&1 | grep -E "只读体检：|失败项")

echo "########## ⑨ 批次 4 全套（独立 67 / 端到端 36 / 演示库 13）##########"
(cd code-app/backend && "$PY" tools/batch4_api_test.py 2>&1 | grep "独立验收结果")
"$PY" tools/batch4_e2e_probe.py 2>&1 | grep -E "端到端探针：|失败项"
(cd code-app/backend && "$PY" tools/batch4_demo_verify.py 2>&1 | grep -E "体检：|失败项")

echo "########## ⑩ 批次 3 全套（自测 159 / 独立 168 / 端到端 40 / 演示库 26）##########"
(cd code-app/backend && "$PY" tools/check_batch3_report.py 2>&1 | grep "自测：" ; "$PY" tools/batch3_api_test.py 2>&1 | grep "独立验收结果")
"$PY" tools/batch3_e2e_probe.py 2>&1 | grep -E "端到端黑盒探针"
(cd code-app/backend && "$PY" tools/batch3_demo_verify.py 2>&1 | grep -E "演示库体检")

echo "########## ⑪ 批次 2 全套（自测 92/89 / 独立 105 / 端到端 29 / 演示库 34）##########"
(cd code-app/backend && "$PY" tools/check_batch2_visit.py 2>&1 | grep -E "汇总|失败" | tail -1
 "$PY" tools/check_batch2_pharmacy.py 2>&1 | grep -E "全部断言|失败" | tail -1)
"$PY" tools/batch2_api_test.py 2>&1 | grep "独立验收"
"$PY" tools/batch2_e2e_probe.py 2>&1 | grep "端到端黑盒探针"
(cd code-app/backend && "$PY" tools/batch2_demo_verify.py 2>&1 | grep "演示库体检")

echo "########## ⑫ 批次 1 全套（自测 57 / 独立 50 / 端到端 19）##########"
(cd code-app/backend && "$PY" tools/check_batch1_api.py 2>&1 | grep "汇总：")
"$PY" tools/batch1_api_test.py 2>&1 | grep "验收结果"
cd code-app/backend
"$PY" ../../tools/kill_app_servers.py --port 5000
cp data/app.db data/batch1_e2e.db
APP_DB_PATH="D:/hermes/workspace/中医问诊系统/code-app/backend/data/batch1_e2e.db" "$PY" app.py > "$TMPDIR/v5000_b6.log" 2>&1 &
sleep 8
"$PY" ../../tools/batch1_e2e_probe.py 2>&1 | grep -E "端到端结果"
"$PY" ../../tools/kill_app_servers.py
rm -f data/batch1_e2e.db data/batch1_e2e.db-wal data/batch1_e2e.db-shm
cd /d/hermes/workspace/中医问诊系统

echo "########## ⑬ 演示库未污染复核（批次 6 基线 + 业务行指纹）##########"
"$PY" -c "
import sqlite3,hashlib
c=sqlite3.connect(r'code-app/backend/data/app.db');c.row_factory=sqlite3.Row
base={'task_TODO':\"SELECT COUNT(*) FROM flow_task WHERE status='TODO'\",
      'task_DONE':\"SELECT COUNT(*) FROM flow_task WHERE status='DONE'\",
      'inst_RUNNING':\"SELECT COUNT(*) FROM flow_instance WHERE status='RUNNING'\",
      'inst_APPROVED':\"SELECT COUNT(*) FROM flow_instance WHERE status='APPROVED'\",
      'history':'SELECT COUNT(*) FROM flow_history','audit':'SELECT COUNT(*) FROM audit_logs',
      'dispense':'SELECT COUNT(*) FROM dispense_record','prescription':'SELECT COUNT(*) FROM prescription'}
print('  基线:', {k:list(c.execute(q))[0][0] for k,q in base.items()})
for q,n in (('SELECT id, herb_code, stock_quantity, low_stock_threshold, herb_status, flag FROM herb ORDER BY id','herb'),
            ('SELECT id, visit_no, register_time, visit_status, flag FROM visit ORDER BY id','visit')):
    r=[tuple(x) for x in c.execute(q)]
    print('  %s %d:%s' % (n, len(r), hashlib.sha256(repr(r).encode()).hexdigest()[:16]))
print('  今日 audit 行:', list(c.execute(\"SELECT COUNT(*) FROM audit_logs WHERE created_at LIKE '2026-10-01%'\"))[0][0],
      '其中非 LOGIN:', list(c.execute(\"SELECT COUNT(*) FROM audit_logs WHERE created_at LIKE '2026-10-01%' AND action <> 'LOGIN'\"))[0][0],
      '(其它批次体检会登录，LOGIN 增长属预期)')
print('  今日 flow_history 残留:', list(c.execute(\"SELECT COUNT(*) FROM flow_history WHERE created_at LIKE '2026-10-01%'\"))[0][0])
"

echo "########## ⑭ 残留副本与端口清场 ##########"
ls code-app/backend/data/ | grep -E "^(b6_|check_batch6|batch[0-9]_)" || echo "  无残留用例库"
"$PY" tools/kill_app_servers.py

echo "########## 取证完成 ##########"
