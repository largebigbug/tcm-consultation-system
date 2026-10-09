# 中医问诊系统（TCM Consultation System）

> **本体驱动开发（Ontology-Driven Development）的完整实践**：需求规格 → 7 个本体模型 → 可运行的全栈应用（含工作流引擎与能真实查业务数据的 AI 助手）。
> 三个阶段的需求文档、模型、实现契约与验收脚本，全部收录在本仓库。

---

## 这是什么

一个面向中医门诊场景的**问诊业务系统**：患者建档 → 就诊登记 → 辨证 → 处方开具 → 审核 → 调剂 → 发药 → 随访，覆盖饮片库存与出入库流水，并附带报表与查询。业务范围以《中医问诊系统-需求规格说明书-V9》为准。

项目按「本体驱动开发」三步法推进，三个阶段各自留下可核查的交付物：

| 阶段 | 产出 | 位置 |
|---|---|---|
| 一 · 需求探索 | 需求规格说明书 V9（2529 行 / 189 KB） | `中医问诊系统-需求规格说明书-V9.md`（+ `.docx`） |
| 二 · 本体建模 | 7 个本体模型：对象 M1 / 行为 M2 / 规则 M3 / 角色 M5 / 流程 M6 / 报表 M7 / 界面 MU | `yaml/`（冻结源）+ `code-app/models/`（运行时副本） |
| 三 · 应用构建 | 6 个批次的实现契约 + 后端/前端代码 + 验收脚本 | `code-app/`、`tools/`、`阶段三-批次N-交付说明.md` |

## 亮点

- **模型是唯一语义来源**：字段、字典取值、枚举取值域、状态码、接口路径、屏幕规格全部由 YAML 模型**机械抽取**成文档与代码，禁止手写；模型改一处，运行时会话与文档同步（`yaml/` 与 `code-app/models/` 双副本以 md5 校验一致）。
- **AI 助手真的能调业务数据**：59 个工具由本体模型生成（导航 19 / 查询 7 / 报表 7 / 动作 24 / 图表 / 只读 SQL）。模型只负责「点名调用哪个工具」，取数全部在确定性代码里完成；工具名严格符合 LLM function-calling 的 `^[a-zA-Z0-9_-]{1,64}$` 约束并在构建期硬校验。
- **只读 SQL 三层防线**：Schema 白名单（13 表 / 139 字段）→ 执行层限制（`default_limit=100`、`max_limit=500`、3 秒超时）→ SQL 解析层拦截写操作；所有 AI 行为落三类审计（`AI_CHAT` / `AI_TOOL_CALL` / `AI_SQL_QUERY`）。
- **工作流引擎 + 工作台**：串行审批流（通过 / 驳回 / 作废终止）、我的待办 / 已办 / 我的申请、转办与催办按任务归属鉴权。
- **可验证**：跨模型一致性门禁 + 每批独立的验收装置（API 测试 / 端到端探针 / 演示库体检），全部是可复跑脚本，交付说明里附实测计数。

## 技术栈

| 层 | 选型 |
|---|---|
| 数据库 | SQLite 3（WAL 模式，`sqlite3` 直连，不用 ORM） |
| 后端 | Python 3.10+ + Flask 3.0.3 + PyJWT 2.8.0 + PyYAML 6.0.1 + python-dotenv 1.0.1 + simpleeval 0.9.13 |
| 前端 | React 18 + TypeScript + Vite（开发端口 5173，`/api` 代理到 5000） |
| UI | 原生 CSS 设计系统、lucide-react 图标、ECharts 图表、react-flow 流程设计器 |
| AI | 任意 OpenAI 兼容接口（默认 DeepSeek `deepseek-chat`），function calling + SSE 流式输出 |

## 目录结构

```
中医问诊系统/
├── 中医问诊系统-需求规格说明书-V9.md/.docx      # 阶段一：需求规格
├── 阶段二-本体建模交付说明.md/.docx              # 阶段二交付说明
├── 七模型评审要点与验收清单.md/.docx             # 模型评审与验收口径
├── 开发实施说明-七模型落地指南.md/.docx          # 如何用这套模型开发
├── 阶段三-批次1..6-交付说明.md/.docx             # 阶段三各批交付说明（含已知缺口登记）
├── 交付索引.md/.docx                            # 总索引：文件清单 / 复跑命令 / 偏差登记
├── yaml/                                       # 本体模型冻结源（7 模型 + manifest + CHANGELOG）
├── code-app/
│   ├── models/                                 # 运行时模型副本（与 yaml/ 逐字节一致）
│   ├── docs/                                   # 各批次实现契约与机械抽取文档
│   ├── backend/                                # Flask 后端（app.py / api / services / engine / ai / sql_readonly）
│   └── frontend/                               # React 前端（src / vite.config.ts）
├── code-paas/                                  # 早期通用「系统管理 + 流程引擎」脚手架（技术底座原型）
├── tools/                                      # 一致性校验、抽取、验收脚本（含 verify_all_batch*.sh）
├── 启动中医问诊系统.bat                          # Windows 一键启动
└── 配置AI密钥.bat                               # Windows 交互式写入 .env（不回显、不写日志）
```

