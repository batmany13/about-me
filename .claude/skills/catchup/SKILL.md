---
name: catchup
description: >
  Catch up on any git repo, one ISO week at a time. Runs in two passes: first it
  extracts durable ENTITIES from the week's activity — meetings and partner
  notes, technical threads, decisions, corrections — into a per-repo store that
  accumulates across weeks; then it writes the week's summary from those
  entities. Entities optionally sync to DeepVista as context cards, one card per
  entity, updated rather than duplicated. Repo-agnostic: works with no config,
  and a `.claude/catchup.config.json` teaches it a repo's people and vocabulary.
  Accepts natural args: "this week", "last week", "last 2 weeks", "all",
  "backfill", "since August", or a specific date or week.
  Triggers: "/catchup", "/catchup last week", "catch me up", "what shipped this
  week", "weekly summary", "what changed while I was away".
---

# Catchup — entities first, summary second

A catchup answers "what happened while I was away". This skill answers it twice
over: once as a **durable record** and once as **prose**.

| Pass | Produces | Lives at | Lifetime |
|---|---|---|---|
| **1. Extract** | entities — the things worth tracking | `<out>/entities/<id>.json` | forever, accumulating |
| **2. Summarize** | the week's readable catchup | `<out>/<YYYY-WNN>.md` | one week |
| *(optional)* **Sync** | DeepVista context cards | one card per entity | updated in place |

**Why two passes rather than straight to prose.** A thread that runs for six
weeks, written as prose alone, is six disconnected bullets in six files — and
"what ever happened with X" is unanswerable without reading all six. As an
entity it is *one file with six weekly notes*, so the history is a single read
and the summary becomes a rendering of it rather than the only copy. It is also
what makes the DeepVista sync coherent: DeepVista's own model is that a context
card captures an **entity**, so one entity maps to one card that accumulates.

**The summary is derived. The entities are the record.** If the two ever
disagree, the entities win — rewrite the summary from them.

**Filenames use ISO weeks (`2026-W35.md`) so they sort. The user-facing arg is
always natural language — never make anyone type `WNN`.**

## Categories

Three, fixed. A repo may retitle one or extend its matching rules; it may not
invent a fourth, because the whole value is that the vocabulary is the same
everywhere.

| Key | Default title | What belongs here |
|---|---|---|
| `meeting` | **Meeting / Partner Notes** | Conversations with people: 1x1s, partner and founder calls, events attended, intros, interviews. Anything whose subject is a *person or a room*. |
| `technical` | **Technical Notes** | How the thing works and how it changed: features, refactors, migrations, specs, tests, infrastructure, tooling. |
| `other` | **Other** | Real work that is neither — writing, admin, planning, structure, process, finance. Not a junk drawer: if it lands here a lot, the repo probably wants a category rule, not a shrug. |

Precedence when a commit could be two things: **meeting beats technical beats
other.** A meeting note *about* a technical subject is still a meeting note.

---

## Step 0: Locate the repo and read its config

Run everything against a specific repo — default is the cwd, `--repo <path>`
otherwise. Nothing in this skill knows about any particular repo.

```bash
SKILL=<this skill dir>/scripts
python3 $SKILL/pull_week.py --repo . --list-weeks | head -40
```

Config is optional and lives at `.claude/catchup.config.json` in the target
repo. With no config the skill still works — it just cannot name people or know
the repo's own vocabulary. See `reference/config.md`; a ready-to-copy starting
point is in `assets/catchup.config.example.json`.

If the repo has no config and the week's classification comes out mostly
`other`, say so and offer to write one. Don't silently accept a bad split.

## Step 1: Resolve the arg to a set of weeks

Today's date and ISO week: `date +%Y-%m-%d` and `date +%G-W%V` — note `%G`, not
`%Y`. At year boundaries Jan 1 can be W52 of the *prior* year.

