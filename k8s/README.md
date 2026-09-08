# Fund Commentary Automation: IH 集群部署

当前目标是公司 IH 集群的 UAT/PRD，而不是 VM 直接运行网站。
VM 在本方案中是构建、推送镜像和执行 kubectl 的操作台；应用运行在集群 Pod 中。
仅生成了本地文件，没有验证这些镜像仓库或集群资源是否已由 IT 创建。

## 第一次在 VM1 操作

先理解三件事：**build** 只打包，**push** 只把镜像放到 ECR，**apply** 才会通知集群创建或更新
工作负载。构建文件名里有 Compose，不代表这次要在 VM1 执行 `docker compose up`。
完整顺序：检查工具和授权 -> 准备发布代码 -> 填构建参数 -> 构建并推送 -> 填应用配置和机密 ->
确认目标集群 -> dry-run -> 发布后端 -> 发布前端 -> Ingress/DNS -> 业务验收 -> 再推进 PRD。

以下命令均在 VM1 的 Ubuntu Bash 执行，不在个人电脑的 PowerShell 执行。
出现错误就停止该步骤，不把整份手册一次性粘贴执行。需要密码时只在终端输入，不发到聊天。

### 先看 VM1 已有什么

```bash
hostname
pwd
df -h /
free -h
git --version
docker version
docker compose version
docker context show
aws --version
aws configure list-profiles
kubectl version --client
kubectl config get-contexts
python3 --version
```

这些是检查，不会创建 Pod。Docker 要同时有 Client 和 Server，且 context 指向批准的构建引擎；
只有版本号不等于引擎可用。AWS profile/context 列表为空时，让 IT 配置访问，不要自行新建一套
生产凭据。缺工具或没权限时，由管理员按公司规范安装/授权，不自行重启 Docker、升级系统或清理卷。
VM1 曾显示磁盘使用率 83.4%，构建前应重新核对余量，尤其要为浏览器镜像及回滚镜像留空间。

### 把发布代码放到 VM1

VS Code 中生成文件不表示它们已在 VM1。先由负责人把审查过的变更纳入一个可获取的发布版本；
不要复制整个 Windows 工作区、机密文件或开发数据库。首次获取时：

```bash
mkdir -p ~/apps
cd ~/apps
REPO_URL='REPLACE_WITH_APPROVED_GIT_URL'
git clone "$REPO_URL" fund-commentary-automation
cd fund-commentary-automation
git fetch --tags
RELEASE_REF='REPLACE_WITH_APPROVED_GIT_TAG_OR_COMMIT'
git switch --detach "$RELEASE_REF"
git status --short
git rev-parse HEAD
ls deploy/uat/compose.build.yaml k8s/uat/srvapp-deployment.yaml k8s/create-secret.py
```

目录已存在时不要重新 clone 或覆盖，先 `cd` 到现有仓库并检查未提交修改；后续切换版本不能
使用 `reset --hard` 丢弃配置。Git URL 不嵌入 token，使用公司批准的 SSH 或凭据管理器。
以上三个文件不存在，说明获取的版本还没有部署文件，不应继续照后续命令操作。

### 三个名字分别是什么

| 名称 | 大白话 | 如何取得 |
| --- | --- | --- |
| AWS profile | 这次用哪份 AWS 身份 | `aws configure list-profiles` 列出候选，由 IT 确认 UAT/PRD 及权限 |
| Kubernetes context | kubectl 要去哪个集群、使用哪份身份 | `kubectl config get-contexts` 列出候选，由 IT 确认 |
| namespace | 项目在目标集群里的资源分区 | IT 提供；不能从 ECR 名字里的 `ih` 推断 |

2026-09-07 用户已明确确认本项目两环境使用 `ih` namespace，现有清单已同步；
UAT/PRD 仍属于不同集群，不能因为 namespace 相同而省略 context 核对。

