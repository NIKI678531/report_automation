# 发布检查清单

## 本地与构建

- [ ] Python lock 与 pyproject 一致，前端 npm ci/build 通过。
- [ ] 两个 Dockerfile 构建成功，镜像没有 .env、数据库、测试数据或凭据文件。
- [ ] UID 为后端 10001 / nginx 101；只读根下仅 tmpfs/emptyDir 可写。
- [ ] nginx 模板渲染成功；缺少 API_UPSTREAM 或不可写 conf.d 时进程退出。
- [ ] 新增 REMOTE 模式仍拒绝 SQLite、默认签名密钥和测试数据通道。
- [ ] Linux shell 文件为 LF；填好的 .env.uat / .env.prd 不进入 git。
- [ ] 如需用户手动验镜像，填写 .env 后运行 docker compose up --build；本地 MySQL 可丢弃。

## 发布前

- [ ] 确认 context、AWS 账号、namespace ih 和给定 ECR repositories。
- [ ] 确认 MySQL 8/utf8mb4、DDL 权限及 schema；供应商网络与权限从目标网络验证。
- [ ] ConfigMap 数据来源配置正确；Secret 按环境模板齐全（Production 9 个 key，UAT 11 个）且通过 --check；旧环境文件移除 REDIS_URL、两个 S3 密钥和 MARKETAUX_API_KEY；NEWS_PROVIDER=DA_REPORT；只在 Production 填入其专用 DA_REPORT_DATABASE_URL。
- [ ] Production 移除 DA_REPORT_OBJECT_URL / DA_REPORT_SQLITE_SHA256 和 DA_REPORT_CACHE_DIR；UAT 保留原快照配置。
- [ ] Production 从目标网络验证 DA MySQL TLS/SELECT/字段合同；UAT 未注入该生产连接。
- [ ] TASK_MODE 为 EAGER，旧队列已清空；宿主平台代理允许长请求，并通过真实渲染／翻译验证超时。
- [ ] 远程平台将 `/remote/fund-cmt-auto/` 原样转发到 webapp Service:3030，静态资源与 API 均经过现有访问控制。
- [ ] 宿主注册 `fundCmtAuto` / `./App` / `/fund-cmt-auto`，remote URL 为 `/remote/fund-cmt-auto/remoteEntry.js`。
- [ ] `remoteEntry.js` 为 JavaScript、Cache-Control 为 no-store；不存在的 chunk 返回 404，不回退 HTML。
- [ ] 保存当前镜像 digest/版本及配置版本；新镜像同时保留 git SHA 标签。
- [ ] 等待渲染和翻译任务结束；确认 Recreate 短暂停机窗口。

## 发布后

- [ ] migration init container 完成，API 为 1/1 Ready，webapp 为 1/1 Ready。
- [ ] 日志有应用 INFO、没有探针刷屏，没有启动配置错误。
- [ ] webapp `/healthz` 与 `/remote/fund-cmt-auto/api/v1/health` 均为 200，深检查各依赖为 ok。
- [ ] 宿主加载、返回/重新进入、编辑保存、预览/签名下载正常；宿主样式和语言保持正常。
- [ ] 通过远程平台实际创建/编辑报告、取得所需数据、按需下载 HTML/PDF/DOCX；重复下载、归档定稿下载正常，临时文件清理且 export.generated 审计存在。
- [ ] 上游 provider 仅对业务实际启用的能力做真实验证；关闭的翻译保持 DISABLED。
- [ ] 记录实际镜像 digest、git SHA、配置版本和验证结果；回滚方案兼容当前数据库 schema。
