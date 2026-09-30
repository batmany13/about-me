---
name: fnr
description: >
  Bruce's weekly Field Notes & Reflections (FNR), as a reflection tool. The
  machine writes a rich private memory aid of the week from the private repos'
  catchups, plus a scrubbed machine version of every block as fallback and
  eval baseline; then it asks the owner one question per turn, showing his
  notes but not the machine's prose, and his words go straight into the public
  file, verbatim. The sections, the owner's blocks, the pick lists, the one
  required block and the questions are declared in the private config.
  Resumable across sessions under Claude or Codex. Triggers: "/fnr", "write my
  weekly", "field notes", "weekly reflection", "time for the weekly", and —
  when a week is mid-conversation — any reply to the current question.
---

# FNR — Field Notes & Reflections

The Monday weekly. Bruce left Netflix in August 2026 and is on a "no-break
career break". FNR is the public record of that — and the name is a pun on
Netflix's Freedom & Responsibility, which is the joke and also the point.

**A reflection tool, not a summarizer.** Bruce, 2026-09-29: *"This is really
more of a self blog that I want to type and reflect."* The machine's job is to
help him **remember** the week; the writing is his, as much as he wants to do.
Machine prose on the page is a fallback, until the evals say it has earned more.

| Layer | Where | Audience | What it is |
|---|---|---|---|
| **Memory aid** | `fnr/.private/drafts/<W>.unredacted.md`, over each repo's `catchup/<W>.md` | Bruce only | **The product.** Everything, unscrubbed, organized for recall — names, numbers, PRs, goals, how the plan changed. Never copy. |
| **Public weekly** | `fnr/<W>.md` in about-me | The internet | **His writing.** Where he doesn't write, the scrubbed machine version. |

Every section has one of three kinds, declared per section in the config:

- **machine** — written from the record, scrubbed, never asked. He changes one
  by telling you.
- **owner** — asked. The candidate holds a machine version: a fallback he can
  keep, and the baseline his words are measured against. Never a draft to polish.
- **pick** — the machine's job is to surface options. The candidate list lives
  on the private side; he picks; **nothing is listed that he did not pick.**

**Blind write, then compare.** The question shows his notes, not the machine's
version. Seeing the machine's prose first does the reflecting for him and
anchors the answer; writing blind keeps the reflection his and the comparison
honest. He can ask to see it first (`reveal`, recorded) or after (`compare`).

**Nothing in this public skill names a section.** Titles, kinds, the required
block, the machine defaults, the memory shapes and the questions live in
**`fnr/.private/fnr.config.json`** (`sections[]`, contract `fnr-config/v1`;
the schema is in `reference/questions.md`). Read it before writing a line.

### The verbatim rule (owner blocks)

**Grammar and spelling only.  Nothing else.**  Do not summarize, compress,
expand, reorder, split into headline-plus-paragraph, or smooth an odd turn of
phrase — that's voice, not error. The test: diff your output against what he
sent; every difference must be nameable as a spelling or punctuation fix. If
you can't name it, revert it.

**And the machine never edits an answered block.** Answers live in the state
file; a re-render pastes them back byte for byte (`state.py paste`), and
`state.py check` fails if the file and the state disagree.

---

## Step 0 — Preflight

`fnr/.private/` is **its own private git repo**, cloned into a directory that
about-me gitignores. Check it before reading anything:

```bash
git -C fnr/.private fetch --quiet && git -C fnr/.private status --short --branch
```

Dirty or behind → say so and stop. Absent → it was never cloned here:

```bash
git clone https://github.com/batmany13/about-me-private.git fnr/.private
```

**Never reconstruct `repos.json`, `scrub_policy.md` or `fnr.config.json`** —
clone the reviewed copy. Then read all three: the registry names the repos,
their `disclosure` (`named` / `described` / `hidden`) and `public_stats`, and
the `intake` block; the policy is the judgment layer — **read it in full every
run**; the config is the shape of the page.

Naming the private repo here is fine; naming the repos it points at is not.
This skill refers to them by lane, as the registry does.

## Step 1 — Resolve the week

`date +%Y-%m-%d` and `date +%G-W%V` (`%G`, not `%Y`, at year boundaries).

| Bruce says | Resolves to |
|---|---|
| `/fnr`, `last week` | **the last closed week** — on Monday and every other day |
| `this week` | the current week; stamp `_Draft — week still in progress._` |
| `last N weeks`, `the week of <date>`, `2026-W36` | as named |
| `backfill` | every week since the first FNR with commits and no file |