AWS profile 的账号检查通过，不证明 kubectl 的 context 也正确：它们是两条独立的身份路径。
每条集群命令都显式使用 `--context`，不要只看终端之前选择了什么环境。

你可以把以下问题直接发给 IT：

> Please confirm the UAT and PRD AWS CLI profiles, EKS kubeconfig contexts and namespaces for
> Fund Commentary Automation. Please also confirm that the four requested ECR repositories exist,
> VM1 has image-push permissions, and the cluster nodes can pull these images. Please provide the
> approved application database/Redis endpoints, TOS configuration, application hostname and ACM
> certificate ARN through the appropriate secure channels.

### 两份环境文件不要混用

- `deploy/uat/.env` / `deploy/prd/.env` 是**构建参数**：版本标签、基础镜像、Playwright 版本。
- `k8s/uat/.env.secrets` / `k8s/prd/.env.secrets` 是**运行机密**：数据库连接串、密钥等。
- `k8s/<env>/configmap.yaml` 是**非机密运行配置**：认证模式、API audience、桶名、域名等。
- Deployment 的 image 标签必须等于构建时使用的 `RELEASE_TAG`；改构建 env 不会自动改 K8s YAML。
- Shell 里的 `NAMESPACE=...` 不会替换 YAML 的 `metadata.namespace`。每份 YAML 都要改成真实值。

`nano 路径` 是打开编辑器，不是启动应用；保存用 Ctrl+O、Enter，退出用 Ctrl+X。
下面的构建、Secret 和提交工作负载章节就是从这一步接着执行的实际命令。

## 环境目录

```text
k8s/
  README.md
  create-secret.py
  uat/
    configmap.yaml
    srvapp-deployment.yaml
    srvapp-service.yaml
    webapp-deployment.yaml
    webapp-service.yaml
    secret.example.yaml.txt
    .env.example
    ingress/ingress.yaml
  prd/                         # 与 uat 文件结构相同
deploy/
  uat/compose.build.yaml       # UAT 镜像构建及推送
  uat/.env.example             # 构建参数，无机密
  prd/compose.build.yaml       # PRD 镜像构建及推送
  prd/.env.example
  vm/                         # 之前的 VM 直跑方案，非当前集群入口
```

使用纯 YAML，不使用 Helm/Kustomize。两个环境结构相同，但资源名、ECR 账号和产物前缀不同。
Ingress 放在子目录，Secret 示例保留 `.txt` 后缀，普通非递归 apply 不会提交它们。
仍然推荐按下面的明确文件顺序发布，**不要 `kubectl apply -R -f k8s/`，也不要同时 apply 两环境**。

## 已填写的镜像仓库

| 环境 | 后端镜像仓库 | 前端镜像仓库 |
| --- | --- | --- |
| UAT | `978533598453.dkr.ecr.ap-east-1.amazonaws.com/ih-uat-remote-fund-cmt-auto-srvapp` | `978533598453.dkr.ecr.ap-east-1.amazonaws.com/ih-uat-remote-fund-cmt-auto-webapp` |
| PRD | `449732370091.dkr.ecr.ap-east-1.amazonaws.com/ih-prd-remote-fund-cmt-auto-srvapp` | `449732370091.dkr.ecr.ap-east-1.amazonaws.com/ih-prd-remote-fund-cmt-auto-webapp` |

Deployment 与 Service 名称沿用上述仓库最后一段。真正的 Pod 名称由 Kubernetes 自动生成，
会追加 ReplicaSet 和 Pod 后缀，不能把镜像仓库名称当作固定 Pod 名称。

## 两个 Deployment 内运行什么

- `srvapp` Deployment：单副本、Recreate；一个 Pod 内两个常驻容器 `srvapp` 和 `worker`。
  init 容器 `migrate` 先校验配置、执行 Alembic，再启动 API 和 worker，三者共用同一后端镜像。
- `webapp` Deployment：单副本、RollingUpdate；nginx 监听 8080，Service 对集群暴露 80。
  `/api/` 转发到本环境后端 Service 的 8000 端口；ALB 只路由至前端 Service。
