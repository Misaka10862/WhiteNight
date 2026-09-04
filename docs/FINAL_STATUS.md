# WhiteNight current status (2026-09-04)

This is the current acceptance summary. [PROGRESS.md](PROGRESS.md) records implementation and
final verification evidence; dated reports in [reports/](reports/) remain historical evidence.
A previous successful run or an old "in progress" entry does not certify the current build.

## Implemented and covered by automated checks

- Core chat has durable request identities, per-session serialization, cancellation, structured
  attachment receipts, and correlated event envelopes. The WebUI keeps streams separate across
  sessions and page changes, refreshes history after termination, and protects IME confirmation.
- Approval scope is selected explicitly. A one-time approval does not create a session grant;
  session grants remain limited to eligible low-risk operations. Tool arguments, channel identity,
  parameters and approval consumption are checked before execution.
- Task state records preserve uncertain outcomes and cancellation failures. Automatic replay of
  work with unknown effects is refused; the dashboard only offers retries for failed read-only tasks.
- Memory extraction and embedding maintenance have bounded background execution and persistent
  progress/cache metadata. Lexical retrieval remains available when embeddings are unavailable.
- Backups cover the database plus attachments, QQ files, character assets and stickers. SQLite and
  SQLCipher paths are tested; restore uses an exclusive maintenance lock, retained generations and
  a recoverable journal. The WebUI supports create, verify, preview and download; restore is offline.
- The local gate runs Ruff, strict mypy, Python tests, frontend behavior tests, TypeScript/Vite,
  tracked-secret checks and the technical-English audit. Dependency installation is a separate step.
- The stability monitor records component health, service memory, task stalls and sampling gaps.
  A short tool test is not a 72-hour acceptance result.

## Current evidence boundaries

| Item | Current status |
|---|---|
| Automated implementation checks | 332 Python tests passed, 4 optional integrations skipped; 13 frontend behavior tests passed; complete local gate passed |
| Real browser interaction and narrow viewport | Isolated fixture acceptance completed; desktop/narrow screenshots and observed scenarios are recorded in the project-review report |
| Full 72-hour run, sleep/wake and sustained network outage | Not completed for this revision; requires a new dated report |
| Production backup/migration/restore drill | Isolated automated tests exist; no production data was restored during this review |
| Real QQ delivery and proactive messages | Historical deployment evidence exists; no fresh external messages were sent for this review |
| Codex delegation | Explicit `/codex`, newly created read-only sandbox tasks only; real current-version task validation remains separate |
| Codex write delegation | Refused because a tested per-action WhiteNight policy bridge is unavailable |
| Hermes delegation | Disabled by default; endpoint/authentication and per-action capability validation remain incomplete |
| LoRA training and blind test | Intentionally paused; prompt-based character/persona support remains available |
| GitHub Actions | Intentionally disabled since 2026-08-22; restoring hosted automation requires a project decision |

## Historical evidence

The 2026-08-15 phase reports describe the then-current local model, real QQ link, backup drills,
and the start of an earlier stability inspection. Later August/September progress entries describe
Provider, visual-input, attachment and sticker repairs. These records must retain their dates;
none establishes that an old monitor is still running or that the present runtime uses that model.

## Delivery status

The user authorized one final commit and push after verification. Git history and remote revision
comparison provide the delivery identifier; operational release acceptance remains separate.
Use [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the remaining acceptance gates.