**If a state file exists for the week, resume it** — go to Step 5 and ask the
next pending question. That is how a reply to the current question lands.

## Step 2 — The catchups must exist, and the rollup runs

Each source repo writes its own week with its own `catchup` skill; this skill
never re-derives a week from git. For every repo with commits that week:

```bash
uv run <repo>/.claude/skills/catchup/scripts/entities.py check-summary <W> --repo <repo>
```

Missing → run `/catchup <W>` **in that repo** and let it land its PR;
reimplementing a repo's format here produces a file that looks right and
violates its convention. Then, from the private repo, roll up and snapshot:

```bash
uv run .claude/skills/rollup/scripts/rollup.py <W> --snapshot rollups --table
```

Read `rollups/<W>.md`. It is the source for Step 4; the raw pull is not.

Pull the rest of the raw material:

```bash
uv run .claude/skills/fnr/scripts/pull_week.py <W> > /tmp/fnr_week.json
```

- **The week is cut in the registry's `timezone`** (top-level key, e.g.
  `America/Los_Angeles`; `--timezone` overrides, UTC with a notice when absent)
  — the same zone every repo's catchup declares, so this pull and the rollup
  count the same week. The output carries `timezone` and the exact
  `start`/`end` instants; `first_day`/`last_day` and `span` are for display.
- **Stats** for the line: `commits_publishable_primary` (work lanes only),
  `prs_merged_publishable`, `prs_open_now_publishable`, per-day ÷ 7.
  `public_stats: false` repos never feed it; `disclosure` decides naming, not
  counting. No lines-changed figure unless the number means something.
- **Events**: name, host, date, public link. The registry's `format`/`venue`
  describe the plan; `entities[].note` and `disposition` are judgments about
  people in a social room — never quoted, never paraphrased.
- **Pick candidates** — **check the registry's `intake` block first.** A
  source marked `retired` is gone on purpose, and a compacted outbox reads
  empty after delivery; either way say the source is **unavailable** and ask.
  Never fill a pick list from memory or from older weeks. Otherwise the
  `public_summary` only — never `id`, `source_uri`, or anything implying a
  watchlist — filtered by the section's `candidates` rule.
- **Next week's calendar** (Google Calendar MCP, the following Mon–Sun):
  counts and shape for the machine version; names only in the memory aid.
- **The forward draft** `fnr/.private/drafts/<W>.wip.md`, if it exists: its
  stated outcomes and running notes hold what he was *trying* to do. Put
  intent beside result at the top of the memory aid.

## Step 3 — Mine the corrections

Both catchups carry `correction` entities. Read them together and name the
shared shape **in the memory aid and the rollup**. They reach the public page
only where a section's `source` asks for them, and then as the pattern, never
the incident.

## Step 4 — Write the memory aid, then the machine versions

**Four files, in one pass, before any question is asked** — all in the private
repo. Read the past cases first, for every section, machine ones included:

```bash
uv run .claude/skills/fnr/scripts/state.py examples
```

The config's `examples` holds what was kept, cut and rewritten on weeks
already walked, each with his reason and the rule it generalises to. Draft
against the rules, not the texts; nothing in them is quoted into the weekly.
After each walk, add that week's cases to `examples`.

| File | What |
|---|---|
| `drafts/<W>.unredacted.md` | **The memory aid — the product.** The config's page shape, each section written to its `memory` field: rich, unscrubbed, organized for recall, not for reading. For the build lane that is typically *outcome → step*: the goal, how the plan itself changed during the week, each step's state at week end, the PRs. For conversations, by contact. A pick section's block holds the candidate list. Owner and pick blocks carry `<!-- fnr:key -->` markers, so the packet can show exactly that block. |
| `drafts/<W>.public.md` | **The candidate**, scrubbed: machine sections as prose; each owner block marked and filled with its machine version (`default`); a pick block marked, holding only a placeholder; a block whose `default` is null holding a single placeholder line. It reaches `fnr/<W>.md` only through `state.py release`. |
| `drafts/<W>.delta.md` | What the candidate holds back, by category, and a `## Flagged for review` list of borderline calls on machine text. |
| `drafts/<W>.state.json` | Written by `init` below. |

Markers, exactly, keyed by the config's `key`:

```markdown
<!-- fnr:blurb -->
The machine version of this block.
<!-- /fnr:blurb -->
```

**The scrub is for machine text that could reach the public page — nothing
else.** The memory aid is never scrubbed; his answers are never scrubbed. When
unsure about a machine line, hold it in the delta's flagged list.

