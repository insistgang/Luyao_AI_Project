# 阿里云 Docker 部署

部署入口使用现有 Nginx HTTPS 服务的 `/luyao/` 路径。Gradio 容器只映射主机回环端口 `127.0.0.1:17860`，FastAPI 保留在容器内部。

## 配置

从 `.env.ecs.example` 复制 `.env.ecs`，限制权限为 `600`。启用聊天和语音时填写 MiniMax 中国区 API Key，确认音色 ID 属于该账号；需要登录保护时再填写访问密码。真实凭据文件不会进入 Git 或 Docker 构建上下文。

首次只验证界面时，可以设置 `LUYAO_ALLOW_UNCONFIGURED=true` 并保持 `MINIMAX_API_KEY` 为空。默认保留 `LUYAO_REQUIRE_AUTH=true` 和非空访问密码；需要免登录访问时，设置 `LUYAO_ALLOW_PUBLIC=true`、`LUYAO_REQUIRE_AUTH=false`。公开模式会忽略已保存的访问账号和密码，直接展示界面。

没有 Key 时，页面显示“等待配置”，不启用云端聊天和语音。免登录模式也允许使用付费 Key：填写服务器私有 `.env.ecs` 后重建容器即可，不需要恢复登录；`LUYAO_ALLOW_UNCONFIGURED=true` 只允许空 Key 启动，不会阻止已配置的付费服务。Key 不会发送到浏览器，健康检查也不会调用付费接口。

公开使用意味着任何访客都可能消耗账号额度。当前长期记忆使用默认身份 `awu_001`，不同访客可能共享该身份的记忆；多人公开使用前应实现访客记忆隔离，并避免输入私密信息。调用限额和费用预算属于后续加固事项，不是公开模式的启动条件。

```bash
docker compose --env-file .env.ecs -f compose.ecs.yml config --quiet
docker compose --env-file .env.ecs -f compose.ecs.yml build
docker compose --env-file .env.ecs -f compose.ecs.yml up -d
docker compose --env-file .env.ecs -f compose.ecs.yml ps
```

容器使用 UID 1000 和资源限制。三个命名卷分别保存 ChromaDB、会话密钥与运行数据、嵌入模型缓存。更新镜像和重建容器会保留这些卷；不要使用 `down -v`，该选项会删除持久化数据。

## HTTPS 代理

将 `deploy/nginx-luyao.location.conf` 包含在目标 HTTPS `server` 块中。保存修改前的配置备份，先运行 `nginx -t`，通过后执行 `systemctl reload nginx`。

`LUYAO_ROOT_PATH=/luyao` 与代理路径对应。代理保留转发主机和协议头，并关闭流式响应缓冲。可参考 [Gradio 的 Nginx 指南](https://gradio.app/guides/running-gradio-on-your-web-server-with-nginx)。

当前域名入口为 `https://dmp.insistgang.top/luyao/`，复用该域名已有的 DNS 和 HTTPS 证书。在它的 HTTPS `server` 块中包含上述 location 文件，不改变主域名博客的解析或其他应用路由。原 IP 的 `/luyao/` 路径重定向到此域名。

## 验证和更新

镜像安装 `requirements.lock` 中的已测试版本。容器健康检查同时检查 FastAPI 和 Gradio；正式模式要求后端状态为 `ok`，预览模式允许如实报告未配置的 `degraded` 状态。两种模式都不在健康检查中消耗 MiniMax API 额度。

```bash
docker compose --env-file .env.ecs -f compose.ecs.yml logs --tail 50
docker compose --env-file .env.ecs -f compose.ecs.yml exec luyao python -m scripts.container_healthcheck
```

首次启动可能下载嵌入模型，因此预留了 180 秒启动时间。部署前可以预填模型缓存卷。进程监督器会在前端或后端退出时退出，由 Docker 的重启策略恢复服务；停止时会先通知两个进程，再等待记忆抽取任务收尾。

服务器安装 Docker 应使用可信的软件仓库；[Docker 官方 Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)提供安装和防火墙说明。本部署仅在回环地址发布容器端口，外部访问通过 Nginx HTTPS。登录保护默认开启，仅在明确配置公开访问时关闭。
