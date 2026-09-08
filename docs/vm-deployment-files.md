# VM 部署文件与执行顺序

此文为备用的 VM 直跑方案。最新目标已改为 IH 集群 UAT/PRD，请从
[Kubernetes 部署说明](../k8s/README.md) 开始。旧配置已归档至 [deploy/vm/README.md](../deploy/vm/README.md)。

本配置面向 Ubuntu VM 直跑 Docker，使用公司提供的外部 MySQL 8 和 Redis。
不适用于 EKS，也不需要 kubectl。文件已生成，不代表已经完成生产发布。

## 文件用途

| 文件 | 用途 |
| --- | --- |
| [deploy/vm/compose.vm-trial.yaml](../deploy/vm/compose.vm-trial.yaml) | 与原 Compose 合并的隔离试运行配置；回环端口默认 18080 |
| [deploy/vm/compose.vm-build.yaml](../deploy/vm/compose.vm-build.yaml) | 只负责构建正式版 API 和 web 镜像，不用于运行 |
| [deploy/vm/compose.vm-production.yaml](../deploy/vm/compose.vm-production.yaml) | 独立运行清单：migrate、api、worker、web；回环端口默认 18081 |
| [deploy/vm/.env.example](../deploy/vm/.env.example) | 正式配置模板，无可用机密 |
| [backend/Dockerfile.vm](../backend/Dockerfile.vm) | 保留 Chromium 和报告字体，固定 UID 10001 |
| [frontend/Dockerfile.vm](../frontend/Dockerfile.vm) | Node 构建、nginx-unprivileged 运行，固定 UID 101、端口 8080 |
| [frontend/nginx/vm.conf.template](../frontend/nginx/vm.conf.template) | 运行时替换后端地址与域名，提供 /healthz、SPA 回退和缓存策略 |

**不要把正式运行清单与原 [compose.yaml](../compose.yaml) 合并。** 原文件中的本地数据库、
Redis、LOCAL 配置及磁盘卷仅属于开发/试运行；正式清单故意不继承它们。
两个项目名不同，默认端口不同，可以区分，但仍须先确认 VM 资源与端口预算。

## 正式配置的约束

- API、worker、migrate 共用环境配置、数据库、队列和存储桶。
- `AUTH_MODE=ENTRA`、`STORAGE_BACKEND=S3`、`ALLOW_TESTING_LANE=false` 固定在 YAML 中。
- 一次性 migrate 服务先通过配置守卫，再执行 Alembic；API 等它成功，worker 等 API 健康。
- 三个后端服务都是只读根、非 root、无额外 capabilities；写入仅使用有容量上限的 tmpfs。
- `/app/var/output` 的 tmpfs 是渲染中间文件，不是产物存储；最终产物必须上传到 TOS。
- web 仅发布 `127.0.0.1:18081`，数据库、Redis、API 不发布宿主机端口。
- `init: true` 提供 PID 1 子进程回收；日志轮转，每个服务有内存和 CPU 上限。
- API/worker/web 自动重启，migrate 不重启。健康检查变成 unhealthy 不会自动重启容器，仍需监控告警。
- 默认总内存上限约 6.25 GiB，包含迁移服务的瞬时预算；tmpfs 使用计入对应容器内存。
  需要按共享 VM 实际余量调节，不能直接按默认值认定容量足够。
- Compose 不支持安全的跨版本滚动数据库迁移；本方案按单 API、维护窗口发布。

## 在 VM 上准备

先完成 [Ubuntu VM 操作手册](vm-docker-deployment-guide.zh-CN.md) 的机器检查和代码获取步骤。
Docker Engine 需为团队批准版本，Compose 至少 2.24.4。以下命令都在 VM 的仓库根目录执行。

```bash
cd ~/apps/report-automation
umask 077
test -e deploy/vm/.env.vm || cp deploy/vm/.env.example deploy/vm/.env.vm
chmod 600 deploy/vm/.env.vm
nano deploy/vm/.env.vm
```

填值要求：

1. `API_IMAGE`、`WEB_IMAGE`：使用本次发布专属标签，如包含 Git SHA，不要用 latest。
   有镜像仓库时，构建后推送并记录 digest；运行配置可改用 digest，但 build 的 image 必须是标签。
2. `BACKEND_BASE_IMAGE`：批准的 Playwright Python Noble 镜像 digest；
   `PLAYWRIGHT_VERSION` 必须对应镜像内浏览器版本，不是随意填一个 Python 包版本。
3. `NODE_BASE_IMAGE`：批准的 Node 24 镜像 digest；`NGINX_BASE_IMAGE`：
   批准的 nginxinc/nginx-unprivileged Alpine 镜像 digest。不能改用普通 nginx 镜像充数。
4. `DATABASE_URL`：公司应用库的 `mysql+pymysql://...?...charset=utf8mb4` 连接串，
   不是 DA-Report 数据库，也不是数仓只读账号。数据库需预先创建，并授予迁移所需权限。
5. `REDIS_URL`：批准的独立 Celery broker/数据库，不能与其他项目复用默认队列。
   优先使用 TLS；Celery 的 rediss 连接应按供应商要求配置证书验证，例如 `ssl_cert_reqs=required`，
   不能用 CERT_NONE 绕过。MySQL TLS 同样遵循公司要求，不通过关闭证书校验解决连接问题。
6. `PUBLIC_HOST`：纯域名；`PUBLIC_ORIGIN`：对应的 `https://域名`，不要加路径或尾斜杠。
   API_UPSTREAM 固定为内部服务 `api:8000`，不能填公网 API 地址。
