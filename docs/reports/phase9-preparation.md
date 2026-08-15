# 阶段 9 LoRA 人格固化 离线准备报告（2026-08-15）

> 状态：离线准备完成；实际训练与盲测受阻（租用 GPU + 用户参与）。
> 复跑：`uv run pytest`（121 passed, 4 skipped）。

## 1. 数据规范与审阅

- `model/specs/persona_data_spec.md`：JSONL 字段、9 类覆盖、内容红线、版本目录。
- `model/specs/review_format.md`：accept/reject/modify + reason_code + 用户最终裁决。
- `model/specs/license_checklist.md`：许可、生成语料、发布前复核清单。
- 示例语料 `model/specs/persona_samples.jsonl`：6 条合成 CC0 样本，全部通过校验。

## 2. 数据校验工具

`scripts/validate_training_data.py` 校验：JSON、消息角色与首条 user、
长度、9 类 category、source/license、reviewed、红线短语、内容去重（可选拒绝）。
坏样本测试：非法类别/缺许可/红线短语均被拒绝。

## 3. 训练与导出配置

- `model/configs/qwen3vl_persona_qlora.yaml`：ms-swift QLoRA 基线，
  **freeze_vit=true**（阶段 1 结论：视觉能力必须回归），rank 32/alpha 64，
  单卡 ≥24GB 参考超参。
- `model/scripts/export_to_ollama.sh`：合并 LoRA → 量化 → Modelfile →
  `ollama create`；默认 dry-run，`--run` 才执行。

## 4. 人格评估与盲测

- `evals/persona/golden.jsonl`：10 例（comfort/chat/serious/fact×2/
  delegation/progress/correction/romance/boundary）。
- `scripts/eval_persona.py`：**不注入常驻人格 prompt**，自动检查禁用词/
  必备内容/长度，输出 JSON 报告。基线 `qwen3-vl:8b` 实测通过率 1.00
  （自动阈值 0.6；主观“像不像小白”仍需用户盲测）。
- `scripts/blind_ab.py`：模型随机打码 A/B，逐题匿名输出；`reveal` 查看映射，
  用户填写裁决。
- `scripts/run_model_regression.sh`：人格无 prompt 评估 + Ollama 契约 +
  路由/文档/权限回归。

## 5. 阻塞与后续

- 实际 QLoRA：需要租用 GPU（或本地足够资源），非当前会话可完成。
- 语料审阅与盲测：需要用户参与，尤其“是否像小白”最终裁决。
- 阶段 9 未标记完成；阶段 10 中不依赖 LoRA 的加固工作可先行。
