# Monthly Commentary Platform — Agent Notes

本文件是 Agent 的**执行合同摘要**。权威来源是
`docs/spec/月度基金评论报告生成系统_Agent执行规格书_V2.1.md`；本文件只做提炼，
冲突时以规格书为准，且任何偏离都必须留下 ADR（`docs/adr/`）。

## 技术与依赖

- 后端：Python 3.12+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、PyMySQL
- 前端：React 18 + TypeScript + Webpack Module Federation（Vitest 使用 Vite 转换）
- 任务：`TASK_MODE=EAGER`，API 内按需导出／同步翻译；不安装 Celery/Redis，不运行独立 worker（ADR-0028）
- 数据：**上线一律 MySQL 8（utf8mb4）**；SQLite 只是本地回退，部署进程会拒绝以 SQLite 启动；定稿文档、快照和导出审计保存在数据库
- 认证：`AUTH_MODE=REMOTE`（远程平台准入，共享操作身份）/ `AUTH_MODE=LOCAL`（请求头断言身份，仅限本机）/ `AUTH_MODE=ENTRA`（校验 Microsoft Entra
  访问令牌，需装 `entra` extra，即 `pyjwt[crypto]`）
- 成品导出：按定稿版本即时生成 HTML/PDF/DOCX，每请求独立临时目录，响应完成或失败后清理；不依赖对象存储（ADR-0029）。
- 渲染：Jinja2 规范 HTML → Playwright/Chromium PDF；python-docx 生成 DOCX
- Python 包管理：`pip -e ./backend[dev,render]`（`backend/pyproject.toml`；可选认证加 `entra`。
  生产镜像已内置 `[render,entra]`，切模式时不需要再装东西）
- Node 包管理：**`npm`**（根 `package.json` 的 npm workspaces，工作区为 `frontend`）

## 启动与常用命令

- 前端开发：`npm run dev`（Webpack，`http://localhost:3030/remote/fund-cmt-auto/`，remote API 代理到 8000）
- 后端开发：`.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8000`
- 后端测试：`.\.venv\Scripts\python -m pytest backend/tests`
  - `backend/tests/fixtures/` 是批准的基准数据（照已发布报告转录的金标准、供应商 EOD 样本），
    随仓库一起发布；但它也是检出里唯一可能缺席的部分（精简导出、稀疏克隆）。
    需要它的用例一律调 `conftest.require_fixtures()`，缺失就**跳过**而不是失败；
    `addopts = "-rs"` 会把每条跳过原因打进日志，覆盖变少时日志自己会说。导入期就读基准文件的模块必须
    用 `module_level=True`，否则整轮在收集阶段就死。TESTING 通道的用例不碰文件：应用返回 503
    `FIXTURE_MISSING`，conftest 的测试客户端把这一个错误码转成同样的跳过。
- 真机 MySQL 迁移验证：设 `TEST_MYSQL_URL` 指向**一次性**库后跑 `backend/tests/test_migrations.py`
  （该用例会先 downgrade 到 base，切勿指向有数据的库）
- 前端测试：`npm test`；生产构建：`npm run build`
- 迁移：`cd backend && python -m alembic upgrade head`
- 全栈容器：`docker compose up --build`（仅用户手动验证镜像，参见 `k8s/README.md`）
- 上线前自检：`.\.venv\Scripts\python scripts/check_deployment.py [--token "$ACCESS_TOKEN"]`
  （跑一遍会拒绝启动的那些检查，外加数据库可连/是否在 head/列是否 utf8mb4、JWKS 是否可达、
  导出临时目录可写且可清理；给了 token 还会解析出真实的 subject / 角色 / 产品范围。退出码非 0 表示该环境
  不得对外提供服务）
  - `--env-file <路径>`：改为体检该文件描述的环境。生产配置在任何进程读它之前就已经写好，
    所有守卫都是配置的纯函数，因此可以在开发机上先把生产环境证明干净，再发布
  - `--skip-network`：跳过租户 JWKS 请求（提供 --token 时仍校验）；数据库与临时目录检查继续执行

## 容器与部署现状

