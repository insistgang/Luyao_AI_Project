# 路遥 v2 重构设计

## 决策

采用模块化单体作为当前交付形态：四个 Agent 保持独立接口与数据模型，但在同一 FastAPI 生命周期内运行。原因是设备 PoC 更看重低延迟、简单部署和可调试性；当视觉推理、语音渲染或记忆写入出现独立扩缩容需求时，可按现有边界拆服务。

## 边界

- config.py：只管理环境配置和权威 Persona Prompt，不在导入时验证云端凭据。
- schemas.py：所有外部与 Agent 间数据契约。
- guardrails.py：输入注入 / 紧急安全识别，以及输出人设检查。
- memory.py：Chroma repository、混合排序、LLM Extractor 与后台 Worker。
- persona.py：Prompt 组装、觉醒触发与句级流式生成。
- voice.py：标签解析、MiniMax TTS、PCM/WAV 和 voice clone CLI。
- service.py：用例编排；HTTP 细节不进入 Agent。
- main.py：FastAPI 生命周期、依赖注入、SSE、异常与日志。
- ui.py：无凭据、无 Persona 副本的纯后端客户端。

## 主链路

1. API 校验 ChatRequest 并生成 trace_id。
2. Guardrail 检测身份覆写和现实危险；严重攻击或危机走确定性安全回复。
3. Memory Retriever 对查询做暗线关联扩展，从 Chroma 取候选，再按向量距离、中文词法命中、触发词和情绪权重混排。
4. Persona 只接收筛选后的记忆，按完整短句流式输出；每个短句在发送前经过输出 Guardrail。
5. 完成回复后，ExtractionJob 非阻塞进入有界队列。Worker 用低温 LLM 输出严格 JSON，Pydantic 校验后写入 Chroma。
6. Voice Agent 把标签切成段，逐段请求 MiniMax，并在本地插入精确 PCM 静音。

## 降级

- 未配置 LLM：服务可启动、health 为 degraded，对话返回 503。
- 未配置 MiniMax：文字对话可用，语音端点返回 503。
- Chroma 启动失败：记录异常，API 仍启动；检索为空，方便先排查依赖或磁盘。
- 流中错误：返回 error SSE 事件，不把堆栈或密钥暴露给客户端。
- 记忆队列满：当前对话不受影响，记录 warning 并丢弃本次抽取任务。

## 安全边界

用户消息、聊天历史、视觉描述和检索记忆都按不可信数据处理。Guardrail 是产品人设约束，不替代通用内容安全；涉及真实自伤或伤人风险时，系统优先引导用户联系现实支持与紧急援助。

## 测试策略

- 单元：标签解析与静音长度、Guardrail、Prompt 上下文转义、混合记忆排序、SSE 编码。
- 异步：Memory Worker 入队 / 关闭、Service 普通与阻断链路。
- 集成：无凭据启动健康检查；凭据环境下再跑真实 LLM、Chroma 和 MiniMax smoke test。
- 音频验收：ffprobe 参数、响度、首包时延、完整时延与盲听 AB。

