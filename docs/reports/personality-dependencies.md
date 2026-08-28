# Personality and prompt dependency review

Date: 2026-08-26

| Dependency | Locked / requested version | Upstream | License | Compatibility conclusion |
|---|---:|---|---|---|
| `regex` | `2026.7.19` | `mrabarnett/mrab-regex` `0525affc5309f8d53deac351e4926b11eb8a282c` | Apache-2.0 AND CNRI-Python | Compatible; used only for bounded keyword regex matching with per-call timeout. |
| `tokenizers` | `0.23.1` | `huggingface/tokenizers` `7f1623b90b5adfb9bc327d4c3468d2f70bbce262` | Apache-2.0 | Compatible; loads a user-supplied local `tokenizer.json`; no model weights are committed. |
| `png-chunk-text` | `1.0.0` | `hughsk/png-chunk-text` `19b674eafc5de60e3992db14c2b34fcdfc80ff18` | MIT | Compatible; independent PNG `tEXt` codec used for CCv2/V3 metadata. |
| `png-chunks-extract` | `1.0.0` | `hughsk/png-chunks-extract` `d098d583f3ab3877c1e4613ec9353716f86e2eec` | MIT | Compatible; independent structured PNG chunk parser. |
| `png-chunks-encode` | `1.0.0` | `hughsk/png-chunks-encode` `24290360e008a9b1504557ec6344bd4a93e25896` | MIT | Compatible; independent structured PNG chunk encoder. |

No SillyTavern AGPL source file is copied or linked. Character Card behavior is implemented
against the public CCv2/V3 wire format and project-owned contract tests. Exact resolved package
integrity data is recorded by `uv.lock` and `apps/web/package-lock.json`.
