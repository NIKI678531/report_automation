# Report-Automation 项目健康度审计报告

- 审计日期：2026-09-03
- 审计对象：`C:\Development\Report-Automation` @ `cec9abb`（`main`，"chore: publish sanitized source snapshot"）
- 审计方式：只读静态分析 + 尝试运行测试套件；未修改任何被跟踪文件
- 代码规模：173 个跟踪文件；后端 Python 约 25,100 行（含约 2,630 行死代码），前端 TS/TSX/CSS 约 6,400 行

---

## 0. 执行摘要

**一句话结论**：这是一个领域建模认真、局部工程纪律良好（无 TODO、无 print、无 `type: ignore`、指标层纯函数、迁移线性可逆、SQL 全参数化）的项目，但存在几处会直接击穿其核心承诺（"每个数字可追溯、不可篡改"）的结构性缺陷，且**当前仓库快照无法在新克隆上构建、测试或运行**。作为本地开发工具可用；作为可部署产品，尚未达标。

### 各维度评级

| 维度 | 评级 | 一句话 |
|---|---|---|
| 可构建性 / 可复现性 | **严重** | `backend/Dockerfile`、渲染 logo、golden fixture、`docs/` 全被 `.gitignore` 排除；CI 必红；`pip` 无锁、前端 8 个 `"latest"` |
| 安全 | **严重**（生产） / 可接受（LOCAL） | ENTRA 模式不校验 token 且信任客户端 `X-User-Role`；Jinja2 autoescape 实际关闭；审计无 actor；`product_scope` 从未执行 |
| 架构 / 约束合规 | **较差** | 对象存储端口是占位；`MetricValue` 原地覆写；三条并行 snapshot 管线；全栈硬绑定 3033/HSTECH/HKD |
| 测试 / CI | **较差** | 安全边界近零覆盖；迁移仅 SQLite 双端；无 lint / 类型检查 / 覆盖率 / 审计门禁 |
| 后端代码质量 | **一般** | 小处纪律好；大处 34 个 >80 行函数、`HTTPException` 渗入 9/10 个 service 模块、约 120 行复制粘贴 |
| 前端代码质量 | **一般** | 设计令牌落地出色；但无 ESLint/Prettier、450 行 god component、API 层裸 `as T`、两个死组件 |
| 文档一致性 | **较差** | CLAUDE.md / AGENTS.md / README / CONTEXT.md 有 16 处与代码不符 |

### 必须优先处理的 5 件事

1. **`backend/app/rendering/html.py:37`** — `select_autoescape(["html","xml"])` 对唯一模板 `3033.html.j2` 返回 `False`，所有 `{{ }}` 原样输出。EDITOR 可通过 block 标题、新闻标题覆盖、`terminology_overrides` 注入脚本，在 SPA 同源预览中执行，也能在 PDF 渲染的 headless Chromium 中改写 DOM 数字。**一行修复**：`autoescape=True`。
2. **`backend/app/core/security.py:26-36`** — ENTRA 模式只检查 `Authorization` 以 `"Bearer "` 开头，全仓无任何 JWT/OIDC 校验代码；角色、用户 ID、产品范围全部来自客户端头。`Principal.product_scope` 定义后从未被任何查询使用。
3. **`backend/app/domain/service/audit.py:14`** — `audit()` 没有 actor 参数，`AuditEvent.actor` 恒为默认值 `"local-user"`。监管可追溯性名存实亡。
4. **仓库不可复现** — `backend/Dockerfile`、`backend/app/rendering/static/csop-logo.png`（`html.py:379` 无条件读取，任何渲染必崩）、`backend/tests/fixtures/3033_202606/*.json`、`fixtures/ingestion/*` 均被 gitignore；`.github/workflows/ci.yml` 第 14 步必然在收集阶段中断。
5. **`backend/app/domain/service/calculations.py:232-239`** — 同 `(snapshot, metric_code, dimension, formula_version)` 的 `MetricValue` 被原地覆写，而 `formula_version` 等于产品目录的 `formula_profile`（`:385`），算法改动不产生新版本 → 无法证明"当时算的是什么"。

---

## 1. 可构建性与可复现性（严重）

### 1.1 新克隆无法 build / test / run

这个仓库是"脱敏快照"，`.gitignore` 排除了运行所必需的文件：

| 被排除的路径 | `.gitignore` 规则 | 后果 |
|---|---|---|
| `backend/Dockerfile` | L204 | `compose.yaml:16,56` 引用它 → `docker compose up --build` 必败 |
| `backend/.env.example` | L203 | 无环境变量模板 |
| `backend/app/rendering/static/csop-logo.png` | `*.png` L32 | `html.py:379`、`artifacts.py:277` 无条件 `read_bytes()` → **生产渲染路径**抛 `FileNotFoundError`，不只是测试 |
| `backend/tests/fixtures/3033_202606/{snapshot,expected,editorial}.json` | L60 | `snapshots.py:447`（生产代码）与 `test_golden_expectations.py:18` 读取 → pytest 收集即中断 |
| `backend/tests/fixtures/3033_202606/reference.pdf` | `*.pdf` L21 | 视觉回归不可运行 |
| `backend/tests/fixtures/ingestion/*.{csv,xlsx}` | L18/L27 | 摄取测试 11 例失败 |
| `docs/` 整个目录 | L62 | CLAUDE.md / AGENTS.md / README 引用的所有文档、ADR、规格书全部缺失 |

`build_fixture.py` 只能从原作者机器 `~/Downloads/HSTECH_eod_con_20260630.csv` 重建其中两个文件，且全仓无任何运行说明（`grep build_fixture` 在所有 md/py/yml 中零命中）。

### 1.2 实际测试运行结果

本机无 `.venv`、无 `node_modules`，唯一带依赖的解释器是 Python 3.10（项目要求 ≥3.12，且已装依赖版本低于 pyproject 下限），因此以下结果仅作参考：

- 原样运行：`conftest.py → app.main → routes/render.py → worker.py:3 from celery import Celery` → `ModuleNotFoundError`，**零用例被收集**。`worker.py` 在模块顶层 import celery，使 celery 成为整个 API 的硬依赖。
- 注入 celery 桩后：`43 failed, 140 passed, 1 skipped, 3 errors`。43 个失败逐个核实全部归因于上表缺失文件及其下游效应，**未发现独立于 fixture 缺失的代码缺陷**。
- 前端 `npm test` / `tsc` 因无 `node_modules` 无法运行，未获得客观结果。

