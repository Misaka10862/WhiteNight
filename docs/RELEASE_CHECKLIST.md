# First-version release acceptance

Current review: 2026-09-04. A checked implementation item means code and automated coverage exist;
it does not certify live channels, long-running operation or a published release.

## Implementation and automated coverage

- [x] Chat request identity, session isolation, terminal-event persistence, cancellation and restart handling.
- [x] WebUI stream ownership, approval-scope distinction, IME behavior and document-upload client contracts.
- [x] Typed tool parameters, bound approvals, one-time consumption, policy enforcement and batch-delete refusal.
- [x] Task outcomes preserve uncertainty; unsafe or unknown-effect work is not automatically retried.
- [x] Memory maintenance is bounded, resumable and isolated from unavailable embedding backends.
- [x] SQLite/SQLCipher backup verification and restore; retained database/resource generations; interruption recovery.
- [x] Shared service/exclusive maintenance locks, including direct Alembic commands.
- [x] WebUI backup creation, verification, preview and download; offline restore procedure.
- [x] Local checks include strict mypy and frontend behavior tests without installing dependencies.

## Evidence required for release

- [x] Record the final `./scripts/check.sh` result: 332 Python tests passed, 4 optional integrations skipped,
  and 13 frontend behavior tests passed; see the dated project-review report.
- [x] Record isolated browser interaction and desktop/narrow-window screenshots for the revised workflows.
- [ ] Complete a new 72-hour report with healthy required components, complete sampling and no unexplained
  task stalls or memory growth. A shorter run only validates the monitoring tool.
- [ ] Exercise sleep/wake and network interruption, checking duplicate replies, request/task terminal states,
  recovery and memory isolation; record timing and results.
- [ ] Perform an explicitly scheduled production backup → migration → recovery drill with a verified backup.
  Isolated test databases do not replace this operational acceptance step.
- [ ] Validate current-version real QQ owner-only delivery and proactive scheduling when external delivery
  is authorized. Historical NapCat success is not a fresh current-version result.
- [ ] Validate an explicitly requested real Codex read-only task, including progress and verified cancellation,
  before advertising that live capability as accepted.

## Intentionally unavailable or paused

- Codex write delegation is rejected until a Provider demonstrates per-action policy/approval enforcement.
  A read-only task must not resume an older thread with unverified sandbox permissions.
- Hermes remains disabled by default. Authentication alone does not establish a safe task/approval contract.
- LoRA training and personality blind testing remain paused by user decision. They are prerequisites only
  for a future LoRA-specific release claim, not a reason to silently resume paid training.
- GitHub Actions remains disabled by project decision. No workflow-scope refresh is required merely to
  deliver this review; hosted automation must not be re-enabled as an incidental fix.

## Final delivery

- [x] Preserve unrelated user work; record the final verification results and remaining live-test limitations.
- Delivery requires one English commit and remote revision verification before reporting completion.
  The commit identifier and remote state are determined by Git after this checklist is recorded.
