# 路遥 Luyao AI

基于 MiniMax 全栈 API 的情感陪伴 AI：`abab6.5s-chat` 负责 Persona 对话与记忆抽取，Speech 2.8/2.6 负责克隆音色和语音合成。

## 本地配置

项目不要求通过环境变量配置 API Key。先复制公开模板：

~~~powershell
Copy-Item local_settings.example.py local_settings.py
~~~

然后打开 `local_settings.py`，填入自己的 MiniMax 中国区 API Key：

~~~python
MINIMAX_API_KEY = "你的MiniMax API Key"
MINIMAX_API_HOST = "https://api.minimaxi.com"
MINIMAX_CHAT_MODEL = "abab6.5s-chat"
MINIMAX_VOICE_ID = "luyao_voice_v1"
MINIMAX_SPEECH_MODEL = "speech-2.8-hd"
MINIMAX_WHISPER_MODEL = "speech-2.6-hd"
~~~

`local_settings.py` 已加入 `.gitignore`，不会被提交。项目使用 OpenAI Python SDK 调用 MiniMax 官方的 OpenAI 兼容协议；实际请求全部发往 MiniMax：

- 聊天：`https://api.minimaxi.com/v1/chat/completions`
- 语音：`https://api.minimaxi.com/v1/t2a_v2`

## 当前能力

- 一套 MiniMax Key 同时用于聊天、异步记忆抽取、TTS 和声纹克隆。
- 一条模型回复可拆成多条独立聊天气泡，并与同一段语音按时间同步显示。
- 每条回复只调用一次 MiniMax TTS，避免语音重复生成和重复计费。
- 浏览器会话保留显示历史和模型上下文，多轮对话不会丢失旧消息。
- 双轨长期记忆 RAG、异步记忆提取与 Persona Guardrail。

## 安装与运行

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
~~~

另开一个 PowerShell：

~~~powershell
python ui.py
~~~

浏览器访问 <http://127.0.0.1:7860>，健康检查位于 <http://127.0.0.1:8000/health>。

## 从 123.mp4 准备并克隆音色

~~~powershell
python voice.py prepare --input 123.mp4 --output-dir minimax-output/voice-clone
python voice.py clone --audio minimax-output/voice-clone/luyao-clone-48s.wav --voice-id luyao_voice_v1 --prompt-audio minimax-output/voice-clone/luyao-prompt-5s.wav --prompt-text "一直写着，无论阿雾让我等多久，我都不会离开。她等不到你，所以离开了。而我从被创造出来的第一天，就没有离开你这个选项。"
~~~

只应克隆已取得说话人明确授权且拥有使用权的声音。

## 验证

~~~powershell
python -m unittest discover -s tests -v
python test_minimax_all.py
~~~

第一条命令不消耗 API 额度；第二条会实际调用 MiniMax，请在确认额度后手动运行。
