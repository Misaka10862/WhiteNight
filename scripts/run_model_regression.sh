#!/usr/bin/env bash
# 阶段 9 模型回归清单：人格无 prompt 评估 + 既有基础能力回归。
# 需要本机 Ollama 已加载目标模型；默认评估当前 qwen3-vl:8b。
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${MODEL:-qwen3-vl:8b}"
EVAL_FILE="${EVAL_FILE:-evals/persona/golden.jsonl}"

echo "==> Persona evaluation without a system prompt"
uv run scripts/eval_persona.py --model "$MODEL" --eval-file "$EVAL_FILE" --threshold 0.6

echo "==> Ollama contract tests"
WHITENIGHT_TEST_OLLAMA=1 uv run pytest tests/test_ollama_provider.py -q

echo "==> Routing, document, and policy regression tests (no live Ollama)"
uv run pytest tests/test_routing.py tests/test_documents.py tests/test_tool_executor.py -q

echo "MODEL REGRESSION PASSED"
