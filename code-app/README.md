# code-app · 中医问诊系统应用

本目录是**中医问诊系统**的可运行实现（Flask 后端 + React 前端），业务语义全部来自仓库根的 `yaml/` 本体模型。

> 完整的项目说明、技术栈、快速开始与演示账号，见**仓库根目录的 [`README.md`](../README.md)**。

## 目录

| 路径 | 说明 |
|---|---|
| `backend/` | Flask 后端：`app.py` 入口、`api/` 接口层、`services/` 业务服务、`engine/` 流程引擎、`ai/` AI 助手（工具注册表 / 编排器 / SSE）、`sql_readonly/` 只读 SQL 防线、`ontology/` 模型注册表 |
| `frontend/` | React + TypeScript + Vite 前端（开发端口 5173，`/api` 代理到 5000） |
| `models/` | **运行时**本体模型副本，必须与 `../yaml/` 逐字节一致（改动后跑 md5 校验） |
| `docs/` | 各批次**实现契约**与从模型**机械抽取**的文档（抽取文档禁止手改） |

## 跑起来

```bash
# 后端
cd backend
pip install -r requirements.txt
python app.py                 # http://localhost:5000（首次启动幂等建库 + 写入种子数据）

# 前端
cd ../frontend
npm install
npm run dev                   # 开发模式（推荐）
npm run build                 # 生产构建 → dist/，之后由 Flask 统一托管
```

演示账号：`admin/admin123`；`daozhen`/`yishi`/`yaoshi`/`kufang`/`keshi` 密码均为 `123456`。

AI 助手为可选项，凭据写在 `backend/.env`（`DEEPSEEK_API_KEY`，该文件已被 `.gitignore` 排除）。未配置时接口返回「未启用」降级口径，不影响其它功能。
