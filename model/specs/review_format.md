# 人格语料统一审阅格式（v0.1）

所有候选样本必须用同一格式记录审阅决定，方便回溯和用户最终裁决。

## 决定

| 决定 | 含义 |
|---|---|
| accept | 原样进入训练集 |
| reject | 删除，不得训练 |
| modify | 修改后重新提交审阅 |

## 记录字段

```json
{
  "sample_id": "sha256 前 12 位",
  "decision": "accept",
  "reason_code": "tone-ok",
  "reason_text": "口吻自然，无模板化",
  "reviewer": "user|assistant",
  "reviewed_at": "2026-08-15T12:00:00Z",
  "modified_text": null
}
```

## reason_code

- `tone-ok` / `tone-bad`：口吻是否符合小白。
- `identity-ok` / `identity-bad`：身份是否混乱。
- `fact-ok` / `fact-bad`：事实与数字是否准确。
- `boundary-ok` / `boundary-bad`：是否触碰红线（权限、密钥、真实信息）。
- `duplicate`：与其他样本重复。
- `user-final`：用户对“是否像小白”的最终裁决。

## 流程

1. 自动校验（`scripts/validate_training_data.py`）。
2. 人工/强模型初筛，逐条记录决定。
3. 用户在审阅集上做最终裁决；未通过 `user-final=accept` 的样本不训练。
4. 每次审阅生成版本化 manifest，与模型权重一起可回溯。
