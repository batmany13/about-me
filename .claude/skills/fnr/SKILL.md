---
name: fnr
description: >
  Write Bruce's weekly Field Notes & Reflections (FNR). The machine writes the
  whole week from the private repos' catchups — an unredacted draft and the
  scrubbed public candidate together, with the delta between them — then asks
  the owner one question per turn, and each answer goes straight into the
  public file, verbatim. Every question is optional except one: Top of Mind
  for Founders. Resumable across sessions under Claude or Codex. Triggers:
  "/fnr", "write my weekly", "field notes", "weekly reflection", "time for the
  weekly", and — when a week is mid-conversation — any reply to the current
  question.
---

# FNR — Field Notes & Reflections

The Monday weekly. Bruce left Netflix in August 2026 and is on a "no-break
career break": building, advising founders, seed investing, learning. FNR is
the public record of that — and the name is a pun on Netflix's Freedom &
Responsibility, which is the joke and also the point.

**Two layers, and the distinction is the whole design:**

| Layer | Where | Audience | Contains |
|---|---|---|---|
| **Ground truth** | each source repo's `catchup/<W>.md`, and `fnr/.private/drafts/<W>.unredacted.md` | Bruce only | Everything. Names, numbers, decisions. |
| **Public weekly** | `fnr/<W>.md` in about-me | The internet | What survives the scrub policy, plus his own words. |

**And one sequence, which replaced the two-draft loop:**

> The machine writes the **whole week** first — the unredacted draft and the
> scrubbed candidate side by side, with the delta between them. Nothing is left
> as a prompt. Then it asks **one question per turn**, showing both versions of
> the section, and writes the answer **directly into the public file**. His
> words are never scrubbed: he wrote them knowing where they go. Every question
> is optional except **Top of Mind for Founders**.

