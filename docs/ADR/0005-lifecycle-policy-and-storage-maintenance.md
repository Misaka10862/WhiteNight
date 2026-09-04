# ADR-0005: Lifecycle ownership, enforceable delegation and storage maintenance

- Status: Accepted for the 2026-09-04 project review
- Date: 2026-09-04
- Extends ADR-0002 and the request-lifecycle assumptions in ADR-0003

## Context

The review reproduced deterministic defects: one-time approval UI could create a session grant,
stream state could appear under another selected session, incomplete backup coverage omitted resources,
and restore validated database contents after replacement. The old rollback moved in the wrong direction,
while HTTP health checks could not exclude a concurrently running database process. These are program
and contract failures; changing the language model cannot correct them.

## Decision

1. Application lifecycle/composition owns long-lived services. Transport routes delegate orchestration;
   the conversation coordinator owns request identity, session serialization, persisted terminal events
   and cancellation. Page components observe a session/request controller rather than own sockets.
   Restart recovery preserves uncertain outcomes and never silently repeats possible side effects.
2. External work stays behind Provider interfaces. Tool proposals pass through typed parameters,
   deterministic policy and approvals bound to the request's channel/session/parameters. One-time and
   session grants are distinct. Delegate capability checks require demonstrated enforcement: Codex is
   restricted to new read-only tasks, write delegation is refused, and Hermes remains disabled by default.
3. Service and maintenance processes share a canonical database-side advisory lock file that is never
   unlinked. Normal startup takes exclusive access for journal recovery/migration, then retains shared
   access until shutdown. Online backups use shared access; restores and direct migration commands use
   exclusive access. When automatic migration is disabled, startup refuses an unfinished restore
   journal and requires offline recovery. A failed HTTP health probe does not authorize maintenance.
4. Backups remain authenticated WNBK1 containers. A new internal manifest records SQLite/SQLCipher and
   the full managed resource inventory: attachments, QQ files, character assets and stickers. Legacy
   SQLite archives remain readable. SQLCipher snapshots stay encrypted under an independently derived
   recovery key; production database keys never appear in the archive. Cross-backend conversion is rejected.
5. Restoration validates first, stages beside the affected filesystem roots, persists a journal, and
   switches database/WAL/SHM plus resource roots through retained generations. Exceptions restore the
   original generation; startup or the offline recovery command rolls back an uncommitted interrupted
   operation idempotently. Old generations are retained, with no automatic directory wipes. Corrupt
   journals stop recovery and require inspection. Every existing-database migration first verifies a
   snapshot of the same database type, including SQLCipher.
6. Recovery credentials live in Keychain. The CLI supports `generate-key`, hidden-prompt `configure-key`,
   `backup`, `verify`, `preview`, `restore` and journal-only `recover`. No recovery secret is accepted in
   command-line arguments or environment variables. WebUI restore is limited to preview and download;
   applying a restore requires the offline maintenance workflow.

## Consequences

- Local correctness has deterministic regression coverage and no dependency on a more capable model.
- Existing callers retain the backup function signatures and WNBK1 compatibility; callers using old
  recovery-key shell arguments must configure Keychain before using the CLI.
- Locks are advisory: every WhiteNight service/migration/restore entrypoint must participate. Tools
  that open the database independently are outside this coordination contract and must be stopped.
- Retained generations and encrypted SQLCipher scratch files consume disk space. Inspection and any
  eventual user-directed cleanup are separate tasks; maintenance does not erase user directories.
- A full authenticated backup is still required for an operational recovery drill. Verified migration
  snapshots and isolated tests do not imply completed production or 72-hour acceptance.

## Validation

Regression coverage includes scope distinction, request isolation/cancellation/replay, missing managed
resource roots, invalid database rejection before replacement, injected restore failures, interrupted
journal recovery, shared/exclusive lock conflict, legacy archives, SQLCipher key independence and
blocked migration after an invalid safety snapshot. Browser and long-running results are recorded
separately; the final verification record belongs in PROGRESS.md.