- 以用户提供的 deploy-conventions（2026-09）为基础，项目适配见 `docs/adr/0026-remote-app-deployment-conventions.md`。
- 部署手册为 `k8s/README.md`；UAT / PRD 的 EKS 清单位于 `k8s/uat` / `k8s/prd`，namespace 为 `ih`。
- 根目录 `docker-compose.uat.yml` / `docker-compose.prd.yml` 只用于构建推送；旧 VM 文件已移除。
- `compose.yaml` 仅作用户手动镜像验证：临时 MySQL + migrate/srvapp/webapp，不自动启动。
- 远程应用平台负责入口和访问准入；无独立 Ingress、域名、证书和登录。
  `AUTH_MODE=REMOTE` 使用共享 `remote-app` 身份，仍执行 MySQL/签名密钥/测试通道校验。
  `LOCAL` 只用于工作站；现有可选 `ENTRA` 能力不属于本次部署。
- Secret 来自根目录 `.env.<env>`，模板 `.env.<env>.example`；`k8s/create-secret.sh` 解析而非 source。
- 镜像非 root、只读根文件系统，仅有界 emptyDir/tmpfs 可写；业务数据存外部 MySQL，成品下载后不保留。
- `backend/requirements.lock` 在 Linux Python 3.12 生成，Dockerfile 做离线依赖漂移检查。
- 报告字体固定安装 `fonts-crosextra-carlito`、`fonts-noto-cjk`、`fonts-noto-cjk-extra`，与 CI 同步。
- 前端 npm workspaces / Node 24 构建，nginx-unprivileged 在 3030 运行，`/remote/fund-cmt-auto/api/v1` 反代到 `/api/v1`；接入见 `k8s/REMOTE.md`。
- `.github/workflows/auto-docker-image-build.yml` 仅手动构建推送 latest + git SHA，不部署集群。

## 代码位置约定

- 应用装配：`backend/app/main.py`（`_verify_deployment_configuration()` 先于 `create_app()` 执行，
  配置不安全直接拒绝启动）
- 安全边界：`backend/app/core/security.py`（`Principal` + 纯 ASGI 的 `AuthorizationMiddleware` +
  `current_principal` ContextVar + 按 content-type 选择的 CSP）与 `backend/app/core/entra.py`
  （JWKS 缓存、算法白名单、aud/iss/exp 校验、角色与产品范围取自 claim）
- 路由：`backend/app/api/routes/`，按领域分模块（`reports` / `datasets` / `news` / `render` /
  `catalog` / `admin`，公共依赖在 `deps.py`，上传限额在 `uploads.py`），
  统一挂载在 `settings.api_prefix`（`/api/v1`）
- 领域层：`backend/app/domain/`（`models` ORM / `schemas` Pydantic / `document` 内容模型 /
  `imports` 解析 / `products` 目录）
  - `service/` 会话编排（分层 `audit → lifecycle → catalog → documents → snapshots → imports →
    import_batches → calculations → reports`，`news` 并列），凡是碰 `Session` 的都在这里；
    报告是否可编辑的判断统一走 `lifecycle.ensure_report_editable` / `ensure_report_not_archived`
  - `metrics/` 纯计算，**一个报告模块一个文件**：`historical_performance`（02）/
    `constituent_performance`（04）/ `industry_breakdown`（05 内的环形图）/ `final_analytics`（05）/
    `footnotes`（06）；非报告模块的支撑件为 `errors` / `formatting` / `fund_kpis`，跨模块的质检门
    在 `quality_checks`。01 Review 与 03 Company News 无数值计算，故此处不设文件。
    从具体模块 import，包顶层不做平铺 re-export。
- 渲染：`backend/app/rendering/`（`templates/*.j2`、`tokens/3033-v*.json`、`artifacts.py`、`visual_qa.py`）
- 外部适配器：`backend/app/integrations/`（新闻仅使用 `da_report.py`，在 Production 只读查询 DA MySQL，UAT/本地保留 SQLite 快照（ADR-0030 / ADR-0031））
- 前端：`frontend/src/`（`components/` 通用件、`features/<domain>/` 业务工作台、
  `styles/tokens.css` 设计令牌、`styles.css` 组件样式）
- 运行时产物：`var/`（已 gitignore，容器内不得作为持久化依赖）

## 关键约束（必须遵守）

### 数据与计算

