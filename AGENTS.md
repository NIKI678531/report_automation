# Monthly Commentary Platform — Agent Notes

本文件是 Agent 的**执行合同摘要**。权威来源是
`docs/spec/月度基金评论报告生成系统_Agent执行规格书_V2.1.md`；本文件只做提炼，
冲突时以规格书为准，且任何偏离都必须留下 ADR（`docs/adr/`）。

## 技术与依赖

- 后端：Python 3.12+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic
- 前端：React + TypeScript + Vite
- 任务：Celery + Redis
- 数据：MySQL 8（本地回退 SQLite）+ 对象存储
- 渲染：Jinja2 规范 HTML → Playwright/Chromium PDF；python-docx 生成 DOCX
- Python 包管理：`pip -e ./backend[dev,render]`（`backend/pyproject.toml`）
- Node 包管理：**`npm`**（根 `package.json` 的 npm workspaces，工作区为 `frontend`）

## 启动与常用命令

- 前端开发：`npm run dev`（Vite，`http://localhost:5173`，`/api` 代理到 8000）
- 后端开发：`.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000`
- 后端测试：`.\.venv\Scripts\python -m pytest backend/tests`
- 前端测试：`npm test`；生产构建：`npm run build`
- 迁移：`cd backend && python -m alembic upgrade head`
- 全栈容器：`docker compose up --build`（api / worker / web / mysql / redis）

## 容器与部署现状

- `compose.yaml`：`db(mysql) + redis + api + worker + web(nginx)`
- 前端镜像多阶段构建：`node:24-alpine` 执行 `npm ci && npm run build`，产物交给 `nginx:1.29-alpine`
- CI（`.github/workflows/ci.yml`）：pytest → `npm ci` → `npm test` → `npm run build`

## 代码位置约定

- 应用装配：`backend/app/main.py`（`create_app()`）
- 路由：`backend/app/api/routes/`，按领域分模块（`reports` / `datasets` / `news` / `render` /
  `catalog` / `admin`，公共依赖在 `deps.py`），统一挂载在 `settings.api_prefix`（`/api/v1`）
- 领域层：`backend/app/domain/`（`models` ORM / `schemas` Pydantic / `document` 内容模型 /
  `imports` 解析 / `products` 目录）
  - `service/` 会话编排（分层 `audit → catalog → documents → snapshots → imports →
    calculations → reports`，`news` 并列），凡是碰 `Session` 的都在这里
  - `metrics/` 纯计算，**一个报告模块一个文件**：`historical_performance`（02）/
    `constituent_performance`（04）/ `industry_breakdown`（05 内的环形图）/ `final_analytics`（05）/
    `footnotes`（06）；非报告模块的支撑件为 `errors` / `formatting` / `fund_kpis`，跨模块的质检门
    在 `quality_checks`。01 Review 与 03 Company News 无数值计算，故此处不设文件。
    从具体模块 import，包顶层不做平铺 re-export。
- 渲染：`backend/app/rendering/`（`templates/*.j2`、`tokens/3033-v*.json`、`artifacts.py`、`visual_qa.py`）
- 外部适配器：`backend/app/integrations/`（`da_report.py` 只读快照新闻、`marketaux.py` 可选远程源）
- 前端：`frontend/src/`（`components/` 通用件、`features/<domain>/` 业务工作台、
  `styles/tokens.css` 设计令牌、`styles.css` 组件样式）
- 运行时产物：`var/`（已 gitignore，容器内不得作为持久化依赖）

## 关键约束（必须遵守）

### 数据与计算

- 后端开发与部署**不能依赖任何 PVC**。
- 如有文件存储、媒体（media）等需求，后端必须使用云对象存储（当前为 TOS）或直接存入数据库。
- 后端容器内不得保留 media 等持久化文件；生产 K8s 环境不提供 PVC。

### UI

- `DESIGN.md` 是权威 UI 规范。颜色、圆角、间距、动效时长/曲线一律引用 token，
  **不得**在组件中硬编码。详见 `CLAUDE.md` 的「设计系统」一节。

