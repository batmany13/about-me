---
name: fnr
description: >
  Write Bruce's weekly Field Notes & Reflections (FNR). The machine writes the
  whole week from the private repos' catchups — an unredacted draft and the
  scrubbed public candidate together, with the delta between them — then asks
  the owner one question per turn, and each answer goes straight into the
  public file, verbatim. The sections, the owner's blocks, the one required
  block and the questions are declared in the private config. Resumable
  across sessions under Claude or Codex. Triggers: "/fnr", "write my weekly",
  "field notes", "weekly reflection", "time for the weekly", and — when a
  week is mid-conversation — any reply to the current question.
---

# FNR — Field Notes & Reflections

The Monday weekly. Bruce left Netflix in August 2026 and is on a "no-break
career break". FNR is the public record of that — and the name is a pun on
Netflix's Freedom & Responsibility, which is the joke and also the point.

**Two layers, and the distinction is the whole design:**

| Layer | Where | Audience | Contains |
|---|---|---|---|
| **Ground truth** | each source repo's `catchup/<W>.md`, and `fnr/.private/drafts/<W>.unredacted.md` | Bruce only | Everything. Names, numbers, decisions. |
| **Public weekly** | `fnr/<W>.md` in about-me | The internet | What survives the scrub policy, plus his own words. |

**One sequence, which replaced the two-draft loop:**

> The machine writes the **whole week** first — the unredacted draft and the
> scrubbed candidate side by side, with the delta between them. Nothing is left
> as a prompt. Then it asks **one question per turn**, showing both versions of
> the section, and writes the answer **directly into the public file**. His
> words are never scrubbed: he wrote them knowing where they go. Every question
> is optional except the one the config marks required.

The facts come from the record. The meaning comes from him. The machine fills
every block with the best *machine* answer — the record's own headline, the
top-ranked learning — and never with an invented reflection in his voice.

**Nothing in this public skill names a section.** The sections, their titles,
which blocks are his, which one is required, where each machine default comes
from, and the question asked for each live in **`fnr/.private/fnr.config.json`**
(`sections[]`, contract `fnr-config/v1` — the schema is in
`reference/questions.md`). Read it before writing a line; the template below
is rendered from it.

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

- **Stats** for the line: `commits_publishable_primary` (work lanes only),
  `prs_merged_publishable`, `prs_open_now_publishable`, per-day ÷ 7.
  `public_stats: false` repos never feed it; `disclosure` decides naming, not
  counting. No lines-changed figure unless the number means something.
- **Events**: name, host, date, public link. The registry's `format`/`venue`
  describe the plan; `entities[].note` and `disposition` are judgments about
  people in a social room — never quoted, never paraphrased.
- **The vetting queue**: the processed queue and the outbox, `public_summary`
  only — never `id`, `source_uri`, or anything implying a watchlist. Prefer
  items that trace to something in this weekly; group cohorts; researching a
  conference program is not attending it.
- **Next week's calendar** (Google Calendar MCP, the following Mon–Sun):
  counts and shape, never names. Cross-reference against the catchups — the
  tie usually runs build → meeting: this week's research was prep for next
  week's conversation.
- **The forward draft** `fnr/.private/drafts/<W>.wip.md`, if it exists: its
  stated outcomes and running notes are the highest-value input, because they
  hold what he was *trying* to do. Open the draft by comparing intent to result.

## Step 3 — Mine the corrections for a pattern

Both catchups carry `correction` entities. Read them together and name the
shared shape — **publish the pattern, never the incident.** A correction only
an insider can parse is trivia; the same correction seen with the week's
twenty others is a class of mistake a stranger recognizes. Illustrate with two
or three, abstracted of system vocabulary, and say what the fix bought.

## Step 4 — Write the pair: unredacted, scrubbed, and the delta

**Three files, in one pass, before any question is asked.**

| File | What |
|---|---|
| `fnr/.private/drafts/<W>.unredacted.md` | The weekly in the config's shape, **with names and numbers intact.** The memory jog. |
| `fnr/.private/drafts/<W>.public.md` | The same weekly after the scrub policy — **the candidate, and it stays in the private repo.** Every owner block wrapped in markers and filled with its machine default. It reaches `fnr/<W>.md` in about-me only through `state.py release`, only after Step 6. |
| `fnr/.private/drafts/<W>.delta.md` | What was held back, by category, and a `## Flagged for review` list of borderline calls the policy says cut but he might want. |

**No block is left empty.** Each owner block carries the machine default the
config names for it (`default`), reading as the weekly's until he replaces
it. The required block is the one exception: its marker holds a single
placeholder line, and the weekly cannot publish while that line stands.

Markers, exactly, keyed by the config's `key`:

```markdown
<!-- fnr:blurb -->
The machine default for this block.
<!-- /fnr:blurb -->
```

Then start the state — `--without <key>` for a `conditional` block the week
has no material for:

```bash
uv run .claude/skills/fnr/scripts/state.py init <W> [--without <key>]
```

