# ADR-0026：采用公司部署规范的远程应用部署

- 后续变更：成品存储、渲染任务及下载流程已由 [ADR-0029](0029-on-demand-report-downloads.md) 覆盖；当前按需生成下载，不依赖对象存储，Secret 为 11 个 key。本记录其余内容保留当时决策背景。
- 日期：2026-09-08
- 状态：已接受（用户明确指定）
- 依据：用户提供的 `deploy-conventions.zip`（2026-09 版 README、RUNBOOK、CHECKLIST 及模板）。
- 后续变更：本记录中的 Celery/Redis/worker 拓扑由 [ADR-0028](0028-synchronous-jobs-without-redis.md) 覆盖；当前采用 EAGER 同步执行。

## 决策

删除 VM 专用 Dockerfile、Compose、旧部署手册、旧 Secret 草稿生成器和独立 Ingress。
统一使用标准 Dockerfile、根目录 `docker-compose.uat.yml` / `docker-compose.prd.yml`、
`k8s/uat` / `k8s/prd` 纯 YAML，以及 `k8s/README.md` 的操作步骤。
命名保留给定的 `ih-<env>-remote-fund-cmt-auto-{srvapp,webapp}`，namespace 为现有 `ih`。

用户进一步明确“只作为远程应用，不需要处理域名、证书、Entra”，并要求移除登录部分。
因此本部署不创建 Ingress、不提供独立登录、不引入没有消费者的 VITE 认证变量。
入口约定已由后续 [ADR-0027](0027-module-federation-remote.md) 明确：webapp ClusterIP 和
容器均使用 3030，通过 `/remote/fund-cmt-auto/` 提供 Federation 入口、静态资源及 API。

新增显式 `AUTH_MODE=REMOTE`，统一使用 `remote-app` / ADMIN / 全产品范围操作身份，
不相信请求头提供的用户身份，也不要求 Bearer token。访问准入由远程应用平台负责；
本应用不会区分真实操作人员，下载签名也绑定此共享身份。保留现有 LOCAL 开发方式与
可选 ENTRA 代码，避免删除无关业务能力；新部署文件不使用 Entra。

REMOTE 仍执行部署校验；MySQL/utf8mb4、S3 兼容对象存储、强下载签名密钥、
禁用测试数据通道等约束不随登录移除。镜像入口在迁移、API 和 worker 之前执行相同守卫。

## 对规范的项目适配

- 两个镜像、两个 Deployment。srvapp Pod 中是 API + Celery，migration 为 init container。
  `Recreate` + 单副本避免部署时两个迁移并行；发布前等待长任务结束。存在短暂停机，
  暂不声称符合原规格书的多副本目标；扩容前应拆分 migration Job 与 worker Deployment。
- 前端继续 npm workspaces / Node 24；后端 Python 3.12。基础镜像固定版本及 digest，
  Linux 运行依赖通过 pip-tools 生成 requirements.lock；保留报告所需字体与 Chromium。
- 平台惯例 `latest` + `Always`；每次构建同时保存完整 git SHA 标签，回滚必须恢复两镜像。
- Secret 通过标准库脚本按固定 key 解析整份 `.env.<env>`，经 stdin server-side apply；
  避免 shell source、凭据进入参数和 last-applied 明文注解，重复运行可更新。
- 环境 Compose 仅作 build/push；本地验证使用独立 `compose.yaml`，避免环境构建清单
  被误当成完整应用栈。机密通过 raw env_file 读入，ConfigMap 是集群非机密配置来源。
- 不提供持久化卷。应用暂存采用有上限的 emptyDir/tmpfs；报告存对象存储。

## 验证边界

结构、配置、权限模式、Secret 字面值、日志过滤、健康检查和镜像构建在本地验证。
未连接目标 AWS 账号、未推送镜像、未操作集群或迁移真实数据库；远程平台路由、真实
MySQL/Redis/TOS 和上游数据权限由部署时按手册验证。