Then start the state — `--without <key>` for a `conditional` block the week
has no material for:

```bash
uv run .claude/skills/fnr/scripts/state.py init <W> [--without <key>]
```

`init` captures every block's machine version into the state (and snapshots
the machine sections by heading); nothing touches those again. **It prints
question 1 and you ask it in the same turn** — a status report instead of the
question is what reliably stalls a weekly.

**Push the private files early.** Commit and push the week's branch in the
private repo as soon as the drafts exist, and again after every answer.
Pushing the private repo is always fine — only the public repo waits for the
word. A walk that lives only in a working tree is one lost session from gone.

## Step 5 — Ask for his words, one question per turn

`reference/questions.md` has the mechanism; the config has the questions.

```bash
uv run .claude/skills/fnr/scripts/state.py next <W>      # the whole question packet
uv run .claude/skills/fnr/scripts/state.py answer <W> <key> --file /tmp/a.md   # or --keep / --skip
uv run .claude/skills/fnr/scripts/state.py reveal <W> [<key>]    # only if he asks to see the machine's first
uv run .claude/skills/fnr/scripts/state.py compare <W> <key>     # after he answers, if he wants to look
uv run .claude/skills/fnr/scripts/state.py paste <W> fnr/.private/drafts/<W>.public.md
```

**`next` prints the turn**: position (`question 3 of 6`), the block from the
memory aid, the question verbatim, the nudge, the block's past cases, and the
legal replies. **Not the machine version.** `answer` prints the next packet,
so the walk advances on its own; `paste` is the one step it leaves to you.

- **One question per turn.** The packet is the turn. Never read ahead, batch,
  or summarise the rest — he answers each with that block's notes in front of him.
- **Ask for his words first.** Keep is legal wherever there is a machine
  version, but it is the fallback, not the offer. If he wants to see the
  machine's before deciding, `reveal` shows it and records that it did; a kept
  answer after a reveal is a different signal from a blind one.
- **Pick blocks**: he names items from the candidate list; write exactly those
  items, as listed, with `--file`. Keep is refused; skip drops the section.
- **Write his answer into the candidate directly**, verbatim, and never over
  the memory aid. The memory aid stays the record of the week; his words live
  in the state and the candidate.
- **The required block refuses Skip and Keep.** Show its `nudge` from the
  memory aid and remind him nothing in the nudge may appear by name. If he
  stops here, the draft is saved and nothing publishes.
- **The machine sections are not in the walk.** He changes one by telling you;
  re-render and say what moved. `release` snapshots the result, so a machine
  section he rewrote is still a pair.
- **Stopping mid-way is normal.** `state.py next` on a later day resumes.

## Step 6 — Publish check, then publish — and publish is a word he says

When `state.py next` says `publish`, show the delta's `## Flagged for review`
list — machine calls only, never his text — and ask once: publish, or hold?

**Publish is the literal word, from him, in answer to that question.** A
decision on the flagged items ("1 is fine, cut 2") is not a publish decision.
"Looks good" is not. Silence is not. Until his message contains the word
*publish*, the answer is hold, the candidate stays in the private repo, and
nothing is written to about-me. This is enforced, not remembered:

```bash
uv run .claude/skills/fnr/scripts/state.py publish <W> --decision hold
# or, only with his words in hand:
uv run .claude/skills/fnr/scripts/state.py publish <W> --decision publish --quote "<his message>"
uv run .claude/skills/fnr/scripts/state.py release <W> fnr/<W>.md      # the ONLY writer of the public path
uv run .claude/skills/fnr/scripts/state.py check <W> fnr/<W>.md
```

`publish` refuses a `--quote` that does not contain the word; `release`
refuses a state without it. **Never write `fnr/<W>.md` by any other means.**
A weekly once reached a public pull request because the owner's answers on
four flagged items were read as consent — he had not read the private draft
and had never said publish.

Then land it: the released file on a branch of about-me with a PR; the
unredacted draft, the candidate, the delta, the state file and the rollup
snapshot on a branch of the private repo with a PR. Never commit or push to
`main`; never merge.

## Step 7 — Open the coming week