The scrub happens **here, once, on machine text.** Derive the public file from
the unredacted one under `scrub_policy.md`. When unsure, hold it in the
delta's flagged list and ask at Step 6 rather than guessing in public.

## Step 5 — Ask, one question per turn

`reference/questions.md` has the mechanism; the config has the questions.

```bash
uv run .claude/skills/fnr/scripts/state.py next <W>      # which block
# show the unredacted section, the scrubbed section, the nudge, then ask ONE thing
uv run .claude/skills/fnr/scripts/state.py answer <W> <key> --file /tmp/a.md   # or --keep / --skip
uv run .claude/skills/fnr/scripts/state.py paste <W> fnr/.private/drafts/<W>.public.md
```

- **Show both versions of the section every time.** The unredacted one is
  why he can answer; the scrubbed one is what his answer joins.
- **Write his answer into the candidate directly**, verbatim. It is not
  scrubbed. Mirror it into the unredacted file so the private record is whole.
- **The required block refuses Skip.** Show its `nudge` from the unredacted
  draft and remind him nothing in the nudge may appear by name. If he stops
  here, the draft is saved and nothing publishes.
- **Stopping mid-way is normal.** `state.py next` on a later day resumes.
- **Never batch the questions.** One per turn is the design: he answers each
  with the section in front of him.

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

---

## The public template

Rendered from the config, in its section order. A machine section is its
title and prose; an owner block is its title (or none, for the opening) and a
marked block holding the machine default.

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY>

<!-- fnr:<opening key> -->
<the machine default: the rollup's headline, scrubbed>
<!-- /fnr:<opening key> -->

## <machine section title>

_<N> commits · <N> PRs · <N> open · ~<N> commits/day_   ← on the build-lane section only

<3–4 short paragraphs at the level of the decision, ordered by consequence.
The corrections pattern from Step 3 belongs in the build-lane section.>

**<owner block title>**  <!-- fnr:<key> -->
<the machine default the config names>
<!-- /fnr:<key> -->

## <conditional section title>          ← omitted, and `--without`, on a week with none

<!-- fnr:<key> -->
<facts from the registry>
<!-- /fnr:<key> -->

## <required section title>

<!-- fnr:<key> -->
_(his — asked below)_
<!-- /fnr:<key> -->

## <machine section title>

<bullets from the vetting queue: what it is and why it's queued, framed as
learning, grouped by cohort, never a conclusion>

## <owner section title>

<!-- fnr:<key> -->
<the calendar's shape for the following week>
<!-- /fnr:<key> -->

<the config's footer line>
```

### Section rules

- The build-lane section and the required block are the spine; always present.
- A section that draws on the same material as another says its part once.
  The relationship lane is the lane, not the repo: its plumbing belongs in the
  build-lane section.
- Stats: figures only, work lanes only, mainline commits.
- The vetting-queue section runs as long as the intake earns; framing decides
  whether it reads as curiosity or a leaked pipeline.
- The required block is **one** item, his, hand-written.
- Never name what he's building. Research subjects are a per-mention
  allowance, kept sparse; the policy's standing exceptions are the only names
  cleared by default.

### Voice

Direct, first person, past tense, active. Two spaces after a period. Keep his
insider vocabulary — his word beats your clearer word. No LinkedIn cadence.
**The update is short; the learning is the point.** Each machine section has a
`budget` in the config — typically 150–250 words, three short paragraphs at
most — and a corrections pattern is one sentence inside a paragraph, never a
block of its own. Personal detail is one or two sentences. A whole weekly
lands around 600–900 words; length is never a reason to cut his blocks, and
always a reason to cut the machine's.

### Read it back before the questions

Balance tracks the stat line — a section a third the size of another that did
comparable work is under-reported. Each learning grows out of the paragraphs
above it. Strip `significantly`, `a lot`, `much better`. Two or three
aphorisms, not five. Say a thing once. A trailing paragraph belongs to its
item. Cut vague-and-pointless lines rather than shipping them hollow.

---

## Conventions

- **Filename** `<YYYY-WNN>.md`; **cadence** Monday; `fnr/README.md` is the
  index and `ls` the table of contents; **backfill** oldest first; don't
  repeat adjacent weeks.

## Common pitfalls

- **Inferring publish.** Only the word, from him, quoted into the state.
  Everything before that is hold, and the public repo is not touched.
- **Asking a question before the whole draft exists.** The draft is the thing
  he reacts to; a prompt in an empty slot is not.
- **Writing a reflection he didn't write.** The default is the machine's own
  best answer, from where the config says — never an invented feeling in his
  voice.
- **Naming a section, a question, or a lane's repo in this public skill.**
  They live in the private config and registry.
- **Scrubbing his answer.** He wrote it for the public file. Grammar only.
- **Editing an answered block by hand.** `state.py paste` is the only writer.
- **Publishing the raw pull.** The public file derives from the catchups and
  the rollup; skipping the middle is how names leak.
- **Trusting commits over his correction.** He's right; the commits are
  missing context.
- **Counting the hidden lane, or naming a repo.** `public_stats` and
  `disclosure` are two different questions.
