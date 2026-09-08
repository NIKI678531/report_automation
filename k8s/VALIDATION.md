# 本次改写的验证记录

日期：2026-09-08。对应 ADR-0026 / ADR-0027，验证均在本机执行。

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
本次验证不包含真实平台入口、集群 Pod 生命周期、MySQL/Redis/TOS/供应商连通性和端到端业务准入；
这些按 README / REMOTE / CHECKLIST 在部署环境验证。nginx 的代理和缓存已做配置审查及语法验证，
没有启动 nginx 发 HTTP 请求；平台路径、响应头和缺失资源 404 仍需按发布清单实际验收。
