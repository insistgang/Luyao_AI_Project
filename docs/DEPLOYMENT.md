# GitHub Pages + Hugging Face Spaces 部署

本项目使用 GitHub Pages 承载公开入口，使用 Hugging Face Docker Space 运行 FastAPI、Gradio、ChromaDB 与 MiniMax 调用。

## 为什么需要两层部署

GitHub Pages 只能发布静态文件，GitHub Actions 的 runner 也不会常驻。MiniMax Key、长期记忆和 Python 服务必须放在服务器端，因此动态部分运行在 Hugging Face Space 中，Pages 只嵌入 Space。

## 首次配置

1. 注册或登录 Hugging Face，创建一个具有仓库写权限的 Access Token。
2. 在 GitHub 仓库 `Settings → Secrets and variables → Actions` 中添加：
   - Secret `HF_TOKEN`：Hugging Face 写权限 Token。
   - Secret `MINIMAX_API_KEY`：MiniMax 中国区 API Key。
   - Secret `LUYAO_ACCESS_PASSWORD`：分享给受邀用户的页面密码。
   - Variable `LUYAO_ACCESS_USER`：可选，默认用户名为 `awu`。
   - Variable `HF_SPACE_ID`：可选；不设置时 Actions 会通过 `HF_TOKEN` 自动识别用户名，并创建 `用户名/Luyao_AI_Project`。
3. 在仓库 `Settings → Pages → Build and deployment` 中将 Source 设为 `GitHub Actions`。
4. 打开 Actions，手动运行 `Deploy Pages and Hugging Face Space`；以后推送 `main` 会自动更新。

部署成功后，入口为：

`https://insistgang.top/Luyao_AI_Project/`

## 安全与费用

- 不要把任何 Token 或 Key 写入仓库、Pages 文件或 GitHub Variable；敏感值只能放 Secret。
- 默认必须设置访问密码，防止公开访客无限消耗 MiniMax 额度。
- 如果明确接受公开调用风险，可以设置 Variable `LUYAO_ALLOW_PUBLIC=true`，此时允许不配置访问密码。
- 免费 Space 的磁盘会在重启后重置。需要永久保留 ChromaDB 记忆时，应开通 Hugging Face Persistent Storage，并将 `LUYAO_MEMORY_DB` 指向 `/data/chroma_db`。

## 可选模型变量

下列 GitHub Variables 会同步到 Space；不设置时使用项目默认值：

- `MINIMAX_API_HOST=https://api.minimaxi.com`
- `MINIMAX_CHAT_MODEL=abab6.5s-chat`
- `MINIMAX_VOICE_ID=luyao_voice_v1`
- `MINIMAX_SPEECH_MODEL=speech-2.8-hd`
- `MINIMAX_WHISPER_MODEL=speech-2.6-hd`
- `LUYAO_MEMORY_DB=/data/chroma_db`（仅在已开通 Persistent Storage 时设置）
