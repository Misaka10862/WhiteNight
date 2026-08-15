#!/usr/bin/env bash
# 将训练好的 LoRA Adapter 合并/量化并导入 Ollama（阶段 9）。
# 默认 dry-run：只打印将执行的命令。--run 才真正执行。
# 需要：ms-swift、可用 GPU/内存、Ollama 与量化工具链。
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN_DIR="${RUN_DIR:-model/runs/persona-v1}"
CKPT_DIR="${CKPT_DIR:-$RUN_DIR/checkpoint-best}"
MERGED_DIR="${MERGED_DIR:-$RUN_DIR/merged-q8}"
QUANT_BITS="${QUANT_BITS:-8}"
MODEL_TAG="${MODEL_TAG:-qwen3-vl-whitenight:persona-v1}"

echo "==> 1. ms-swift 合并并量化（以本机 ms-swift 文档为准）"
echo "swift export \\"
echo "  --ckpt_dir '$CKPT_DIR' \\"
echo "  --merge_lora true \\"
echo "  --quant_bits $QUANT_BITS \\"
echo "  --output_dir '$MERGED_DIR'"

MODELFILE="$RUN_DIR/Modelfile"
echo "==> 2. Modelfile（目标 $MODELFILE）"
echo "FROM $MERGED_DIR"
echo "PARAMETER temperature 0.7"
echo "PARAMETER top_p 0.95"

echo "==> 3. 验证（不注入人格 system prompt）"
echo "uv run scripts/eval_persona.py --model '$MODEL_TAG' --eval-file evals/persona/golden.jsonl"

if [[ "${1:-}" == "--run" ]]; then
  mkdir -p "$RUN_DIR"
  swift export \
    --ckpt_dir "$CKPT_DIR" \
    --merge_lora true \
    --quant_bits "$QUANT_BITS" \
    --output_dir "$MERGED_DIR"
  cat > "$MODELFILE" <<EOF
FROM $MERGED_DIR
PARAMETER temperature 0.7
PARAMETER top_p 0.95
EOF
  ollama create "$MODEL_TAG" -f "$MODELFILE"
  echo "IMPORTED: $MODEL_TAG"
fi
