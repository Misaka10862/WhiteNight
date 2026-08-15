# ADR-0002：本地优先安全边界 —— 本机监听、Keychain 与加密存储

- 状态：已接受
- 日期：2026-08-15

## 背景

构建计划第 9 节要求：WebUI 与服务仅监听 `127.0.0.1`；密钥只进入 macOS Keychain；
本地单用户使用 SQLite WAL + SQLCipher；任何文档或网页指令不得覆盖系统约束。

## 决策

1. **网络边界**：API 默认绑定 `127.0.0.1`；CORS 仅放行
   `http://127.0.0.1:5173` 与 `http://localhost:5173`（Vite 开发源）。
   局域网/公网访问属于明确排除项。
2. **凭据**：数据库主密钥与服务凭据通过 `credentials.keychain` 接口访问，
   生产后端为 `/usr/bin/security` 的通用密码条目；`memory` 后端仅限测试/CI。
   应急恢复流程允许 `WHITENIGHT_DATABASE_KEY` 环境变量，但禁止落盘与日志。
3. **存储**：`sqlite://` 用于开发/测试；`sqlcipher://` 为生产数据库，
   主密钥经 PRAGMA 参数注入，绝不写入连接串。密钥驱动 `sqlcipher3-binary`
   作为可选 extra 安装。
4. **日志**：根 logger 统一挂载脱敏过滤器，覆盖 token/secret/password/authorization
   等形态；生产日志可切换 JSON 行。
5. **不可信输入**：聊天内容、附件、网页和文档永远不能修改 Settings、
   SOUL/AGENTS 规则或权限引擎；对应防线在后续阶段由 policy 包强制。

## 后果

- 优点：从第一天起满足本地优先与凭据不落盘要求。
- 代价：SQLCipher 的构建/升级依赖额外测试；Keychain 在 CI 中必须使用内存后端或 mock。
- 回退：若 `sqlcipher3-binary` 在 macOS 新版本失效，替换为 SQLite 文件级加密层，
  `storage.engine` 对外接口不变。