### 1.3 依赖不可复现

- `backend/pyproject.toml` 全为范围约束，CI 用 `pip install -e` 直接解析，无锁文件。
- `backend/uv.lock` 存在但已过期（缺 `opencc-python-reimplemented` 与 `python-dotenv` 两个直接依赖），CI 不读它；CLAUDE.md 却声称"no `uv` in this repo"。
- `frontend/package.json` 中 `react`、`react-dom`、`typescript`、`vite`、`vitest`、`@vitejs/plugin-react`、`@types/react`、`@types/react-dom` 共 **8 个 `"latest"`**；`package-lock.json` 当前解析到 react 19.2.8、typescript **7.0.2**、vite 8.2.1、vitest 4.1.10。`npm ci` 可复现，任何一次 `npm install` 都会无审查地跨大版本。
- `typescript`、`vite`、`@vitejs/plugin-react` 放在 `dependencies` 而非 `devDependencies`。
- Node：CI 与 Dockerfile 用 24，无 `engines` / `.nvmrc`。
- `frontend/Dockerfile` 基础镜像仅按 tag 固定，无 digest。

### 1.4 README 命令错误

`README.md:9,27,57` 三处 `\.\.venv\Scripts\python` 有多余前导反斜杠，PowerShell 无法执行；应为 `.\.venv\Scripts\python`。

### 1.5 `.gitignore` 卫生

230 行中约 150 行是一次性个人路径（`.codex-artifacts/automation-commentary-slide-20260824/...` 逐文件列举、`Automation of Commentary - Bi-Weekly Update v2.pptx` 等），应清理为目录级规则。

---

## 2. 安全（生产：严重；LOCAL 开发：可接受）

### 2.1 认证 / 授权

| # | 严重度 | 位置 | 发现 |
|---|---|---|---|
| S1 | **Critical** | `core/security.py:26-28` | ENTRA 模式只检查 `authorization.startswith("Bearer ")`，全仓无 `jwt`/`jose`/`msal`/`oidc` 依赖或校验代码。发 `Bearer x` + `X-User-Role: ADMIN` 即为 ADMIN。 |
| S2 | **High** | `core/security.py:16,35` | `Principal.product_scope` 来自客户端头 `X-Product-Scope`（默认 `*`），全仓仅此一处引用，**任何查询都不过滤**。多租户隔离在设计上存在、实现上为零。 |
| S3 | **High** | `service/audit.py:14`、`models.py:358` | 审计事件不记录操作者；唯一写入主体的地方 `catalog.py:160 approved_by=principal.subject` 取自可伪造的 `X-User-ID`。 |
| S4 | Medium | `api/routes/deps.py` | 只有 `Db` 与 `RequestId`，无角色依赖。仅 3 个端点自行检查 ADMIN（`catalog.py:41,62,123`）；其余写端点 EDITOR 与 ADMIN 权限等同。`GET /audit`（`admin.py:22`）对 VIEWER 开放。 |
| S5 | Low | `security.py:23,33` | `endswith("/health")` 放行与 `endswith("/finalize")` 门禁都是脆弱的字符串匹配；将来任何 `/reports/{id}/health` 路由会整体跳过认证。当前无可利用绕过。 |
| S6 | Low | `main.py:20-22` | `/docs` 不以 `/api/v1` 开头，完全绕过中间件；compose 下仅内网可达。 |

前端 `api.ts:254-256` 从不发送角色头，因此 LOCAL 模式下所有 SPA 用户都是 ADMIN。

### 2.2 输出注入（XSS）

| # | 严重度 | 位置 | 发现 |
|---|---|---|---|
| S7 | **High** | `rendering/html.py:35-39,397` | `select_autoescape(["html","xml"])` 按文件名后缀判断，`"3033.html.j2".endswith(".html")` 为 `False`（本机 jinja2 实测复现）。可控注入点：`{{ block.title }}`（`.j2:124`，仅校验长度）、`{{ product_display_name }}`（`.j2:121` ← `terminology_overrides.product_name`，`documents.py:43` 让任意键透传）、新闻 `title/summary/source`（`.j2:140`）、`{{ review_title }}`。影响：(a) `GET /reports/{id}/preview` 与 SPA 同源 → 存储型 XSS；(b) PDF 渲染用 `file://` + `wait_until="networkidle"`，注入脚本在 render worker 的 Chromium 中执行，可 `fetch()` 内网、挂起渲染、**在 `page.pdf()` 前改写 DOM 数字**。`block.content|safe` 本身有服务端白名单清洗（`document.py:27-59`，质量不错），说明作者以为 escaping 是开着的。 |
| S8 | Low | `schemas.py:251`、`CompanyNewsWorkbench.tsx:469` | 手动新闻 `source_url: str` 无 scheme 校验，前端直接作 `href`；另一 EDITOR 经 API 写入 `javascript:` URL 即可触发。 |

### 2.3 签名下载与文件处理

| # | 严重度 | 位置 | 发现 |
|---|---|---|---|
| S9 | Medium | `render.py:99-110`、`storage.py:41-46` | 签名 `HMAC(secret, f"{artifact_id}:{principal.subject}:{expires}")` 中 `subject` 来自客户端头，任何人带相同 `X-User-ID` 即可复用链接。实现细节正面：`hmac.compare_digest`、TTL 服务端校验、`storage.resolve()` 做容器检查，无路径穿越面。 |
| S10 | High（生产） | `config.py:33`、`compose.yaml:7-8,18,22,59,62` | `DOWNLOAD_SECRET` 默认值公开在仓库；compose 明文硬编码 MySQL 密码与签名密钥，无启动时拒绝默认值的守卫。 |
| S11 | Medium | `datasets.py:96-127` | `data = await file.read()` 先于 20MB 检查，全量读入内存。nginx 未配 `client_max_body_size`（默认 1MB）反而挡住了这条路径 —— 但也意味着**合法的 20MB 上传经 nginx 会 413**（功能 bug）。 |
| S12 | Low | `ingestion.py:512-515` | `list(sheet.iter_rows())` 读整张表，无行/列上限；`stage_import` 对每个 APPROVED profile 重新 `load_workbook`。 |

### 2.4 未发现问题的领域（做得好）

