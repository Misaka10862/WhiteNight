# Personality and prompt compilation contract (v1)

## Identity scope

- A session is permanently bound to one character and the single local-user Persona.
- Editing a character, Persona, prompt profile, or lorebook affects the next generation in all
  bound sessions. Every edit creates an immutable revision; generation traces identify the
  revisions and hashes actually used.
- New Web/QQ sessions default to the Xiaobai character. QQ role switching uses deterministic
  server-side list and switch commands that rotate to a new session.

## Character Card compatibility

- Import/export accepts public Character Card v2 (`chara_card_v2`, `2.0`) and v3
  (`chara_card_v3`, `3.x`) JSON.
- PNG cards use standard `tEXt` chunks: `ccv3` takes precedence over `chara`; export writes both.
- Unknown extension data is retained for round trips but is never evaluated or executed.
- Cards are bounded and type-validated before storage. Character and lorebook removal is archival.

## Prompt order and trust

The compiler order is: pinned safety kernel, main prompt, world-before, Persona, character fields,
world-after, examples, author note, rolling summary, scoped memory, recent history/depth inserts,
post-history instructions, and pinned trusted runtime constraints.

Only an allowlist of inert macros is expanded. Character cards, Persona, lorebooks, memories,
attachments, and custom blocks are data and cannot modify policy, approval, audit, or tool schemas.
`kernel` and runtime blocks cannot be created or overridden through the public API.

## Lorebook semantics

The server supports constant and keyword activation, secondary boolean logic, bounded regex,
recursion, scan depth, reproducible probability, groups, sticky/cooldown/delay state, generation
triggers, prompt/depth/example/author-note positions, and named outlets. Regex, recursion, pattern
length, scan text, state duration, and entry counts have hard bounds. `ignore_budget` bypasses only
the lorebook soft budget, never request or security limits.

## Context and memory

- A configured local `tokenizer.json` enables exact text-token accounting and deterministic
  trimming. Without it, counts are unavailable and the model Provider enforces context.
- Facts and episodes are isolated by character and reserved local-user namespace. Conflicted,
  superseded, and deleted facts are never injected.
- Summaries are session-scoped. Extraction uses a durable sequence checkpoint; summaries and
  retrieved memory are injected as sourced data, not instructions.
