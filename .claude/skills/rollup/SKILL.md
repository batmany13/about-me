---
name: rollup
description: >
  The summary-of-summaries. Reads every registered repo's weekly catchup —
  its entities and its week record — and merges them into one cross-repo view
  for a given ISO week: combined stats, entities grouped by category across
  repos, corrections, and the threads that appear in more than one repo. This
  is the private layer that sits between the per-repo `catchup` skill and the
  public weekly. Use when asked for the cross-repo picture of a week, combined
  stats across repos, or to prepare the raw material a weekly is written from.
  Triggers: "/rollup", "roll up the week", "summary of summaries", "what
  happened across all my repos", "combined stats", "cross-repo view".
---

# Rollup — one week, every repo

Each repo writes its own catchup. This reads all of them and adds them up.

```
per repo:    git ──catchup──▶ entities/<id>.json + weeks/<W>.json + <W>.md
here:        weeks/<W>.json × N repos ──▶ one merged view
downstream:  the public weekly, after the scrub policy
```

**One producer per fact.** This skill never walks a git log. If a repo has no
week record, the answer is to run `catchup` *in that repo*, not to re-derive the
week here — two producers of the same number is how they start disagreeing.

## The naming rule, which is not optional

**This skill lives in a public repo.** Repo names and paths live in the private
registry and nowhere else. Refer to repos by **role** — the tech repo, the fund
repo, the personal repo — and resolve real names through the registry at run
time.

Everything this skill produces is **private by construction**: it carries repo
names, unscrubbed entity notes, and per-repo counts. Write output to the private
layer, never into a tracked file here. If you are about to write a repo name
into a committed file in this repo, stop — that is the leak this design exists
to prevent.

## Step 0: The registry

`fnr/.private/repos.json` — repo paths, each one's `disclosure` level
(`named` / `described` / `hidden`) and its `public_stats` flag.

If `fnr/.private/` is absent it was **never cloned into this checkout**, not
lost — the parent repo ignores that path by design:

```bash
git clone https://github.com/batmany13/about-me-private.git fnr/.private
```

**Never reconstruct the registry from memory or from a conversation.** A
reconstructed registry is one nobody reviewed.

`disclosure` governs *naming*; `public_stats` governs whether a repo's volume
feeds a published count. They are separate decisions and the script keeps the
two populations apart — `totals` covers every reporting repo, `public_totals`
only those cleared to be counted publicly. **Never publish `totals`.**

## Step 1: Resolve the week

Default is the **last closed week**. `this week`, `last week`, `last N weeks`,
`the week of <date>`, or `2026-W35` all work. More than 4 weeks → confirm first.

## Step 2: Run the rollup

```bash
uv run .claude/skills/rollup/scripts/rollup.py 2026-W35 --table   # human read
uv run .claude/skills/rollup/scripts/rollup.py 2026-W35           # full JSON
```

The table is the orientation pass; the JSON carries every entity body.
`--no-entities` gives stats only when the full bodies are too much.

**If any repo reports `no week record`, stop and deal with it.** Either run
`catchup` in that repo first, or state plainly in the output that the totals
cover N of M repos. A total presented as complete when a repo is missing is the
one error this layer can make that nobody downstream can detect.

## Step 3: Read across, not down

The per-repo summaries already exist — restating them is not the job. What this
layer can see that no single repo can:

- **`cross_repo_entities`** — the same entity id in more than one repo. A
  subject that is a research thread in one repo and a portfolio position in
  another is one story told in two places, and this is the only view that shows
  it. Look here first; it is the highest-value output.
- **The shape of the week across lanes** — where the volume actually went versus
  where the attention went. They are frequently not the same repo, and the
  divergence is usually the interesting part.
- **Corrections in aggregate.** Each repo's corrections are individually small;
  read together they show what class of mistake the week kept making.
- **Carried-over entities** (`carried_over`) — what is *continuing* rather than
  new. A weekly that treats a six-week thread as this week's news is misleading.
- **Entities with no counterpart in the stats** — a repo with heavy commit volume
  and two entities was probably under-extracted; a repo with three commits and
  nine entities was probably over-extracted. Say so.

## Step 4: Write the merged view

Write to the **private layer**, `fnr/.private/rollups/<YYYY-WNN>.md`. Create the
directory if absent.

```markdown
# <YYYY-WNN> — rollup (<N> repos, <N> commits, <N> PRs)

**<One line: what this week was, across everything.>**

## Where the week went
| Repo | Lane | Commits | PRs | Entities | Corrections |
(from --table; keep it, it is the fastest read in the file)

## Threads across repos
- <cross_repo_entities, and what each one means read together>

## By category
### Meeting / Partner Notes
### Technical Notes
### Other

## Corrections, read together
- <the pattern, not a re-list>

## Carried over
- <what is continuing, with its span>

## For the weekly
- <what a reader outside would find interesting — the candidates, not the copy>
```

That last section is the handoff, not the weekly itself. **Nothing here is
scrubbed.** Publishing is a separate act under the scrub policy, and the
public/private boundary is the whole point of keeping the layers apart.

## Step 5: Report

State the week, repos reporting out of registered, combined stats (making clear
which are publishable), the cross-repo threads, and anything that looked
under- or over-extracted. If any repo is missing a week record, lead with that.

---

## Common pitfalls

- **Publishing `totals` instead of `public_totals`.** They differ precisely
  because some repos are not publishable. The script keeps them separate; keep
  them separate downstream.
- **Totalling over a missing repo.** Report N of M, always.
- **Writing repo names into a committed file here.** Output goes to the private
  layer. Every time.
- **Re-deriving a week from git.** If the number is wrong, fix it in the repo's
  catchup and re-run — don't compute a second version here.
- **Restating the per-repo summaries.** If a paragraph would be equally true in
  a single repo's catchup, it does not belong in the rollup.
