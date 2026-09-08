# 基金评论远程应用部署手册

本目录按用户提供的 `deploy-conventions.zip`（2026-09）重写，项目适配见
[ADR-0026](../docs/adr/0026-remote-app-deployment-conventions.md)。所有命令从仓库根目录执行。
现有远程应用平台负责入口和访问准入；本项目只提供 ClusterIP，不创建独立 Ingress、域名、
证书或 Entra 登录。平台访问 webapp Service:3030，nginx 在 3030 提供远程入口，
将 `/remote/fund-cmt-auto/api/v1` 转发到 srvapp:8000 的 `/api/v1`。
远程接入契约和宿主注册见 [REMOTE.md](REMOTE.md) / [ADR-0027](../docs/adr/0027-module-federation-remote.md)。

## 环境与对象

| 环境 | ECR registry | srvapp repository / Deployment / Service | webapp repository / Deployment / Service |
|---|---|---|---|
| UAT | `978533598453.dkr.ecr.ap-east-1.amazonaws.com` | `ih-uat-remote-fund-cmt-auto-srvapp` | `ih-uat-remote-fund-cmt-auto-webapp` |
| Production | `449732370091.dkr.ecr.ap-east-1.amazonaws.com` | `ih-prd-remote-fund-cmt-auto-srvapp` | `ih-prd-remote-fund-cmt-auto-webapp` |

两个集群均使用现有 namespace `ih`；命名沿用规范允许的环境前缀形式。
`namespace.yaml` 只声明命名空间，不修改共享 namespace 的标签或配额。
应用库必须为外部 MySQL 8 / utf8mb4，报告成品按下载请求生成；无需 S3/TOS、Redis 或独立 worker。
不部署数据库到 EKS，不创建 PVC。Pod 的 `/tmp`（含导出暂存）、nginx conf.d 全部为有上限的 emptyDir。

srvapp Deployment 是单副本 Recreate：先运行 migration init container，再启动一个 API 容器（1/1 Ready）。
迁移和 API 使用同一镜像、ConfigMap、Secret。渲染／翻译在 API 请求内同步执行。
uvicorn 优雅退出等待 210 秒，Pod 终止宽限为 240 秒；这不是任务执行时限。
发布有短暂停机；发版前等待运行中的渲染／翻译完成。不要直接把 replicas 改为 2。
webapp 为单副本 RollingUpdate，不配置会阻止节点排空的 PDB。

