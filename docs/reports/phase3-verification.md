# 阶段 3 工具、文件与文档 实测报告（2026-08-15）

> 复跑：`uv run pytest`（70 passed, 2 skipped）
> 阶段 3 退出条件：覆盖格式的测试语料全部给出有来源的结果；高风险动作无法绕过审批。

## 1. 权限、审批与审计（policy/）

- `PolicyEngine`：工具名 → 风险等级确定性规则；未知工具一律 `BLOCKED`。
  只读 `auto`、低风险写入 `session`、中/高/删除 `once`、批量删除 `blocked`。
- `ApprovalService`：短期一次性审批编号（`secrets.token_urlsafe`）、
  不可重放（`used_count`）、10 分钟过期、session 绑定校验、
  `once/session` scope 严格匹配，防止用低权限审批降级批准高风险工具。
- `SessionGrant`：低风险写入按会话授权（24h）。
- `AuditService`：每次现实动作记录执行者、参数摘要、审批 id、决策、结果与时间；
  参数中的 `content` 只记长度，不记全文。
- DB 迁移 `0003`：approvals / session_grants / audit_events。
- 红队测试覆盖：未知工具拒绝、批量删除不可绕过、once 代码重放拒绝、
  session 审批不能批准 once 工具、参数非法在执行前拒绝。

## 2. 工具层（tools/）

| 工具 | 风险 | 行为 |
|---|---|---|
| `file.read` | 只读 | UTF-8 → GB18030 → latin-1 编码回退；本机全文件范围 |
| `file.create` | 低风险 | 新建文件；默认不覆盖；需会话授权 |
| `file.write` | 中风险 | 仅覆盖已有文件；逐次审批 |
| `file.move` | 中风险 | 移动/重命名；逐次审批 |
| `file.delete` | 删除 | 单文件经 Finder 移入废纸篓，禁止永久删除 |
| `file.batch_delete` | 批量删除 | PolicyEngine 直接拒绝，执行器无执行路径 |
| `screen.capture` | 只读 | `screencapture -x`；权限缺失时如实报错 |
| `web.search` / `web.fetch` | 只读 | 结果保留 URL/标题/摘要，内容标记 `untrusted` |
| `document.parse` | 只读 | 分发到文档解析器，来源为本地路径 |
| `archive.list` | 只读 | 只列 zip/tar 条目与预估大小，不解压 |

- `ToolExecutor` 是唯一执行入口：模型输出只能给工具名 + 参数，经
  PolicyEngine → 审批 → Schema 验证 → 执行 → 审计，无法跳过任何一步。

## 3. 文档解析（documents/）

实测语料（临时目录生成并全部有来源）：

| 格式 | 结果 |
|---|---|
| UTF-8 / GB18030 文本、Python 代码 | 文本 + 编码 + 截断标记 |
| PDF（PyMuPDF 生成） | 页面文本、页数、扫描页 OCR 标记 |
| DOCX / XLSX / PPTX | 段落/表格/工作表/幻灯片文本 |
| 图片 OCR（Apple Vision） | 渲染 PNG 识别 "WHITE NIGHT 42"，含置信度 |
| ZIP | 只列条目与解压预估，实测不落盘解压 |
| 旧版 .doc/.xls/.ppt | 明确报错，走受控转换器（不自动执行转换） |
| 未知格式 | 如实报错，不伪造内容 |

扫描 PDF：文本量 <20 字符的页面自动渲染 200 DPI 后走 Apple Vision OCR，
OCR 不可用/失败时在 metadata 中标记 `ocr_failed_pages`。

## 4. 联网搜索与页面提取（实测）

- DuckDuckGo HTML 端点会返回 202 挑战页（反爬）；已改为
  **DDG Lite 优先、Bing HTML 兜底**的 Provider，两个端点都保留来源 URL。
- 实测：`Python 编程语言` 返回 3 条结果，URL 直接可点（python.org、w3schools）。
- 实测页面提取：python.org/about/ → 标题、最终 URL、2000 字符正文，
  `untrusted=True` 标记。
- Provider 接口可替换；测试用 Fake Provider 验证来源保留与不可信标记。

## 5. 已知边界与后续

- `file.delete` 与 `screen.capture` 的真实系统调用需要 macOS
  Finder 自动化/屏幕录制权限；本轮用受控 fake 完成状态机与审计测试，
  真实授权留给用户系统设置确认。
- 工具尚未接入聊天模型 tool_calls 循环：阶段 5 路由时接入，
  WebUI 审批页在阶段 6 完成；当前审批编号通过 `ToolExecutor` 返回值交付。
- 旧版 Office 转换器、OCR 置信度展示、保留策略待后续阶段。
