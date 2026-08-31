---
description: Merge every repo's weekly catchup into one cross-repo view (private)
argument-hint: [last week | this week | 2026-W35 | the week of Aug 24 | (empty for last closed week)]
---

Run the **rollup** skill with the following user args.

The skill lives at `.claude/skills/rollup/SKILL.md`. It reads each registered
repo's week record and entities — produced by the `catchup` skill in that repo —
and merges them into one view. It never walks a git log itself: a repo missing a
week record needs `catchup` run there, not a second derivation here.

Two rules that are not optional. **Repo names live in the private registry, not
in this repo** — refer to repos by role and resolve names at run time. And
**output is private**: write to `fnr/.private/rollups/<week>.md`, never to a
tracked file here.

Report `public_totals` when stating anything publishable; `totals` includes repos
that are not.

**User's args:** $ARGUMENTS

If `$ARGUMENTS` is empty, default to the last closed week.
