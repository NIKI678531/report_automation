# 本次改写的验证记录

日期：2026-09-08。对应 ADR-0026 / ADR-0027 / ADR-0028 / ADR-0029 / ADR-0030 / ADR-0031，验证均在本机执行。

## 移除可选新闻源（ADR-0031）

- 删除 Marketaux 适配器、注册项、6 个运行配置项、环境及 Secret 字段和供应商专属测试；新闻流程仅保留 DA-Report，通用 provider 测试迁入 test_news_providers.py。
- 新闻、DA 数据源、安全和部署定向回归：182 passed / 12 skipped；跳过项均因未配置独立 DA MySQL 合同测试库，本次没有连接真实供应商或启动服务栈。
- 对抗式验证覆盖：DA 唯一可见、配置状态、默认/显式/大小写兼容抓取、候选与审计保存；旧或未知 provider 请求返回 422 且不回退，旧 Secret 字段被拒绝且错误不泄露值。
- 环境模板、Secret 模板和生成器字段完全一致：Production 9 个 key、UAT 11 个 key；本地 Production 环境文件和 Secret YAML 同步删除旧字段，其他内容原样保留。此处数量覆盖下方历史记录。
- 历史新闻、报告内容与审计数据保留；无数据库迁移、集群更新或凭据输出。

## Production YAML legacy 配置清理（ADR-0030 后续）

- Production 删除 DA_REPORT_OBJECT_URL / DA_REPORT_SQLITE_SHA256 和 DA_REPORT_CACHE_DIR；Secret 精简为 10 个 key。UAT 保留 12 个 key 及快照能力，以下初版 MySQL 记录中的两环境 12 key 已由本节更新。
- Secret 生成器按环境选择完整字段集合，拒绝 Production 旧字段；生产必填 DA URL、字面值保留、缺失字段/弱密钥拒绝、错误信息脱敏和 YAML 引用回归共 124 passed。
- 两环境模板与生成器字段一致；本地 .env.prd / Secret YAML 已同步清理，DA 连接保持一致且凭据文件受 Git 忽略保护。本机无 .env.uat，UAT 模板的 DA MySQL URL 为空。
- 本地 Production Secret 仍待填写应用 DATABASE_URL 和 DOWNLOAD_SECRET；未操作集群、启动服务或修改上游数据。

## Production DA-Report MySQL（ADR-0030）

- 用户明确提供的连接仅用于 Production，保存于 Git 忽略的 .env.prd；UAT 未填写该连接，实际 Secret 未 apply。
- 生产只读探测返回 MySQL 2003，无法建立连接；未查询或修改生产表，真实网络/字段/权限仍需目标环境验收。
- 基于 DA-Report 本地源码确认 news_sources / news_items / news_enrichments 和 market_monthly_turnovers 合同。
- 临时 MySQL 8.4.9 在 network none、无宿主端口、临时数据目录中运行；测试进程只共享其网络命名空间。
  19 项测试通过，涵盖只读写入拒绝、TLS、查询超时、日期类型、JSON、筛选分页、新闻选择、中文/全角匹配、月度公式和稳定 checksum。
- 本机后端全量 386 passed / 14 skipped；其中 12 项 MySQL 测试已在上述隔离库执行通过，其余 2 项为原有外部数据/一次性应用 MySQL 地址缺失。
  最后补充配置和去重检查后，定向回归 178 passed / 12 MySQL skips。
- 对抗式检查发现并修复：MySQL 浮点测试需匹配上游 DOUBLE；查询时间不能进入内容 checksum；MySQL 新来源需进入上传合并及快照血缘；生产 CA 曾被默认 PEM 排除规则挡住，现只对明确的公共 CA 文件放行，并在 Docker 构建时验证。
- Secret 现为 12 个 key；Production 必填独立 DA_REPORT_DATABASE_URL，UAT 保持空值。CI 增加仅接受 localhost/da_contract 的隔离 MySQL 合同测试。
- 后端最终镜像 `fund-commentary-srvapp:da-mysql-check` 构建成功，构建输出 manifest 为 `sha256:6241d11535c6b8a40d74864446477d8f39946b6db83f1096f048d42f6e90c5e6`；本机镜像 OCI index digest 为 `sha256:cf323034f6afe2e4cd637d0903e3fe9072f94dfd2006c3930aafca4fc095bc29`。
- 最终镜像在断网、只读根、非 root 条件下通过 Production 配置守卫、公共 CA 加载、应用导入和 MySQL engine 创建验证；未建立数据库连接，未启动 API。
- 本次隔离 MySQL 容器已核对完整 ID 和任务标签后停止并删除，临时数据随 tmpfs 清理。
- 最后部署结构检查 10 passed；`git diff --check` 和凭据隔离检查通过：`.env.prd` 被 Git 忽略，UAT 未使用生产 DA 连接，受版本控制源码未包含该连接或生产主机。

## 按需下载（ADR-0029）