- **SQL 注入：未发现**。`datawarehouse.py:82-87` 视图名经 `^[A-Za-z0-9_]+$` 校验后才拼接；所有用户值 `:param` 绑定；`PRAGMA query_only=ON`、`mode=ro`、`SET SESSION TRANSACTION READ ONLY` 只读加固到位。
- **SSRF**：MarketAux / FMP 强制 https + host 白名单，`follow_redirects=False`；对象 URL 下载流式校验 SHA256 与 `max_bytes`，未配置 SHA 时 fail closed。仅 `*_OBJECT_URL` 下载 `follow_redirects=True` 且无 host 白名单（Low，运维配置而非用户输入）。
- **机密**：`datawarehouse_mysql_password` 设 `repr=False`；MarketAux `_redact` + `from None` 切断含 token 的 URL；`admin.py` 无 settings 回显；前端无 `dangerouslySetInnerHTML`。

### 2.5 其他

- `frontend/nginx.conf`：无 CSP、无 HSTS、无 `X-Frame-Options`，仅 80 端口；未设 `X-Forwarded-For/Proto`。
- DoS 面：EAGER 模式下 Playwright 在 HTTP 请求内同步执行且无超时；无速率限制；`GET /reports/{id}/snapshots` 返回**完整 payload** 且不分页。
- `worker.py:28`、`render.py:79` 把 `str(error)` 写入 `job.error` 返回前端，可能含文件系统绝对路径。

---

## 3. 架构与约束合规（较差）

以 CLAUDE.md / AGENTS.md / CONTEXT.md 声明的硬约束逐条核对：

| 约束 | 裁定 | 关键证据 |
|---|---|---|
| No hardcoded report facts | **PARTIAL（偏 FAIL）** | 无个股/日期事实，但：`schemas.py:11 product_code="3033"`；`snapshots.py:440` golden 门禁写死 `"3033"`/`"2026-06-30"`；`industry_breakdown.py:28 INDUSTRY_DISPLAY_ORDER` 按参考报告校准；`footnotes.py:38,62-65,105-110` 脚注整句字面量；`html.py:387`、`artifacts.py:922` 传字面量 `"HKD"`（计算侧 `final_analytics.py:201` 正确用 `product_currency`）；`localization.py:60-67` "百万港元"写死；4 个迁移 seed 业务事实（10 只 ETF 来源标注 `CSOP_SCREENSHOT_202608`，即从截图转录）；前端 `App.tsx:12 PRODUCT_CODE="3033"`、`ReportModulesV2.tsx:154-155 "3033.HK"/"HSTECHN Index"` 覆盖后端 `row.name` |
| No authoritative calculation in browser | **PASS（附注）** | 均为格式化；但 `ReportModulesV2.tsx:204 Number(row.close_price ?? 0).toFixed(2)` 把缺失价格渲染为 `0.00`；`:39-76 portfolioRows` 在浏览器编造 AUM/Turnover 行与币种标签 |
| Nothing immutable is overwritten | **PARTIAL** | `calculations.py:232-239` `MetricValue` 原地覆写、`:264-271` `QualityCheckResult`、`:338-346` `ModuleSnapshot`；`import_batches.py:532-533` 已 flush 的 `DataSnapshot.payload/checksum` 重赋；`catalog.py:105-108 import_products` 对 `ProductCatalog` `setattr` 原地改写（它是所有血缘的解析锚点）。正面：`delete_report` 软归档；`discard/clear` 只改状态或追加 |
| No implicit mixing of CDB / upload | **PARTIAL** | 元数据记录到位；但 `snapshots.py:258-275 enrich_constituent_returns` 用 FMP 回报覆盖上传的 canonical 行后 `source_type` 仍标 `UPLOAD` 并保留原文件 checksum；`source_policy` 推导在三处各异 |
| AI never produces numbers | **PARTIAL（不强制）** | 无 LLM，`ai_assisted_draft` 是确定性模板；QC-008 `reports.py:908-942` 存在但 `update_document` 不调用，`finalize:1057-1064` 把 BLOCKING 失败收进 `advisory_failures` 后照常 `FINALIZED`。CLAUDE.md "must pass QC-008" 在后端无门禁 |
| Secrets never leak | **PARTIAL** | 见 §2.1 S1 / §2.3 S10；其余到位 |
| `var/` runtime-only；容器不依赖本地盘 | **FAIL** | `storage.py:19-49` 仅 `LocalObjectStorage`，`settings.storage_backend` 全仓仅定义处一次引用，无分派；`artifacts.py:962-968` 直接写 `output_root`，`put_file` 目标==源为 no-op；`compose.yaml:53,76` api/worker 共享 bind-mount `./var/output`，等价 PVC |
| `metrics/` 纯净 | **PASS** | 仅 stdlib + `validation`/`localization`，无 Session/models |
| service 分层顺序 | **PARTIAL** | `snapshots→calculations` 逆向 ×3（`677,705,783`）、`reports→calculations` ×2、`import_batches→calculations` ×1，全部函数内 import；`reports.py:50` import 私有 `_stage_auto_snapshot`；`lifecycle`/`import_batches` 未入文档；`__init__.py` 说"单一例外两个函数"实为 3 模块 6 处 |
| "凡碰 Session 的都在 service/" | **FAIL** | `domain/industry.py:117-189`、`rendering/artifacts.py:952-1027 build_artifact(db)`、`api/routes/*` 14/52 个 handler 直接 `select(...)`、`worker.py` |
| 血缘 `Config→Snapshot→Metric→Document→Artifact` | **PARTIAL** | `ReportDocument.snapshot_id`、`RenderArtifact.document_version`、`Report.active_snapshot_id`、`RenderJob.artifact_id`、`*.applied_snapshot_id` 均 nullable 字串**无 FK**；`RenderArtifact` 无 `snapshot_id/formula_version/design_token_version` 列；`formula_version == product.formula_profile`（CONTEXT.md 明确区分两者，代码合二为一） |
| API 约定（version→409、202+status URL、`unit+display_precision`） | **PARTIAL** | `PATCH document`/`finalize`/`DELETE`/`PUT news` 有 version；`imports/apply`、`snapshots`、`calculations` 无；`JobRead` 字段名 `id` 非 `job_id` 且**无 status URL**；EAGER 模式先同步渲染再回 202；`GET metrics` 无 `display_precision`；`analytics.portfolio[].value` 是格式化串 `"1,234.56 million"`；两个都叫 `version` 的乐观锁令牌（`Report.version` vs `ReportDocument.version`）会漂移 |

### 3.1 文档未覆盖的架构风险