同步执行的限制与从旧队列迁移见 [ADR-0028](../docs/adr/0028-synchronous-jobs-without-redis.md)。
平台代理需要允许长请求；当前 nginx 的 API 超时为 900 秒，需在真实平台验证。
现有 `.env.<env>` 删除 `REDIS_URL`、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY` 后按新模板重建 Secret；切换前等待旧队列清空。
按需导出见 [ADR-0029](../docs/adr/0029-on-demand-report-downloads.md)：每次下载读取定稿版本，
完成或失败后清理临时文件；数据库只保留版本与审计，不保存成品 BLOB。
旧 render/job/artifact 下载接口已退役，发布前后端必须同步更新；历史表、已有桶和对象不删除。

## 文件

- `backend/Dockerfile`、`frontend/Dockerfile`：唯一镜像入口；固定版本及 digest。
- `backend/requirements.lock`：Linux Python 3.12 的运行依赖，包括 render 和可选 entra extra。
- `docker-compose.uat.yml` / `docker-compose.prd.yml`：仅 build / push，不是运行栈。
- `compose.yaml`：本地镜像验证；使用本地临时 MySQL，数据重建时会丢失。
- `k8s/<env>/configmap.yaml`：非机密运行参数；没有应用登录参数。
- `.env.<env>.example`：复制为被 gitignore 的 `.env.<env>`，只存该环境机密。
- `secret.example.yaml.txt`：空模板，扩展名保证目录 apply 不会覆盖线上 Secret。
- 本地填写的 Secret YAML 放 `k8s/<env>/secrets/secret.local.yaml`（Git 忽略目录）；必须补齐必填值后才能使用，常规发布仍由 `.env.<env>` 和 `create-secret.sh` 管理。
- `k8s/create-secret.sh`：Python 标准库辅助脚本的 Linux 入口，解析文件后通过 stdin apply。
- `.github/workflows/auto-docker-image-build.yml`：手动触发；只构建推送，无集群发布步骤。

## 1. 配置与预检

按业务需要检查 `k8s/<env>/configmap.yaml` 的数据来源与翻译配置；无需配置成品存储桶。
UAT / Production 模板已移除未启用的统一基金 KPI 视图字段；当前 AUM 使用 CDB 基金估值视图，日均成交额使用 DA-Report 的月度成交额和交易日数（ADR-0019）。
数仓 TLS 配置保留；Production 使用镜像内 `/app/backend/app/integrations/certs/aws-rds-ap-east-1.pem` 验证 RDS 证书，并保持主机名校验开启。
MySQL、签名密钥和供应商凭据放 `.env.<env>`；不复用 UAT 和 PRD 的机密。

```bash
cp .env.uat.example .env.uat
# 用批准的环境值填完整；生成 DOWNLOAD_SECRET 可用：
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
sh k8s/create-secret.sh uat --check
```

文件采用字面 `KEY=value`：不 source、不变量插值、不加外层引号；值里的 `$`、空格、`#`、`=` 原样保留。
按对应环境模板保留全部 key：Production 为 9 个，UAT 为 11 个；未启用供应商的值留空。DATABASE_URL、DOWNLOAD_SECRET 必填；Production 另外必填 DA_REPORT_DATABASE_URL，UAT 的该值留空；数据库 URL 内特殊字符须 URL 编码。
脚本不会读取 `.env` 或另一个环境文件作为回退，也不输出 key 的值。
Production 通过 `DA_REPORT_DATABASE_URL` 只读查询 DA-Report MySQL，使用镜像内 AWS RDS CA 并校验证书主机名；Production 的 Secret/环境文件已删除 DA_REPORT_OBJECT_URL / DA_REPORT_SQLITE_SHA256，ConfigMap 已删除 DA_REPORT_CACHE_DIR。
UAT 保留原快照来源，禁止复制生产 DA 连接；详情见 [ADR-0030](../docs/adr/0030-production-da-report-mysql.md)。
已有 Production 环境文件须删除两个旧 DA 快照 key，再按 9 个 key 的模板重建 Secret；生成器拒绝这些旧字段，即使其值为空。UAT 保留快照字段和配置，其他机密保持环境隔离。
两环境同时删除旧 `MARKETAUX_API_KEY`，开发配置删除全部 `MARKETAUX_*`，`NEWS_PROVIDER` 设为 `DA_REPORT`（[ADR-0031](../docs/adr/0031-remove-marketaux-news-provider.md)）。旧字段即使留空也会被 Secret 生成器拒绝。
开启翻译时填写 ConfigMap 的 provider/base URL/model 和 Secret 的 `TRANSLATION_API_KEY`。

两环境固定 `AUTH_MODE=REMOTE`、`TASK_MODE=EAGER`、`ALLOW_TESTING_LANE=false`。
REMOTE 不提供个人登录，所有操作与下载签名使用共享身份 `remote-app`，应用内有完整操作权限。
部署校验仍拒绝 SQLite 和默认签名密钥；网络准入由现有远程应用平台负责。

真实 RDS 连通性应在目标集群网络内检查。提前确认外部 MySQL 的 migration 权限、utf8mb4、
以及启用的数仓/新闻/FMP/翻译来源权限。不要把测试迁移的
`TEST_MYSQL_URL` 指向真实环境：迁移测试会清空目标库。

## 2. 构建与保存可回滚版本

Production 按规范在 `AI-Workstation-01`，使用 `AWS_PROFILE=ih_ecr_prd`。
UAT 使用已配置的 UAT AWS profile。先确认目标账号：

```bash
aws sts get-caller-identity
# UAT 示例；PRD 对应 449732370091 和 docker-compose.prd.yml。
aws ecr get-login-password --region ap-east-1 | docker login --username AWS --password-stdin 978533598453.dkr.ecr.ap-east-1.amazonaws.com
docker compose -f docker-compose.uat.yml build
# 同时保存完整 git SHA，必须在发布前保留已知可用版本。
TAG=$(git rev-parse HEAD)
REGISTRY=978533598453.dkr.ecr.ap-east-1.amazonaws.com
for COMPONENT in srvapp webapp; do
  IMAGE="$REGISTRY/ih-uat-remote-fund-cmt-auto-$COMPONENT"
  docker tag "$IMAGE:latest" "$IMAGE:$TAG"
  docker push "$IMAGE:$TAG"
done
docker compose -f docker-compose.uat.yml push
```

