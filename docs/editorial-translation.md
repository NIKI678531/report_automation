# 报告语言与回顾翻译

## 页面行为

- Report Centre 的语言偏好只控制中心页和新建页。打开报告后，界面、日期、状态和模块跟随报告语言；返回中心页恢复原偏好。
- 工作台切换语言会打开或创建同产品、月份和修订号的语言版本，并保留当前模块。归档报告没有对应版本时保持原页面，不会只切换界面语言。
- 简繁转换仍使用离线 OpenCC。英中自动翻译仅覆盖回顾正文和自定义标题，新闻、术语主数据、数字数据、脚注和免责声明不交给模型。
- 目标版本中人工改过的译文会保留，并提示源文变化待核对。无变更字段不重复翻译；已终稿和归档的目标不写入。
- 切换语言保存失败时不跳转。翻译失败保留目标已有正文，使用“同步译文”显式重试；普通打开报告不会新建付费翻译任务。

## 启用条件

默认 `TRANSLATION_PROVIDER=DISABLED`，不影响阅读、导航和既有简繁转换。真实翻译尚未在本次开发中调用或验收。

1. 在目标环境按既有发布流程执行 Alembic `upgrade head`，应用 `e91c2d3f4a50` 翻译作业迁移。不要将破坏性迁移测试指向业务库。
2. 通过公司安全配置渠道，在 API 与 worker 同时设置以下变量。模板在 [backend/.env.example](../backend/.env.example)，不得把真实密钥写进仓库或聊天。
3. 生产环境使用 `TASK_MODE=CELERY` 和已配置的 Redis；本地 `EAGER` 模式在请求中执行同一作业逻辑。
4. 用获批的非敏感样例验证网关响应、术语质量、超时与限额，再开放正式使用。

| 变量 | 要求 |
| --- | --- |
| `TRANSLATION_PROVIDER` | 启用时为 `OPENAI_COMPATIBLE` |
| `TRANSLATION_BASE_URL` | 已批准的 HTTPS 基础地址，通常以 `/v1` 结尾；程序追加 `/chat/completions` |
| `TRANSLATION_MODEL` | 该网关已批准的模型名称，不超过 255 字符 |
| `TRANSLATION_API_KEY` | 由安全配置渠道注入，不提供公共默认值 |
| `TRANSLATION_TIMEOUT_SECONDS` | 默认 45 秒，范围 1–60 |
| `TRANSLATION_MAX_CHARACTERS` | 默认 30000，上限 50000 |
| `TRANSLATION_MAX_TOKENS` | 默认 16000，范围 256–32000，须符合模型额度 |

网关必须支持 Chat Completions、`response_format: {"type":"json_object"}` 和 `max_tokens`。
只发送字段 ID 到文本的映射，不发送整份报告；禁止重定向，不配置公共服务回退。
HTTP 429、服务器或连接故障最多尝试三次；队列中断后超时作业会显示失败，用户可显式重试。

## 接口与冲突

`POST /api/v1/reports/{source}/language-variants/{target}/translations` 接收
`source_document_version`、`target_document_version` 和 `Idempotency-Key`，返回 202、`job_id`、`status_url`。
客户端不允许指定网关地址、模型、提示词或任意待翻译文本。幂等键按调用者和报告对隔离，同键不同请求返回 409。

`GET /api/v1/reports/{target}/translation-jobs/latest` 恢复最近任务；状态地址查询指定任务。
作业读取检查双方产品权限，范围外返回 404。排队后源/目标版本变化、目标终稿化或归档均会阻止旧任务落地。
文档和成功状态在同一事务提交；重复执行不会追加第二份译文。

| 错误码 | 处理 |
| --- | --- |
| `TRANSLATION_DISABLED` / `TRANSLATION_CONFIGURATION_INVALID` | 检查启用配置；不影响已有报告阅读 |
| `TRANSLATION_CONFIGURATION_CHANGED` | 模型、网关或提示版本改变，按当前版本重新发起 |
| `VERSION_CONFLICT` | 重新加载双方版本，确认人工修改后重试 |
| `TRANSLATION_UNBOUND_NUMBER` | 原文数字没有匹配已绑定指标/所选新闻引用，先核对数据 |
| `TRANSLATION_FACT_CHANGED` / `TRANSLATION_LANGUAGE_MISMATCH` | 模型返回不满足保真或语种检查，没有写入译文 |
| `TRANSLATION_PROVIDER_UNAVAILABLE` / `TRANSLATION_INCOMPLETE` | 检查服务可用性、模型限制或缩短内容后重试 |
| `TRANSLATION_EXPIRED` / `TRANSLATION_DISPATCH_FAILED` | 检查 worker/Redis，再显式重试 |

## 开发验证

- 前端：`npm test`、`npm run build`。
- 后端：`python -m pytest backend/tests/test_translations.py backend/tests/test_security.py backend/tests/test_reports_api.py backend/tests/test_migrations.py`。
- 本次使用模拟网关验证，未调用真实供应商。桌面 1440×1050、移动端 390×844 的浏览器测试拦截 API，不修改业务报告；证据在 `output/playwright/report-locales/`。
- 本地没有一次性 MySQL 测试地址，因此真机迁移和并发验收仍需在隔离 MySQL 环境完成。