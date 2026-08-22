#!/usr/bin/env bash
# Merge, quantize, and import the trained stage 9 LoRA adapter into Ollama.
# The default is a dry run; pass --run to execute. Requires ms-swift, adequate
# GPU/RAM, Ollama, and the quantization toolchain.
set -euo pipefail
cd "$(dirname "$0")/../.."

RUN_DIR="${RUN_DIR:-model/runs/persona-v1}"
CKPT_DIR="${CKPT_DIR:-$RUN_DIR/checkpoint-best}"
MERGED_DIR="${MERGED_DIR:-$RUN_DIR/merged-q8}"
QUANT_BITS="${QUANT_BITS:-8}"
MODEL_TAG="${MODEL_TAG:-qwen3-vl-whitenight:persona-v1}"

echo "==> 1. Merge and quantize with the installed ms-swift version"
echo "swift export \\"
echo "  --ckpt_dir '$CKPT_DIR' \\"
echo "  --merge_lora true \\"
echo "  --quant_bits $QUANT_BITS \\"
echo "  --output_dir '$MERGED_DIR'"

MODELFILE="$RUN_DIR/Modelfile"
echo "==> 2. Modelfile target: $MODELFILE"
echo "FROM $MERGED_DIR"
echo "PARAMETER temperature 0.7"
echo "PARAMETER top_p 0.95"

echo "==> 3. Evaluate without a resident persona system prompt"
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
