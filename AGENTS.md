# AGENTS.md — instruction entry point

Before starting any task:

1. Read this file from disk.
2. Read the root `CLAUDE.md` **completely and carefully from disk**. Do not rely
   on an injected, summarized, or truncated copy.
3. Read every applicable nested `AGENTS.md` and `CLAUDE.md`.
4. Incorporate all applicable instructions into the plan and execution before
   taking action.

The root `CLAUDE.md` is canonical, including its **Working in this repo**,
**Conventions**, and **What NOT to change without explicit ask** sections;
follow those in full. This file is intentionally a small, real instruction
router — not a symlink and not a duplicate policy document.

## This repository is public

Everything committed here is world-readable the moment it is pushed, and **a
pull request publishes it just as effectively as a merge.** That is the one fact
that changes how every other rule applies.

- **Repo names live in `fnr/.private/repos.json` and nowhere else.** Refer to the
  source repos by role — the tech repo, the fund repo, the personal repo — and
  resolve real names at run time. `about-me` and `about-me-private` are the only
  two nameable here.
- **`fnr/.private/scrub_policy.md` is the judgment layer. Read it in full before
  writing anything public**, including code comments and commit messages. It has
  green / yellow / red categories and a five-question test; when two rules
  conflict, the more restrictive wins.
- **Never publish** what Bruce is building by name, investment decisions,
  unannounced pipeline, per-company conclusions, attendee lists, anything a
  founder said in confidence, or the contents of the personal repo.
- **Criticism of a third party is a red-list item even when it is accurate** —
  a founder, an attendee, a portfolio company. Put the finding in the private
  layer and say you did.
- If `fnr/.private/` is missing it was never cloned into this checkout, not lost:
  `git clone https://github.com/batmany13/about-me-private.git fnr/.private`.
  **Never reconstruct it from memory or from a conversation.**
- When genuinely unsure, flag it for Bruce rather than guessing in public.

## Worktrees are the only edit surface

Leave the main checkout on `main`, untouched. Create a feature branch in a
worktree, make every change there, push the branch, and open or update a PR.
**Agents never merge pull requests** and never push directly to `main`.

## One skill source for every runtime

Repository skills live canonically under `.claude/skills/`. Claude discovers them
there; Codex reaches the same files through the tracked `.agents/skills` symlink.
**Never create a second `.agents/skills/` copy** — a copy works the day it is
made and diverges silently from then on, because the copy is what that runtime
reads. Edit canon, never a copy.

| Skill | What it does |
|---|---|
| `catchup` | Per-repo weekly: extract entities from a week, then summarize from them. **Source of truth** — deployed into other repos with its `deploy.py`, so edit it here and redeploy |
| `rollup` | Cross-repo summary-of-summaries. Output is private by construction |
| `fnr` | The public weekly, written under the scrub policy |

When the human names a skill, **invoke it through its front door** rather than
hand-assembling an equivalent. A substitute changes what the run measured while
leaving the output looking like a success.
