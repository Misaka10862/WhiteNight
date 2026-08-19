#Uniform review format for personality corpus (v0.1)

All candidate samples must record review decisions in the same format to facilitate review and final user determination.

##Decision

| Decision | Meaning |
|---|---|
| accept | Enter the training set as is |
| reject | delete, no training |
| modify | Resubmit for review after modification |

## Record fields

```json
{
"sample_id": "sha256 first 12 digits",
  "decision": "accept",
  "reason_code": "tone-ok",
"reason_text": "Natural tone, no template",
  "reviewer": "user|assistant",
  "reviewed_at": "2026-08-15T12:00:00Z",
  "modified_text": null
}
```

## reason_code

- `tone-ok` / `tone-bad`: Whether the tone is suitable for Xiaobai.
- `identity-ok` / `identity-bad`: Whether the identity is confusing.
- `fact-ok` / `fact-bad`: Whether the facts and figures are accurate.
- `boundary-ok` / `boundary-bad`: Whether the red line (permissions, keys, real information) is touched.
- `duplicate`: Duplicate with other samples.
- `user-final`: The user’s final judgment on “whether it looks like a noob”.

## Process

1. Automatic verification (`scripts/validate_training_data.py`).
2. Manual/strong model preliminary screening, record-by-record decision.
3. The user makes the final decision on the review set; samples that fail `user-final=accept` are not trained.
4. A versioned manifest is generated for each review, which can be traced together with the model weights.
