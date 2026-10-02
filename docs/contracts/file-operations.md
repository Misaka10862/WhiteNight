# File operations and approval selection

`file.find` accepts `entry_type: file | directory | any` (default `file`).
Candidates include their entry type. `partial`, `timed_out`, `truncated`, and
`errors` describe incomplete searches; incomplete results do not establish absence.
Explicit move destinations are resolved as directories before searching by name.

Approval messages are parsed before model invocation in both Web and OneBot.
Whitespace before an approval code is optional. Plain approval selects one current
request; the all-approval command freezes all presented requests in the current
session, channel and recipient. Each request retains its original policy level,
one-time code, expiry and parameter binding. No future request inherits consent.

`POST /api/v1/approvals/batch` accepts:

```json
{"session_id": "current-session", "codes": ["code1", "code2"], "allow": true}
```

It returns `ok`, `reason`, and `results`, each with `code`, `tool_name` when known,
`status`, and `message`. Statuses include `succeeded`, `approved` (authorization
only), `running` (delegated), `rejected`, `invalid`, `unavailable`, `failed`, and
`blocked`. Failure stops later execution conservatively; completed effects are
not rolled back. The existing single-approval endpoint remains available.
Web endpoints cannot authorize OneBot requests; use the original QQ conversation.

Exact pending operations reuse an approval and its durable pending-call ID.
File paths use filesystem identity rather than unconditional lowercasing.
A changed pending move for the same source supersedes its old approval. Atomic
pending-to-running claims and one-time authorization consumption prevent concurrent
execution. Interrupted work is reconciled with audit receipts at startup. Without
a conclusive receipt, source/destination existence is recorded for review and
automatic re-execution is blocked. No batch deletion capability is introduced.

`GET /api/v1/system/file-access` reports the actual service PID, interpreter,
dedicated application path and settings URL. It does not probe protected folders.
`POST /api/v1/system/file-access/probe` performs read-only directory enumeration
from that service process. Results distinguish denied, missing/error and readable
locations; writable means an OS permission flag, not a successful write test.
