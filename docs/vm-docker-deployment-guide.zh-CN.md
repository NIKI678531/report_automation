# Ubuntu VM 部署操作手册

此文保留早期 VM 直跑流程。最新部署目标是 IH 集群的 UAT/PRD，当前入口为
[k8s/README.md](../k8s/README.md)；下面的 VM 备用配置已归档到 deploy/vm。

适用：在现有 Ubuntu 22.04 x86_64 VM 上直接运行本项目，使用 Bash 和 Docker Compose。
核对日期：2026-09-07。本文是操作说明，未连接 VM，也未执行远端安装或发布。

现已生成可直接使用的试运行覆盖文件，以及使用外部 MySQL/Redis 的独立正式构建、运行清单。
文件入口与正式版执行命令见 [VM 部署文件与执行顺序](vm-deployment-files.md)。
下文中原 Compose 的限制仍然成立，不能把它与正式运行清单合并。

## 1. 先用大白话理解

你选的是“把网站放在 VM 上跑”，不是“在 VM 上操作 Kubernetes”。附件的部署规范主要
面向公司 AWS EKS，因此这次不需要 ECR、AWS 登录、kubectl、Namespace 或 Ingress 命令。
仍然要遵守它关于机密、健康检查、版本、备份、非 root 和发布验证的要求。

整个过程可以理解为六步：

1. **检查房间**：VM 有没有足够磁盘和内存，Docker 能不能用，端口有没有被别的项目占用。
2. **搬代码**：从仓库取一个确定版本，不是复制整个 Windows 工作目录。
3. **填配置**：数据库密码、登录配置、数据源和对象存储，都从运行环境提供，不塞进镜像。
4. **打包启动**：Docker 把程序和依赖打包成镜像，再从镜像启动容器。
5. **验收业务**：页面能打开只是第一步，还要能取数据、生成报告、下载并再次打开产物。
6. **正式开放**：登录、HTTPS、备份和运维条件齐备后，才允许同事访问。

本项目的五个服务已经定义在 [compose.yaml](../compose.yaml)：

| 服务 | 大白话 | 数据去向 |
| --- | --- | --- |
| `web` | 浏览器看到的网页，以及转发 API 请求的 nginx | 静态文件在镜像里 |
| `api` | 接收点击、导入数据、保存报告的后端 | 应用 MySQL |
| `worker` | 在后台生成 PDF、DOCX 等文件 | 与 API 共用数据库和产物桶 |
| `db` | 应用数据库，不是上游数仓 | 试运行使用 Docker named volume |
| `redis` | 给 API 和 worker 传递任务、保存任务结果 | 试运行使用 Docker named volume |

访问链路是“浏览器 -> web -> api -> MySQL / Redis -> worker -> 对象存储”。
前端和后端不是分别开放两个网站，也不需要在 VM 上另装 Node 或 Python 来运行应用。

**镜像**是程序包装，**容器**是正在运行的程序，**卷**是独立于容器的存储空间。
删容器不等于删卷，但删卷会丢数据；重建镜像也不会替你备份数据库。

## 2. 当前不能直接正式上线的原因

以下是当前代码的实际情况，不是要求你通过命令绕过的报错：