Create `fnr/.private/drafts/<W+1>.wip.md`: **Outcomes I want this week** (his,
one optional question: "two or three outcomes, concrete enough to check on
Friday?"), **Carried over** (open threads from the catchups, machine),
**Known shape of the week** (the calendar table with prep owed, machine),
**Running notes** (empty), **Against the outcomes** (next Monday). It goes on
the same private PR.

## Evals — the pairs

Every walked block is a pair: the machine version captured at `init`, and what
shipped. After release, regenerate the private dataset over every walked week:

```bash
uv run .claude/skills/fnr/scripts/state.py pairs <W1> <W2> ... \
  --machine-from 'first:drafts/{week}.public.md' --out fnr/.private/evals/fnr-pairs.jsonl
```

One JSONL row per block — `week, key, owner, machine, final, verdict
(kept/rewritten/skipped), revealed_before_answer, chars_machine, chars_final,
similarity` (`difflib`), `machine_from`. It names things, so it never leaves
the private repo. **The metric to watch is how often `kept` beats `rewritten`
over the weeks** — blind keeps count for more than keeps after a reveal — and,
within `rewritten`, whether similarity climbs. That is the evidence for handing
the machine more of the page, not a feeling that the drafts got better.
`--machine-from` only backfills states written before machine versions were
captured, from the candidate's first commit; a captured version always wins.

---

## The public template

Rendered from the config, in its section order: a machine section is its
title and prose; an owner block is its title (or none, for the opening) and a
marked block; a pick section is its title and a marked block holding only what
he picked; a `conditional` section is omitted on a week without its material.
The build-lane section carries the stat line
(`_<N> commits · <N> PRs · <N> open · ~<N> commits/day_`); the config's footer
closes the page.

### Section rules

- The build-lane section and the required block are the spine; always present.
- A section that draws on the same material as another says its part once.
- Stats: figures only, work lanes only, mainline commits.
- The required block is **one** item, his, hand-written.
- Never name what he's building in machine text. Research subjects are a
  per-mention allowance, kept sparse; the policy's standing exceptions are the
  only names cleared by default.

### Insight-forward — for the fallback, and for judging it

The shape the machine's versions aim for, and the yardstick when a pair is
reviewed. It is never a template for his words. Bruce, 2026-09-22, on the
paragraph that finally landed after three rewrites: *"this is strong, exact
kind of insight forward we should focus on."* The example below is invented;
it has the same shape.

> A team rebuilt its onboarding flow and sign-ups fell for a month.  The dip
> isn't the interesting part; holding the line through it is.  A change that
> removes a shortcut people relied on looks like a regression before it looks
> like an improvement, and deciding up front how long you'll wait is what keeps
> a good change from being rolled back.

Four moves, in this order:

1. **The event, one clause.** Enough to ground it and not a word more.
2. **Name what is *not* the point.** The move drafts skip, and the one that
   converts news into a lesson. It tells the reader where to look.
3. **The general form, in the reader's own terms** — a sentence they can hold
   against their own company without translating it first.
4. **The cost, or the rarity.** Why it is hard, and therefore worth saying.

**The test: cover the first clause.** If what remains still teaches, the
paragraph is insight-forward. If what remains is nothing, it was news wearing a
lesson's clothes — and anonymising it does not fix that. Paragraphs in this
shape are the easiest to scrub, which is the tell that they are the right
ones. A rough signal: **if a paragraph's first sentence is its longest, it is
probably event-forward.**

### Voice (machine text)

Direct, first person, past tense, active. Two spaces after a period. Keep his
insider vocabulary. No LinkedIn cadence. Strip `significantly`, `a lot`,
`much better`; say a thing once; cut a vague line rather than ship it hollow.
Keep each section inside its config `budget`.

---

## Conventions

- **Filename** `<YYYY-WNN>.md`; **cadence** Monday; `fnr/README.md` is the
  index and `ls` the table of contents; **backfill** oldest first; don't
  repeat adjacent weeks.

## Common pitfalls

- **Inferring publish.** Only the word, from him, quoted into the state.
- **Showing the machine's version with the question.** It anchors him and
  poisons the pair. His notes, the question — and the machine's only on request.
- **Polishing the machine version toward his voice.** It is a fallback and a
  baseline; a draft that imitates him is scored against itself.
- **A thin memory aid.** A scrubbed summary in the private file is the failure
  that started this redesign; the private side keeps every detail.
- **Overwriting the memory aid with his answer.** It stays the record.
- **Listing a pick item he didn't pick**, or filling a pick list from memory.
- **Asking before the whole draft exists**, or reporting instead of asking.
- **Holding private work unpushed.** Push the private branch after every answer.
- **Naming a section, a question, or a lane's repo in this public skill.**
- **Scrubbing his answer, or editing an answered block by hand.** `paste` is
  the only writer.
- **Publishing the raw pull**, **counting the hidden lane**, or **trusting
  commits over his correction** — he's right; the commits are missing context.
