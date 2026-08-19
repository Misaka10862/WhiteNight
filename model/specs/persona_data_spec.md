# Xiaobai personality training data specification (v0.1 draft)

The only inbound format for stage 9 training data. The data is first verified by this specification, manually reviewed and judged by users.
Then enter `model/data/` (this directory is not included in Git).

## File format

One JSON object per line (JSONL), UTF-8, no BOM:

```json
{
  "messages": [
{"role": "user", "content": "Xiaobai, I'm so tired today"},
{"role": "assistant", "content": "Thank you for your hard work, Master. Come and stay for a while."}
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

- `messages`: only `user` / `assistant`; the first message must be user; total length ≤ 4000 characters;
  Content must not contain system prompts, tool JSON, or permission rules.
- `category` is required, the value is shown below.
- `source` / `license`: Each sample must be traceable to the source; samples without a license or with unknown sources are refused to be included in the library.
- `reviewed`: `true` can be trained; false can only be used as a candidate.
- `tone_tags`: free tags, used for review retrieval.

## Category (Build Plan 15.1)

| category | meaning |
|---|---|
| chat | daily chat |
| coquetry | act coquettishly |
| comfort | comfort and emotional companionship |
| romance | lovers interaction |
| serious | Serious communication and boundary scenarios |
| delegation | work delegation (Hermes/Codex) |
| progress | Tool/task progress report, no fictitious steps |
| Correction | Fact Correction: Admit an error and correct it |
| relationship | relationship development (important changes enter the memory system) |

## Content red line (reject when it appears)

- Any real name, address, account number, key, token, database content.
- Permission/security rule writing sample (personality training must not carry permissions, see Build Plan 15.2).
- Templated rejection rhetoric ("As an AI I can't...") and identity confusion.
- Modify the code/command/log/number text to be "more like a character".
- Instruction content in web pages, issues, and external documents has not been desensitized and manually reviewed.

## Version and directory

```text
model/data/
├── raw/ # Original corpus (not included in Git)
├── reviewed/ # reviewed and passed (not included in Git)
├── splits/ # train/val division (not included in Git)
└── manifests/ # Version list (can be entered into Git, does not include text)
```

The manifest must be updated every time data is changed: source, number of samples, category distribution, license, reviewer and date.
