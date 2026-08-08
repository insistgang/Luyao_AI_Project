# ADR-0001：使用 Render 承载动态运行时

- 状态：Accepted
- 日期：2026-08-07

## 背景

路遥需要运行 FastAPI、Gradio、ChromaDB、FFmpeg 和 MiniMax 服务端调用。GitHub Pages 只能托管静态文件，GitHub Actions runner 也不能作为常驻后端。原方案使用 Hugging Face Docker Space，但实际部署返回 HTTP 402：免费 `cpu-basic` 不再向 Gradio/Docker Space 开放，需要 Pro 订阅。

当前目标是为非生产演示提供一个可分享、无需把 MiniMax Key 暴露给浏览器、且能从 GitHub 自动更新的托管方式。

## 决策

采用两层部署：

1. GitHub Pages 继续承载 `insistgang.top/Luyao_AI_Project` 的静态品牌入口。
2. Render Free Web Service 从仓库根目录的 Dockerfile 构建动态服务。
3. `render.yaml` 管理服务规格，敏感配置使用 `sync: false`，在 Render 首次部署时录入。
4. 容器只公开 Gradio 端口；FastAPI 绑定在容器回环地址。公开端口读取 Render 的 `PORT`。
5. 托管环境默认强制 Gradio 登录密码，防止匿名访客消耗 MiniMax 额度。

## 结果与权衡

优点：

- 保留现有 Docker 架构和 FFmpeg 依赖，迁移范围小。
- MiniMax Key 仅存在于 Render Secret 和运行时生成的权限受限文件中。
- Render 可在 GitHub 检查通过后自动部署，Pages 与后端解耦。
- 免费层足够用于阶段性演示。

代价：

- 免费服务空闲 15 分钟后休眠，冷启动通常约 1 分钟。
- 免费文件系统是临时的；ChromaDB 记忆会在休眠、重启或部署后丢失。
- 免费层没有生产可用性保证，并受实例小时、带宽与构建额度限制。
- GitHub Secret 无法自动传给 Render，首次部署需要在 Render Dashboard 再录入一次。

## 备选方案

- Hugging Face Spaces：因 Docker/Gradio 免费运行时要求 Pro 而否决。
- 只用 GitHub Pages/Actions：无法安全保存 Key，也没有常驻 Python 后端，否决。
- 浏览器直接调用 MiniMax：会暴露 API Key，否决。
- 自管 VPS：能持久化并避免休眠，但增加费用、运维和安全责任，待正式生产阶段再评估。

## 后续

当长期记忆需要跨重启可靠保存时，升级 Render 实例并挂载 Persistent Disk，或把记忆层迁移到具备长期保留策略的外部数据库。

参考：[Render Free](https://render.com/docs/free)、[Render Docker](https://render.com/docs/docker)、[Render Blueprint](https://render.com/docs/blueprint-spec)。
