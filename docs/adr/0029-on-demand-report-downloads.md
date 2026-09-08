# ADR-0029：按需生成下载，不保存报告成品

- 后续：DA-Report Production 数据源及 Secret key 数由 [ADR-0030](0030-production-da-report-mysql.md) 更新为直连 MySQL / 12 个 key；本决策的按需导出不变。
- 日期：2026-09-08
- 状态：已接受，用户明确要求「采用按需生成下载，并记录这项设计变更」。
- 关联：[ADR-0026](0026-remote-app-deployment-conventions.md)、[ADR-0028](0028-synchronous-jobs-without-redis.md)。

## 背景与覆盖范围

应用作为远程报告工作台，数据库已保存定稿内容、数据快照和完整文档版本。
用户确认成品只需在下载时输出，不需要长期保存文件。按此要求取消本应用成品存储桶依赖。

本决策覆盖执行规格书 V2.1 中 §4.2–4.5 的成品对象存储／worker 编排、§6.1–6.2 的
RenderArtifact 文件复用及旧文件留存、§6.4 的成品文件保留、FR-604 的渲染任务重试、
§9 的旧渲染／成品 API，以及 ADR-0026/0028 中相应部署和渲染流程。
§4.6 的三格式内容与版式合同继续适用；FR-605 的下载授权及短期签名继续适用。
快照、文档、审计的保留要求没有被取消。此变更不扩展到上游 DA-Report 快照交付或其他媒体需求。

## 决策

1. Finalize 只锁定文档版本。下载菜单针对 HTML、PDF、DOCX 显示「生成并下载」。
   每次下载单独生成所选格式，不自动生成其他格式，不复用已保存成品。
2. 服务端只读取报告的 `finalized_document_version`，验证文档 checksum，复制固定输入后释放数据库事务。
   不读取后来追加的文档，不刷新外部数据、不重新计算指标、不重新翻译。
   FINALIZED 和具有定稿版本的 ARCHIVED 报告可下载；草稿和未定稿的归档报告不可下载。
3. 定稿文档、快照、版本与导出审计继续保存在 MySQL；不把文件 bytes 写入 S3/TOS、数据库 BLOB 或 PVC。
   每个请求使用独立 TemporaryDirectory，成功发送、断连、发送失败以及生成失败均执行清理。
   SIGKILL/OOM 等无法执行清理的情形依赖容器/Pod 临时空间回收；K8s `/tmp` 为有容量上限的 emptyDir。
4. 生成成功追加 `export.generated` 审计，记录操作者、请求 ID、报告及文档版本、快照 ID、
   文档 checksum、格式、语言、通道、模板/设计令牌/渲染器版本、文件大小、SHA-256、content manifest。
   生成失败追加 `export.failed` 和安全错误码。`export.generated` 仅证明文件生成完成，
   不证明浏览器收完文件或用户已保存。审计不保存文件内容、签名或凭据。
5. 授权、产品范围、签名及 TTL 在实际生成前再次校验。签名绑定报告、定稿版本、格式与 subject。
   REMOTE 使用平台共享 `remote-app` 身份，审计不能据此辨认个人。
   响应设置 `Cache-Control: no-store`；每次重新生成，因此忽略 Range/If-Range，不支持跨请求断点续传。

## 接口与发布迁移

- `GET /api/v1/reports/{id}/exports/{html|pdf|docx}/download`：签发短期下载地址。
- `GET /api/v1/reports/{id}/exports/{format}/content?version=…&expires=…&signature=…`：校验并生成文件响应。
- 前端经 `/remote/fund-cmt-auto/api/v1` 请求，获取 blob 后触发保存；失败继续显示结构化错误。
- 旧 `POST /reports/{id}/renders`、`GET /jobs/{id}` 和 `/artifacts/{id}/download|content` 已退役，返回 404。
  ReportDetail 不再返回 artifacts；发布时必须同步更新前后端。翻译任务 API 保持现状。
- 不需要新数据库迁移。历史 RenderArtifact / RenderJob 表和记录原样保留，新下载不读写这些记录。
  旧报告只要保存了有效定稿文档，即可重新导出；没有定稿版本时不回退到旧文件。
- 删除运行时 storage adapter、boto3/storage extra、成品 S3 配置和 output volume。
  Secret 模板为 11 个 key，其中 `DATABASE_URL`、`DOWNLOAD_SECRET` 必填。
  既有环境文件移除两个 `S3_*` 密钥；其他旧成品 `S3_*` / `STORAGE_BACKEND` 配置一并退役。
  本变更不删除真实桶、对象、历史本地文件或线上 Secret，不处理其生命周期。
- 回滚到成品持久化旧版时，恢复匹配的前端、存储配置、凭据和权限；本版本新增下载没有成品对象可回迁。

## 取舍与运行边界

固定输入保证内容来源可追溯，但模板实现、字体、Chromium、python-docx 或其他渲染依赖更新，
以及文件内生成时间等元数据，都可能改变再次下载的字节和版式。记录版本和 checksum 用于解释差异，
不承诺原样取回历史文件。如未来需要对外发布原件留存或字节级复现，应另行恢复不可变成品归档。

每次下载都消耗 API 的渲染资源并等待完成；没有后台渲染队列、成品缓存、任务自动恢复或下载断点。
失败后重新下载即可，其他格式与业务数据不受影响。沿用 ADR-0028 的低并发及长请求限制，
不宣称满足规格 NFR-002 的十个并发渲染任务/队列背压。宿主代理超时与实际负载需在目标环境验证。

## 验证

覆盖重复下载、临时目录隔离/清理、发送中断、固定定稿版本、归档边界、签名篡改和权限；
保留三格式内容、水印、翻译一致性和版式回归。部署检查确认无成品桶、Redis/worker 或 PVC 依赖。
具体测试及镜像验证结果见 [k8s/VALIDATION.md](../../k8s/VALIDATION.md)。
