# VM 直跑备用配置

这里保留较早讨论的 VM Docker Compose 方案，不是当前申请的 IH 集群 UAT/PRD 清单。
当前部署入口是 [Kubernetes 部署说明](../../k8s/README.md)。

运行时配置模板为 [.env.example](.env.example)，填写后的副本使用本目录的 `.env.vm`。
所有命令在仓库根目录执行，显式指定文件，避免依赖当前目录：

```bash
docker compose --env-file deploy/vm/.env.vm -f deploy/vm/compose.vm-production.yaml config --quiet
docker compose --env-file deploy/vm/.env.vm -f deploy/vm/compose.vm-build.yaml config --quiet
docker compose --env-file .env -p commentary-trial -f compose.yaml -f deploy/vm/compose.vm-trial.yaml config --quiet
```

试运行依然与根目录本地 Compose 合并；正式 VM 配置依然独立，不能与根 Compose 合并。
这些命令只是检查，不会创建集群资源；旧说明见 [VM 部署文件说明](../../docs/vm-deployment-files.md)。