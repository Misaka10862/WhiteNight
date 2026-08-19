# First version release acceptance list

Build Plan Section 18 Check Items. `[ ]` means waiting for user/long-running confirmation.

- [x] WebUI stabilizes chat, recognizes images, processes agreed documents and restores historical sessions (actual test in phase 2/3/6)
- [x] Correctly remember, display, modify and delete user preferences and episodic memory (Phase 4)
- [x] Search results include sources; web content cannot trigger unauthorized tool operations (Phase 3)
- [x] Simple tasks, Hermes tasks and Codex tasks are routed correctly by rules (Phase 5 golden set)
- [ ] Hermes/Codex task progress is visible, abortable, resumable or explicitly failed
(Progress events have been implemented; Hermes real tasks are waiting for users to log in to Provider, and Codex real tasks are waiting for quota confirmation)
- [x] All portals share the same identity, session, memory, task and permission records (Phase 2/4/5/8)
- [x] QQ Only the owner account can trigger tools and process approvals (Phase 8 contract testing)
- [x] Active QQ messages subject to frequency, silent period and pause status (Phase 7; real QQ sending pending NapCat)
- [x] Deleting a single file will go to the trash by default; batch deletion cannot be performed by the Agent (Phase 3 Red Team)
- [x] WebUI and services only listen natively; credentials are not written in clear text to logs or configuration (ADR-0002 + desensitization)
- [ ] No repeated recovery/lost tasks/string memory on restart, sleep wake-up and network interruption
(Restart and resume actual measurement; sleep wake-up and long-term network interruption will be tested for 72 hours)
- [ ] 72 hours of continuous operation without blocking failures and obvious memory leaks (script ready, to be executed)
- [ ] When there is no resident personality prompt, the final LoRA model passes the user personality blind test (stage 9 is pending for GPU/user)

## Must be done before publishing

1. `./scripts/check.sh` + `uv run mypy src/whitenight` All green.
2. Backup → Migration drill → Recovery drill once (real data directory).
3. `uv run scripts/run_72h.py --hours 72`。
4. The user completes the LoRA blind test and selects the default model; continue to use SOUL.md before completion.
5. GitHub push (first `gh auth refresh -s workflow`).
