# ADR-0032：输出时追加固定的专业投资者免责声明

- 日期：2026-09-25
- 状态：已接受
- 关联：[ADR-0017](0017-continuous-html-and-paged-documents.md)、[ADR-0018](0018-paged-preview-restores-reference-chrome.md)、[ADR-0029](0029-on-demand-report-downloads.md)

原四页报告规范没有为最新香港专业投资者免责声明预留页面。我们决定由渲染边界读取并校验版本化资源
`csop-hk-professional-investor-v1`，而不是把法律文本存进可编辑的 `ReportDocument`：分页预览、PDF
和 DOCX 无条件追加带标准页眉、Logo、连续页码及 TESTING 标识的第 5 页；连续 HTML 仅在末尾追加
同一语义区块，不显示运行页眉页脚。该规则同样适用于旧模板和已归档定稿的重新导出，文档中伪造的
`disclaimer` 字段不会被读取。

法律资源的版本与 checksum 写入导出 content manifest 和成功／失败审计，并参与 manifest checksum；
既有 document checksum 保持不变。资源缺失、结构错误或 checksum 漂移会以
`DISCLAIMER_RESOURCE_INVALID` 阻断导出。原四页黄金样例继续只比较前四页，第 5 页单独验证 A4、固定
文案和安全区；历史已下载文件不会被追溯修改。
