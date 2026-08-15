# model/ —— 训练配置与数据规范

本目录**不存储**任何模型权重、Adapter 或训练语料（`.gitignore` 已排除）。

## 目录约定

```text
model/
├── configs/     # 训练/量化配置（阶段 9）
├── specs/       # 数据规范、审阅格式、类别定义
├── evals/       # 训练侧评估输出（与仓库 evals/ 的黄金集联动）
├── data/        # 本地语料（不入 Git）
├── weights/     # 本地权重与 Adapter（不入 Git）
└── runs/        # 训练运行记录
```

## 阶段 9 前置要求

- 语料许可与许可证复核完成（`specs/license_checklist.md`）；
- 用户对“是否像小白”的最终裁决流程已就绪（`specs/review_format.md`）；
- 保留未训练基线、候选 Adapter 与完整评估结果，支持回滚；
- LoRA 不写入实时用户偏好、权限规则、工具清单或易变化事实。

## 阶段 9 工具

```bash
uv run scripts/validate_training_data.py model/specs/persona_samples.jsonl
uv run scripts/eval_persona.py --model qwen3-vl:8b
uv run scripts/blind_ab.py run --model-a qwen3-vl:8b --model-b <candidate>
bash model/scripts/export_to_ollama.sh          # dry-run；--run 才执行
```

- 数据规范：`specs/persona_data_spec.md`；示例（合成 CC0）：`specs/persona_samples.jsonl`。
- 训练配置基线：`configs/qwen3vl_persona_qlora.yaml`（freeze_vit=true）。
- 盲测结果与训练运行记录不入 Git。