手动构建使用干净、已提交的检出，确保 SHA 能对应镜像内容。GitHub Actions 的
`Build ECR Images` 在 `uat` / `prd` GitHub Environment 读取 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY，
校验目标 AWS 账号并同时推送 `latest` 和完整 git SHA；两项构建都成功后才发布。

依赖更新须在 Linux Python 3.12 中生成 lock，再构建镜像：

```bash
python -m pip install pip-tools==7.5.3
pip-compile --extra render --extra entra --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file backend/requirements.lock backend/pyproject.toml
```

Dockerfile 安装 lock 后执行离线 manifest 漂移检查和 `pip check`。前端仅使用根目录 `package-lock.json` / `npm ci`。
报告字体 Carlito、Noto CJK / CJK Extra 必须与 CI 一致。

## 3. 部署

`CONTEXT` 必须替换成目标集群的真实 context，不依赖当前默认 context。
首次部署或配置变更先应用配置与 Secret；部署镜像前确认长任务已结束。

```bash
CONTEXT=REPLACE-ME-UAT-CONTEXT
kubectl --context "$CONTEXT" cluster-info
kubectl --context "$CONTEXT" apply -f k8s/uat/namespace.yaml -f k8s/uat/configmap.yaml
sh k8s/create-secret.sh uat --context "$CONTEXT"
kubectl --context "$CONTEXT" apply -f k8s/uat/
# 首次 apply 会创建 Pod；已有 Deployment 需要显式 restart，latest/配置变化不会自动滚动。
kubectl --context "$CONTEXT" -n ih rollout restart deploy/ih-uat-remote-fund-cmt-auto-srvapp
kubectl --context "$CONTEXT" -n ih rollout status deploy/ih-uat-remote-fund-cmt-auto-srvapp --timeout=10m
kubectl --context "$CONTEXT" -n ih rollout restart deploy/ih-uat-remote-fund-cmt-auto-webapp
kubectl --context "$CONTEXT" -n ih rollout status deploy/ih-uat-remote-fund-cmt-auto-webapp --timeout=5m
```

首次部署可省略 restart，避免触发第二次迁移。PRD 将路径与对象名中的 `uat` 替换成 `prd`。
不 apply `.txt` Secret 模板；更新 Secret 是整份更新，漏 key 会被本地校验拒绝。
如果其他工具管理相同 Secret 字段，先协调所有权；脚本不强行覆盖 server-side apply 冲突。

## 4. 验证和回滚

按 [CHECKLIST.md](CHECKLIST.md) 检查，日常命令见 [RUNBOOK.md](RUNBOOK.md)。
API 容器的浅健康检查 `/api/v1/health` 只检查 API 响应；从 webapp/平台访问时路径为
`/remote/fund-cmt-auto/api/v1/health`。nginx 探针 `/healthz` 不依赖 API。
深检查 `/api/v1/health/deep`（或容器内 `python -m app.core.health`）只返回数据库状态，
不输出连接信息；它不是 Kubernetes 探针。预检脚本会检查导出临时目录；三格式下载需单独验证生成、响应与临时文件清理。

回滚时先保存故障日志，从发布记录取上一对已知可用 git SHA 镜像，分别重新推成 latest，再 restart 两个 Deployment。
也可同时将 YAML 中 API、migration 和 webapp 的 image 改成旧 SHA 后 apply。
不要仅运行 `rollout undo`：相同 latest 标签不会恢复旧镜像，ConfigMap/Secret 也不会随 ReplicaSet 回退。
数据库默认前向修复；旧镜像必须兼容当前 schema，不能随意执行 downgrade。
若回滚到成品持久化版本，须同步恢复其存储配置、凭据和匹配前端；新导出没有历史文件可迁移。
若回滚到 Celery 版本，必须同步恢复其 Redis/worker、TASK_MODE 和 Secret，不能只退镜像。
