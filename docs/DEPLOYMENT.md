# GitHub Pages + Render 部署

本项目使用 GitHub Pages 承载 `https://insistgang.top/Luyao_AI_Project/`，使用 Render Docker Web Service 运行 FastAPI、Gradio、ChromaDB 与 MiniMax 调用。

## 为什么仍然需要两层部署

GitHub Pages 只能发布静态文件，GitHub Actions runner 也不会常驻。MiniMax API Key 和 Python 服务必须留在服务器端，因此 Render 负责动态服务，Pages 只负责品牌入口和嵌入。

Hugging Face 当前要求 Pro 才能在 `cpu-basic` 上运行 Gradio/Docker Space，所以本项目已停止使用 Hugging Face 自动部署。

## 首次部署 Render

1. 登录 [Render Dashboard](https://dashboard.render.com/)，连接 GitHub 账号。
2. 选择 **New → Blueprint**，选择仓库 `insistgang/Luyao_AI_Project` 和 `main` 分支。
3. Render 会自动识别根目录的 `render.yaml`。检查服务名称为 `luyao-ai-project`、运行时为 Docker、实例类型为 Free。
4. 在 Blueprint 首次创建页面填写两个 Secret：
   - `MINIMAX_API_KEY`：MiniMax 中国区 API Key。
   - `LUYAO_ACCESS_PASSWORD`：分享给受邀用户的访问密码。
5. 点击 **Deploy Blueprint**，等待构建完成。首次构建可能需要数分钟。
6. 打开 Render 服务，复制实际的 `https://*.onrender.com` 地址。

GitHub Secret 与 Render Secret 彼此独立，Render 无法读取之前配置在 GitHub 的值，因此第 4 步需要在 Render 中再填写一次。不要把 Secret 写入 `render.yaml` 或 GitHub Variable。

## 接通 insistgang.top

1. 打开 GitHub 仓库的 **Settings → Secrets and variables → Actions → Variables**。
2. 新建仓库变量 `LUYAO_APP_URL`，值为第 6 步复制的完整 Render HTTPS 地址，不要带查询参数。
3. 在 **Settings → Pages → Build and deployment** 中将 Source 设为 **GitHub Actions**。
4. 打开 Actions，手动运行 **Deploy GitHub Pages**。

部署成功后访问：

`https://insistgang.top/Luyao_AI_Project/`

## 自动更新

- 推送 `main` 后，GitHub Actions 先运行单元测试，再更新 Pages。
- Render Blueprint 使用 `autoDeployTrigger: checksPass`，仓库检查通过后自动重新构建 Docker 服务。
- `MINIMAX_API_KEY` 与访问密码只存在于 Render Secret 中，不会进入 Docker 镜像或 Pages 构建产物。

## 免费实例限制

Render 官方说明中的 Free Web Service 限制包括：

- 连续 15 分钟无入站流量会休眠；下一次访问会唤醒，通常约需 1 分钟。
- 每个 workspace 每月有 750 个免费实例小时。
- 文件系统是临时的；休眠、重启或重新部署后，本地 ChromaDB 记忆会丢失。
- Free Web Service 不能挂载持久磁盘，不适合作为正式生产环境。

公开演示阶段可以接受这些限制。若要永久保存长期记忆，应升级到可挂载 Persistent Disk 的付费实例，或将记忆迁移到外部持久化数据库。

参考：[Render Free 服务限制](https://render.com/docs/free)、[Docker 部署](https://render.com/docs/docker)、[Web Service 端口规则](https://render.com/docs/web-services#port-binding)、[Blueprint 规范](https://render.com/docs/blueprint-spec)。

## 可选配置

`render.yaml` 已提供当前默认值：

- `MINIMAX_API_HOST=https://api.minimaxi.com`
- `MINIMAX_CHAT_MODEL=abab6.5s-chat`
- `MINIMAX_VOICE_ID=luyao_voice_v1`
- `MINIMAX_SPEECH_MODEL=speech-2.8-hd`
- `MINIMAX_WHISPER_MODEL=speech-2.6-hd`
- `LUYAO_ACCESS_USER=awu`

如需改变这些值，在 Render 服务的 Environment 页面修改即可。公开托管时请保持 `LUYAO_REQUIRE_AUTH=true`。
