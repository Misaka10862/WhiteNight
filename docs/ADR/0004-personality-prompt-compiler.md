# ADR-0004: Native personality and prompt compiler

## Status

Accepted on 2026-08-26.

## Decision

WhiteNight implements its own typed character, Persona, lorebook, prompt compiler, token counter,
and memory-recall integration behind Core interfaces. It supports the public CCv2/V3 wire format
and selected observable SillyTavern behavior, but copies or links no SillyTavern AGPL source.

The non-overridable safety kernel and trusted runtime constraints remain outside editable prompt
profiles. Imported extensions are inert data. Real-world actions continue through the existing
typed tools, policy engine, approvals, and audit services.

Independent MIT PNG chunk packages and Apache-compatible Python packages are reviewed in
`docs/reports/personality-dependencies.md`. Model weights, tokenizer assets, cards, avatars,
databases, and generation data stay outside Git.

## Consequences

- WhiteNight remains MIT and does not require a SillyTavern process.
- Roleplay configuration becomes richer while execution authority remains deterministic.
- Live edits need revision records and generation manifests for reproducibility.
- Advanced SillyTavern script/plugin behavior is deliberately unsupported.