- **三条并行 snapshot 组装管线**：`_stage_auto_snapshot` / `apply_import` / `apply_import_batch` 在 lane 继承、BLOCKING 处理、`source_policy` 推导、`datasets[]` 元数据构造、后续 `ReportDocument` 创建上各自实现、语义不一致，是血缘失真的根源。
- **单基金硬耦合**：`html.py:397` 直接 `get_template("3033.html.j2")`，`template_version` 只控制 `enable_review_layout`；token 文件颜色在模板 `<style>` 中被重复硬编码（`.j2:9`），token 实际只控制环图和水印；`industry.py:64-65` 拒绝非 HSICS；seed 的 10 只 ETF 被后续迁移全部停用。产品目录 schema 通用，渲染/税则/术语/前端/货币全部绑定 3033。
- **God modules**：`da_report.py` 1321、`datawarehouse.py` 1203、`snapshots.py` 1090、`reports.py` 1072（语言变体 + OpenCC + QC-008 + finalize）、`artifacts.py` 1027（docx XML 助手 + PIL 环图 + DOCX 布局 + Playwright + DB 持久化）、`ingestion.py` 918。
- **前端复制后端展示契约**：portfolio 标签逻辑 ×3（`final_analytics.normalize_portfolio_rows` / `ReportModulesV2.portfolioRows` / `localization.PORTFOLIO_LABELS`）、占位符列表 ×3、HSICS 颜色表在 `SectorDonut.tsx:23-29` 重复。JS `toFixed` 与后端 `ROUND_HALF_UP` 在 x.xx5 边界可能不同，UI 与 PDF 末位可能不一致。
- **生产代码依赖 `tests/` 目录**：`snapshots.py:447` 运行时读 `service_root/tests/fixtures`。

---

## 4. 后端代码质量（一般）

客观基线（排除两个死模块）：428 个函数，**34 个超过 80 行**，6 处 `except Exception`，0 TODO/FIXME，0 `print`，0 `type: ignore`/`noqa`，216 处 `Any` 注解，1 个未用 import，18 个迁移单线性链、全部有非空 `downgrade()`。

### 4.1 死代码（High）

`backend/app/api/routes.py`（983 行）与 `backend/app/domain/service.py`（1647 行）是拆包前的旧版本。Python 解析时同名包优先，二者**不可达**。AST 对比：`routes.py` 比 `routes/` 少 9 个函数，`service.py` 比 `service/` 少 43 个函数，是过期副本。保留会让 grep/审计产生误判（本次审计已遇到）。建议直接删除。

### 4.2 超长函数（前 10）

| 行数 | 位置 | 混合的关切 |
|---|---|---|
| 316 | `service/calculations.py:49 persist_calculation_records` | 从 4 个 payload 段构建 spec + upsert `MetricValue` + upsert `QualityCheckResult` + 构建 `ModuleSnapshot` |
| 262 | `integrations/da_report.py:812 _list_company_news_catalog_sync` | 参数校验 + SQL 谓词拼装 + 游标分页 + 4 个 facet 聚合 + 结果整形；facet 谓词 `1000-1004` 以字面量重述 `841-845` |
| 250 | `domain/ingestion.py:401 parse_constituent_returns` | 嵌套深度 5 |
| 237 | `integrations/datawarehouse.py:470 load_fund_kpis` | |
| 217 | `domain/snapshot_composer.py:19 compose_da_report_fragment` | 六段顺序 `try/except`，每段手工构造 9 键 finding dict；一个 `finding()` 助手可砍半 |
| 211 | `metrics/quality_checks.py:49 snapshot_checks` | |
| 208 | `service/snapshots.py:461 _stage_auto_snapshot` | 上传保留策略 + provider 片段合并 + 历史表现计算 + QC + 去重 + `source_policy` 推导 + `mapping_version` 推导 + 持久化 + 文档版本 |
| 205 | `integrations/da_report.py:363 load_monthly_data` | |
| 202 | `rendering/artifacts.py:748 render_docx` | |
| 198 | `service/reports.py:511 create_language_variant` | |

### 4.3 重复

- **High** `da_report.py:190-310` ↔ `datawarehouse.py:121-227`：`_verify_file` / `_materialize_snapshot` / `_file_checksum` / `_engine` 约 120 行近乎逐字复制，只差 settings 前缀与异常类。
- **Medium** "追加新 `ReportDocument` 版本"的仪式（构造 + `db.add` + `report.version += 1`）手写 **10 次**：`calculations.py:435`、`documents.py:76`、`import_batches.py:556`、`reports.py:79,637,877,1065`、`snapshots.py:650,765,929,1065`。
- **Medium** 环境变量布尔解析 `os.getenv(...).strip().lower() in {"1","true","yes","y"}` 在 `config.py` 重复 6 次。
- **Medium** 上传大小限制在 `routes/datasets.py:117-127`（裸魔数）与 `service/import_batches.py:322-327`（已有 `MAX_FILE_BYTES` 常量）重复。
- **Medium** 三个 provider 错误类字段相同但属性名不一致（`news.py:24 http_status` vs `datawarehouse.py:63` / `fmp.py:32 status_code`）；HTTP 状态→错误梯度在 `fmp.py:127-141` ↔ `marketaux.py:159-169` 重复。
- **Low** 深拷贝写法不一致：`json.loads(json.dumps(x))` 17 次（12 次在 `snapshots.py`）vs `copy.deepcopy` 26 次。

### 4.4 分层与耦合

- **High** `from fastapi import HTTPException` 出现在 **9/10 个 `domain/service/*` 模块**、约 60 个 raise 点。领域规则无法脱离 FastAPI 在 Celery worker 或 CLI 中运行；`import_batches.py:350-357` 甚至捕获 `HTTPException` 再解包 `detail` 作控制流。
- **Medium** 14/52 个路由 handler 直接 `select(...)` 而不经 service；`routes/catalog.py:116-171 create_mapping_profile` 整个写事务在路由内；`routes/render.py:44-82` 幂等查找、产物复用决策、job 创建、dispatch 全在路由内。
- **Medium** `routes/news.py:46-79` 等 `async def` handler 调用同步 SQLAlchemy `Session`，每次 DB 往返阻塞事件循环。

### 4.5 错误处理