| User says | Resolves to |
|---|---|
| `/catchup` (no arg) | **The last closed week.** Not the current one — a partial week published as whole is the one thing this format must not do. Glance at the current week; if it has commits, mention them in a one-line tail. |
| `this week` | Current ISO week; overwrite freely, the week isn't done |
| `last week` | The ISO week before this one |
| `last N weeks` | The previous N ISO weeks |
| `all` | Every ISO week with commits (`--list-weeks`) |
| `backfill` / `missing` | Every week with commits that has no summary file yet |
| `since <date>` / a date or range | The week(s) those dates fall in |
| `W35` / `2026-W35` | That week — accepted, never required |

More than 5 weeks → confirm before running. Zero weeks → say so and stop.
Backfill runs **oldest first**, so each week can build on the entity store the
earlier weeks left behind.

## Step 2: Pull the week

```bash
python3 $SKILL/pull_week.py --repo . 2026-W35 > /tmp/week.json
```

Emits classified commits, per-category counts, per-author counts, the
directories that moved, and — the part that matters most — **`pr_details`: every
PR merged in the week, with its title and body.**

**Read the PR bodies. They are the richest source in the pull and a commit log
cannot substitute for them.** A commit subject is one line written in passing; a
PR body is the considered writeup — what was learned, what turned out wrong, what
a document or a demo actually said. An extraction built from subjects alone
reconstructs a week's *mechanics* and loses its *findings*, which is usually the
only part worth reading later.

A busy week can run 100k+ characters of PR bodies (`pr_body_chars_total` says how
many). Budget for it: skim titles first, then read the long ones in full —
length correlates with substance. `--pr-body-limit N` truncates, `0` disables the
cap, `--no-prs` skips them entirely when you only need counts.

Also read `git show --stat <sha>` for any commit whose subject is ambiguous.

Two things in that output decide how much to trust it:

- **`category_why`** records the rule that classified each commit.
  `path:` is strong evidence, `keyword:` is weaker, **`path-weak:`** means a rule
  matched a small share of the diff and `default` means nothing matched at all.
  Re-classify those yourself in pass 1 — the script's guess is a starting point,
  not a verdict.
- **`commit_count` vs `commit_count_primary`** — the first spans all refs and
  includes pre-squash worktree branches, so it is inflated and machine-specific.
  Publish the primary number. Prefer `prs_merged` (from `gh`) over the `prs`
  list, which is scraped from subjects and picks up cross-repo mentions.

If the week has 0 commits, say so and stop. Don't write an empty file.

## Step 3 (pass 1): Extract entities — the judgment step

This is the work. Turn the week's raw activity into entities: things worth
tracking, not commits worth listing.

**What makes something an entity.** It has an identity that outlives the week —
you could plausibly write another note about it next week. "Rewrote the auth
middleware" is an entity. "Fixed a typo in the auth middleware" is not; it is
evidence for one.

**Mine the PR bodies for the learnings, not just the changes.** The difference
between a weak catchup and a useful one is almost entirely here. A commit says
*what moved*; a PR body says *what was found* — the claim that turned out wrong,
the mechanism worth borrowing, the number that meant something other than it
looked like. Those findings are frequently the most valuable thing in the week
and they appear nowhere in the commit log.

**People, companies and products deserve their own entities.** When a week
produces real learnings about an outside party — an architecture, an auth model,
a benchmark — file it as an `org` or `person` entity rather than burying it in
the note of the meeting it came from. It will recur, and next time it should
accumulate rather than start over.

**Reuse ids.** Before creating an entity, check the store:

```bash
python3 $SKILL/entities.py list
python3 $SKILL/entities.py show <id>
```

If the week continues existing work, **reuse that entity's id** — that is the
entire mechanism by which history accumulates. A new id for continuing work
silently forks the record. When in doubt, reuse: merging is a judgment you can
revisit, a fork is a fact you lose.

**Types:** `meeting` · `person` · `org` · `thread` · `decision` · `correction` ·
`other`. `thread` is the workhorse. **`correction` earns its own type** —
reverts, refuted claims, things an audit found wrong. They are the
highest-signal entries in any catchup and the easiest to lose, so never fold a
correction into the thread that caused it.

