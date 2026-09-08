# ADR-0027：基金评论应用的 Module Federation 接入

- 日期：2026-09-08
- 状态：已接受（用户指定 remote、3030 和 remote URL）
- 宿主参考：`investment-research-database@b33ca51dcae0c4b4cb27a42fdd8fc519eeb71e73`
- 样例参考：`DA-Report@c1946395a608b780413986442da13dcabc637f97`

宿主以普通 script 加载 remote URL，再调用 `window[scope].init(defaultShareScope)` 和
`container.get('./App')`，将模块默认导出交给 React.lazy。原有 Vite 独立 SPA 产物不符合此协议。
用户提供的仓库是接入材料；本仓库不修改或发布宿主，也不照搬样例中的登录参数。

采用原生 Webpack 5 ModuleFederationPlugin，scope `fundCmtAuto`，公开 `./App`。
开发及生产构建改用 Webpack；Vite 仅作为 Vitest 的转换依赖。这是对执行规格书 Vite 构建约定的明确偏离。
TypeScript 继续独立 `tsc -b` 检查，Webpack 用 esbuild-loader 转换（TypeScript 7 不再提供 ts-loader 依赖的旧 API）。
依赖树强制 React/ReactDOM 18.x，避免 npm workspace 及第三方 peer 混入 React 19。

保留原业务 Router 7/useBlocker，不共享宿主 Router 6；嵌入时使用 memory data router，避免嵌套路由
上下文及双方修改浏览器 history.idx。内部页面切换仍先保存编辑。独立调试模式使用带 basename 的
browser data router；宿主模式暂不提供报告深链接。路由实例在 effect 中创建及释放，兼容 StrictMode。

公开组件用 React portal 将应用放入 Shadow DOM，提供 LocaleProvider 和全部样式，隔离宿主 CSS 与语言。
字体定义单独注册并随组件卸载清理。沿用现有设计 token 值；DOM inert 用原生属性赋值兼容 React 18。

webapp 开发/容器/Service 统一 3030。入口固定 `/remote/fund-cmt-auto/remoteEntry.js`，chunks/fonts
相对于实际入口 URL 加载，支持本机跨端口；API 固定走宿主同域的 `/remote/fund-cmt-auto/api/v1`。
nginx 仅对 API 去除 remote 前缀；FastAPI 和签名算法仍使用内部 `/api/v1`。
`remoteEntry.js` 不缓存；缺失 chunks 返回 404，避免旧入口误收到 HTML 200。

部署、React 18 回归和无服务离线 Chromium 契约检查纳入 CI。真实平台注册、路由及 AWS 发布需在部署环境
完成；本次未执行。宿主侧程序化离开没有异步保存协议，当前需先手动保存，见 `k8s/REMOTE.md`。