- **Medium** `routes/render.py:80`：CELERY 模式下 dispatch 后 job 仍为 `QUEUED`，审计被记为 `render.failed`。
- **Medium** `import_batches.py:105-108`：`except Exception` 吞掉解析错误后按扩展名猜 dataset type。
- **Medium** `worker.py:16-18` job 不存在时返回 dict 而非 raise，Celery 任务报成功；`:35 autoretry_for=(OSError,)` 但 `:28` 所有失败都标 `retryable: True`。
- **Medium** `security.py` 直接返回 `JSONResponse`，绕过 `main.py:33-51` 的 envelope handler，401/403 缺 `severity/fix_hint/request_id`；service 层约 25/60 处 `HTTPException` 只带 `error_code`，靠 handler 回填 `"Request failed."`。
- **Medium** `artifacts.py:961,1007` 用 `ValueError("QC-010: ...")` 把错误码嵌进字符串，`worker.py:28` 再压平为 `RENDER_FAILED`，丢失原码。
- **Low** `snapshots.py:838-847` 用 4 个 `getattr` 从 `ValueError` 重建 envelope，而 `metrics/errors.py` 的 `CalculationError` 正是为此存在。

### 4.6 配置

- **High** `config.py:9-13` 把 `Path.home()/"Downloads"/...` 写进模块常量，生产进程会静默绑定到 `~/Downloads` 里恰好存在的文件。
- **Medium** 10 处 `int()`/`float()` 在 import 时对原始 env 字串求值（`:34,39,40,51,52,61,108,109,115,116`），`DOWNLOAD_TTL_SECONDS=5m` 之类 typo 会让 app 与 alembic 一起在 import 时以裸 `ValueError` 崩溃。
- **Medium** 不安全默认：`auth_mode="LOCAL"`、`download_secret` 公开值；无 fail-fast 守卫把 `auth_mode != LOCAL` 与非默认 secret 绑定。
- **Low** `database.py:17-20` MySQL 引擎无 `pool_pre_ping`/`pool_recycle`（适配器引擎 `datawarehouse.py:261-262` 反而设了）。

### 4.7 数据库 / ORM

- **Medium** `calculations.py:207-217,257-263,314-315` N+1 upsert：每个 metric（30 成份股 × 4 周期 + 行业 ≈ 150+ 行）、每个 QC 结果、每个模块各一条 `SELECT`。
- **Medium** 7 个被 join 的 ID 列无 `ForeignKey`（`models.py:118,119,126,219,242,252,335`）。
- **Medium** `DataSnapshot.payload` / `DataImport.payload` / `ReportDocument.content` 每个版本全量复制，存储 O(versions × payload)。
- **Medium** `admin.py:24-26` 先 `LIMIT 500` 再按 `report_id` 过滤 → 旧报告返回空。
- **Medium** `import_batches.py:331` + `imports.py:117` 循环内 commit，文件 N 失败留下半 staged 的 `STAGING` 批次；`render.py:68,73,81` 每格式 commit。
- **Low** `GET /reports`、`/news`、`/industry-master`、`/mapping-profiles` 不分页。

### 4.8 迁移

- 链完整：18 个 revision 单头 `c8f0e1a2b345`，无分叉，全部有 downgrade。
- **Medium** `b7d8e9f0a123` upgrade 是状态相关的（`:76-77 if industry_count == 0`），两个同 head 环境可能持有不同数据；其 `downgrade():100-103` 会重新激活**所有** `CSOP_SCREENSHOT_202608` 行，包括管理员后来停用的。
- **Medium** `c216f31d8a42`、`f3b8c4d2a6e1`、`b7d8e9f0a123`、`c05e7a9f3b86`（`CASE WHEN product_code='3033' THEN 'HSTECHN'`）在迁移中 seed 业务事实与 per-product 逻辑。

### 4.9 Celery / 渲染

- **Medium** `worker.py:41-47 dispatch_render` 三条代码路径（`.delay()` / 调用方 session 内直跑 / `.apply(throw=True)` 开第二个 `SessionLocal`），事务边界不一致。
- **Medium** `artifacts.py:981-982` 每次 PDF 新启 Chromium；`browser.close()`（`:1006,1009`）不在 `finally`，`page.goto/evaluate/pdf` 任一失败即泄漏浏览器。
- **Medium** `render.py:47` 幂等 check-then-insert 无 `IntegrityError` 处理，并发同 key 会 500。

### 4.10 其他遗留

- `localization.py:212 enrich_simplified_names`、`da_report.py:330 _validate_monthly_schema`、`datawarehouse.py:25-29` 五个视图名常量：从未引用。
- `snapshots.py:818-819` 死赋值；`:884` 集合含 `"constituents"` 等已被 `:811` 提前拒绝的成员；`models.py:229` `DataImport.dataset_type` 默认值仍是已退役的 `"constituents"`。
- `documents.py:95-141 ai_assisted_draft` 写 `drivers/monitor` 字段，V2 文档 schema 已不用，靠 `html.py:101-107` 兼容代码活着。
- 9 行分号连接语句；`imports.py:110` 单行嵌套三元 + 生成器。

---

## 5. 前端代码质量（一般）

### 5.1 亮点

`styles.css` **0 处硬编码 hex、0 处 rgba**；焦点环用 `var(--focus-ring)`；按压 `scale(.97)`、玻璃 `backdrop-filter` 19 处、骨架屏、`i*60ms` 交错封顶 540ms、`prefers-reduced-motion` 全局降级、`tabular-nums` 19 处 —— 全部合规。`strict: true`，0 `any`，0 `@ts-ignore`。`CompanyNewsWorkbench.tsx:277-318` 用 generation counter + `useDeferredValue` 做竞态防护，是全项目唯一做对的地方。

### 5.2 问题

