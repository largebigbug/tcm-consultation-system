#!/usr/bin/env bash
# 批次 3 最终统一取证：一次跑全全部验收项，输出真实计数
set -u
cd /d/hermes/workspace/中医问诊系统
PY="D:/hermes/workspace/中医问诊系统/code-app/backend/.venv/Scripts/python.exe"
DXV="D:/hermes/workspace/docx-venv/Scripts/python.exe"
DB="D:/hermes/workspace/中医问诊系统/code-app/backend/data/app.db"
NPM="D:/hermes/.hermes/cache/scratch/npm-fresh/package/bin/npm-cli.js"

echo "########## ① 阶段二 十类模型门禁 ##########"
"$DXV" tools/validate_ontology.py yaml 2>&1 | tail -3

echo "########## ② 批次 1 开发侧自测 ##########"
(cd code-app/backend && "$PY" tools/check_batch1_api.py 2>&1 | tail -3)

echo "########## ③ 批次 1 主代独立验收 ##########"
"$PY" tools/batch1_api_test.py 2>&1 | tail -3

echo "########## ④ 批次 1 端到端（真实服务器 :5000，跑在演示库副本上） ##########"
cd code-app/backend
"$PY" ../../tools/kill_app_servers.py --port 5000   # 清场：端口被占会让探针打到别的库
cp data/app.db data/batch1_e2e.db                   # 副本：探针会写饮片/入库，不污染演示库
APP_DB_PATH="D:/hermes/workspace/中医问诊系统/code-app/backend/data/batch1_e2e.db" "$PY" app.py > "$TMPDIR/v5000.log" 2>&1 &
sleep 7
"$PY" ../../tools/batch1_e2e_probe.py 2>&1 | grep -E "通过|失败|汇总|越权" | tail -6
"$PY" ../../tools/kill_app_servers.py
rm -f data/batch1_e2e.db data/batch1_e2e.db-wal data/batch1_e2e.db-shm
cd /d/hermes/workspace/中医问诊系统

echo "########## ⑤ 批次 2 开发侧自测（门诊 + 药房） ##########"
(cd code-app/backend && "$PY" tools/check_batch2_visit.py 2>&1 | tail -2; "$PY" tools/check_batch2_pharmacy.py 2>&1 | tail -2)

echo "########## ⑥ 批次 2 主代独立验收 ##########"
"$PY" tools/batch2_api_test.py 2>&1 | tail -3

echo "########## ⑦ 批次 2 端到端 ##########"
"$PY" tools/batch2_e2e_probe.py 2>&1 | tail -3

echo "########## ⑧ 批次 3 开发侧自测 ##########"
(cd code-app/backend && "$PY" tools/check_batch3_report.py 2>&1 | tail -3)

echo "########## ⑨ 批次 3 主代独立验收 ##########"
(cd code-app/backend && "$PY" tools/batch3_api_test.py 2>&1 | tail -3)

echo "########## ⑩ 批次 3 端到端黑盒探针 ##########"
(cd code-app/backend && "$PY" ../../tools/batch3_e2e_probe.py 2>&1 | tail -3)

echo "########## ⑪ 演示库体检（批次 3 + 批次 2 回归） ##########"
(cd code-app/backend && "$PY" tools/batch3_demo_verify.py 2>&1 | tail -3; "$PY" tools/batch2_demo_verify.py 2>&1 | tail -3)

echo "########## ⑫ 前端生产构建 ##########"
(cd code-app/frontend && node "$NPM" run build 2>&1 | grep -E "dist/|built in|error")

echo "########## 取证完成 ##########"
