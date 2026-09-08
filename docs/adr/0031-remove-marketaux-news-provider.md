# ADR-0031：移除 Marketaux 新闻源

- 日期：2026-09-08
- 状态：已采纳
- 决策依据：用户明确要求删除 MARKETAUX 相关功能与配置。

## 决策

新闻源仅保留 DA-Report。删除 Marketaux 适配器、注册项、全部 `MARKETAUX_*` 设置、环境和 Secret 模板字段及供应商专属测试、使用说明。

保留新闻 provider API 和 DA-Report 的新闻目录、候选抓取、选择、手工录入与审计。显式指定旧 provider 或将其保留为默认值的抓取请求，返回 422 `NEWS_PROVIDER_UNKNOWN`，不会回退到 DA-Report。

历史新闻、已选入报告的内容和审计记录继续保留；本次无数据库迁移或数据删除。FMP 提供成分股行情回报，属于独立数据路径，保持现有配置。共享 HTTP 依赖仍供其他适配器使用。

## 配置迁移

- 开发环境删除所有 `MARKETAUX_*`，`NEWS_PROVIDER` 设为 `DA_REPORT`。
- UAT / Production 环境文件和 Secret 删除 `MARKETAUX_API_KEY`；生成器拒绝旧字段，即使留空。
- 当前完整 Secret 集合为 Production 9 个 key、UAT 11 个 key，覆盖前期验证记录中的数量。仍按各自环境模板填写；Production 的 DA MySQL 与 UAT 的快照配置隔离保持不变。
- 发布时由操作人员重建 Secret 并按部署手册更新后端；代码清理不会自动操作集群。

## 验证

保留并迁移通用新闻测试，验证 DA-Report 唯一可见、配置状态、默认与显式抓取、成分股上下文、候选落库和审计；反向验证旧 provider 和未知 provider 不触发 DA 调用、旧 Secret 字段不被接纳且错误不泄露值。