7. `ENTRA_*`、TOS、CDB、FMP、DA-Report：通过批准的秘密管理渠道填入。
   密码里的特殊字符按 URL 规则编码，dotenv 中含 `$` 的字面值要按 dotenv 规则单引号保护。

空白必填项会让 Compose 拒绝解析。不要 source 这个配置文件；也不要把完整 `config`、
`inspect`、环境变量或签名 URL 发到聊天/工单。Shell 已导出的同名变量会覆盖 env 文件，
请确认当前会话没有遗留另一个环境的配置。

数仓默认使用镜像内公共 CA bundle；公司私有 CA 需要经审查的只读挂载并设置容器内路径。
只把 Windows 路径填入配置不会让证书出现在容器里。应用库、Redis 的私有 CA 也要单独确认。

## 构建与首次启动

在当前 Bash 会话定义两个缩写；重新登录后需重新定义：

```bash
build_vm() { docker compose --env-file deploy/vm/.env.vm -f deploy/vm/compose.vm-build.yaml "$@"; }
prod() { docker compose --env-file deploy/vm/.env.vm -f deploy/vm/compose.vm-production.yaml "$@"; }
build_vm config --quiet
prod config --quiet
build_vm build
```

先确认镜像已构建成功。下面的 `true` 只运行镜像自带的配置守卫，不执行数据库迁移：

```bash
prod run --rm --no-deps migrate true
```

随后确认目标数据库属于本环境、有备份或为空库、没有其他进程在迁移，并取得发布授权。
以下命令会**实际修改数据库 schema**，不能对不确定的数据库执行：

```bash
prod up -d --wait --wait-timeout 300
prod ps -a
prod logs --tail=80 migrate api worker web
curl -fsS http://127.0.0.1:18081/healthz
curl -fsS http://127.0.0.1:18081/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/api/v1/reports
```

预期 migrate 为 Exited(0)，三个长驻服务为 healthy，无令牌的 reports 请求返回 **401**。
只要迁移失败，API 与 worker 就不应启动。端口改过时，同步替换 curl 的端口。
第一次上线后仍需运行完整预检和真实业务验收；预检的容器执行方式见长手册第 9 节。

nginx 从同一个 VM 上的受信任 TLS 代理接收流量，并保留其 HTTPS 转发标识。
代理必须设置正确 Host、X-Forwarded-Proto，并覆盖不可信的外部转发头；域名、证书及现有
80/443 端口由管理员管理。**没有生成或安装 TLS 证书，也没有修改任何云防火墙或 DNS。**
如公司的 TLS 代理在另一台机器，不能直接连本配置的回环端口，需要另行审批网络入口方案。

## 更新和回滚

更新前确认并排空业务任务，取得维护窗口，备份外部数据库与产物，保留旧镜像引用和旧配置。
不要重建并覆盖旧标签。然后更新源码及新镜像标签，按顺序执行：

```bash
build_vm config --quiet
prod config --quiet
build_vm build
prod run --rm --no-deps migrate true
prod stop web worker api
prod up -d --force-recreate --wait --wait-timeout 300
prod ps -a
```

`--force-recreate` 会重新执行 migrate，并重建 web，使 nginx 重新解析 API 容器地址。
更新失败时保留错误日志，不要反复启动迁移或自动降级数据库。

回滚先确认旧应用兼容当前 schema；只有兼容时，恢复旧镜像引用及相应配置，再按相同的
维护窗口流程启动。否则使用事先演练的数据库恢复/迁移回退方案。
修改 env 文件后用 `up -d` 重建受影响容器，单纯 restart 不会重新载入环境变量。
当前没有本地数据卷，仍不能以此为由忽略外部数据库和对象存储的备份。

## 试运行 YAML

只做工作站隔离试运行时，不使用正式镜像和 `.env.vm`，而使用原镜像、根 `.env` 和覆盖文件：

```bash
dc() { docker compose --env-file .env -p commentary-trial -f compose.yaml -f deploy/vm/compose.vm-trial.yaml "$@"; }
dc config --quiet
dc build api web
dc up -d --wait --wait-timeout 300 api
dc up -d --no-build worker web
```

试运行配置继承原 Compose 的五个服务、LOCAL 配置和测试卷，仅发布回环端口 18080。
不要加载生产敏感数据。访问与结束方法见长手册的 SSH 隧道和 `dc stop` 步骤。

## 尚未完成的发布门槛

- 前端还没有浏览器登录/访问令牌注入；正式 YAML 不会替它完成，业务页面目前会遇到 401。
  当前 nginx 保留原产品 CSP/COOP/防嵌入策略，后续需配合所选登录方式验证，不盲目放宽。
- Python 全量传递依赖还没有 Linux 平台的冻结 lock；这次固定了 Playwright 版本，并要求
  指定基础镜像与发布镜像版本，但不能宣称源码重建完全可重复。正式发布前须补齐该门槛。
- 当前机器只有 Docker CLI、没有可连接的 Linux engine，未构建镜像，也未验证非 root
  Chromium、nginx 模板渲染、只读文件系统下的真实运行及端到端报告输出。
- 真实 MySQL 版本/权限/TLS、Redis 隔离/TLS、公司登录、TOS 写入下载、上游数据、资源容量、
  备份恢复和 HTTPS 入口尚需现场验收。文件没有填写任何公司凭据或虚构基础镜像 digest。

本次只生成部署文件，不会连接 VM、创建云资源、修改外部数据库或开放访问。