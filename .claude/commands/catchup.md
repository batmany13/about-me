---
description: Catch up on this repo — extract entities from a week, then summarize from them
argument-hint: [last week | this week | last 2 weeks | all | backfill | the week of Aug 24 | (empty for last closed week)]
---

Run the **catchup** skill with the following user args.

The skill lives at `.claude/skills/catchup/SKILL.md`. It runs against **this
repo** (cwd) unless the user names another. Two passes, in order: Step 3 extracts
durable entities into `<output.dir>/entities/`, Step 4 writes the week's summary
*from those entities*. Don't skip pass 1 and write prose straight from the commit
log — the entity store is the record and the summary is derived from it.

Before creating any entity, run `entities.py list` and reuse the id of anything
this week continues. A new id for continuing work silently forks the history,
which is the one failure here that leaves no trace.

Categories are fixed: **Meeting / Partner Notes**, **Technical Notes**, **Other**
— with `Corrections` rendered as a lens across all three.

**User's args:** $ARGUMENTS

If `$ARGUMENTS` is empty, default to the **last closed week**, not the current
in-progress one.

If the resolution is more than 5 weeks, confirm before running. Backfill runs
oldest first.
