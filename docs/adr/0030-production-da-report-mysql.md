# ADR-0030：Production 直接只读查询 DA-Report MySQL

- 日期：2026-09-08
- 状态：已接受；用户提供 DA-Report MySQL 连接，并明确「仅 Production」。
- 关联：[ADR-0029](0029-on-demand-report-downloads.md)、[数据来源手册](../news-sources-and-data-imports.md)。

## 决策

Production 通过专用机密配置 `DA_REPORT_DATABASE_URL` 直接查询 DA-Report 数据库。
它与本应用的 `DATABASE_URL` 分离；不将应用表或 Alembic 迁移写入 DA-Report。
真实连接只填入被 Git 忽略的 `.env.prd`，通过现有 Secret 流程注入，不写入代码、ConfigMap 或文档。
UAT 未获授权使用该生产连接，继续保留原 SQLite 快照配置；UAT 的新变量留空。

适配器优先使用显式 MySQL 配置；一旦配置，即使无法连接也不回退到本地或对象存储中的旧快照。
未配置 MySQL 时保留既有 `DA_REPORT_SQLITE_PATH`、`DA_REPORT_OBJECT_URL` 和
`DA_REPORT_SQLITE_SHA256` 路径。Production 不再需要 DA 快照下载地址和文件校验值。

MySQL 8 查询覆盖 Regional Corporate 新闻目录、筛选/分页/单项重新读取、旧成分股新闻候选接口，
以及 DA 月度数据和 `market_monthly_turnovers`。字段合同以既有适配器及本机 DA-Report
`backend/app/models/news.py`、`market.py` 为依据；真实数据库的迁移版本仍需在目标网络确认。
缺表或缺字段按原质量规则返回明确错误/缺失发现，不以空数据伪装成功。

## 只读、版本和数据边界

- 独立连接池、`REPEATABLE READ`、会话默认 `TRANSACTION READ ONLY`，只执行参数化查询。
  建议数据库账号也仅授予 SELECT；本次不修改上游账号或权限。
- 校验 TLS 证书与主机名；检测服务器未建立 TLS 时拒绝连接。Production 使用随镜像提供的
  AWS ap-east-1 RDS 公共 CA bundle，来源及 SHA-256 见 `backend/app/integrations/certs/README.md`。
- 默认连接/读写/查询超时为 10 秒，连接池最多 5 条连接；不缓存整个数据库到容器文件系统。
- 搜索使用 MySQL 字符串拼接；公司筛选使用 ICU 正则并保留中英文、全角 ASCII、标点和英文词边界。
  查询条件绑定参数；分页继续绑定筛选条件并按时间与 ID 排序。
- 日期与时间转换为可序列化的内容；月度数据标记 `DA_REPORT_MYSQL`，保存表名、记录 ID、查询窗口、
  内容 checksum 和读取一致性。读取时间由本应用快照/审计记录承担，避免每次查询时间变化破坏去重。
- 浏览新闻目录直接读 DA；保存选择时仍由服务端重新读取验证后保存到本应用数据库。
  已选新闻、已有快照、定稿内容和按需成品导出在 DA 故障时继续使用本应用已保存的数据。
  新的搜索或数据刷新反映上游当前内容，不承诺跨多个浏览请求的数据库快照一致性。

## 部署迁移

新增 `DA_REPORT_DATABASE_URL` 后，Secret 初版由 11 增为 12 个 key。2026-09-08 按用户后续
“删除 legacy”的 YAML 清理要求，Production 删除 `DA_REPORT_OBJECT_URL`、`DA_REPORT_SQLITE_SHA256`，
Secret 减为 10 个 key；同时删除 Production ConfigMap 的 `DA_REPORT_CACHE_DIR`。
Production 环境模板、本地环境文件、Secret YAML 和生成器同步清理；生成器拒绝重新传入旧字段。
UAT 保留 12 个 key 和快照配置，其 DA MySQL URL 仍留空，不使用生产连接。
Production 除 `DATABASE_URL`、`DOWNLOAD_SECRET` 外还必填 DA 连接；已有 Production 环境文件
须删除两个旧 DA 字段后按对应模板重建 Secret。不删除上游历史对象或本地/UAT 快照兼容代码。
应用数据库不需要迁移，前端接口不变。回滚旧镜像时需要恢复可用 SQLite 快照配置，旧版不能读取新连接变量。

## 验证与限制

工作站对用户指定 Production RDS 的只读探测返回 MySQL 2003，未能建立连接，未执行生产查询或写入。
部署前应从获准网络验证 DNS/路由、安全组、TLS、SELECT 权限和实际字段合同；不能据此宣称生产已连通。

隔离的 MySQL 8.4 测试库验证了搜索、筛选、分页、新闻选取、日期/JSON、月度公式、稳定 checksum、
TLS 与只读事务；本地 SQLite 兼容及完整后端回归通过。CI 增加独立 `da_contract` schema 的同类测试，
不接受应用连接变量或生产数据库名。详细结果见 `k8s/VALIDATION.md`。