| 严重度 | 位置 | 发现 |
|---|---|---|
| **High** | `App.tsx:257-707 ReportWorkspace` | 450 行 god component：11 `useState`、4 `useEffect`、12 个 async handler；`changeLanguage`（438-501）单函数串行 6 次 API 调用 |
| **High** | `App.tsx:613-619` | 渲染任务轮询 `while (!isTerminal)` **无上限、无取消、无退避**，组件卸载后继续 setState |
| **High** | `App.tsx:291-298` | 页面加载的 `useEffect` 触发写操作 `POST refreshAutomaticData`；`StrictMode` 下开发态双发 |
| **High** | `api.ts:252-261` | `request<T>` 是 `response.json() as Promise<T>`，无运行时校验；`:258` 后端 `{error_code, message, severity, fix_hint}` 被 `await response.text()` 塞进 `Error.message`，随后 17 处 `setError(String(caught))` 把原始 JSON 展示给用户；409/422 无专门处理，`fix_hint` 从未显示 |
| **High** | 全局 | **无 ESLint、无 Prettier、无 `.editorconfig`**。直接后果：`ReportModulesV2.tsx:146` 单行 JSX **2157 字符**；`reportModules.ts`/CSS 用 tab、其余用 2 空格；6+ 处 hooks 依赖数组不完整（`ReportModulesV2.tsx:108,110,183,279`、`CompanyNewsWorkbench.tsx:281-288`） |
| **High** | `components/MultiFileBatchUpload.tsx`（153 行）、`DatasetUploadSlot.tsx`（83 行） | 生产代码零引用的死组件；随之死亡 8 个 `api.*` 方法（`uploadImportBatch/excludeImportBatchFile/applyImportBatch/discardImportBatch/getImportBatch/listNewsProviders/listReportNewsCandidates/fetchNewsCandidates`）与类型 `NewsProvider` |
| **High** | `ReportModulesV2.tsx:204` | `Number(row.close_price ?? 0).toFixed(2)` 把缺失价格渲染为 `0.00`；`:39-76,246` 在浏览器编造 AUM/Turnover 指标行与"百万港元"标签，测试 `ReportModulesV2.test.tsx:160` 反而固化了这一行为 |
| Medium | `ReportModulesV2.tsx:210-212,257-259`、`CsvDatasetUpload.tsx:38-45` | 4 处 `listDatasets` 裸 `useEffect + then(setState)`，无 `AbortController`（全项目 0 处）、无 generation 守卫 → 快速切换报告时旧响应覆盖新状态；`CsvDatasetUpload.tsx:44` 无 `.catch` |
| Medium | `api.ts:227` | `latest_document.content: Record<string, unknown>` → 下游 34 处 `as JsonRecord` 强转，文档结构完全无类型 |
| Medium | `tsconfig.json` | 缺 `noUncheckedIndexedAccess`、`noUnusedLocals`、`noUnusedParameters`（死导出因此未被编译器发现） |
| Medium | `tokens.css:186-212` | `body.dark-mode` 令牌完整定义，但 `styles.css` 与所有 `.tsx` 中零处引用 —— **暗色模式不可达** |
| Medium | `styles.css` | 70 行含无令牌的 px 值：`10px` 出现约 20 次、`3px` rail 5 次、`max-height: 610px/560px`、`min-height: 680px` 等；`.news-list 560px` 与 `.news-catalog-list var(--layout-news-list-height)=640px` 同类列表两套值 |
| Medium | 多处 | 11 处中文字面量绕过 i18n（`ReportModulesV2.tsx:87-88,143,202,246`、`SectorDonut.tsx:61`、`ReviewCanvas.tsx:47-49`、`CompanyNewsWorkbench.tsx:464`）；约 35 处英文字面量（`MultiFileBatchUpload.tsx` 整文件、`ReviewCanvas.tsx:27-34`、`App.tsx:23,615,621`）；`locale === "zh-Hans" ? … : …` 三元链重复 23 次 |
| Medium | `i18n.tsx:772` | `statusLabel` 在英文下直接返回原始枚举，用户看到 `READY_TO_FINALIZE`；无复数规则（`"1 reports"`） |
| Medium | `CompanyNewsWorkbench.tsx:184` | 只读报告下"移除"按钮未 `disabled`，可在 FINALIZED 报告本地删除已选新闻 |
| Medium | `frontend/nginx.conf` | 缺 `client_max_body_size`（默认 1m，CSV/XLSX 超 1MB 会 413）；`/assets/*` 哈希文件无 `immutable`、`index.html` 无 `no-cache`；缺 CSP / `X-Frame-Options` |
| Medium | `App.test.tsx:99-161` | 24 处按英文文案精确匹配（`"Open English report for 2026-07-31, EDITING"`），文案一改即碎；`api.test.ts` 17 处断言 `JSON.stringify` 键顺序 |
| Medium | `frontend/package.json:9` | `vitest run --pool=forks --maxWorkers=1` 强制串行，无文档说明，是脆弱性绕行方案；无 `vitest.config`，jsdom 靠每文件头部注释声明 |
| Low | `ReviewCanvas.tsx:64,69`、`App.tsx:540` | 拖拽把手是 `<span>` 不可键盘操作；`window.prompt` 输入链接；`window.confirm` 删除确认（与 DESIGN.md 弹层规范不符） |
| Low | `package.json` | `@tiptap/extension-link` 冗余（StarterKit v3 已内置）；`react-resizable` 仅用其 CSS |

---

## 6. 测试与 CI（较差）

### 6.1 CI 现状

`.github/workflows/ci.yml` 18 行、单 job：checkout → Python 3.12 → Node 24 → `pip install -e` → playwright → pytest → `npm ci` → `npm test` → `npm run build`。

- **必然失败**：第 14 步 `pytest` 在收集阶段因 `test_golden_expectations.py:18 FileNotFoundError: expected.json` 中断（exit 2）；即使加 `--continue-on-collection-errors` 仍 ≥43 例失败。前端步骤永远不执行。**CI 现状等于没有 CI**。
- 缺失（逐项确认）：lint（ruff/eslint）、类型检查（mypy/pyright/独立 `tsc`）、覆盖率阈值、安全扫描（pip-audit/npm audit）、MySQL service、Docker build 验证、pip 缓存、`concurrency` 取消、Action SHA 固定、`permissions:` 块、`timeout-minutes`、失败工件上传。
- `config.py:121-124` 注释说"CI turn it on deliberately"（`ALLOW_TESTING_LANE`），实际 CI 未设置，靠 `conftest.py:24` monkeypatch。

### 6.2 覆盖缺口

52 个端点中 **10 个**没有任何 `client.<method>()` 调用：`GET /health`、`GET /industry-master`、`GET .../import-batches/{id}`、`POST .../exclude`、`POST .../import-batches/{id}/discard`、`GET .../data-diff`、`GET /news`、`GET /jobs/{id}`、`GET /artifacts/{id}/content`（仅间接）、`GET .../preview`。

