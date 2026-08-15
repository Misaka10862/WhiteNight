# 阶段 1 高风险能力实测报告（2026-08-15）

> 状态：进行中。每项能力给出「可用 / 部分可用 / 待用户操作 / 替代方案」结论。
> 复跑命令：`uv run scripts/verify_phase1.py --smoke-model --smoke-gateway`
> 原始 JSON 证据：`data/reports/phase1-*.json`（本机数据目录，不入 Git）。

## 0. 本机环境

- macOS 26（arm64），16 GiB 统一内存，可用磁盘约 348 GiB
- Ollama 0.32.1（本机常驻服务）
- Python 3.12.14（uv 管理）；Node v26.4.0；Hermes v0.17.0；Codex CLI 0.147.0

## 1. 本地模型：Ollama qwen3-vl:8b —— 可用

| 项目 | qwen3:8b（文本） | qwen3-vl:8b（视觉） |
|---|---|---|
| 量化 / 大小 | Q4_K_M / 5.2 GB | Q4_K_M / 6.1 GB |
| 上下文长度 | 40 960 | 262 144 |
| 能力 | completion, tools, thinking | completion, vision, tools, thinking |

烟测结果（16 GiB 机器、模型冷加载、`think` 关闭文本模型）：

| 烟测 | 首 token | 首可见内容 | 总时长 | 输出 |
|---|---|---|---|---|
| 文本「只回复两个字：好的」 | 2.19 s | 2.19 s | 2.23 s | 「好的」 |
| 视觉「描述这张图片的内容，一句话」（32×32 红色 PNG） | 8.17 s | 11.54 s | 12.27 s | 「这张图片完全由均匀的红色填充，无任何其他视觉元素或细节。」 |
| 工具调用「查杭州天气」（`get_weather` JSON Schema） | — | — | 3.45 s | `tool_calls[0].arguments == {"city":"杭州"}`，Schema 通过 |

结论：文字聊天 5–8 秒、图片理解 15 秒内开始输出的性能目标**在当前硬件上成立**。

### 必须固化的实测结论（供 Provider 实现使用）

1. **图片必须挂在 user message 的 `images` 字段**。Ollama 0.32 的 qwen3-vl
   会静默忽略顶层 `images` 字段，模型会说“没有看到图片”。
2. **qwen3-vl 当前模板忽略 `think:false`**：总是先输出 `<think>` 推理 token，
   可见内容在其后到达（实测多出约 3.4 s）。上下文预算和“首内容延迟”计算
   必须把 thinking token 计入；若后续 Ollama 版本支持关闭，重新跑烟测对比。
3. qwen3 文本模型支持顶层 `think:false`，应默认关闭以获得陪伴式即时回复；
   仅路由/结构化任务按需开启 thinking。
4. 16 GiB 下只常驻一个 8B 模型：Ollama 自动卸载未用模型；调度与嵌入按需加载。
   并发参数建议先按 `OLLAMA_NUM_PARALLEL=1` 保守配置，阶段 2 用负载测试锁定。
5. 工具调用可用：`/api/chat` + `tools` 返回结构化 `tool_calls`，参数符合 JSON Schema
   （实测 `get_weather(city="杭州")`）；阶段 2 的工具执行层必须仍由程序校验参数，
   不能直接执行模型输出。

## 2. Hermes —— 部分可用（需用户登录模型 Provider）

- Hermes Agent v0.17.0（upstream 2f5950a8）已安装于 `~/.local/bin/hermes`。
- **Gateway 烟测通过**：`hermes serve --host 127.0.0.1 --port <port>` 可自动构建
  WebUI 并在限时内返回 HTTP 200；OpenAPI 暴露 sessions、files、tools、
  computer-use、auth 等完整 REST 面。
  - 注意：`--skip-build` 在首次没有 web dist 时会直接退出，先建后可用。
- **任务级验证被凭据阻塞**：`hermes status` 显示所有模型 Provider 均未登录；
  `/api/sessions` 返回 401。需要用户执行 `hermes model` / `hermes auth`
  登录一个可用 Provider 后才能验证创建会话、流式事件、审批与中止。
- **computer-use（cua-driver）**：已安装 `cua-driver 0.19.3`（经本地代理下载成功），
  位于 `~/.local/bin/cua-driver` 与 `/Applications/CuaDriver.app`（bundle id
  `com.trycua.driver`）。`hermes computer-use doctor` 结果：
  二进制/平台/MCP 会话/bundle 身份均通过；**辅助功能与屏幕录制 TCC 未授权**，
  UI 检查与事件注入不可用。需要用户在系统设置授权，或运行
  `hermes computer-use permissions grant` 并在弹出的系统对话框确认。
  授权前 computer-use 不能执行真实 GUI 操作，但这不阻塞 Gateway 协议开发。
- 替代方案：若 computer-use 在权限或稳定性上不达标，GUI 操作 Provider 可替换
  （构建计划第 19 节风险表已预留）；Hermes Adapter 只依赖 Gateway 协议。

## 3. Codex —— 可用（协议握手已验证）

- `codex-cli 0.147.0` 已全局安装；`~/.codex/auth.json` 存在（内容未读取）。
- **MCP stdio 握手通过**：向 `codex mcp-server` 发送 JSON-RPC
  `initialize`（protocolVersion `2025-03-26`），返回
  `serverInfo: codex-mcp-server 0.147.0`。
- 新建/续接线程、工作目录、沙箱与错误恢复将在阶段 5 用契约测试验证；
  阶段 1 已确认官方 MCP 入口可用，无需自行实现协议。

## 4. NapCat / QQ —— 待用户操作

- NapCat 未安装；npm 包 `napcat` 已被官方撤下（404），需从 NapCatQQ 官方
  发布渠道下载构建并由用户扫码登录专用 QQ 小号。
- 阻塞点属于账号风控与扫码交互，Agent 无法代做；OneBot 11 Adapter 可以先用
  mock OneBot server 开发，不受阻塞。

## 5. SQLCipher + Keychain —— 可用

- 初版 `sqlcipher3-binary` 仅发布 Linux wheel，在 macOS 安装失败（已记录
  ADR-0002 修订）；切换为 `sqlcipher3==0.6.2`（提供 macOS arm64 cp312 wheel），
  `uv sync --extra sqlcipher` 成功。
- 实测：正确密钥可建表写入/读取；错误密钥被拒绝；驱动版本 SQLCipher 3.51.1。
- **引擎层集成测试通过**（`tests/test_sqlcipher_integration.py`，23 tests 全绿）：
  `storage.engine.build_engine("sqlcipher:///...", key=...)` 经由 PRAGMA key
  工作；`PRAGMA key` 不接受绑定参数，已改为转义字面量注入且不入日志。
- macOS Keychain 一次性条目写入/读取/删除探针通过（`security` CLI 后端）。

## 6. 阶段 1 结论与待办

| 能力 | 结论 |
|---|---|
| qwen3-vl:8b 推理 | 可用，性能达标，接口结论已固化 |
| Hermes Gateway | 协议面可用；任务链路待用户登录 Provider |
| Hermes computer-use | 驱动 0.19.3 已安装；TCC 授权待用户确认（doctor 已给出精确诊断） |
| Codex MCP | 可用，握手通过 |
| NapCat / QQ | 待用户下载与扫码；开发可用 mock 先行 |
| SQLCipher / Keychain | 可用，原型与集成测试通过 |

退出条件中“每项高风险能力都有可用方案或明确替代方案”已基本满足；
仅 Hermes 任务链路与 QQ 链路需要用户完成登录/扫码后再跑一次契约烟测，
期间不阻塞阶段 2（最小纵向链路）的开发。
