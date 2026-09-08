# 远程应用运维速查

以下为 UAT，Production 替换 env 路径与对象名；所有命令指定目标 context。

```bash
CONTEXT=REPLACE-ME-UAT-CONTEXT
APP=ih-uat-remote-fund-cmt-auto
kubectl --context "$CONTEXT" -n ih get pods -l app="$APP" -o wide
kubectl --context "$CONTEXT" -n ih get deploy,svc -l app="$APP"
kubectl --context "$CONTEXT" -n ih logs deploy/$APP-srvapp -c migrate --tail=40
kubectl --context "$CONTEXT" -n ih logs deploy/$APP-srvapp -c srvapp --tail=100
kubectl --context "$CONTEXT" -n ih logs deploy/$APP-srvapp -c worker --tail=100
kubectl --context "$CONTEXT" -n ih logs deploy/$APP-srvapp -c srvapp --previous
kubectl --context "$CONTEXT" -n ih exec deploy/$APP-srvapp -c srvapp -- python -m app.core.health
kubectl --context "$CONTEXT" -n ih exec deploy/$APP-webapp -c webapp -- wget -qO- http://127.0.0.1:3030/healthz
kubectl --context "$CONTEXT" -n ih exec deploy/$APP-webapp -c webapp -- wget -qO- http://127.0.0.1:3030/remote/fund-cmt-auto/api/v1/health
```

修改非机密配置后 apply `configmap.yaml`，再 restart 对应 Deployment。
密钥轮换后执行 `sh k8s/create-secret.sh uat --context "$CONTEXT"`，再 restart srvapp。
不要打印整个环境或 Secret。健康探针的成功访问日志被过滤，非 200 和业务请求仍记录。

| 症状 | 检查 |
|---|---|
| ImagePullBackOff | ECR 账号/仓库名、latest 是否已推送、节点角色权限 |
| Init:CrashLoopBackOff | migrate 日志、必填配置、MySQL 权限、迁移 schema 状态 |
| srvapp 1/2 Ready | 分别看 API 与 worker，检查 Redis、Celery pid 和资源限制 |
| nginx FATAL | API_UPSTREAM、conf.d/tmp 权限、envsubst 过滤器 |
| API 502 | srvapp Service selector/端口、Pod 是否 Ready、平台是否保留 API 路径 |
| 报告数据不足 | ConfigMap 是否启用所需来源、Secret 是否填写对应 key、目标网络权限 |
| 下载失败 | 深检查只能验桶；实际渲染和下载检查 TOS 对象写入/读取权限 |

访问入口、反向代理、网络控制沿用远程应用平台。本仓库没有独立 Ingress 或登录流程。