| 模块 | 结论 | 缺口 |
|---|---|---|
| `core/security.py` | **thin** | 仅 2 例（VIEWER 写→403、EDITOR finalize→403）；无 ENTRA 401、无 `INVALID_ROLE`、无 REVIEWER 正向 finalize、无 `X-Product-Scope`、无 `/health` 绕过 |
| `core/storage.py` | **thin** | 仅 happy path；无篡改签名 / 过期 / 跨 subject / 路径穿越测试 |
| `worker.py` | **thin** | `task_mode`/`celery`/`dispatch_render` 在 tests 中零命中；CELERY 分支与 `autoretry` 完全未测 |
| `service/import_batches.py`（564 行） | thin | 5 个端点中 4 个无直接调用 |
| `metrics/fund_kpis.py`（9 个公共函数）、`constituent_performance.py`、`formatting.py` | thin / untested | |
| `domain/metrics/*` 其余、`integrations/*`（httpx.MockTransport）、`products.py` | covered | |

### 6.3 迁移测试

`test_migrations.py` 单个用例：SQLite 临时文件 `upgrade head` → 断言 → `command.check` → `downgrade base`。**不做** downgrade→re-upgrade，**不逐 revision** 步进，**无 MySQL**。18 个迁移中 16 个含 `op.execute`/`batch_alter_table`，从未在 compose 声明的 MySQL 8.4 上验证。

### 6.4 测试质量

- **内联黄金数字**（违反"golden 值只放 `fixtures/`"）：`test_chart_snapshot.py:172,190,191,237,239`（`"47.8%"`、`"67,536.55 million"`）、`test_content_workflow.py:212`、`test_reports_api.py:469`、`test_visual_qa.py:63-71`。
- **吞掉状态码的 helper**：`test_content_workflow.py:7-11`、`test_marketaux_news.py:124-127`、`test_chart_snapshot.py:165-169` 对 `POST .../snapshots` 不检查状态码，503 被吞后到下游才炸，产生 15 个误导性失败。
- 超长测试：`test_reports_api.py::test_traditional_variant_...` 182 行等 4 个 >100 行。
- 条件 skip：`test_import_batches.py:10` 依赖 `HSTECH_ACCEPTANCE_FIXTURE` 环境变量，CI 未设置 → 永远 skip。
- 正面：196 个 test def 中 0 个无断言；全部网络经 `httpx.MockTransport`；`client` fixture 每例新建内存 DB，无顺序依赖。

### 6.5 工具链缺口（全部确认缺失）

`ruff` / `mypy` / `pyright` 配置、`.pre-commit-config.yaml`、ESLint / Prettier 配置、`.editorconfig`、`CODEOWNERS`、`Makefile`/任务运行器、`dependabot.yml`、`SECURITY.md` / `CONTRIBUTING.md` / `LICENSE`。`pyproject.toml` 仅有 setuptools 与 pytest 段；两个 `package.json` 无 `lint`/`format` 脚本。

---

## 7. 文档与现实偏差

| # | 文档声明 | 实际 |
|---|---|---|
| 1 | CLAUDE.md "no `uv` in this repo" | `backend/uv.lock` 1315 行 + README 有 uv 指引 |
| 2 | CLAUDE.md/AGENTS.md `rendering/static/` | 不存在；`html.py:379` 无条件读 → 渲染必崩 |
| 3 | `docs/adr/`、`docs/implementation-status.md`、`docs/spec/...V2.1.md`、`docs/product-catalog-import.md`、`docs/news-sources-and-data-imports.md`、ADR-0014 | `docs/` 被 gitignore，全部不存在（代码注释 `marketaux.py:11`、`news.py:61`、`test_visual_qa.py:16` 也引用） |
| 4 | compose / AGENTS.md "全栈容器" | `backend/Dockerfile` 不存在 |
| 5 | README:62 "checked-in 3033 visual baseline under `fixtures/3033_202606`" | 目录只有 `build_fixture.py` |
| 6 | CLAUDE.md `imports.py` "CSV/XLSX parsing" | XLSX 在 `ingestion.py`；`ingestion/industry/localization/snapshot_composer/validation` 未记载 |
| 7 | CLAUDE.md integrations 只列 `da_report/marketaux` | 漏 `datawarehouse.py`、`fmp.py`、`news.py`；Settings 漏 `datawarehouse_*`、`fmp_*`、`storage_backend`、`allow_testing_lane` |
| 8 | "凡碰 Session 的都在 service/"；`__init__` "单一例外两个函数" | 见 §3；实为 3 模块 6 处 |
| 9 | CONTEXT.md source policy 5 个值 | 代码 ≥10 个；`DA_REPORT_AUTO_LOAD`/`CDB_ONLY` 从未产出 |
| 10 | CONTEXT.md "formula change creates a new value rather than mutating" | `MetricValue` 原地覆写 |
| 11 | CONTEXT.md 环图"its own formula version" | 实用产品 profile |
| 12 | CLAUDE.md "App.tsx owns fund selection" | 静态 `PRODUCT_CODE="3033"` |
| 13 | CLAUDE.md "must pass QC-008" | advisory，不阻断 |
| 14 | AGENTS.md "no PVC / TOS or DB" | 仅本地盘 + bind-mount |
| 15 | CLAUDE.md "202 with `job_id` and a status URL" | 字段名 `id`、无 status URL |
| 16 | `routes/catalog.py:4` "versioned rather than edited in place" | `import_products` `setattr` 原地改写 |

---

## 8. 做得好的地方

为避免报告只有负面，以下是审计中确认的高于平均水平的实践：

- **领域词汇表**（`CONTEXT.md`）清晰、有"避免用词"栏，是少见的好习惯。
- **SQL 安全**：全参数化、视图名白名单校验、只读连接三重加固。
- **出站请求**：https 强制、host 白名单、流式 SHA256 + 大小校验、fail closed。
- **富文本清洗**（`document.py:27-59`）：标签白名单、丢弃全部属性、`href` scheme 限制。
- **指标层纯净**：`domain/metrics/` 无任何 Session/ORM 依赖，是唯一被充分测试的层。
- **迁移纪律**：18 个 revision 线性、全部可逆、有测试。
- **前端设计令牌**：颜色/焦点/动效/骨架/reduced-motion 全部合规，0 硬编码颜色。
- **小处纪律**：0 TODO、0 print、0 类型抑制、0 `any`。
- **错误封装设计**：`{error_code, message, severity, fix_hint, request_id}` 结构统一（虽然前端没用上）。

---

## 9. 修复路线图

### P0 — 立即

