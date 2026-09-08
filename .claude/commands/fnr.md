---
description: Write the weekly Field Notes & Reflections — the machine writes the whole week, then asks one question per turn
---

Run the **fnr** skill with the following user args.

The skill lives at `.claude/skills/fnr/SKILL.md`.  It resolves the week (default: the last closed one), checks that each source repo's `catchup` has run and rolls them up from the private repo, then writes the whole weekly in one pass — the unredacted draft, the scrubbed public candidate with every owner block wrapped in `<!-- fnr:key -->` markers, and the delta between them.  Only then does it ask the owner **one question per turn** (`reference/questions.md`), showing the unredacted and scrubbed section together, and writes each answer straight into the public file, verbatim, through `scripts/state.py`.  The sections, the owner's blocks, the required block and the questions come from `fnr/.private/fnr.config.json`; every question is optional except the one the config marks required.  If a `drafts/<week>.state.json` exists, resume at the next pending question — that is how a reply to the current question lands.  Read `fnr/.private/scrub_policy.md` in full before writing anything public; never publish without the required block; never edit an answered block by hand.

Args: $ARGUMENTS