- 后端全量：377 passed / 2 skipped（缺 HSTECH_ACCEPTANCE_FIXTURE 和一次性 TEST_MYSQL_URL）。
- 随后的对抗式复查补充非 ASCII 签名、Range 请求、文档 checksum 损坏用例，导出/安全回归 120 passed。
- 三格式内容、翻译一致性、TESTING 水印、归档定稿版本、生成失败/发送中断清理均通过。
- 前端 9 个测试文件、106 passed；TypeScript / Webpack 生产构建通过。
- 离线 Chromium 宿主契约通过：同域及 localhost 3000→3030 各连续两次下载并核对文件内容、文件名，签名查询参数原样保留；原有编辑、预览、重挂载流程保持通过。
- 前端镜像 `fund-commentary-webapp:on-demand-check` 构建成功，manifest `sha256:8989b7d701fc4042b33e24bb37722ae09734ea1bf88da49189156ee6a200d74a`。
- 后端最终镜像 `fund-commentary-srvapp:on-demand-check` 构建成功，manifest `sha256:458b8d1dece7407a9d39f3c9d5f18c6ca9e6de2578ca78f6a0587b9e4a79227c`；锁定依赖离线检查及 `pip check` 通过。
- 后端镜像在 UID 10001、断网、只读根、drop ALL、1 CPU/2 GiB 和临时 /tmp 下导入 REMOTE 应用成功；确认未安装 boto3/botocore/Celery/Redis，三格式生成、ASGI 文件响应、checksum 及响应后目录清理均通过。诊断只运行 Python，不启动 API。
- 前端镜像在断网、只读根和临时 conf.d/tmp 下模板展开及 `nginx -t` 通过；不启动 nginx。
- 对抗式复查覆盖固定定稿来源、权限/签名/版本篡改、损坏内容拒绝、Range 全量响应、生成与传输失败清理，以及活跃部署残留；`git diff --check` 通过。
- Linux Python 3.12 lock 移除 7 个成品存储专属依赖：boto3、botocore、jmespath、python-dateutil、s3transfer、six、urllib3；其余版本未升级。
- Secret 当前 11 个 key，前 2 个必填；活跃代码/部署配置无 S3 成品依赖、output volume、Redis/worker 或 PVC。

以下保留前一阶段验证记录，旧存储要求和 13 个 Secret key 已由 ADR-0029 覆盖。

## 移除 Redis（ADR-0028）

移除 Redis 后：`test_jobs.py`、`test_translations.py`、`test_security.py`、
`test_deployment_compose.py`、`test_k8s_deployment.py` 共 **161 passed**。
覆盖同步渲染成功/失败、独立 Session、翻译重试成功/耗尽、旧 TASK_MODE 拒绝、
13 个 Secret key、无 Redis 健康检查和单 API 容器拓扑。重试测试发现并修复了 ORM 在
复用 Session 时比较有/无时区时间戳导致提前终止的问题。
Linux Python 3.12 重新生成 lock，移除 14 个队列专属依赖，保留其他版本不变。
`fund-commentary-srvapp:no-redis-check` 构建成功（manifest
`sha256:9a2004c27cf7ed4594cfd99e49fc915ba80625adce7d022366ed597a733aa54d`），
离线依赖漂移检查及 `pip check` 通过。镜像确认未安装 Celery/Redis；UID 10001、断网、
只读根、drop ALL、临时目录、1 CPU/2 GiB 下，REMOTE 配置守卫和完整应用导入通过，
Chromium PDF 与 python-docx 运行时示例生成成功。未启动 API/前端/队列服务，未连接真实数据库或供应商。
对抗式复查覆盖应用 import、运行依赖、两环境拓扑和 Secret 模板；`git diff --check` 通过。

以下为此前部署和远程接入改写的验证记录：

| 检查 | 结果 |
|---|---|
| 部署/Secret/权限回归 | `test_security.py`、`test_k8s_deployment.py`、`test_deployment_compose.py`：128 passed |
| 后端广泛回归 | 首次 355 passed / 13 failed / 2 skipped；13 个失败均因本机缺 Chromium，安装后这 13 项复跑全部通过 |
| 数据库 URL 编码 | 新增迁移用例 1 passed，证明 `%40` / `%25` 不再被 ConfigParser 误解释；不连接真实库 |
| React 18 前端回归 | 9 个文件，106 passed；包含 Shadow DOM/语言清理、签名路径及原有编辑业务测试 |
| 远程浏览器契约 | HTTPS 同域、localhost 3000→3030 跨端口和独立入口全部通过；classic script init/get、宿主 React 18.3.1 singleton、Router 6.30.0、编辑/保存失败/预览/返回/卸载重挂载均通过；请求全部本地拦截 |
| webapp 镜像 | `fund-commentary-webapp:remote-check` 构建成功，包含 Node 24.19 / npm ci / TypeScript / Webpack 构建，端口 3030 |
| srvapp 镜像 | 标准 Dockerfile 构建成功，锁定依赖安装、离线漂移检查、pip check、Chromium 和字体安装通过 |
| nginx 只读验证 | UID 101、只读根、tmpfs 的 envsubst + nginx -t 通过；缺 API_UPSTREAM 按预期失败 |
| 后端只读验证 | UID 10001、断网、drop ALL、只读根、临时目录下成功 import 应用和生成 PDF / DOCX |
| 配置结构 | UAT/PRD 对称、引用/selector/端口/探针/Secret key 一致；无 Ingress/PVC；构建 ECR 地址准确 |
| 工作区检查 | git diff --check 通过；原有未跟踪 PROJECT_AUDIT_2026-09-03.md 保留 |

后端跳过的两项：未配置 HSTECH_ACCEPTANCE_FIXTURE、未配置一次性 TEST_MYSQL_URL。
测试中的 Python/Starlette/pypdfium2 弃用提示不影响上述通过结果。

没有启动 uvicorn、nginx 或 Celery 服务；镜像诊断仅运行 nginx -t、Python import 和渲染命令。
没有登录 AWS、向 ECR 推送、操作远端集群、创建云资源或迁移真实数据库。
本次验证不包含真实平台入口、集群 Pod 生命周期、MySQL/供应商连通性和端到端业务准入；
这些按 README / REMOTE / CHECKLIST 在部署环境验证。nginx 的代理和缓存已做配置审查及语法验证，
没有启动 nginx 发 HTTP 请求；平台路径、响应头和缺失资源 404 仍需按发布清单实际验收。