- 后端开发与部署**不能依赖任何 PVC**。
- 如有文件存储、媒体（media）等需求，后端必须使用云对象存储（当前为 TOS）或直接存入数据库。
- 后端容器内不得保留 media 等持久化文件；生产 K8s 环境不提供 PVC。
- 按需导出是临时文件处理，不持久化成品，不写数据库 BLOB，不需要 S3/TOS（ADR-0029）。
- 下载固定读取 `finalized_document_version`；定稿和已归档定稿可下载，草稿不可下载。
- 每次导出写 `export.generated` / `export.failed` 审计；成功仅表示生成完成，不表示用户已保存文件。
- 历史 RenderArtifact / RenderJob 表记录保留，但不再创建新记录或提供旧成品链接。

### 安全边界

- REMOTE 使用共享 `remote-app` 身份，由远程应用平台控制访问，不提供独立登录。
- LOCAL / ENTRA 使用原有身份校验路径。`LOCAL` 是**断言**身份（请求头），`ENTRA` 是**证明**身份（签名令牌）；
  `ENTRA` 下请求头一律忽略，否则拿 VIEWER 令牌的人只要加一个 `X-User-Role: ADMIN` 就成了管理员。
- 角色序：`VIEWER < EDITOR < REVIEWER < ADMIN`。VIEWER 全站只读；finalize 需 REVIEWER/ADMIN；
  产品目录、行业主数据、映射档案的写入需 ADMIN。
- **产品范围过滤的是行，不是端点**：范围外的报告返回 404 而非 403 —— 403 等于确认该报告存在。
- 上传边读边限额（不得先缓冲整个请求体），且上限不得超过 nginx 的 `client_max_body_size`；
  被代理层挡下的 413 不带结构化错误信封。
- 下载链接是 HMAC 签名 + TTL + 绑定调用者 subject 的，不是可以转手的凭证。
- Jinja 必须 `autoescape=True`；模板名为 `*.html.j2`，用 `select_autoescape([...])` 按后缀判断会
  静默关闭转义。
- 任何默认值都不得是可用的凭证；新增设置要同时进 `.env.example`，不安全的还要进
  `Settings.deployment_problems()`。
- 相关测试统一写进 `backend/tests/test_security.py`（按属性分节：角色 / 范围 / 响应头 / 审计 /
  上传 / 下载 / XSS / Entra / 配置守卫）。
- 租户侧配置见 `docs/entra-setup.md`（应用注册、四个 app role 取值、产品范围三种承载方式、
  `error_code` → 原因对照表）。改 `app/core/entra.py` 的错误码时必须同步那张表。

### 数据库（上线适配 MySQL）

- 部署即 MySQL 8 + utf8mb4；`deployment_problems()` 会拒绝非 LOCAL 进程以 SQLite 启动。
- 索引中的 `String` 列必须声明长度且 **≤ 768 字符**（InnoDB 索引键上限 3072 字节，utf8mb4 一字符
  四字节）。长值靠哈希列做唯一，例如 `news_items.source_url_hash`。
- 连接池按 MySQL 配置：`pool_pre_ping` + `pool_recycle`（须小于服务端 `wait_timeout`），
  否则闲置后第一笔请求会撞上 "MySQL server has gone away"。
- 每个迁移都要能**逐条** upgrade 与 downgrade；`backend/tests/test_migrations.py` 会一条条走。
- downgrade 里**先删外键，再删支撑它的索引**；而**要 `drop_table` 的表根本不要写 `drop_index`**——
  `DROP TABLE` 本来就会带走自己的索引，autogenerate 生成的那几行纯属冗余，列上带外键时还会直接报错。
  InnoDB 要靠那个索引来执行外键，顺序反了或先删索引都报 1553；SQLite 是整表重建，两种写法都收，
  所以这个错只有跑真机 MySQL 才看得见（CI 已设 `TEST_MYSQL_URL`）。

### UI

- `DESIGN.md` 是权威 UI 规范。颜色、圆角、间距、动效时长/曲线一律引用 token，
  **不得**在组件中硬编码。详见 `CLAUDE.md` 的「设计系统」一节。
- 错误提示走 `api.ts` 的 `ApiError`（已把 message / fix_hint / findings 拼成可读句子）。
  调用点用 `String(caught)` 渲染，**不得**把原始 JSON 或 nginx 的 HTML 错误页塞进状态栏。
