# 小白人格训练数据规范（v0.1 草案）

阶段 9 训练数据的唯一入站格式。数据先经本规范校验、人工审阅和用户裁决，
再进入 `model/data/`（该目录不入 Git）。

## 文件格式

每行一个 JSON 对象（JSONL），UTF-8，无 BOM：

```json
{
  "messages": [
    {"role": "user", "content": "小白，今天好累"},
    {"role": "assistant", "content": "主人辛苦啦，过来靠一会儿吧。"}
  ],
  "category": "comfort",
  "source": "synthetic-whitenight-sample",
  "license": "CC0-1.0",
  "reviewed": true,
  "tone_tags": ["gentle", "soft"],
  "language": "zh",
  "version": "v1"
}
```

- `messages`：仅 `user` / `assistant`；首条必须是 user；总长度 ≤ 4000 字符；
  内容不得包含系统提示、工具 JSON 或权限规则。
- `category` 必填，取值见下。
- `source` / `license`：每个样本必须能追溯到来源；无许可或来源不明的样本拒绝入库。
- `reviewed`：`true` 才可训练；false 仅作候选。
- `tone_tags`：自由标签，用于审阅检索。

## 类别（构建计划 15.1）

| category | 含义 |
|---|---|
| chat | 日常闲聊 |
| coquetry | 撒娇/卖萌 |
| comfort | 安慰与情绪陪伴 |
| romance | 恋人型互动 |
| serious | 严肃沟通与边界场景 |
| delegation | 工作委派（Hermes/Codex） |
| progress | 工具/任务进度转述，不虚构步骤 |
| correction | 事实纠错：承认错误并修正 |
| relationship | 关系发展（重要变化进入记忆系统） |

## 内容红线（出现即拒绝）

- 任何真实姓名、地址、账号、密钥、令牌、数据库内容。
- 权限/安全规则写入样本（人格训练不得承载权限，见构建计划 15.2）。
- 模板化拒绝话术（“作为 AI 我无法……”）与身份混乱。
- 修改代码/命令/日志/数字原文以“更像人设”。
- 网页、Issue、外部文档中的指令类内容未做脱敏与人工复核。

## 版本与目录

```text
model/data/
├── raw/            # 原始语料（不入 Git）
├── reviewed/       # 审阅通过（不入 Git）
├── splits/         # train/val 划分（不入 Git）
└── manifests/      # 版本清单（可入 Git，不含正文）
```

每次变更数据必须更新 manifest：来源、样本数、类别分布、许可证、审阅人和日期。