**Statuses:** `active` · `done` · `parked` · `dropped`.

Write the extraction as JSON and pipe it in:

```json
{"entities": [
  {"id": "auth-middleware-rewrite", "type": "thread", "category": "technical",
   "title": "Auth middleware rewrite",
   "summary": "Current state of this thread, rewritten as it evolves.",
   "status": "active", "tags": ["auth"],
   "note": "What happened THIS week — one or two sentences.",
   "commits": ["abc1234"], "prs": [41], "paths": ["src/auth/"],
   "people": [], "date": null, "links": []}
]}
```

`summary` is the entity's **present tense** — rewrite it each week it moves.
`note` is **this week only** and is never rewritten later. That distinction is
what lets the card read as current while the timeline stays honest.

```bash
python3 $SKILL/entities.py upsert --repo . --week 2026-W35 --file extraction.json
python3 $SKILL/entities.py validate --repo .
```

Upsert is idempotent — re-running a week **replaces** that week's block rather
than appending, so a corrected extraction overwrites cleanly. Re-running an
*older* week will not clobber a newer week's summary or status.

Aim for **5–15 entities** in a normal week. Fifty means commits are being
transcribed rather than entities extracted; two means a week got flattened.

## Step 3b: Record the week's stats

```bash
python3 $SKILL/entities.py record-week --repo . --week 2026-W35 --pull /tmp/week.json
```

Writes `<out>/weeks/<YYYY-WNN>.json`: commit and PR counts, what was ignored and
why, per-author and per-category splits, top directories, the entity ids the week
touched, its corrections, and which entities carried over from earlier weeks.

**This is the only machine-readable record of the week's size.** Prose cannot be
added up. Anything reading across repos — a cross-repo roll-up, a quarterly, a
stat line — reads these files, and without one a week is invisible to every
layer above this skill even though its summary reads fine.

Run it *after* the entity upsert, so the record captures the entity ids.

## Step 4 (pass 2): Write the summary from the entities

```bash
python3 $SKILL/entities.py week 2026-W35 --repo .
```

That scaffold — grouped by category, with the multi-week ones marked
`[running since ...]` — is what the summary is written from. **Write from the
scaffold, not from the commit log.** If something belongs in the summary but is
not in the scaffold, the fix is to add the entity, not to reach past it.

Save to `<out>/<YYYY-WNN>.md`:

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY> (<N> commits, <N> PRs<, partial week if applicable>)

**<One-line theme of the week.>**

### Meeting / Partner Notes
- <who, what was decided, what happens next>

### Technical Notes
- <what shipped, what it replaced, what it enables — PRs as `(#NN)`>

### Other
- <the rest that mattered>

### Corrections
- <what was refuted, reverted, or found wrong>

PRs merged: <#NN, …>

Open threads: <what's mid-flight going into next week>

