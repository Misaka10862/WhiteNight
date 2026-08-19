# model/ ——Training configuration and data specification

This directory does not store any model weights, adapters or training corpus (`.gitignore` is excluded).

## Directory convention

```text
model/
├── configs/ # Training/quantization configuration (stage 9)
├── specs/ # Data specifications, review formats, category definitions
├── evals/ # Training side evaluation output (linked with the golden set of warehouse evals/)
├── data/ # Local corpus (not included in Git)
├── weights/ # Local weights and Adapter (not included in Git)
└── runs/ # Training run record
```

## Phase 9 Prerequisites

- Corpus licensing and license review completed (`specs/license_checklist.md`);
- The final judgment process for users on "whether they look like novices" is ready (`specs/review_format.md`);
- Retain untrained baselines, candidate Adapters and complete evaluation results, and support rollback;
- LoRA does not write live user preferences, permission rules, tool lists, or volatile facts.

## Stage 9 Tools

```bash
uv run scripts/validate_training_data.py model/specs/persona_samples.jsonl
uv run scripts/eval_persona.py --model qwen3-vl:8b
uv run scripts/blind_ab.py run --model-a qwen3-vl:8b --model-b <candidate>
bash model/scripts/export_to_ollama.sh # dry-run; --run only executes
```

- Data specifications: `specs/persona_data_spec.md`; samples (synthetic CC0): `specs/persona_samples.jsonl`.
- Training configuration baseline: `configs/qwen3vl_persona_qlora.yaml` (freeze_vit=true).
- Blind test results and training run records are not recorded in Git.