| 现状 | 后果或必须完成的准备 |
| --- | --- |
| 前端 [api.ts](../frontend/src/api.ts#L329) 没有获取或发送访问令牌 | 后端虽然支持 `ENTRA`，但只改配置后，网页业务请求会返回 401；需要补浏览器登录、令牌获取和请求注入 |
| Compose 默认 `AUTH_MODE=LOCAL` | 这是信任调用者的开发模式，不能当正式登录；内网也不是身份认证 |
| 默认发布 `8080:80` | 会监听所有网卡；必须先限制监听地址，不能先启动再补防火墙 |
| 正式模式拒绝 `STORAGE_BACKEND=LOCAL` | 报告必须去 TOS 等对象存储，配置值是 `S3`，不是 `TOS` |
| 后端 Dockerfile 使用 `COPY .`，后端忽略规则未排除 SQL dump / 所有 `.env*` | 构建前必须排除数据库导出和机密，不能把开发数据一起打包 |
| 当前镜像未配置非 root，Python 依赖使用版本范围 | 尚未符合附件的运行加固和依赖锁定要求；渲染基础镜像与 Playwright 包版本也要验证匹配 |
| Compose 没有重启策略、日志轮转和资源限额 | 正式环境需补上；不能仅凭 `up -d` 宣称可长期运维 |
| 上游 CDB、FMP、DA-Report 需要环境输入 | 数据库迁移只建应用表，不会自动搬来 Windows 数据、新闻快照和数仓数据 |

下面第 3 至 10 节是**隔离试运行**，使用测试数据，不等于正式部署。
远端回环地址仍可被 VM 上其他本地用户访问；共享机器须先得到管理员允许，不能加载敏感生产数据。
生产放行条件见第 11 节。不能为了打开页面而把 `ENTRA` 改回 `LOCAL` 后对外发布。

## 3. 第一次登录：先检查，不改机器

以下命令在 VM 的 Ubuntu 终端执行，不要把提示符一起输入。每个步骤成功后再继续。

```bash
hostname
whoami
pwd
uname -m
df -h / /var/lib/docker
df -i /
free -h
nproc
docker version
docker compose version
docker context show
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker system df
ss -lnt
```

判断方法：

- `docker version` 应有 Client 和 Server；只有 Client 不表示 Docker 服务可用。
- 确认 Docker context 指向这台 VM 的本地引擎；若指向别的机器，先停下来确认。
- 本文的覆盖配置要求 Docker Compose **2.24.4 或更新**，使用 `docker compose`，不是旧的 `docker-compose`。
- 本文用 VM 的 `18080` 端口；如果已占用，选空闲端口并同步修改后续配置。
- 磁盘需同时容纳浏览器基础镜像、构建缓存、新旧镜像和数据库，不能只按源码大小估算。
- 你提供的登录信息显示根盘使用 83.4%，约余 80 GB，但必须以现场检查为准。
- 内存需为 MySQL、两个并发渲染 worker 和现有服务留余量；先与管理员确认资源预算。

如果提示 Docker permission denied，请管理员授权。Docker 组基本等同宿主机 root 权限，
不要用 `chmod 666 /var/run/docker.sock` 解决，也不要自行扩大权限。

你的登录信息还有“需要重启”和大量更新提示。**不要自行 reboot、升级 Ubuntu、重启 Docker、
运行全局 prune 或删除卷**；共享 VM 上这些操作可能中断别人的业务，应由管理员安排维护窗口。
旧版 Docker 的回环端口隔离也有历史问题，要求管理员使用已修复的受支持版本；不要仅依赖 UFW。

## 4. 只有 Docker 确实未安装时，才安装

已有 Docker 并且能用时，整节跳过。已有旧版本、冲突包或容器服务时，由管理员处理升级，
不要按新机流程卸载它们。下面命令仅供管理员在批准后的新机安装中使用。

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git nano openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo nano /etc/apt/sources.list.d/docker.sources
```

在编辑器中填入以下内容，适用于本次确认的 Ubuntu 22.04 / x86_64：

```text
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
```

`nano` 保存是 Ctrl+O、Enter，退出是 Ctrl+X。然后执行：

```bash
sudo apt-get update
apt-cache madison docker-ce
apt-cache madison docker-ce-cli
apt-cache madison containerd.io
apt-cache madison docker-buildx-plugin
apt-cache madison docker-compose-plugin
```

让管理员从输出里选团队批准的版本，替换下面的值。这里故意不写未经核实的固定版本：

```bash
DOCKER_VERSION='REPLACE_WITH_APPROVED_VERSION'
CONTAINERD_VERSION='REPLACE_WITH_APPROVED_VERSION'
BUILDX_VERSION='REPLACE_WITH_APPROVED_VERSION'
COMPOSE_VERSION='REPLACE_WITH_APPROVED_VERSION'
sudo apt-get install -y "docker-ce=$DOCKER_VERSION" "docker-ce-cli=$DOCKER_VERSION" "containerd.io=$CONTAINERD_VERSION" "docker-buildx-plugin=$BUILDX_VERSION" "docker-compose-plugin=$COMPOSE_VERSION"
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

如需 sudo 密码，只在 VM 终端直接输入，不发到聊天中。余下步骤假设账号已获准使用 Docker；
没有授权就先停在这里，不能通过更改 socket 权限绕过。

## 5. 把一个确定版本的代码放到 VM

先向项目负责人拿真实 Git 地址和已批准的 release tag 或完整 commit SHA。
仓库地址里不要嵌入 token，不要把密码写进命令行；认证使用公司批准的 SSH key 或凭据管理器。

```bash
mkdir -p ~/apps
cd ~/apps
REPO_URL='REPLACE_WITH_REPOSITORY_URL'
git clone "$REPO_URL" report-automation
cd report-automation
git fetch --tags
RELEASE_REF='REPLACE_WITH_APPROVED_TAG_OR_COMMIT'
git switch --detach "$RELEASE_REF"
git status --short
git rev-parse HEAD
```

已有目录时，不再 clone，不覆盖文件；先确认其中是否已有部署及未提交修改。
Windows 上未推送到仓库的改动不会随 clone 出现，`.env` 和本机数据库也不会自动同步。
没有 Git 访问权限时，先解决访问或获取经审查的发布包，不要整目录复制 OneDrive 工作区。

## 6. 构建前排除数据文件

这一步应作为正式代码修正提交审查；为隔离试运行，也可以先在 VM 上做同样的本地补充，
但要记录差异，后续更新不得覆盖或丢失这些规则。

```bash
nano backend/.dockerignore
nano .dockerignore
```

保留原有内容，在**两个文件**中补充以下规则。这里是编辑器内容，不是终端命令：

```text
.env*
**/.env*
*.sql
**/*.sql
*.sql.gz
**/*.sql.gz
*.sqlite*
**/*.sqlite*
*.db
**/*.db
*.pem
**/*.pem
*.key
**/*.key
*.pfx
**/*.pfx
*.p12
**/*.p12
```

尤其要排除后端目录里的 SQL dump。`.gitignore` 不负责 Docker 构建，根目录的
[.dockerignore](../.dockerignore) 也不能代替独立 backend 构建上下文中的
[backend/.dockerignore](../backend/.dockerignore)。

上述规则不是通用机密扫描器；正式发布还需审查其他名称的备份、压缩包及凭据文件。
不要直接套用附件的后端 Dockerfile：本项目必须保留 Chromium 和报告字体。

## 7. 准备试运行配置

先在仓库根目录执行。已有 `.env` 时不要覆盖，先核实它属于哪个环境。

```bash
umask 077
test -e .env || cp .env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
nano .env
```

三个随机值分别填 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`DOWNLOAD_SECRET`，必须互不相同。
生成值只在本地安全填写，不截图或粘贴到聊天，不提交 Git。使用 hex 可以避免密码里的
`@`、`:`、`$` 等字符在数据库 URL 或 Compose 插值里产生歧义。

隔离试运行的关键设置如下。随机值占位符必须替换，不能保留模板原值：

```dotenv
MYSQL_PASSWORD=REPLACE_WITH_FIRST_RANDOM_VALUE
MYSQL_ROOT_PASSWORD=REPLACE_WITH_SECOND_RANDOM_VALUE
DOWNLOAD_SECRET=REPLACE_WITH_THIRD_RANDOM_VALUE
AUTH_MODE=LOCAL
STORAGE_BACKEND=LOCAL
CORS_ALLOW_ORIGINS=http://localhost:18080
```

这些 LOCAL 设置只为受限的工作站试运行，不能用于正式共享服务。
这里的本地文件只是测试输出；正式输出必须使用对象存储，不能依赖后端容器磁盘。

需要真实业务测试时，将批准的 CDB、FMP、DA-Report 测试配置也填入根 `.env`，
参考 [backend/.env.example](../backend/.env.example) 和现有 Compose 传入的变量。
DA-Report 用 `DA_REPORT_OBJECT_URL` 加对应 `DA_REPORT_SQLITE_SHA256`，缓存只在 `/tmp`；
预签名 URL 是机密且会过期，要有续发流程。Windows 路径在 Linux 容器内不能使用。

**不要误以为根 `.env` 的每个变量都会自动传给容器**：只有 Compose 引用或 `env_file`
声明的才会传入。目前只往根 `.env` 写 `DATABASE_URL`，不会覆盖 Compose 内拼出的数据库地址。
也不要直接 `source .env`，它是配置文件，不是 shell 脚本。

## 8. 创建仅监听回环地址的试运行覆盖文件

仓库已包含 [deploy/vm/compose.vm-trial.yaml](../deploy/vm/compose.vm-trial.yaml)，无需重新创建。
下面保留默认配置的说明示例；实际文件还允许通过 `VM_HTTP_PORT` 修改回环端口：

```yaml
x-trial-runtime: &trial-runtime
  restart: "no"
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"

services:
  db:
    <<: *trial-runtime
  redis:
    <<: *trial-runtime
  api:
    <<: *trial-runtime
    image: commentary-api:${RELEASE_TAG:-trial}
  worker:
    <<: *trial-runtime
    image: commentary-api:${RELEASE_TAG:-trial}
  web:
    <<: *trial-runtime
    image: commentary-web:${RELEASE_TAG:-trial}
    ports: !override
      - "127.0.0.1:18080:80"
```

`!override` 很重要：普通覆盖文件可能把端口列表合并，留下原来的全网卡 `8080`。
如果 Compose 不支持这个标签，应先让管理员升级；**不能简单删掉标签继续启动**。
试运行不设自动重启，以免 VM 重启后未经确认就重新运行 LOCAL 应用；日志会按大小轮转。

定义一个命令缩写，以后不会忘记覆盖文件。此函数只在当前 Bash 会话有效，每次重新 SSH
都要重新定义。`-p commentary-trial` 固定项目名，避免与别人的 Compose 项目混用：

```bash
cd ~/apps/report-automation
export RELEASE_TAG="$(git rev-parse --short=12 HEAD)-trial"
dc() { docker compose --env-file .env -p commentary-trial -f compose.yaml -f deploy/vm/compose.vm-trial.yaml "$@"; }
mkdir -p var/output
dc config --quiet
dc config --services
```

应看到 `db`、`redis`、`api`、`worker`、`web`。`--quiet` 成功时不输出内容。
不要把不带 `--quiet` 的完整 `config`、`docker inspect` 环境内容或 `printenv` 发到聊天：
这些可能包含密码、API key 和签名 URL。

## 9. 构建、启动、检查

在资源预算和构建排除规则确认后，逐步执行。构建失败时先解决失败，不能跳过：

```bash
dc pull db redis
dc build api web
dc up -d db redis
dc ps
dc up -d --wait --wait-timeout 300 api
dc exec -T api sh -c 'cd /app/backend && python -m alembic current'
dc exec -T api sh -c 'cd /app/backend && python -m alembic heads'
dc up -d --no-build worker web
dc ps
dc logs --tail=80 api worker web
curl -fsS http://127.0.0.1:18080/api/v1/health
dc exec -T api celery -A app.worker:celery_app inspect ping --timeout=10
```

后端和 worker 共用同一镜像，所以只 build `api web`。API 的启动脚本会先执行
`alembic upgrade head`；等待 API 健康后再启动 worker，避免 worker 抢在建表前接任务。
`current` 与 `heads` 应指向相同迁移版本。这里启动的是空的试运行应用库，不是导入旧数据。

检查结果：

- `web` 端口应只有 `127.0.0.1:18080->80/tcp`，没有 `0.0.0.0:8080` 或 `:::8080`。
- API 和数据库应 healthy；worker 要有 Celery `pong`，不能只看容器是 running。
- curl 应成功，但健康接口成功**不能证明**数仓、登录、文件存储和报告链路都正常。
- 不需要把 VM 的 3306、6379、8000 开给外部；它们只用于容器内部通信。
- 配置失败应修正对应设置，不能关闭安全守卫。

若要运行项目的完整预检，脚本在仓库根目录，**当前后端镜像并没有复制它**。
下面通过标准输入运行已跟该版本检出的脚本，并让它在容器里定位到 `/app/backend`：

```bash
dc exec -T -w /app api python -c 'import sys; source = sys.stdin.read(); sys.argv = ["/app/scripts/check_deployment.py"]; exec(compile(source, sys.argv[0], "exec"), {"__name__": "__main__", "__file__": sys.argv[0]})' < scripts/check_deployment.py
```

这个检查会连接数据库，也可能联系身份服务和对象存储。LOCAL 下的通过不是生产放行。
`--skip-network` 只跳过部分身份/桶检查，**仍连接数据库**；正式验收不能依赖它。
脚本没有核验全部上游业务数据，也没有证明对象的实际上传下载权限，必须继续做业务验收。

## 10. 在你自己的电脑上打开网页

**这条在你自己的 Windows PowerShell 执行，不在 VM 执行**，并保持该终端打开：

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:18080 azureuser@10.70.1.4
```

然后在自己电脑的浏览器打开 `http://localhost:18080`。
如果 Windows 本机 18080 已占用，换一个本地端口，并同步使用新浏览器地址及允许来源配置。
SSH 主机密钥首次提示应向 IT 核实，不能关闭 host key 检查；网络需具备访问该内网 VM 的条件。

验收顺序：页面加载 -> 产品目录 -> 使用批准的测试输入创建报告 -> 取新闻及行情 -> 编辑 ->
生成 HTML/PDF/DOCX -> 下载并打开。需要的上游配置没有提供时，只能验收基础启动，
不能把空数据、缺指标或业务错误称作完整成功。

试运行结束后，在 VM 执行：

```bash
dc stop
```

这样保留测试容器及卷。不要运行 `down -v`，也不要复制删除 Docker 全局数据的命令。

## 11. 正式开放前必须完成的工作

这部分是发布门槛，不是现在就能照抄执行的第二套生产配置。
当前代码和未知的公司域名、证书、存储凭据不足以给出诚实的“一键正式上线”命令。

1. **批准部署位置**：确认这台共享工作站允许长期托管业务；生产更适合受运维管理的专用主机。
2. **完成浏览器登录**：接入 Entra 登录与 API 访问令牌，校验角色/产品范围、退出和续期；
   配置真实回调域名，检查 nginx 的 CSP、COOP 和 iframe 策略是否与所选登录方式相容。
   现有后端说明见 [entra-setup.md](entra-setup.md)，不能只填租户 ID 就宣称前端已接入。
3. **生产配置**：设置 `AUTH_MODE=ENTRA`、真实 `ENTRA_*`、随机签名密钥、`ALLOW_TESTING_LANE=false`。
   API 和 worker 必须共享完整一致的身份、数据库及存储设置；当前 Compose 的 worker 未显式传入
   全部 `ENTRA_*`，正式配置要补齐，不能原封不动当生产模板。
4. **对象存储**：设置 `STORAGE_BACKEND=S3`、TOS endpoint、region、bucket、prefix 和批准的凭据；
   移除后端的持久化本地输出绑定，运行时渲染和缓存只用临时目录；验证实际写入、下载和重启后读取。
5. **数据库与 Redis**：落实 MySQL 8 / utf8mb4、备份、容量告警和恢复演练。
   如果使用外部数据库，需修改 Compose 的实际 `DATABASE_URL`、依赖和连接策略，
   不是仅往 `.env` 加一行。API 和 worker 必须指向同一环境，数仓账号只读。
6. **容器加固**：固定依赖与镜像版本，非 root 运行，验证只读根和临时目录，保留报告字体，
   加日志轮转、资源上限与批准的自动重启策略；健康检查和 worker 恢复要实际测试。
7. **HTTPS 与域名**：让 IT 分配真实域名、证书和入口，反向代理到 VM 回环服务端口。
   域名可以指向公司入口而不是直接指向 VM，取决于网络设计；不能凭空填写 DNS 或证书。
   如在本机新增 TLS 代理，先确认现有 80/443 归属，避免覆盖其他项目配置。
8. **网络限制**：由管理员按批准的来源限制入口、SSH 和管理权限，不开放数据库/Redis/API 原始端口。
   Docker 发布端口可能绕过 UFW，必须核对 Docker 转发规则及云网络边界，不可简单全网放行。
9. **发布验收**：无令牌业务请求为 401；合法用户可登录且权限正确；数据刷新、队列渲染、
   三种产物下载和重启后存取通过；完整预检无阻断项，业务/安全负责人批准。

正式运行配置应作为独立、经审查的文件纳入版本管理，机密仍在公司批准的秘密管理渠道。
正式项目名和卷应与 `commentary-trial` 分开，不能将未经确认的试运行数据直接变成生产数据。
这些工作完成后，启动方式仍是“构建 -> 启动依赖 -> 迁移并等 API 健康 -> 启动 worker/web -> 验收”，
不会因为直接使用 VM 就突然需要 Kubernetes。

## 12. 后续更新与回滚

下面命令沿用 `dc` 的**试运行**项目，正式环境使用审查后的命令和配置。

更新前先确认没有正在运行或排队的渲染任务；安排停写窗口，备份数据库和产物。
数据库卷在磁盘上不等于备份，单独备份数据库也不能替代对象存储备份。
有价值的数据必须有异机/对象存储备份和恢复演练；备份同样是机密。

记录并保留旧镜像，避免只记 Git SHA 却失去当时的依赖构建结果：

```bash
dc images
OLD_TAG="$RELEASE_TAG"
docker image tag "commentary-api:$OLD_TAG" "commentary-api:rollback-$OLD_TAG"
docker image tag "commentary-web:$OLD_TAG" "commentary-web:rollback-$OLD_TAG"
git status --short
git fetch --tags
```

核实本地改动，尤其是构建排除规则。切换前应妥善保留，不能 `reset --hard` 清掉。
以下只用于已获批准、与现有数据兼容的新版本；构建先完成，停机时间才不会包含构建时间：

```bash
NEW_REF='REPLACE_WITH_APPROVED_TAG_OR_COMMIT'
git switch --detach "$NEW_REF"
export RELEASE_TAG="$(git rev-parse --short=12 HEAD)-trial"
dc config --quiet
dc build api web
dc stop web worker api
dc up -d --no-build --wait --wait-timeout 300 api
dc up -d --no-build worker web
dc ps
curl -fsS http://127.0.0.1:18080/api/v1/health
```

还要重新执行 worker ping 和浏览器业务验收。若更新新增迁移，API 会在启动时自动迁移数据库。
迁移前必须有备份；不要同时启动多个执行迁移的 API 实例。

**仅当旧代码与当前数据库 schema 兼容，且配置仍匹配时**，才可回切保留的镜像：

```bash
export RELEASE_TAG="rollback-$OLD_TAG"
dc stop web worker api
dc up -d --no-build --wait --wait-timeout 300 api
dc up -d --no-build worker web
dc ps
```

新终端中 `OLD_TAG` 不会自动存在，必须从发布记录恢复。若 schema 不兼容，先停止，
按经过演练的数据库恢复/迁移回退方案处理，不能把“重启旧镜像”当作完整回滚。
旧镜像回滚后不要再运行 `build` 覆盖它。源码、配置、镜像和数据库版本都应记入发布记录。

## 13. 常用排查命令

以下在 VM 仓库目录执行，需先定义第 8 节的 `dc`：

```bash
dc ps -a
dc logs --tail=100 api
dc logs --tail=100 worker
dc logs --tail=100 web
dc logs --tail=100 db
dc exec -T web nginx -t
dc exec -T redis redis-cli ping
dc exec -T api celery -A app.worker:celery_app inspect ping --timeout=10
docker stats --no-stream
df -h /
docker system df
```

| 症状 | 先看什么 |
| --- | --- |
| 镜像拉不到 | 基础镜像 tag 是否存在、公司镜像源/代理和 VM 出网；不要关闭 TLS 校验 |
| API 退出 | API 日志里的配置拒绝、MySQL 连接或 Alembic 迁移错误 |
| 网页 502 | API 是否 healthy；Compose 内 `api:8000` 是否可达 |
| 网页 401 | 是否启用了 ENTRA，但浏览器没有取得或发送访问令牌 |
| 新闻或指标缺失 | CDB/FMP/DA-Report 配置、网络、只读权限、快照 checksum 与 URL 有效期 |
| 任务一直等待 | worker 是否 pong、Redis 是否 PONG、两个服务是否共用数据库与队列 |
| PDF 失败 | worker 日志、Chromium 与 Python Playwright 版本、字体、内存和临时目录权限 |
| 数据库改密码后仍连不上 | 已有 MySQL 卷不会因改 `.env` 自动改库内账号密码；需按轮换流程处理 |
| 改 `.env` 不生效 | 是否真的映射进 Compose；需 `up -d` 重建受影响容器，单纯 `restart` 不重新读环境 |
| 重启后下载失败 | 对象存储权限、bucket/prefix、产物是否错误地只留在容器本地 |

日志可能包含业务信息，只截取并脱敏相关错误，不贴整个环境或完整日志。
不要为修复磁盘问题运行全局镜像/卷清理；先确认归属、保留回滚镜像及备份。

## 14. 参考与边界

- 用户提供的部署规范 README、CHECKLIST、RUNBOOK；其 EKS 发布命令不适用于本次 VM 直跑。
- [compose.yaml](../compose.yaml)、[backend/Dockerfile](../backend/Dockerfile)、
  [frontend/Dockerfile](../frontend/Dockerfile)、[frontend/nginx.conf](../frontend/nginx.conf)。
- [scripts/check_deployment.py](../scripts/check_deployment.py)、[docs/implementation-status.md](implementation-status.md)。
- [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)。
- [Docker Compose 覆盖合并规则](https://docs.docker.com/reference/compose-file/merge/)。

本手册不是一次已完成的部署记录。尚未验证 VM 的权限、磁盘余量、镜像拉取、构建、网络、
真实登录、数据库和对象存储。未提供的仓库地址、发布版本、生产入口与公司凭据必须由负责人确认。