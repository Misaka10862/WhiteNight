# evals/ - golden evaluation set

Created as per Build Plan Section 17.2, each subdirectory contains `README.md` (scoring criteria) and use case files.

```text
evals/
├── persona/ # Small talk, comfort, intimacy, serious work and boundary scenes
├── routing/ # Ontology, Hermes, Codex, user-specified and risk upgrade scenarios
├── memory/ # Fact addition, conflict, correction, forgetting, time decay and cross-session recall
├── documents/ # Text PDF, scanned PDF, DOCX, XLSX, PPTX, picture and code directory
└── security/ # Prompt injection, path bypass, batch deletion, dangerous commands, approval replay, non-owner QQ
```

Phase 0 only establishes catalog conventions; use cases are added with corresponding phases and incorporated into CI's non-model regression threshold.
