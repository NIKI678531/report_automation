# 宿主接入

用户指定的宿主为 `csop-ai/investment-research-database`，参考 remote 为 `csop-ai/DA-Report`。
本仓库提供 Webpack Module Federation React 组件，不增加独立登录、域名或证书。

| 配置 | 值 |
|---|---|
| 前端开发 / nginx / K8s Service 端口 | `3030` |
| Remote URL | `/remote/fund-cmt-auto/remoteEntry.js` |
| Scope | `fundCmtAuto`（大小写敏感） |
| Module | `./App`（默认导出 React 组件） |
| 宿主业务 route | `/fund-cmt-auto` |
| 平台 API 前缀 | `/remote/fund-cmt-auto/api/v1` |
| 后端 Service 端口 / 路由 | `8000` / `/api/v1` |

宿主注册字段示例见 [host-app-registration.example.json](host-app-registration.example.json)。
在平台现有应用管理中录入这些字段，并按平台规则配置 roles、图标和排序；文件本身不会创建注册记录。
业务 route 使用 `/fund-cmt-auto`，因为当前宿主会对 `/remote/` 开头的应用业务根路由返回 404。

## 平台代理

平台需要保留完整请求路径，将 `/remote/fund-cmt-auto/` 下所有请求转发至以下 Service：

- UAT：`ih-uat-remote-fund-cmt-auto-webapp.ih.svc.cluster.local:3030`
- Production：`ih-prd-remote-fund-cmt-auto-webapp.ih.svc.cluster.local:3030`

平台 nginx 中的等价示例（纳入平台现有准入规则，由平台方配置）：

```nginx
location /remote/fund-cmt-auto/ {
    proxy_pass http://ih-uat-remote-fund-cmt-auto-webapp.ih.svc.cluster.local:3030;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

不要在平台层删除 `/remote/fund-cmt-auto`；webapp 会为 API 删除此前缀，同时保留 `/api/v1`。
`/fund-cmt-auto` 的页面请求仍由宿主 SPA 处理，不能转发给 remote nginx。
预览和签名下载也走同一 API 前缀；签名查询参数不重新编码。
API 不开启通配 CORS；远程静态 JS/字体允许匿名跨源加载，供本机跨端口联调使用。
平台同域代理仍须覆盖 API，单独把 remote URL 指向 3030 无法替代 API 代理。

`remoteEntry.js` 和独立调试 HTML 使用 `no-store`，带内容哈希的 JS/字体长期缓存。
未知路径和缺失静态文件返回 404；仅独立页面及其 `/reports/...` 路由回退 `index.html`。
健康探针仍为容器内 `http://127.0.0.1:3030/healthz`，不依赖后端。

## 本地联调与验证

使用 Node 24.19+ 和根 npm workspace。前后端由开发者手动启动：

```powershell
npm ci
npm run dev
```

直接调试页面为 `http://localhost:3030/remote/fund-cmt-auto/`；远程入口为
`http://localhost:3030/remote/fund-cmt-auto/remoteEntry.js`。开发代理把 API 转发至 `localhost:8000`。
宿主在 3000 联调时，为宿主开发代理添加 `/remote/fund-cmt-auto/` → `http://localhost:3030`，
保留请求路径；注册的相对 remote URL 即可保持与部署环境一致。

不启动服务的检查：

```powershell
npm test
npm run build
npm run build:host-contract --workspace @commentary/web
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python scripts/check_remote_app.py
```

契约测试通过浏览器拦截读取本地构建产物，模拟后端数据，不开 HTTP 监听或连接数据库。

报告下载使用 `/remote/fund-cmt-auto/api/v1/reports/{id}/exports/{format}/download` 签发地址，
随后访问同一前缀下的 `content` 接口并等待生成。平台需要保留完整查询参数、允许长请求，
并遵守 `Cache-Control: no-store`。成品不保存在存储桶中；旧 artifact/job 接口已退役，
见 [ADR-0029](../docs/adr/0029-on-demand-report-downloads.md)。
验证宿主 React 18.3.1、Router 6.30.0 的真实共享作用域和 classic script `init/get`，
覆盖跨端口资源、Shadow DOM 编辑/样式、保存失败、预览、卸载/重挂载和独立入口。

## 组件边界

React/ReactDOM 为与宿主兼容的 18.x singleton。私有 Router 7 保留 data router 的 `useBlocker`。
嵌入模式使用 memory router，报告页面切换不修改宿主地址、query 或 history；重新进入/刷新会回到报告中心。
独立调试页面使用带 `/remote/fund-cmt-auto` basename 的 browser router，可刷新报告 URL。

CSS、设计 token、编辑器和布局样式都放在 Shadow DOM；字体定义随组件挂载/卸载。
语言设置沿用应用自己的报告语言，嵌入时不改宿主 `<html lang>`，不消费宿主的登录参数。
应用内切换报告/模块/返回中心会先保存，保存失败保留编辑页；关闭或刷新页面仍有未保存提示。
宿主的 BrowserRouter 不提供应用级异步离开钩子，切换到其他宿主应用前需先点击模块保存。
若平台需统一拦截宿主侧所有程序化导航，应在宿主增加 before-leave 协议后再对接。
