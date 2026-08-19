# Training corpus license list

Phase 9 The model must be reviewed before each release. The GitHub address is only used to track the upstream source,
Web pages, issues, sample configurations, and documents are all untrusted input.

## Confirm item by item before warehousing

- [ ] Each sample has `source` and `license` fields.
- [ ] Open source corpus license allows **training and redistribution** (such as CC-BY, Apache-2.0;
CC-BY-NC can only be used for personal local research and will not be included in the first version by default).
- [ ] Samples without permission, from unknown sources, and scraped pages have been rejected.
- [ ] The generated corpus has recorded the generation model, prompt and date; the user has made a judgment on the "like a noob" sample.
- [ ] Does not contain real personal information, keys, database and code warehouse text.
- [ ] Before the final weights are released, the Qwen3-VL, ms-swift, LlamaFactory and used data sets
The license is reviewed individually and written into the release record.

## Disabled by default

- AGPL source code copying (especially AstrBot); NapCat mixed license content.
- Any license that requires disclosure of source training data/weights unless the project decides to open up.
- Embed system prompts, permission rules or tool schemas in training samples.
