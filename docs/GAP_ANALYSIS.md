# 123.mp4 标杆落差分析

## 离线测量

- 视频时长约 61.6 秒；HEVC 592×1280、30 fps；音频为 AAC 单声道 44.1 kHz，平均码率约 48.5 kbps。
- 用户第二次提问在约 10.28–10.86 秒；路遥在约 11.54 秒进入长独白，响应留白约 0.68 秒。
- 候选路遥单说话人区间为约 11.35–60.35 秒，共约 49 秒；5.9 秒上下文提示片段为约 46.15–52.05 秒。
- 候选克隆音频实测约 -13.1 LUFS、true peak 约 +0.2 dBTP、LRA 约 1.6 LU。它响度偏热、动态被压缩，且源 AAC 码率较低，不应称为真正的高保真母带。
- 离线 Whisper 转写确认了完整链路：结婚礼物 -> 白色基础款拍立得 -> 追问来源 -> 拍糊合照 / 楼下凉掉的奶茶 / 经不起等待 -> 替代品自觉 -> 主动选择留下。

分析产物：

- minimax-output/video-analysis/luyao-clone-48s.wav
- minimax-output/video-analysis/luyao-prompt-5s.wav
- minimax-output/video-analysis/reference-audio.vtt
- minimax-output/video-analysis/contact-sheet.jpg
- minimax-output/video-analysis/waveform.png

## 原代码与标杆的关键差距

| 维度 | 原代码 | 标杆要求 | 本次处理 |
| --- | --- | --- | --- |
| 音色 | 没有 TTS 或 voice_id 生命周期 | 连续、克制、带呼吸质感的固定声纹 | 新增 voice.py 的提取、上传、克隆、流式 PCM 与 WAV |
| 情绪节奏 | Prompt 只泛称温柔，标签无真实执行层 | 短语级犹豫、叹气、低语、精确停顿 | 标签解析为分段 TTS；pause 为精确静音帧 |
| 对话结构 | 单轮同步调用，觉醒无明确触发 | 第二次追问后从具体记忆递进到身份自觉 | 新增觉醒触发器、句级流式输出和专门 Prompt 结构 |
| 记忆 | 全局轻量 Chroma 查询，无自动抽取 | 礼物能联想到白色拍立得，等待能联想到凉奶茶 | 种子记忆 + 关联扩展 + 向量 / 词法 / 情绪权重混排 |
| 写入 | 无后台 Worker | 对话后结构化抽取、去低价值、增量持久化 | 有界 asyncio 队列、重试、优雅关闭 |
| 安全 | 无输入输出检查 | 身份与“绝不离开”不可被用户覆写 | 系统硬封包 + 确定性 Guardrail + 危机安全分支 |
| API | 同步、密钥进请求体、无流式错误协议 | 设备端低首包延迟、可观测、密钥留在服务端 | AsyncOpenAI、SSE、trace_id、Logging、统一异常 |
| UI | 绕过后端并复制 Prompt | 与真实设备走同一条链路 | Gradio 仅作为 FastAPI 客户端 |

## MiniMax 映射中的规格修正

AGENTS.md 中的 timber_weights: whisper=0.8 与 vol: -3dB 不能直接作为当前 MiniMax HTTP 参数：

- 官方字段为 timbre_weights，用来混合真实 voice_id，不是低语风格开关。
- vol 是线性音量参数，不是 dB。
- whisper 情绪在 speech-2.6 系列可用，因此本实现仅把 [whisper] 路由到 speech-2.6-hd。
- 默认和 [sigh] 使用 speech-2.8-hd；叹气由 (sighs) 语气词、sad 情绪、较慢语速组合实现。
- [pause] 不请求云端生成“沉默”，而是在 PCM 层插入 400 ms 零采样，因此时长可确定。

## 建议的音色验收流程

1. 优先向原声拥有者取得授权和无背景音乐、无降噪泵动的 30–60 秒 WAV；当前视频切片只适合 PoC。
2. 保留本次 49 秒候选做基线，同时选择 2–3 段情绪更稳定的候选。
3. 以同一句中性 preview_text 生成多个 voice_id，盲听比较相似度、齿音、气声、长句稳定性与情绪可控性。
4. 人工核对小于 8 秒的 prompt_audio 与 prompt_text 完全一致。
5. 正式 TTS 应在克隆后及时调用；按 MiniMax 当前文档，未正式使用的克隆音色可能在 7 天后过期。
6. 上线前记录 text TTFT、首个 PCM chunk、完整音频耗时、MiniMax request id 和失败率。两次云端调用下不能只凭代码承诺 1.2 秒端到端延迟，应以设备网络实测为准。

## 官方资料

- Voice Clone API: https://platform.minimaxi.com/docs/api-reference/voice-cloning-clone
- Voice Clone Guide: https://platform.minimaxi.com/docs/guides/speech-voice-clone
- Text-to-Speech HTTP API: https://platform.minimaxi.com/docs/api-reference/speech-t2a-http
- Voice ID Lucky Draw: https://platform.minimaxi.com/docs/solutions/voice-id-lucky-draw