- 因 API 和 worker 放在同一个 Pod，后端更新会中断服务，不是零停机发布；不得直接横向扩容。
  正式更新前排空队列、停止业务写入并备份应用库，init 迁移会真实修改数据库。
- 外部 MySQL/Redis/TOS 不在清单中创建；无 PVC、hostPath 或数据库容器。
  `emptyDir` 只存临时渲染文件及缓存，所有最终产物仍必须上传对象存储。
- 非 root、只读根、关闭特权提升、移除 capabilities，设置 fsGroup、资源限额及探针。
  后端镜像的 tini 处理子进程回收，K8s 使用 `args`，不绕过镜像的启动守卫。
- worker 用 PID 存活检查，避免 Redis 短暂降级导致整个后端 Pod 不就绪。
  它不等于队列健康，必须另做 Celery ping、排队任务监控及真实报告生成验收。
- 单副本前端不添加 PDB，避免阻塞节点排空。日志写 stdout/stderr，轮转和保留由集群负责。

## 必须由 IT 确认

申请邮件中的名称无法推导下面的信息，不能猜测：

1. **UAT/PRD 各自的 kubeconfig context 和 EKS 集群名**。用户已确认两环境 namespace 为 `ih`，
  每份清单已同步。没有创建 Namespace 的清单，避免误操作共享 IH namespace；发布前仍需核验
  目标集群中该 namespace 的访问权限。
2. ECR 仓库已创建、构建账号有推送权限、节点角色有拉取权限、节点 CPU 架构和资源配额。
   本镜像链按 Linux amd64 规划，应由 IT 确认节点适配；不能仅凭本机架构认定集群相同。
3. UAT/PRD 各自的应用数据库、Redis 队列隔离、TLS/CA、TOS 桶和最小权限密钥。
   数据库必须 MySQL 8 + utf8mb4；不同环境不得共用应用 schema 或 Celery 默认队列。
4. Entra 租户、API audience、角色及产品范围；两个环境浏览器回调域名。
5. 域名、同账号的 ACM 证书 ARN、IngressClass 是否为 `alb`、内网 ALB 和必要的 subnet 设置。
6. 网络/安全组允许 EKS 访问应用库、只读 CDB、Redis、TOS、Entra 及批准的外部数据 API。

ConfigMap 中的 `REPLACE-ME` 和 `.example.invalid` 都是待填写标记，不是默认生产值。
部署引用 `:replace-me-release`，需要替换为已推送的不可变发布标签或 digest，不能用 `latest`
掩盖未选择版本的问题。srvapp 清单里 init、API、worker 的镜像版本必须一起修改。

## 构建并推送

以下为 VM 上的 Bash 命令，先完成公司工具授权和 registry/network 准备。
所有命令在仓库根目录执行。以 UAT 为例；PRD 明确切换 ENV、账号、profile 与 context。

下面已填好申请中的账号和仓库名。第一次只执行 UAT，先不要发布 PRD。
`read` 会在 VM1 终端询问**非机密名称**，填写 IT 确认的 profile、context、namespace；
不在这些提示中输入密码或 token。若还不知道名称，停下来确认，不能填写镜像名称代替。

```bash
ENV=uat
ACCOUNT=978533598453
APP=ih-uat-remote-fund-cmt-auto
REGISTRY=978533598453.dkr.ecr.ap-east-1.amazonaws.com
aws configure list-profiles
kubectl config get-contexts
read -r -p 'Confirmed UAT AWS profile: ' AWS_PROFILE_NAME
read -r -p 'Confirmed UAT Kubernetes context: ' CONTEXT
NAMESPACE=ih
: "${AWS_PROFILE_NAME:?AWS profile is required}"
: "${CONTEXT:?Kubernetes context is required}"
: "${NAMESPACE:?Namespace is required}"
export RELEASE_TAG="$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
printf 'Release tag: %s\n' "$RELEASE_TAG"
umask 077
test -e "deploy/$ENV/.env" || cp "deploy/$ENV/.env.example" "deploy/$ENV/.env"
nano "deploy/$ENV/.env"
```

