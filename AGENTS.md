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
- 路由：`backend/app/api/routes.py`，统一挂载在 `settings.api_prefix`（`/api/v1`）
- 领域层：`backend/app/domain/`（`models` ORM / `schemas` Pydantic / `service` 编排 /
  `calculation` 纯计算 / `document` 内容模型 / `imports` 解析 / `products` 目录）
- 渲染：`backend/app/rendering/`（`templates/*.j2`、`tokens/3033-v*.json`、`artifacts.py`、`visual_qa.py`）
- 外部适配器：`backend/app/integrations/`（当前为 FMP 新闻）
- 前端：`frontend/src/`（`components/` 通用件、`features/<domain>/` 业务工作台、
  `styles/tokens.css` 设计令牌、`styles.css` 组件样式）
- 运行时产物：`var/`（已 gitignore，容器内不得作为持久化依赖）

## 关键约束（必须遵守）

### 数据与计算

- **不得硬编码报告事实**：数字、日期、证券名称、行业、脚注一律来自快照、派生指标或版本化配置。
  黄金样例的具体值只允许出现在 `backend/tests/fixtures/`。
- **不得在浏览器执行权威业务计算**。React 只负责交互、编辑、可视化与预览。
- **不得覆盖不可变对象**：`DataSnapshot`、`ReportDocument`、`RenderArtifact` 一经生成即只增不改；
  刷新、修改、重渲染都创建新版本并保留血缘。
- **不得隐式混合 CDB 与上传文件**。同一数据集只有一个生效来源；覆盖必须记录原因、操作者与差异。
- **AI 不得产出数字**。AI 只能引用系统生成的 `MetricValue`，且必须通过 QC-008 数字回查。

### 安全

- CDB 账号、访问令牌、签名 URL **不得**进入日志、提示词、代码库或成品。
- 所有写接口提交 `version` 做乐观锁；冲突返回 409。校验失败返回 422 且带
  `error_code / field / entity_id / message / severity / fix_hint`。
- 授权在 API 层执行（`AuthorizationMiddleware`），不得只靠前端隐藏。
- 下载走短期签名 URL（HMAC + TTL），不得暴露原始存储路径。

### 渲染

- 三种格式（HTML / PDF / DOCX）必须读取**同一个** `Finalized ReportDocument` 与同一
  `design_token_version`；不得各自维护文案、查询或公式。
- PDF 不得由截图拼接；DOCX 不得由 PDF 转换；前端预览不得维护第二套近似 CSS。
- 不得靠调小字号、压扁 Logo、裁掉脚注、隐藏溢出、截断新闻来通过视觉测试；溢出必须返回结构化错误。

### UI

- `DESIGN.md` 是权威 UI 规范。颜色、圆角、间距、动效时长/曲线一律引用 token，
  **不得**在组件中硬编码。详见 `CLAUDE.md` 的「设计系统」一节。

## 必须暂停并升级的条件

- 同一业务指标存在两个不能等价转换的定义，且会改变对外数字。
- CDB 视图或字段无法稳定识别证券、指数、基金、日期、币种或总回报序列。
- 参考报告与样例数据无法对账且误差超出规格书容差。
- 需要新增外部付费数据源、对外发布权限、个人数据处理或超出既定网络边界。
- 需要破坏旧版本、降低审计粒度或绕过阻断性质量检查才能继续。

## Definition of Done

代码合并；迁移可回滚；单元/集成/契约/权限测试通过；文档更新；3033 黄金样例通过；
无阻断性质量检查失败。**仅完成页面、仅返回模拟数据、缺少来源血缘、存在硬编码数字、
视觉未核验，均不得标记 Done。**
