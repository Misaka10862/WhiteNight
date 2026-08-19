# Stage 4 Long-term Memory Measurement Report (2026-08-15)

>Rerun: `uv run pytest` (87 passed, 3 skipped, Ollama/OCR is an optional integration test)

## 1. Data model (migration 0004)

- `profile_facts`: structured profile; key/value, confidence, source message, status
  (active/superseded/deleted), conflict status (none/conflicted/resolved).
- `episodic_memories`: episodic memory; content, source, confidence, importance, access count,
  Soft delete time.
- `session_summaries`: rolling summaries (keep latest per session).
- FTS5: `profile_facts_fts` and `episodic_memories_fts` (unicode61),
  Synchronized with additions, deletions and modifications by SQLite triggers; triggers use ordinary `DELETE ... WHERE rowid`
  Instead of FTS5 special command (Python 3.12/3.14 SQLite special insert for `'delete'`
  Return SQL logic error, use DELETE syntax after actual measurement).

## 2. Semantic constraints (verified by the red team)

- The same key and the same value are automatically deduplicated and the highest confidence level is used.
- Same key but different value → Both sides mark `conflicted`; repeat confirmation of a certain value to automatically resolve it.
- edit facts → old values ​​are `superseded` immediately, `list_facts`/retrieval only returns new values.
- Delete → Default list with FTS retrieval immediately becomes invisible and writes audit events without body.
- User manual `resolve` conflict: reserved items take effect, and all others are invalid.

## 3. Extraction and recall

- `RuleBasedMemoryExtractor` (deterministic fallback) and `OllamaMemoryExtractor`
  (Strictly JSON Schema, returns empty if parsing fails, does not block chat).
- `asyncio.create_task` is fetched asynchronously after the main reply; the task reference is held by the ChatService to be GC-proof.
- Recall: FTS5 lexical (rank + LIKE) weight 0.6 + semantic cosine 0.4;
  Episodic memory has a 30-day half-life time decay and access count bonus; automatic touch on retrieval hits.
- downgrade semantic layer to null when `embedding_model` is empty (lexical still works);
  Natural language questions require a small embedding model (loaded on demand).

## 4. API

`/api/v1/memory/facts` CRUD + resolve；`/api/v1/memory/episodes` CRUD；
`/api/v1/memory/extract`、`/retrieve`、`/export?fmt=jsonl|markdown`；
`/api/v1/sessions/{id}/summary` and `/summarize`.

## 5. Actual measurement

- The real Ollama (qwen3-vl:8b) is extracted from "I live in Hangzhou and like walking on rainy days most":
  `Residence: Hangzhou`, `Hobby: Walking on rainy days`, `Calling: Master` + 1 scene memory.
- Lexical recall: Query "Hangzhou" → `Residence: Hangzhou`; "Rainy Day" → Situational memory.
- Export: JSONL contains type/id/source/created_at; Markdown is divided into two sections: file and scene memory.

## 6. Boundary

- The embedding model is not enabled for semantic recall (the configuration is empty), and the embedding model needs to be installed/configured for cross-day natural language questions.
- The backup/restore interface and encrypted backup implementation are completed as planned in Phase 6/10; exports are available in Phase 4.
- Remove audit without body (in line with build plan 10.2).