构建参数包括唯一 `RELEASE_TAG`、批准的基础镜像 digest、匹配浏览器版本的 Playwright 版本。
上面的 export 会将本次生成的 RELEASE_TAG 传给 Compose，优先于 env 文件中的同名值。
记录这个输出，后续 YAML 中所有 `replace-me-release` 必须使用同一标签；重连终端后需恢复
本次标签，不能重新生成另一个标签后直接发布。基础镜像 digest 不能由 ECR 应用仓库名推导，
仍须使用经过批准和拉取验证的值。源码有未提交改动时，应先完成发布版本审查，不用标签掩盖差异。
两个构建清单复用 [backend/Dockerfile.vm](../backend/Dockerfile.vm) 与
[frontend/Dockerfile.vm](../frontend/Dockerfile.vm)；文件名中的 vm 是历史名称，容器同样供 K8s 使用。
不要用原本 root 运行的开发 Dockerfile 构建这些部署镜像。应用配置和机密不进镜像。

```bash
ACTUAL_ACCOUNT=$(aws --profile "$AWS_PROFILE_NAME" sts get-caller-identity --query Account --output text)
if [ "$ACTUAL_ACCOUNT" != "$ACCOUNT" ]; then
  echo "STOP: AWS account is not $ACCOUNT. Do not build or publish with this identity."
  exit 1
fi
kubectl --context "$CONTEXT" get namespace "$NAMESPACE"
aws --profile "$AWS_PROFILE_NAME" ecr describe-repositories --region ap-east-1 --repository-names "$APP-srvapp" "$APP-webapp" --query 'repositories[].repositoryName' --output text
docker compose --env-file "deploy/$ENV/.env" -f "deploy/$ENV/compose.build.yaml" config --quiet
docker compose --env-file "deploy/$ENV/.env" -f "deploy/$ENV/compose.build.yaml" build
```

确认输出账号与 ACCOUNT 完全一致，且构建成功后才登录和推送；不把 AWS key 写在命令行。

```bash
set -o pipefail
aws --profile "$AWS_PROFILE_NAME" ecr get-login-password --region ap-east-1 | docker login --username AWS --password-stdin "$REGISTRY"
docker compose --env-file "deploy/$ENV/.env" -f "deploy/$ENV/compose.build.yaml" push
```

PRD 的 `ENV=prd`、`ACCOUNT=449732370091`，profile 和 context 必须使用 IT 确认的生产值，
不能只改 ENV 后沿用 UAT 凭据。优先把验收通过的同一镜像提升到生产仓库，保留 digest 和发布记录。
若重新构建，Python 传递依赖尚未完全冻结，必须重新验证，不能把相同源码当作相同二进制。

生产审批通过后，在单独的发布会话使用下面这一组，替代前面的 UAT 变量组；不要紧跟 UAT
推送命令立即执行。它将后续所有 `$ENV` 路径、仓库和 Deployment 名切换为 PRD：

```bash
ENV=prd
ACCOUNT=449732370091
APP=ih-prd-remote-fund-cmt-auto
REGISTRY=449732370091.dkr.ecr.ap-east-1.amazonaws.com
read -r -p 'Confirmed PRD AWS profile: ' AWS_PROFILE_NAME
read -r -p 'Confirmed PRD Kubernetes context: ' CONTEXT
NAMESPACE=ih
read -r -p 'Approved release tag available for PRD: ' RELEASE_TAG
: "${AWS_PROFILE_NAME:?AWS profile is required}"
: "${CONTEXT:?Kubernetes context is required}"
: "${NAMESPACE:?Namespace is required}"
: "${RELEASE_TAG:?An approved release tag is required}"
export RELEASE_TAG
umask 077
test -e deploy/prd/.env || cp deploy/prd/.env.example deploy/prd/.env
nano deploy/prd/.env
```