## 快速开始

### 后端

```bash
cd code-app/backend
python -m venv .venv && .venv/Scripts/activate     # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt
python app.py                                      # http://localhost:5000
```

首次启动会按 `config.yaml` 幂等建库并写入种子数据（角色、权限、资源、用户、流程定义）。

### 前端

```bash
cd code-app/frontend
npm install
npm run dev        # 开发模式 http://localhost:5173（/api 代理到 5000）
npm run build      # 生产构建 → dist/，随后由 Flask 统一托管（直接访问 5000 即可，SPA 回退已处理）
```

### 一键启动（Windows）

双击 `启动中医问诊系统.bat`：已在运行则直接打开页面，否则以独立进程拉起服务并等端口就绪后打开浏览器。

## 演示账号

| 账号 | 密码 | 角色 | 说明 |
|---|---|---|---|
| `admin` | `admin123` | 超级管理员 | 旁路权限校验，全功能 |
| `daozhen` | `123456` | 门诊 | 患者建档（含 `patient:save`） |
| `yishi` | `123456` | 医师 | 就诊 / 辨证 / 处方 |
| `yaoshi` | `123456` | 药房 | 审核 / 调剂 / 发药 |
| `kufang` | `123456` | 库存 | 饮片与出入库流水 |
| `keshi` | `123456` | 科室 | 基础数据 / 随访 / 报表 |

> 均为**演示口令**，仅用于本地体验，请勿用于任何正式环境。

## AI 助手配置

AI 是**可选**功能：不配置凭据时接口返回「未启用」降级口径（`enabled:false` + 中文提示），页面显示重试按钮，其余业务功能不受影响。

```bash
cd code-app/backend
echo "DEEPSEEK_API_KEY=你的密钥" > .env      # 或用仓库根目录的「配置AI密钥.bat」
echo "AI_PROVIDER=deepseek" >> .env
```

- 配置优先级：**环境变量 > `config.yaml`**；总开关为 `ai.enabled`。
- 支持任意 OpenAI 兼容服务：`AI_PROVIDER` / `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL`。
- `GET /api/ai/status` 只回显「是否已配置」，**绝不回显密钥**；页面不提供写密钥入口（安全口径：明文密钥不入页面、不进日志）。
- `.env` 已被 `.gitignore` 排除，**不会进仓库**。

## 模型与一致性门禁

改了模型（`yaml/`）之后必须同步运行时副本并跑门禁，否则应用与文档会漂移：

```bash
# 1) 同步双副本
cp yaml/*.yaml code-app/models/          # 保持逐字节一致（md5 校验）
# 2) 跨模型一致性门禁
python tools/validate_ontology.py yaml   # 期望：全部一致性检查通过
# 3) 分批验收（按需）
bash tools/verify_all_batch6.sh          # 含模型门禁 + 双副本 md5 + 抽取可复现 + 前端构建 + 批次 1~6 全量回归
```

## 交付文档索引

- **总索引**：`交付索引.md` —— 按角色阅读路径、文件清单、一键复跑命令、模型-代码偏差登记。
- **每批交付说明**：`阶段三-批次N-交付说明.md` —— 本批范围、验收计数（API 测试 / 端到端 / 演示库体检）、已知缺口。
- **实现契约**：`code-app/docs/批次N-实现契约.md` —— 冻结的实现口径（字段表、屏幕规格、状态码、接口路径）。
- **机械抽取文档**：`code-app/docs/*（M1/M5/M7/MU 抽取）.md` —— 由脚本从模型生成，禁止手改。

## 数据与合规声明

- 仓库内所有业务数据均为**演示数据**（种子脚本生成），**不含任何真实患者信息**（无姓名 / 证件号 / 联系方式 / 病历）。
- 演示账号与口令是公开的演示凭据，仅用于本地体验。
- 不含任何密钥：`.env`、`*.key`、`*.pem`、运行库（`backend/data/`）、日志与构建产物均已在 `.gitignore` 中排除。
- 本项目为**技术演示与学习用途**；若要用于真实医疗场景，需自行完成合规评估（分级保护、数据安全、医疗器械软件等）。

## 许可

本项目以 **MIT License** 发布，详见 [`LICENSE`](LICENSE)。
