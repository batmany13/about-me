---
description: Write the weekly Field Notes & Reflections (commits, events, founder lessons)
argument-hint: [last week | this week | last 2 weeks | the week of Aug 17 | backfill | (empty for last closed week)]
---

Run the **fnr** skill with the following user args.

The skill lives at `.claude/skills/fnr/SKILL.md`.  It resolves natural-language args into ISO weeks, pulls commits across the private repos listed in `fnr/.private/repos.json` plus attended calendar events, writes detailed unscrubbed catchups into each source repo, then publishes a scrubbed public reflection to `fnr/<YYYY-WNN>.md`.  Follow that skill's Steps 0–5 exactly — including reading `fnr/.private/scrub_policy.md` in full before writing anything public.

**User's args:** $ARGUMENTS

If `$ARGUMENTS` is empty, default to the last closed week (the skill's Step 1 default) — not the current in-progress week.

If the resolution is more than 4 weeks, confirm before running.