然后重新执行账号核对、仓库检查及本环境的构建/推送（或批准的镜像提升流程）、配置和发布。
不能因为 UAT 已通过就跳过 PRD 的 Secret、数据源和 namespace 核对。只推了 UAT 镜像，
生产仓库里不会自动出现它；镜像提升或重新构建推送完成后才能创建 PRD Pod。

## 配置与 Secret

### 本地填写的 YAML 草稿

2026-09-07 已按本地配置生成以下文件；它们均被 Git 忽略，不会随 clone/pull 到达 VM1：

- UAT：`k8s/uat/secrets/secret.local.yaml`。
- PRD：`k8s/prd/secrets/secret.local.yaml`。
- 无凭据值的逐字段状态表：`k8s/secret-readiness.local.md`。

保留 `secret.example.yaml.txt` 为空值示例是部署规范要求，不能将真实值填回并提交。
生成的 YAML 使用 `stringData`，是明文而非加密；Git 忽略也不会阻止 OneDrive 同步。
请遵循公司的凭据存储政策，不把这些文件放进聊天、工单、邮件、构建上下文或 Git。

| 字段 | UAT 本次结果 | PRD 本次结果 |
| --- | --- | --- |
| namespace | 已设为 ih | 已设为 ih |
| DOWNLOAD_SECRET | 新生成独立随机密钥 | 新生成独立随机密钥 |
| DATAWAREHOUSE_MYSQL_HOST / DATABASE / USERNAME / PASSWORD | 从本地配置复制为待批准的候选值 | 留空，不共用测试环境凭据 |
| FMP_API_KEY | 从本地配置复制为待批准的候选值 | 留空 |
| DATABASE_URL | 留空，本地 SQLite 不可用于部署 | 留空 |
| REDIS_URL | 本地未配置 | 本地未配置 |
| S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY | 本地未配置 | 本地未配置 |
| DA_REPORT_OBJECT_URL / DA_REPORT_SQLITE_SHA256 | 本地未配置 | 本地未配置 |
| MARKETAUX_API_KEY | 当前 DA_REPORT 通道不要求；切换源时提供 | 同左 |

数仓连接不是应用数据库连接：应用需要可写 MySQL 8 / utf8mb4，数仓账号保持只读。
DA-Report URL 必须是集群可访问的已批准对象地址，配套 checksum 指向同一版本；不能把本地
SQLite 路径填成 URL。签名密钥仅为首次部署草稿生成，没有轮换任何运行中的服务。

Secret 以外还缺：ConfigMap 的 Entra tenant/audience、TOS bucket/endpoint/region、浏览器域名；
Ingress 的真实 host/ACM 证书；部署镜像发布标签。前端登录、外部数据库/Redis/TOS 网络与权限
仍未验证。不能把 YAML 语法正确理解为已具备上线条件。

生成工具为 `k8s/prepare-secret-drafts.py`，使用 dotenv 解析而非 source，通用本地值只给 UAT，
PRD 仅接受明确标为生产的配置来源；重复执行拒绝覆盖现有草稿或重新生成签名密钥。
它不会连接 Kubernetes。两份草稿都带 `draft-not-approved` 标记，该标记只是提示，
**不是 Kubernetes 的阻断机制**，缺项和环境权限未确认前不要 apply。

完成缺项审批后，通过公司批准的安全渠道将实际配置交给部署人员，不提交到部署分支。
如果使用下面的 `create-secret.py` 发布方式，部署人员需在目标环境机密文件中填写同一套
已批准值；该脚本不自动读取上述 YAML，避免误把半成品草稿当成可用配置。

### 已批准配置的发布步骤

按 IT 确认值修改该环境 YAML 的 namespace、镜像版本、非机密配置。
没有域名/证书时，先不要部署 Ingress；后端 ConfigMap、webapp 的 SERVER_NAME 仍需明确规划值。