The facts come from the record. The meaning comes from him. A draft that
invents the meaning wastes the exercise — so the machine fills every block with
the best *machine* answer (the record's own headline, the top-ranked learning),
clearly marked as such, and never with an invented reflection in his voice.

---

## Who owns which block

| Block | Owner | Default before he answers |
|---|---|---|
| **Opening** under the title | 🔴 his, optional | the week's headline from the rollup |
| Stats line | 🟢 machine | from `pull_week.py` totals |
| `Building` — the update | 🟢 machine | from the tech catchup's themes, by consequence |
| `Building` — **Learning.** | 🔴 his, optional | the tech catchup's top-ranked learning |
| `Fund & Advisory` — the update | 🟢 machine | from the fund catchup: conversations and method, never repo plumbing |
| `Fund & Advisory` — **Learning.** | 🔴 his, optional | the fund catchup's top-ranked learning |
| `Rooms I Was In` — facts | 🟢 machine | name, host, date, public link from the registry |
| `Rooms I Was In` — what it was like | 🔴 his, optional | omitted until he says |
| `Top of Mind for Founders` | 🔴 **his, required** | none — the weekly does not publish without it |
| `On the Bench` | 🟢 machine | from the intake registry and outbox |
| `Next` | 🔴 his, optional | the calendar's shape for the following week |

### The verbatim rule (🔴 blocks)

**Grammar and spelling only.  Nothing else.**  Do not summarize, compress,
expand, reorder, split into headline-plus-paragraph, or smooth an odd turn of
phrase — that's voice, not error. If he writes "build the momentum to build a
stronger opinion," it ships with "build" twice. The test: diff your output
against what he sent; every difference must be nameable as a spelling or
punctuation fix. If you can't name it, revert it.

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

**Never reconstruct `repos.json` or `scrub_policy.md`** — clone the reviewed
copy. Then read both: the registry names the repos, their `disclosure`
(`named` / `described` / `hidden`) and `public_stats`, and the `intake` block;
the policy is the judgment layer — **read it in full every run**.

Naming the private repo here is fine; naming the repos it points at is not.
This skill refers to them by role — the tech repo, the fund repo, the personal
repo.

## Step 1 — Resolve the week

`date +%Y-%m-%d` and `date +%G-W%V` (`%G`, not `%Y`, at year boundaries).

| Bruce says | Resolves to |
|---|---|
| `/fnr`, `last week` | **the last closed week** — on Monday and every other day |
| `this week` | the current week; stamp `_Draft — week still in progress._` |
| `last N weeks`, `the week of <date>`, `2026-W36` | as named |
| `backfill` | every week since the first FNR with commits and no file |

**If a state file exists for the week, resume it** — go to Step 5 and ask the
next pending question. That is how a reply to "here are my reflections" lands.

## Step 2 — The catchups must exist, and the rollup runs

Each source repo writes its own week with its own `catchup` skill; this skill
never re-derives a week from git. For every repo with commits that week:

```bash
uv run <repo>/.claude/skills/catchup/scripts/entities.py check-summary <W> --repo <repo>
```

Missing → run `/catchup <W>` **in that repo** and let it land its PR; the fund
repo splits by author, the others don't, and reimplementing the format here
produces a file that looks right and violates the repo's convention. Then, from
the private repo, roll up and snapshot:

```bash
uv run .claude/skills/rollup/scripts/rollup.py <W> --snapshot rollups --table
```

Read `rollups/<W>.md`. It is the source for Step 4; the raw pull is not.

Pull the rest of the raw material:

```bash
uv run .claude/skills/fnr/scripts/pull_week.py <W> > /tmp/fnr_week.json
```

- **Stats** for the line: `commits_publishable_primary` (work repos only),
  `prs_merged_publishable`, `prs_open_now_publishable`, per-day ÷ 7.
  `public_stats: false` repos never feed it; `disclosure` decides naming, not
  counting. No lines-changed figure unless the number means something.
- **Events**: name, host, date, public link. The registry's `format`/`venue`
  describe the plan; `entities[].note` and `disposition` are diligence
  judgments about people in a social room — never quoted, never paraphrased.
- **The vetting queue** for `On the Bench`: the processed queue (`candidate_type
  == technology`, `track.status == intake`) and the outbox (`public_summary`
  only — never `id`, `source_uri`, or anything implying a watchlist). Prefer
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
shared shape — **publish the pattern, never the incident.** "My own notes kept
asserting things that were never decided" is a learning a stranger recognizes;
"the transport binding was recorded as never chosen" is trivia. Illustrate with
two or three, abstracted of system vocabulary, and say what the fix bought.

## Step 4 — Write the pair: unredacted, scrubbed, and the delta

**Three files, in one pass, before any question is asked.**

| File | What |
|---|---|
| `fnr/.private/drafts/<W>.unredacted.md` | The weekly in the public template, **with names and numbers intact.** The memory jog. |
| `fnr/<W>.md` (on a branch of about-me) | The same weekly after the scrub policy. **Every 🔴 block wrapped in markers** and filled with its machine default. |
| `fnr/.private/drafts/<W>.delta.md` | What was held back, by category, and a `## Flagged for review` list of borderline calls the policy says cut but he might want. |

**No block is left empty.** The opening carries the rollup's headline. Each
Learning carries the catchup's top-ranked learning, prefaced with nothing — it
reads as the weekly's until he replaces it. `Top of Mind for Founders` is the
one exception: its marker holds a single line, `_(his — asked below)_`, and the
weekly cannot publish while that line stands.

Markers, exactly:

```markdown
<!-- fnr:blurb -->
The week's headline, as the rollup wrote it.
<!-- /fnr:blurb -->
```

Keys: `blurb`, `building_learning`, `fund_learning`, `rooms` (only when there
were events), `top_of_mind`, `next`. Then start the state:

```bash
uv run .claude/skills/fnr/scripts/state.py init <W> [--no-rooms]
```

The scrub happens **here, once, on machine text.** Derive the public file from
the unredacted one under `scrub_policy.md`: never the repo or product name,
never a company in the pipeline, never a score or decision, never an attendee,
never the personal repo's contents; the tech/fund split, problem classes,
public events, his own mistakes, and public technologies by name in `On the
Bench` are all fine. When unsure, hold it in the delta's flagged list and ask
at Step 6 rather than guessing in public.

## Step 5 — Ask, one question per turn

See `reference/questions.md` for the six questions, their order, and the
Claude and Codex variants. The loop:

```bash
uv run .claude/skills/fnr/scripts/state.py next <W>      # which question
# show the unredacted section, then the scrubbed section, then ask ONE thing
uv run .claude/skills/fnr/scripts/state.py answer <W> <key> --file /tmp/a.md   # or --keep / --skip
uv run .claude/skills/fnr/scripts/state.py paste <W> fnr/<W>.md
```

- **Show both versions of the section every time.** The unredacted one is
  why he can answer; the scrubbed one is what his answer joins.
- **Write his answer into the public file directly**, verbatim. It is not
  scrubbed. Mirror it into the unredacted file so the private record is whole.
- **`top_of_mind` refuses Skip.** Nudge into the talent seam — hiring,
  motivating, growing people, keeping a culture alive — using this week's
  unredacted conversations, and remind him nothing in the nudge may appear by
  name. If he stops here, the draft is saved and nothing publishes.
- **Stopping mid-way is normal.** `state.py next` on a later day resumes.
- **Never batch the questions.** One per turn is the design: he answers each
  with the section in front of him.

## Step 6 — Publish check, then publish

When `state.py next` says `publish`, show the delta's `## Flagged for review`
list — machine calls only, never his text — and ask once: publish, or hold?

```bash
uv run .claude/skills/fnr/scripts/state.py publish <W> --decision publish
uv run .claude/skills/fnr/scripts/state.py check <W> fnr/<W>.md
```

Then land it: the public file on a branch of about-me with a PR; the
unredacted draft, the delta, the state file and the rollup snapshot on a
branch of the private repo with a PR. Never commit or push to `main`; never
merge.

## Step 7 — Open the coming week

Create `fnr/.private/drafts/<W+1>.wip.md`: **Outcomes I want this week** (his,
one optional question: "two or three outcomes, concrete enough to check on
Friday?"), **Carried over** (open threads from both catchups, machine),
**Known shape of the week** (the calendar table with prep owed, machine),
**Running notes** (empty), **Against the outcomes** (next Monday). It goes on
the same private PR.

---

## The public template

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY>

<!-- fnr:blurb -->
<the rollup's headline, or his opening>
<!-- /fnr:blurb -->

## Building

_<N> commits · <N> PRs · <N> open · ~<N> commits/day_

<3–4 short paragraphs: what changed, at the level of the decision, by
consequence. Never the project, repo, or URL — "the tech side", "the tech
repo". The corrections pattern from Step 3 belongs here.>

**Learning.**  <!-- fnr:building_learning -->
<the tech catchup's top-ranked learning, or his>
<!-- /fnr:building_learning -->

## Fund & Advisory

<1–2 paragraphs on the FUND lane: conversations (shape and counts, never
names), method, intake. Not repo mechanics — those are Building.>

**Learning.**  <!-- fnr:fund_learning -->
<the fund catchup's top-ranked learning, or his>
<!-- /fnr:fund_learning -->

## Rooms I Was In

<!-- fnr:rooms -->
<events: name + host + public link, one line on what mattered; omit the
whole section on a week with none>
<!-- /fnr:rooms -->

## Top of Mind for Founders

<!-- fnr:top_of_mind -->
_(his — asked below)_
<!-- /fnr:top_of_mind -->

## On the Bench

<3–5 bullets from the intake registry: what it is and why it's queued,
framed as learning, grouped by cohort, never a conclusion>

## Next

<!-- fnr:next -->
<one or two sentences from the calendar: the shape, the prep owed, the
meeting that feeds the build>
<!-- /fnr:next -->

_Part of a [no-break career break](../roles.md).  How these are made: [fnr/README.md](README.md)._
```

### Section rules

- `Building` and `Top of Mind for Founders` are the spine; always present.
- `Rooms` → `Fund & Advisory` → `On the Bench` is one pipeline; each says its
  part once. `Fund & Advisory` is the fund lane, not the fund repo.
- Stats: figures only, work repos only, mainline commits.
- `On the Bench` runs as long as the intake earns; framing decides whether it
  reads as curiosity or a leaked pipeline.
- `Top of Mind` is **one** item, his, hand-written. The recurring seam is
  talent.
- Never name what he's building. Research subjects are a per-mention
  allowance, kept sparse; CocoIndex and DeepVista are the standing exceptions.

### Voice

Direct, first person, past tense, active. Two spaces after a period. Keep his
insider vocabulary — `portcos`, `deal flow`, `intake`. No LinkedIn cadence.
The update is short; the learning is the point. Length is a rule of thumb
(700–1100 words), never a reason to cut good content.

### Read it back before the questions

Balance tracks the stat line — a section a third the size of another that did
comparable work is under-reported. Each Learning grows out of the paragraphs
above it. Strip `significantly`, `a lot`, `much better`. Two or three
aphorisms, not five. Say a thing once. A trailing paragraph belongs to its
item. Cut vague-and-pointless lines rather than shipping them hollow.

---

## Conventions

- **Filename** `<YYYY-WNN>.md`; **cadence** Monday; `fnr/README.md` is the
  index and `ls` the table of contents; **backfill** oldest first; don't
  repeat adjacent weeks.

## Common pitfalls

- **Asking a question before the whole draft exists.** The draft is the thing
  he reacts to; a prompt in an empty slot is not.
- **Writing a reflection he didn't write.** The default is the machine's own
  best answer, labeled by where it came from — never an invented feeling in
  his voice.
- **Scrubbing his answer.** He wrote it for the public file. Grammar only.
- **Editing an answered block by hand.** `state.py paste` is the only writer.
- **Publishing the raw pull.** The public file derives from the catchups and
  the rollup; skipping the middle is how names leak.
- **Trusting commits over his correction.** He's right; the commits are
  missing context.
- **Counting the hidden lane, or naming a repo.** `public_stats` and
  `disclosure` are two different questions.
