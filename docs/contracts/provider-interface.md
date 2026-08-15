# Provider 接口契约（v0.1 草案）

所有外部服务都必须位于 Provider 接口之后，可独立替换。阶段 0 只定义边界，
阶段 1 高风险能力验证完成后，用实测报告锁定每个接口的版本与具体语义。

## ModelProvider

- `complete(messages, images, tools) -> AsyncIterator[ModelEvent]`：流式文本/工具调用事件；
- `health() -> ModelHealth`：延迟、显存、模型列表；
- 实现：Ollama（阶段 1 验证 `qwen3-vl:8b`）；未来可替换其它推理后端。

## SearchProvider

- `search(query) -> list[SearchResult]`：`{title, url, snippet, retrieved_at}`，保留来源；
- `fetch(url) -> FetchedPage`：页面提取，返回内容必须带来源标记，内容视为不可信输入。

## EmbeddingProvider

- `embed(texts) -> list[float]` 与 `health()`；按需加载，避免与 8B 模型争抢内存。

## DelegateProvider（Hermes / Codex 的公共契约）

- `create_session(scope, cwd) -> SessionHandle`；
- `submit(task_pack) -> AsyncIterator[TaskEvent]`：进度、审批、产物、错误、中止；
- `abort(session, task)`；
- `resume(thread_id)`（Codex 可恢复线程，Hermes 会话续接）。
- 适配器不得解析执行器终端文本作为状态来源；升级只修改对应适配器。

## ChannelProvider（Web / OneBot）

- `inbound -> NormalizedMessage`：统一消息 `{sender, channel, kind, text, images, files, quote}`；
- `outbound(NormalizedReply)`；
- 渠道只负责传输与格式，不持有模型、记忆、权限或人格状态。

## 版本纪律

- 阶段 1 完成后，每个运行依赖记录：版本、提交哈希、许可证、兼容性结论；
- 上游升级必须通过契约测试后才能更新 `uv.lock` / `package-lock.json`。