编辑本次环境的三个工作负载配置文件，并分别修改两个 Service 的 namespace：

```bash
printf 'Namespace: %s\nRelease: %s\n' "$NAMESPACE" "$RELEASE_TAG"
nano "k8s/$ENV/configmap.yaml"
nano "k8s/$ENV/srvapp-deployment.yaml"
nano "k8s/$ENV/webapp-deployment.yaml"
nano "k8s/$ENV/srvapp-service.yaml"
nano "k8s/$ENV/webapp-service.yaml"
```

所有 `metadata.namespace` 改成刚确认的 NAMESPACE；后端文件的三处镜像和前端的一处镜像
都将 `:replace-me-release` 改成 `:` 加本次 RELEASE_TAG，仓库前缀已经填好，不改。
ConfigMap 中的租户、audience、桶、endpoint 和域名按公司值填写，不把密码写进 ConfigMap。

```bash
kubectl config get-contexts
kubectl --context "$CONTEXT" get namespace "$NAMESPACE"
kubectl --context "$CONTEXT" auth can-i create deployments -n "$NAMESPACE"
kubectl --context "$CONTEXT" auth can-i patch secrets -n "$NAMESPACE"
test -e "k8s/$ENV/.env.secrets" || cp "k8s/$ENV/.env.example" "k8s/$ENV/.env.secrets"
chmod 600 "k8s/$ENV/.env.secrets"
nano "k8s/$ENV/.env.secrets"
```

机密文件保留模板中的所有键，不使用的可选数据源键可以留空。脚本用 `python-dotenv` 解析，
不执行 shell，不展开 `$`。需安装该项目已有的 `python-dotenv` 依赖；若 VM 未准备好 Python
工具环境，请由 IT 使用批准的工具环境，不为此修改共享系统 Python。下面 PYTHON 指向该解释器。

```bash
PYTHON='REPLACE_WITH_APPROVED_PYTHON_EXECUTABLE'
"$PYTHON" k8s/create-secret.py "$ENV" --context "$CONTEXT" --namespace "$NAMESPACE" --env-file "k8s/$ENV/.env.secrets" --check
```

`--check` 只做本地校验。确认 namespace 与所有 YAML 一致，且 context 是正确账号下的集群，
再执行以下集群写入操作。脚本通过 stdin 传完整 Secret，不打印值、不生成明文中间 YAML；
采用 server-side apply，不会自动强夺已有字段所有权，权限或冲突错误应交给 IT 处理。
Kubernetes Secret 的 base64 不是加密，仍需平台 RBAC、etcd 加密及审计。

```bash
"$PYTHON" k8s/create-secret.py "$ENV" --context "$CONTEXT" --namespace "$NAMESPACE" --env-file "k8s/$ENV/.env.secrets"
```

首次发布前，或轮换后，确认所有数据源依赖都已配置。optional 键为空只表示可解析，
不表示 DA-Report、CDB、FMP 等业务能力可用。缺私有 CA 时应添加批准的只读 CA 挂载，不能关闭校验。

## 提交工作负载

先做占位符检查和服务端 dry-run；这些命令失败就停止，不跳过。脚本中的 `exit 1` 会结束
当前发布 shell，因此建议在独立发布终端运行。不要扫描或打印机密文件。

```bash
if grep -qiE 'replace-me|example\.invalid' "k8s/$ENV/"*.yaml; then
  echo 'STOP: complete namespace, release and ConfigMap values before deployment.'
  exit 1
fi
kubectl --context "$CONTEXT" apply --dry-run=server -f "k8s/$ENV/configmap.yaml" -f "k8s/$ENV/srvapp-service.yaml" -f "k8s/$ENV/webapp-service.yaml" -f "k8s/$ENV/srvapp-deployment.yaml" -f "k8s/$ENV/webapp-deployment.yaml"
```