1. `html.py:37` → `autoescape=True`；给 `block.title`、`terminology_overrides.*`、news 字段加纯文本校验；补 `title`/news 的 XSS 测试。
2. 删除 `backend/app/api/routes.py` 与 `backend/app/domain/service.py`（2,630 行死代码）。
3. 从 `.gitignore` 放行并提交：`backend/Dockerfile`、`backend/.env.example`、`backend/app/rendering/static/csop-logo.png`、`backend/tests/fixtures/**`（至少 JSON 与 CSV）；或把 logo 改为可配置路径 + 缺失时降级。
4. `Settings` 加启动守卫：`auth_mode != LOCAL` 时拒绝默认 `download_secret`；删除 `Path.home()/Downloads` 探测。
5. `worker.py` 把 `from celery import Celery` 改为惰性 import，解除 API 对 celery 的硬依赖。
6. README 修正 `\.\.venv` typo。

### P1 — 上线前必须

7. 实现 ENTRA JWT 校验（签名、`aud`、`iss`、`exp`），角色与 `product_scope` 从 claims 派生；新增 `require_role(*roles)` 依赖并在每个写路由声明；在 `get_report`/`list_reports` 强制 `product_scope`。
8. `audit(db, principal, action, ...)` 强制 actor；`approved_by` 与下载签名 `subject` 改用已验证主体。
9. `MetricValue`/`ModuleSnapshot`/`QualityCheckResult` 改为仅追加，`formula_version = f"{code_constant}+{profile}"`；`import_products` 禁止原地改写；`RenderArtifact` 加 `snapshot_id/formula_version/design_token_version` 列与 FK。
10. QC-008 与 BLOCKING 门禁：在 `update_document` 与 `finalize` 强制，或以 ADR 明确记录 advisory 决策并从 CLAUDE.md 删除 "must pass"。
11. CI：加 ruff + mypy/pyright + eslint + `tsc --noEmit` + pip-audit/npm audit；加 MySQL service 跑迁移；`npm ci` 前先跑前端步骤（分 job）。
12. 前端 `package.json` 去 `"latest"`，`typescript/vite/@vitejs/plugin-react` 移到 devDependencies；生成 `requirements.txt`（`uv export` 或 pip-compile）并在 CI/镜像中使用。
13. nginx：`client_max_body_size 25m`、CSP、`X-Frame-Options`、`X-Forwarded-*`；uvicorn `--proxy-headers`。
14. `api.ts:258` 解析错误 envelope 为类型化对象；409/422 专门处理；展示 `fix_hint`。
15. `ReportModulesV2.tsx:204` 缺失价格显示 `—` 而非 `0.00`；`portfolioRows` 标签/币种改由后端提供。

### P2 — 结构性改进

16. 实现 `STORAGE_BACKEND=TOS` 分派；`build_artifact` 写临时目录再 `put_file`；下载走签名 URL 或流式转发；移除 compose 共享 bind-mount。
17. 收敛三条 snapshot 管线为一个 composer（统一 `source_policy`、lane、`datasets[]` 元数据、文档版本创建）；修正 FMP 覆盖上传 canonical 的 checksum 失真。
18. 领域层去 `HTTPException`：定义 `DomainError(error_code, message, severity, fix_hint)`，在 `api/` 边界统一转换。
19. 抽取 `_materialize_snapshot` 等约 120 行到共享 `integrations/_sqlite_snapshot.py`；抽取 `append_document_version()` 助手替换 10 处手写。
20. 拆分 6 个 >900 行 god module；`persist_calculation_records` 拆为 spec 构建 / metric upsert / QC upsert / module snapshot 四步，并把 N+1 改为预加载。
21. `App.tsx` 拆分 `ReportWorkspace`：抽出 `useRenderJobPolling`（带上限/取消）、`useLanguageVariant`、`useReportLoader`；引入 ESLint（含 `react-hooks/exhaustive-deps`）+ Prettier；删除两个死组件与 8 个死 API 方法。
22. `html.py:387` / `artifacts.py:922` 的 `"HKD"` 改用 `payload["product_currency"]`；`get_template` 由 `template_version` 驱动；`INDUSTRY_DISPLAY_ORDER` 等移入产品配置。
23. 补测试：ENTRA 401、`X-Product-Scope`、签名篡改/过期/跨 subject、CELERY 分支、逐 revision 迁移 + downgrade→re-upgrade。
24. 同步 CLAUDE.md / AGENTS.md / CONTEXT.md / README 的 16 处偏差；把 `docs/` 从 gitignore 放出或在文档中删除引用。

---

## 附录 A：客观指标

| 指标 | 值 |
|---|---|
| 后端函数总数（live） | 428 |
| >80 行函数 | 34 |
| 最长函数 | 316 行（`persist_calculation_records`） |
| >900 行模块 | 6 |
| 死代码 | 2 文件 / 2,630 行 |
| `except Exception` | 6 |
| `Any` 注解 | 216 |
| 无 `response_model` 的路由 | 20 / 52 |
| service 模块 import `HTTPException` | 9 / 10 |
| 函数内逆向 import | 6 处 |
| 迁移 | 18，单头，全部可逆 |
| 无 FK 的 ID 列 | 7 |
| 端点无任何测试调用 | 10 / 52 |
| 前端 `"latest"` 依赖 | 8 |
| 前端死组件 / 死 API 方法 | 2 / 8 |
| `styles.css` 硬编码颜色 | 0 |
| `styles.css` 无令牌 px 行 | 70 |
| `:focus-visible` / `:hover` / `:active` / `:disabled` | 8 / 25 / 6 / 14 |
| 绕过 i18n 的中文 / 英文字面量 | 11 / ~35 |
| 文档偏差项 | 16 |
| 本机 pytest（3.10 + celery 桩） | 140 passed / 43 failed / 3 errors / 1 skipped，失败全部归因缺失 fixture |

## 附录 B：审计范围与局限

- 审计基于 `main @ cec9abb` 的工作树，未访问 `origin/refactor/project-layout` 分支历史。
- 测试在 Python 3.10 + 低于 pyproject 下限的依赖版本上运行，结果仅作参考；前端测试与类型检查因无 `node_modules` 未能运行。
- 未运行 ruff/mypy/eslint（未安装且未被允许安装），复杂度与类型数据来自 AST 与 grep。
- `backend/Dockerfile` 被 gitignore，容器以何用户运行、Playwright 依赖是否完整等无法审计。
- 所有行号引用截至审计当日；核心论断（autoescape、ENTRA、audit actor、`product_scope`、`MetricValue` 覆写、logo 硬依赖、3033 门禁、死代码 AST 对比）已在源码中二次核实。