---
*Stats: N commits (N on mainline) · N PRs merged, N open · N entities
(N new, N carried over) · N corrections · N bookkeeping commits excluded.*
```

**Always close with the stat line.** It is the one part of the summary that is
mechanically checkable, it is what makes weeks comparable to each other, and it
is what a roll-up quotes. Take every figure from the week record rather than
re-counting by hand — a stat line that disagrees with `weeks/<W>.json` means one
of them is wrong and a reader cannot tell which.

Render categories in the fixed order, and **skip a category with no entities**
rather than printing an empty heading. `Corrections` is drawn from entities of
type `correction` across every category — it is a lens on the week, not a fourth
category. Include it whenever the week has any.

**Length:** the repo's `summary.bullets` / `summary.words` budget, defaulting to
**6–12 bullets and 150–250 words**. That default is sized for a normal week; a
repo that routinely runs 200+ commits should raise it in config rather than have
every week overflow it silently. Check the previous week's file — a summary that
is three times the length of its neighbours is the wrong length whatever the
config says.

Group hard on a big week — signal, not completeness. Mark an entity that has
been running with its span (`[since 2026-W31]`); a reader wants to know what is
*new* versus what is *continuing*. Don't restate adjacent weeks; assume the
reader reads in order.

**Account for what was excluded.** The pull reports `ignored_count` —
bookkeeping commits held out of the counts. If it is non-trivial, add a closing
line naming the number and the wide count, so the summary can never be mistaken
for a claim that the week was smaller than it was.

**Voice:** direct, terse, past tense, active. Bold the headline moments. Say
what happened; don't editorialize about it.

**If author-splitting is on** (config `authors.split`), add a
`*Split: Name N · Name N.*` line under the theme and prefix each bullet with the
person when a week has more than one author. Render every configured person even
at zero commits — a quiet week is signal — but state it as a fact and move on.
Any email not in the config shows up in `unknown_authors`: surface it and ask,
never bucket a real contributor under someone else.

## Step 5 (optional): Sync entities to DeepVista

Only when config sets `deepvista.enabled: true`. See
[`reference/deepvista.md`](reference/deepvista.md) for the full prototype —
endpoint, auth, and the one gotcha that makes cards invisible if you miss it.

The key lives in `~/.config/secrets.env` as `DEEPVISTA_API_KEY` and must be
exported before the session starts, or `.mcp.json` cannot interpolate it:

```bash
set -a; . ~/.config/secrets.env; set +a
```

Never read a key into the transcript, and never put one in a repo file.

```bash
python3 $SKILL/deepvista_cards.py plan --repo . --week 2026-W35
```

Emits one item per entity with `action: create | update | skip`. Call the
DeepVista MCP card tool for each, then record what came back:

```bash
python3 $SKILL/deepvista_cards.py record --repo . --id <entity-id> --card-id <returned>
```

`skip` means the entity has not changed since its last push — **let it skip.**
The free tier is 100 credits a month, and re-pushing an unchanged card spends
one to change nothing.

## Step 6: Report

Tell the user:
- the summary path and the week's headline, in one sentence
- **entities: N new, N updated** — and name any entity that just crossed into a
  second week, because that is the signal the store exists to produce
- anything classified `other` by `default` that probably deserved a category
  rule
- if syncing: cards created/updated/skipped
- whether other weeks are missing, and offer to backfill

Commit only if the repo's config asks for it (`git.commit`). Default is off:
catchups are working artifacts and the user decides when they land.

---

## Running under another agent runtime

`.claude/skills/` is the authored canon; a second runtime should **point at it**,
never hold a copy. A copied `.agents/skills/` directory works the day it is made
and diverges silently from then on, because the copy is what that runtime reads.
`deploy.sh` reports which state a repo is in after every deploy. Details and the
one-line fix: [`reference/portability.md`](reference/portability.md).

The scripts are plain Python over `git` and `gh` with no runtime-specific calls,
and `/catchup` is a convenience rather than the interface — the skill can be
followed directly. The only model-called dependency is the optional DeepVista
sync, which is off by default.

---

## Common pitfalls

- **Wrong ISO week-year at boundaries.** Always `%G-W%V`, never `%Y-W%V`.
- **Publishing the wide commit count.** `commit_count` spans all refs and differs
  between machines. Publish `commit_count_primary`.
- **Counting PRs from subjects.** `prs` is scraped text and picks up cross-repo
  references and duplicates. `prs_merged` comes from `gh` and is the real number.
- **Forking an entity that already exists.** The most damaging failure here,
  because it is silent: the history just stops accumulating. Check `list` first.
- **Transcribing commits as entities.** If an entity's note could only ever be
  written once, it is evidence, not an entity.
- **Commit count is not importance.** A 300-commit week can be one idea explored
  300 times; a 4-commit week can close a quarter of work.
- **Letting `other` absorb everything.** A repo whose weeks are 70% `other` needs
  category rules in its config. Say so rather than shipping a vague summary.
