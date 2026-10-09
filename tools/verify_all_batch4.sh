#!/usr/bin/env bash
# 批次 4 最终统一取证：批次 4 全部验收 + 批次 1/2/3 全量回归（一次跑完，输出真实计数）
set -u
cd /d/hermes/workspace/中医问诊系统
PY="D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe"
DXV="D:/hermes/tools/docx-venv/Scripts/python.exe"
DB="D:/hermes/workspace/中医问诊系统/code-app/backend/data/app.db"
NPM="D:/hermes/.hermes/cache/scratch/npm-fresh/package/bin/npm-cli.js"

echo "########## ① 阶段二模型门禁（含批次 4 新增「约定 13」条件组开关检查） ##########"
"$DXV" tools/validate_ontology.py yaml 2>&1 | tail -3

echo "########## ② 模型双副本一致性（yaml ↔ code-app/models） ##########"
ok=1
for f in m1-object-model.yaml m2-behavior-model.yaml m3-rule-model.yaml m5-actor-model.yaml \
         m6-flow-model.yaml m7-report-model.yaml mu-ui-model.yaml manifest.json CHANGELOG.md; do
  a=$(sha256sum "yaml/$f" | cut -c1-12); b=$(sha256sum "code-app/models/$f" | cut -c1-12)
  if [ "$a" = "$b" ]; then echo "  ✅ $f"; else echo "  ❌ $f ($a vs $b)"; ok=0; fi
done
[ "$ok" = 1 ] && echo "  全部一致" || echo "  存在不一致（见上）"

echo "########## ③ 前端生产构建（独立 npm） ##########"
(cd code-app/frontend && node "$NPM" run build 2>&1 | grep -E "dist/|built in|error|Duplicate")

echo "########## ④ 批次 4 主代独立验收（黑盒 HTTP + SQL oracle + 权限矩阵） ##########"
(cd code-app/backend && "$PY" tools/batch4_api_test.py 2>&1 | tail -4)

echo "########## ⑤ 批次 4 端到端黑盒探针（演示库副本） ##########"
(cd code-app/backend && "$PY" ../../tools/batch4_e2e_probe.py 2>&1 | tail -6)

echo "########## ⑥ 批次 4 演示库只读体检 ##########"
(cd code-app/backend && "$PY" tools/batch4_demo_verify.py 2>&1 | tail -3)

echo "########## ⑦ 批次 3 主代独立验收 + 端到端 + 演示库体检 ##########"
(cd code-app/backend && "$PY" tools/batch3_api_test.py 2>&1 | grep "独立验收结果")
(cd code-app/backend && "$PY" ../../tools/batch3_e2e_probe.py 2>&1 | tail -2)
(cd code-app/backend && "$PY" tools/batch3_demo_verify.py 2>&1 | tail -2)

echo "########## ⑧ 批次 3 开发侧自测 ##########"
(cd code-app/backend && "$PY" tools/check_batch3_report.py 2>&1 | tail -3)

echo "########## ⑨ 批次 2 自测 + 主代独立 + 端到端 ##########"
(cd code-app/backend && "$PY" tools/check_batch2_visit.py 2>&1 | tail -2; "$PY" tools/check_batch2_pharmacy.py 2>&1 | tail -2)
"$PY" tools/batch2_api_test.py 2>&1 | tail -2
"$PY" tools/batch2_e2e_probe.py 2>&1 | tail -2

echo "########## ⑩ 批次 2 演示库体检 ##########"
(cd code-app/backend && "$PY" tools/batch2_demo_verify.py 2>&1 | tail -2)

echo "########## ⑪ 批次 1 自测 + 主代独立 ##########"
(cd code-app/backend && "$PY" tools/check_batch1_api.py 2>&1 | tail -2)
"$PY" tools/batch1_api_test.py 2>&1 | tail -2

echo "########## ⑫ 批次 1 端到端（演示库副本 + 清场端口） ##########"
cd code-app/backend
"$PY" ../../tools/kill_app_servers.py --port 5000
cp data/app.db data/batch1_e2e.db
APP_DB_PATH="D:/hermes/workspace/中医问诊系统/code-app/backend/data/batch1_e2e.db" "$PY" app.py > "$TMPDIR/v5000.log" 2>&1 &
sleep 7
"$PY" ../../tools/batch1_e2e_probe.py 2>&1 | grep -E "通过|失败|汇总" | tail -4
"$PY" ../../tools/kill_app_servers.py
rm -f data/batch1_e2e.db data/batch1_e2e.db-wal data/batch1_e2e.db-shm
cd /d/hermes/workspace/中医问诊系统

echo "########## 取证完成 ##########"
