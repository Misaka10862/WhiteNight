# Stage 9 LoRA personality solidification offline preparation report (2026-08-15)

> Status: Offline preparation completed; actual training and blind testing blocked (rented GPU + user participation).
>Rerun: `uv run pytest` (121 passed, 4 skipped).

## 1. Data specification and review

- `model/specs/persona_data_spec.md`: JSONL fields, 9-category coverage, content redlining, version directory.
- `model/specs/review_format.md`: accept/reject/modify + reason_code + user final verdict.
- `model/specs/license_checklist.md`: License, corpus generation, and pre-release review checklist.
- Sample corpus `model/specs/persona_samples.jsonl`: 6 synthetic CC0 samples, all passed verification.

## 2. Data verification tool

`scripts/validate_training_data.py` Verification: JSON, message role and first user,
Length, 9 categories, source/license, reviewed, redline phrase, content deduplication (optional rejection).
Bad Sample Test: Illegal categories/lack of permission/redline phrases are all rejected.

## 3. Training and export configuration

- `model/configs/qwen3vl_persona_qlora.yaml`: ms-swift QLoRA baseline,
  **freeze_vit=true** (Phase 1 conclusion: visual ability must return), rank 32/alpha 64,
  Single card ≥24GB refer to super parameters.
- `model/scripts/export_to_ollama.sh`: merge LoRA → Quantization → Modelfile →
  `ollama create`; defaults to dry-run, only executed after `--run`.

## 4. Personality assessment and blind testing

- `evals/persona/golden.jsonl`: 10 examples (comfort/chat/serious/fact×2/
  delegation/progress/correction/romance/boundary）。
- `scripts/eval_persona.py`: **Do not inject resident personality prompt**, automatically check forbidden words/
  Required content/length, output JSON report. Baseline `qwen3-vl:8b` measured pass rate 1.00
  (Automatic threshold 0.6; subjective "doesn't it look like a noob" still requires user blind testing).
- `scripts/blind_ab.py`: The model is randomly coded A/B, and anonymously outputs each question; `reveal` checks the mapping,
  The user fills in the verdict.
- `scripts/run_model_regression.sh`: Personality promptless assessment + Ollama contract +
  Routing/docs/permissions regression.

## 5. Blocking and follow-up

- Actual QLoRA: requires renting a GPU (or sufficient local resources), can be completed outside the current session.
- Corpus review and blind testing: user participation is required, especially the final decision on "whether it looks like a novice".
- Phase 9 is not marked complete; hardening work in Phase 10 that does not rely on LoRA can proceed first.