已拿到发布授权、完成数据库备份并确认队列排空后，按此顺序发布。后端 Deployment 创建 Pod
即会执行数据库迁移，不能对未知或他人业务库运行。

```bash
kubectl --context "$CONTEXT" apply -f "k8s/$ENV/configmap.yaml" -f "k8s/$ENV/srvapp-service.yaml" -f "k8s/$ENV/webapp-service.yaml"
kubectl --context "$CONTEXT" apply -f "k8s/$ENV/srvapp-deployment.yaml"
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status "deploy/$APP-srvapp" --timeout=10m
kubectl --context "$CONTEXT" apply -f "k8s/$ENV/webapp-deployment.yaml"
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status "deploy/$APP-webapp" --timeout=5m
kubectl --context "$CONTEXT" -n "$NAMESPACE" get pods -l "app=$APP" -o wide
kubectl --context "$CONTEXT" -n "$NAMESPACE" logs "deploy/$APP-srvapp" -c migrate --tail=40
kubectl --context "$CONTEXT" -n "$NAMESPACE" logs "deploy/$APP-srvapp" -c srvapp --tail=80
kubectl --context "$CONTEXT" -n "$NAMESPACE" logs "deploy/$APP-srvapp" -c worker --tail=80
kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "deploy/$APP-srvapp" -c worker -- celery -A app.worker:celery_app inspect ping --timeout=10
```

稳态预期后端 `2/2`、前端 `1/1`，而不是所有 Pod 都是 `1/1`。init 容器应 Completed。
查看日志前先确认不会传播敏感数据；不要输出 printenv、完整 Secret、带签名的 URL 或完整环境。

Ingress 最后单独处理：填好域名、同账号 ACM 证书与平台要求的注解，检查占位符后再提交。

```bash
if grep -qiE 'replace-me|example\.invalid' "k8s/$ENV/ingress/ingress.yaml"; then
  echo 'STOP: confirm ingress hostname, namespace and certificate.'
  exit 1
fi
kubectl --context "$CONTEXT" apply --dry-run=server -f "k8s/$ENV/ingress/ingress.yaml"
kubectl --context "$CONTEXT" apply -f "k8s/$ENV/ingress/ingress.yaml"
kubectl --context "$CONTEXT" -n "$NAMESPACE" get ingress
```

由 IT 把批准域名指向返回的内网 ALB，验收 HTTPS、无令牌 401、合法用户权限、数据获取、
排队渲染、HTML/PDF/DOCX 下载和 Pod 重建后产物读取。健康探针正常不等于业务验收通过。

## 更新与边界

- ConfigMap/Secret 更新不会自动重启 Pod，批准维护窗口后 `rollout restart` 对应 Deployment。
  后端重启会重新运行幂等 Alembic upgrade，也会中断共 Pod 的 worker；先排空任务。
- 后端更新时三个后端 image 引用必须一致；前端镜像版本可独立变更，但要一起验证接口契约。
- `rollout undo` 只回退 Pod 模板，不会回退数据库、同名 ConfigMap 或 Secret。
  有 schema 变更时先证明兼容或按演练方案恢复，不提供“直接 undo 一切”的假保证。
- API 暂不信任转发头（`--no-proxy-headers`），未凭空设置集群可信代理网段；访问日志可能看到
  代理地址。IT 确认可信代理范围后才能开启相应设置，不要全网信任 X-Forwarded-For。
- 尚未完成前端 Entra 登录/访问令牌注入，当前产品 CSP/COOP 也需要与最终登录方案联合验证。
  不能将 UAT 改为 LOCAL 绕过 401。Python Linux 依赖锁定和真实只读/non-root Chromium 验证仍是门槛。
- 本次只完成 YAML 解析、引用、安全约束及脚本单元测试；没有联系集群执行 server-side dry-run，
  没有构建或推送镜像、创建 Pod、迁移数据库，也没有修改 DNS/证书。