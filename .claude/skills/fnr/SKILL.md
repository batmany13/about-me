---
name: fnr
description: >
  Write Bruce's weekly Field Notes & Reflections (FNR). Pulls a week of commits
  across his private repos plus the calendar events he attended, writes a
  detailed private catchup into each source repo, then publishes a scrubbed
  public reflection to `fnr/<YYYY-WNN>.md` in the about-me repo. Sections cover
  what he built, fund and advisory work, rooms he was in, and the leadership
  lessons top of mind for founders. Runs in two passes: draft 1 reconstructs
  the week from the data to jog his memory, he replies with corrections and
  reflections, then draft 2 transcribes those in and revises around them.
  Use when he wants to write, draft, or backfill a weekly. Accepts natural
  args like "this week", "last week", "last 2 weeks", "the week of Aug 17",
  or "backfill". Triggers: "/fnr", "write my weekly", "field notes", "what
  did I do last week", "weekly reflection", "time for the weekly" - and, when
  a draft is already open, "here are my reflections", "draft 2", or any reply
  correcting or adding to the current draft.
---

# FNR — Field Notes & Reflections

The Monday-morning weekly.  Bruce left Netflix in August 2026 and is on a "no-break career break": building, advising founders, seed investing, learning.  FNR is the public record of that experiment — and the name is a pun on Netflix's Freedom & Responsibility, which is the joke and also the point.

**Two layers, and the distinction is the whole design:**

| Layer | Where | Audience | Contains |
|---|---|---|---|
| **Ground truth** | `.claude/catchups/<week>.md` inside each source repo | Bruce only | Everything. Names, decisions, hashes, dispositions. |
| **Public weekly** | `fnr/<week>.md` in about-me | The internet | What survives the scrub policy. |

The source-repo catchups are the record.  The public file is a *derivative* of them — never write the public file from the raw pull directly, because the intermediate step is where the thinking happens.

**And two passes, which matters as much as the two layers:**

> **Draft 1** reconstructs the week from commits and events.  Its job is to remind Bruce what he did — he's been heads-down and doesn't remember the shape of it.  **He replies** with corrections and reflections, usually mixed together in one raw paragraph.  **Draft 2** transcribes those in and revises the update and the learnings around them.

The facts come from the data.  The meaning comes from him.  A draft that invents the meaning wastes the exercise, because a plausible-sounding learning reads well enough to survive review and still isn't his.

---

## Who owns which block

**Know this before you write a line.**  Every block on the page is one of three kinds, and treating a HUMAN block as a MACHINE block is the failure this skill exists to prevent.

| Block | Owner | Rule |
|---|---|---|
| **Top blurb** (under the title) | 🔴 **HUMAN — verbatim** | His text, as written.  Draft 1 leaves a prompt. |
| Stats line | 🟢 MACHINE | Straight from `pull_week.py` totals. |
| `Building` — the update | 🟢 MACHINE | Summarize and adapt from commits + the Step 3 catchups. |
| `Building` — **Learning.** | 🔴 **HUMAN — verbatim** | Prompt in draft 1.  Never synthesized. |
| `Fund & Advisory` — the update | 🟢 MACHINE | Summarize and adapt. |
| `Fund & Advisory` — **Learning.** | 🔴 **HUMAN — verbatim** | Prompt in draft 1. |
| `Rooms` — event facts | 🟢 MACHINE | Name, host, date, public link from `events.json`. |
| Personal-automation mention | 🟡 MIXED | Nameable in moderation when it carries a learning; contents never, stat line never.  Let weeks pass without it. |
| `Rooms` — what mattered | 🟡 MIXED | Draft from the prep files; his reaction overrides.  He'll tell you a room was awkward when the prep file says it was a great opportunity. |
| `Top of Mind for Founders` | 🔴 **HUMAN — verbatim** | **One item only**, hand-written by him.  Draft 1 leaves a prompt.  See the section rule below. |
| `On the Bench` | 🟢 MACHINE | 3–4 items pulled from the intake registry — see Step 2.  He edits the picks. |
| `Next` | 🟡 MIXED | **One sentence, from his calendar for the following week.**  See Step 2.  He reviews it. |

### The verbatim rule (🔴 blocks)

**Grammar and spelling only.  Nothing else.**

- Do **not** summarize, compress, or expand it
- Do **not** split it into a bold headline plus a framing paragraph
- Do **not** reorder his sentences or promote one to a theme line
- Do **not** smooth repetition, informality, or an odd turn of phrase — that's voice, not error

If he writes "build the momentum to build a stronger opinion," it ships with "build" twice.  If he writes "a clear what's next," it ships ungrammatical, because that's how he says it.  Fix a genuine misspelling, add a missing terminal period, and stop.

The test: diff your output against what he sent.  Every difference should be one you could name as a spelling or punctuation fix.  If you can't name it, revert it.

---

## Step 0 — Read the private config

`fnr/.private/` is **its own private git repo**, cloned into a directory that
about-me gitignores.  That is how it syncs between machines — gitignore cannot
sync a file it refuses to track.

**Check it is current before reading anything.**  Because the directory is ignored
by the parent, `git status` in about-me will never mention uncommitted work in
here; a week of running notes can sit unpushed and nothing says so.

```bash
git -C fnr/.private fetch --quiet && git -C fnr/.private status --short --branch
```

Uncommitted changes, or a branch behind `origin/main`?  **Say so before going
further** — a weekly drafted against a stale policy or a missing forward draft is
worse than one that didn't run.  Pull if it is merely behind; if it is dirty, ask
what to do with the local edits rather than deciding.

Both files live in that repo:

- `fnr/.private/repos.json` — which repos to read, where they are, each one's `disclosure` level (`named` / `described` / `hidden`), and the `intake` block naming the two vetting-queue files (`intake.processed` and `intake.outbox`, each a `{repo, path}` pair).

  **Repo names and paths live in this file and nowhere else.**  This skill is committed to a public repo; it refers to the source repos by role — the tech repo, the fund repo, the personal repo — and resolves the actual names through the registry at run time.  If you find yourself about to write a repo name into a committed file, that is the leak this whole design exists to prevent.

  **`disclosure` governs naming, not importance or reading depth.**  `described` means describe it without naming it — it says nothing about how central the repo is.  The most important repo in the registry is currently `described`, and it still drives most of every weekly.  Read every non-`hidden` repo closely regardless of its level; read `hidden` ones too, for the private catchup only.
- `fnr/.private/scrub_policy.md` — **read this in full every run.** It is the judgment layer: green/yellow/red categories, the five-question test, and the standing exceptions.

**If the whole `fnr/.private/` directory is absent, it isn't lost — it was never cloned into this checkout.**  A fresh clone of about-me, or a recycled worktree, starts without it, because the parent repo ignores that path by design.  The recovery is one command, not a reconstruction:

```bash
git clone https://github.com/batmany13/about-me-private.git fnr/.private
```

Naming *that* repo here is fine — it is the private layer, and saying so reveals only that a private layer exists, which this file already says outright.  Naming the repos it *points at* is not.  If you ever find yourself reconstructing `repos.json` or `scrub_policy.md` from memory or from conversation, stop: clone the repo instead.  A reconstructed policy is a policy nobody reviewed.

If `repos.json` is missing after cloning, stop and say so — there is nothing to read without it.  If `scrub_policy.md` is missing, fall back to the most conservative reading (name nothing, abstract everything) and tell Bruce the policy file is gone.

---

## Step 1 — Resolve the week

Today's date and ISO week: `date +%Y-%m-%d` and `date +%G-W%V` (note `%G`, not `%Y` — at year boundaries Jan 1 can be W52 of the prior year).

| Bruce says | Resolves to |
|---|---|
| `/fnr` (no arg) | **The last closed week.**  This holds on Monday *and* every other day — the weekly is a reflection on a finished week, and a partial week published as if whole is the one failure mode this format can't absorb. |
| `this week` | The current, incomplete week.  Allowed, but stamp it `_Draft — week still in progress._` and expect to regenerate. |
| `last week` | Same as no-arg. |
| `last N weeks` | The previous N closed weeks, oldest first. |
| `the week of <date>` / `2026-W34` | That specific week. |
| `backfill` / `missing` | Every week since the first FNR that has commits but no file in `fnr/`. |

More than 4 weeks resolved?  Confirm before running — each week is a real amount of writing.

---

## Step 2 — Pull the raw material

```bash
python3 .claude/skills/fnr/scripts/pull_week.py 2026-W34 > /tmp/fnr_week.json
```

Emits per-repo commits (author-filtered), PR numbers, the directories that moved, attended calendar events, and lane totals.  It collects; it does not judge.  `--this-week` for the in-progress week, `--today YYYY-MM-DD` to test against a fixed date.

**Then go deeper than the blob** — the blob is an index, not the story:

- `git show --stat <sha>` in the source repo for any commit whose subject is ambiguous
- **Event registry fields describe the PLAN, not what happened.**  `format`, `venue`, and the entity list are written *before* the event and are often wrong afterward — one entry said "one-table sit-down dinner" for what turned out to be a room of founders mingling.  Never describe the shape or feel of a room from the registry.  State the facts the registry is reliable for (name, host, date, public link) and ask him what it was actually like.
- Read the event **prep files** (`prep_file` in the events output).  These carry the actual conversations, questions, and follow-ups — the richest source for the founders section, and also the most sensitive material in the whole corpus
- Read existing `.claude/catchups/` in the source repos if the week is already summarized there — the fund repo has run this convention since March 2026; don't redo work
- Check `git log` in about-me itself for writing done that week
- **Read `fnr/.private/drafts/<this-week>.wip.md` if it exists** — the forward draft he started last Monday.  Its stated outcomes and running notes are the highest-value input you have, because they contain what he was *trying* to do and what happened outside version control.  Open draft 1 by comparing intent against result.
- **Pull the vetting queue** for `On the Bench` from **two** sources — read both, the second one especially:

  1. The **processed queue** at `intake.processed` in the registry, `items[]`.  Filter `candidate_type == "technology"` and `track.status == "intake"`, sort `date_in` descending.  Read `candidate` for the one-liner; **`lab.experiment`, `track.zone`, and `registry_layer` are internal reasoning and never get published**.
  2. The **request outbox** at `intake.outbox` in the registry — **usually the more important of the two.**  Event-driven intake lands here first and sits *unprocessed*, so it's the freshest picture of what he's actually just encountered.  Filter by `requested_at` inside or just before the week.

  **The outbox schema does the scrubbing for you — use it.**  Every record carries a `public_summary` written to be publishable; that field, lightly edited, is the item's line.  Everything else is private by construction: `id` encodes watchlist status and the private company it hangs off, `source_uri` is an internal path, and `private_source: true` says so outright.  **Never publish `id`, `source_uri`, or anything implying a company is on a watchlist.**  Name the public technology, drop the fund context that put it in the queue.

  **Reading a conference program is itself an intake source, separate from attending one.**  A batch of records sharing a `requested_at` and a common subject usually means he worked through an event's talk list, not that he was in the room — and whether he attends is irrelevant to what the research turned up.  Say "researching the Ray Summit program turned up a cohort", never "landed off Ray Summit", which implies attendance he may not have.

  Pick 3–4 and **strongly prefer ones that tie back to something already in this week's weekly** — an item that traces to an event or a build decision earns its place; a random pull from a 90-item queue doesn't.  Related items can be grouped into one bullet when they arrived as a cohort.
- **Pull his calendar for the week *after* the one being reflected on** — that's the raw material for `Next`.  Use the Google Calendar MCP (`list_events`, `startTime`/`endTime` bounding the following Mon–Sun, `orderBy: startTime`).  Count the one-on-ones, note any public events, note anything recurring, and reduce it to one or two sentences about the *shape* of the week.  Every attendee name, company, and email is red-list — the sentence carries counts and character, nothing else.
  - **The calendar is incomplete.**  He tracks events he's still deciding on outside it.  Ask what's planned but unconfirmed rather than assuming the calendar is the whole week.  **If an unconfirmed event is public, name it** — "still thinking about attending Ray Summit", not "probably one more event I'm still working out."  Vagueness about a public conference protects nothing and reads evasive; the only reason to abstract an event is that it isn't public.
  - **Check whether next week's meetings connect to this week's build work** — and get the direction right.  Cross-reference attendees against the research subjects and outcomes in the Step 3 catchups.  The link usually runs **build → meeting**: he researches a company *in preparation for* talking to its founder, so the week's tech is prep, not a downstream consequence.  Getting this backwards ("the meetings fed the build") inverts how he works.  Say it without naming anyone: "tech built this week was in prep for meeting two portco founders, and will hopefully make those meetings richer."  That tie is the point of the section.

**The private catchups in Step 3 name everything; the public file in Step 4 names almost nothing about the build.**  That asymmetry is the design, not an oversight — don't "improve" the public file by restoring detail from the catchup.

**The events output deliberately omits `entities[].note` and `entities[].disposition`.**  Those are diligence judgments about real people who were in a social room with Bruce.  Read them from the prep file when you need context; they are red-list and never publish, not even paraphrased.

---

## Step 2.5 — Mine the week's corrections for a pattern

**Publish the pattern, never the incident.**  A single correction — "recorded the transport binding as never chosen" — is unreadable to anyone outside the system: they can't tell what a transport binding is, why leaving it implied was bad, or whether the fix was right.  It reads as trivia.  The same correction, seen alongside the week's other twenty, is a *class* of mistake, and a class is something a stranger can recognise in their own work.

### How to find it

Correction-shaped commits have a characteristic grammar.  Sweep both repos:

```bash
git log --all --no-merges --format="%s" --since="<mon>" --until="<sun> 23:59" \
  | grep -iE "^(fix|correct|retire|revert)|, not |is not | never |no producer|no consumer|instead of|honestly" \
  | sort -u
```

Then **cluster them and name the shared shape.**  Don't rank them and take the best one — the value is in the repetition, because a mistake made once is an accident and a mistake made twenty times in five days is a property of how you were working.

### The test

**Could a reader who has never seen the system recognise this mistake in their own work?**

- ❌ "A portfolio row is not gap-closing work; bundle back to 0.1.0" — needs the system to parse
- ❌ "The gate's independence dimension has no producer" — same
- ✅ "My own notes kept asserting things that were never decided" — anyone who has kept notes has done this

If the pattern only makes sense to someone inside the repo, it isn't a learning yet.  Keep abstracting until it is, or drop it.

### Illustrate with two or three, abstracted

Name instances only as evidence for the pattern, stripped of system vocabulary: *"a binding that looked chosen, a component nothing produced, a rule nobody had agreed."*  The reader needs enough to believe the pattern is real, not enough to reconstruct the architecture.

### Say why the fix was right

The pattern is half of it.  The other half is what it cost and what the correction bought — that's the part that makes it a learning rather than a confession.  **A stranger should finish the paragraph knowing what to do differently**, not just that something went wrong.

### Worked example — W34

Twenty-odd corrections across both repos, and almost all shared one grammar: *X is not Y*, or *X was never Z*.  A decision that was never made, a component with no producer, a rule that was never agreed, a duplicate mistaken for a relocation, an org mistaken for a repo.  Every one was the representation claiming more than the reality — and the reason that matters is that you act on the representation.  Published as three sentences; the individual fixes never appear.

---

## Step 3 — Run each repo's own catchup

**Don't write these from scratch.  Each source repo has its own `catchup` skill — run that.**

For every repo with commits that week, invoke its `.claude/skills/catchup/SKILL.md` (or `/catchup`) with the week.  Each one knows its own conventions, and they differ in ways that matter: the fund repo splits highlights by author and renders every contributor's header even when one has zero commits; the single-author repos have no split section at all.  Reimplementing the format here produces a file that looks right and violates the repo's own convention.

The result lands at `<repo>/.claude/catchups/<YYYY-WNN>.md`, **unscrubbed** — Bruce's own record, in his own private repo.  That skill also commits it and opens a PR on that repo (its final step); let it.

**If a repo has no `catchup` skill, port one** rather than hand-writing the file.  Copy the structure from the fund repo's `.claude/skills/catchup/SKILL.md` and adapt two things: the highlight categories in Step 3, and whether an author split applies.  The other two repos were ported this way on 2026-08-22.

Read the resulting catchups before moving on — Step 4 derives from them, never from the raw pull.

---

## Step 4 — Draft 1: the memory jog

**Draft 1 is not a publishable weekly.  It is a reminder of what he did.**

He has been heads-down across several repos all week and does not remember the shape of it.  Draft 1's only job is to hand that back to him accurately enough that he can react to it.  Reaction is what produces the actual content.

Save to `fnr/<YYYY-WNN>.md` with the draft banner, and a copy to `fnr/.private/drafts/<YYYY-WNN>.draft1.md` so the delta between draft 1 and the final is preserved.  That delta is the interesting record — it shows what the machine could reconstruct versus what only he knew.

Write the full structure (see the template below), with these differences from a finished weekly:

- **Facts get written; learnings and the opening do not.**  Leave every `**Learning.**` slot as a bracketed prompt with two or three *specific* questions drawn from the week's material — not "what did you learn?" but "you reverted the transport decision twice — was that the format's fault or yours?"
- **The top blurb is his, same as the learnings** — see the ownership table above.  It carries how the week *felt*, and the commits contain no evidence about that whatsoever.  Leave it as a prompt; ask two or three specific questions instead ("how are you feeling about what's next?", "what was this week *for*?").  Never write an emotional read of his week in his voice — an invented "I had a vague plan to ease in" is the same error as an invented learning, in the most prominent position on the page.
- **Never write a finished learning in his voice.**  A synthesized-sounding lesson is worse than an empty slot, because it reads plausibly enough to survive review and it isn't his.  A commit message is evidence, never a reflection.
- **Flag what you're unsure of** inline: `[?]  Is this right — did the site split happen this week or before?`  He will correct it faster than you can verify it.
- **Name gaps.**  If a week's commits don't explain *why* something happened, say so rather than inventing a rationale.

Hand it over and say plainly: this is draft 1, it's here to jog your memory, the learnings are yours to fill.

---

## Step 5 — Collect his reflections

He responds in raw form — quick, unpunctuated, several corrections mixed with several reflections in one paragraph.  Read it carefully.  It usually contains three different kinds of thing at once:

1. **Factual corrections** — "no I didn't create the fund repo, that was created a while ago."  These often reveal the update was subtly wrong in a way the commits couldn't show.
2. **Additions** — things that happened outside version control entirely.  Conversations, decisions, where an idea actually arrived.
3. **The learnings** — the reason the weekly exists.

Treat every one of them as authoritative over your draft.  If a correction contradicts what the commits appear to say, he is right and the commits are missing context.

---

## Step 6 — Draft 2: transcribe, don't paraphrase

Rewrite the file incorporating his reflections.  Both the update *and* the learnings change — a factual correction usually reshapes the surrounding paragraph, not just one clause.

**Transcribe his words.**  This is the single most important rule in this step.  When he writes a reflection, it goes in close to verbatim — fix grammar, add punctuation, cut a repetition, and stop.  Do not smooth it into house style.

His phrasing is consistently better than the paraphrase because it's concrete and slightly odd, and odd is what people remember.  "The vampire is real" is a better line than anything you would have written about screen time, and a well-meaning rewrite to "it's important to get outside" destroys it.  When in doubt, keep his sentence and cut yours.

Then re-run the whole file against `scrub_policy.md` — his raw reflections have never been scrubbed, and this is the pass where a portfolio name or an unshipped specific gets in.

---

## The public template

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY>

_<Draft banner, only while the week is still open.>_

<🔴 HUMAN — VERBATIM. His top blurb, exactly as he wrote it: how the
week felt, what it was for, where his head is. Draft 1 leaves this as a
prompt. Draft 2 pastes his text with spelling and punctuation fixed and
nothing else changed. No bold theme line unless he wrote one.>

## Building

_<N> commits · <N> PRs · <N> repos · <~X% tech, ~Y% fund>._

<3–4 short paragraphs. What changed, at the level of the decision rather
than the diff. NEVER name the project, repo, or URL — see the Red list.
"The tech side", "the tech repo", "the engine" is the vocabulary.
Corrections and refuted assumptions go here and are the most credible
thing in the document.>

**Learning.**  <1–2 sentences, in his words. Draft 1 leaves this as a
prompt; draft 2 fills it from what he wrote.

Learnings are NOT required to be technical. Rhythm, energy, time
allocation, where an idea actually arrived, what he's saying no to —
these age better than the engineering ones and are the reason he writes
the weekly. A second learning gets its own bold lead-in when it earns
one.>

## Fund & Advisory

<1–2 short paragraphs on the FUND lane specifically: intake (what got
queued and where it came from), new companies and founders met, and how
he's thinking about this work. Shape and counts, never names.

NOT repo mechanics. The fund repo's own plumbing — contracts, seams,
tooling — belongs in `Building` with the rest of the build work, and
putting it here duplicates that section. This lane kept defaulting to
repo work because repo work is what git can see; the fund's actual week
lives in the intake registries, the event prep files, and the forward
draft's running notes. Go there.>

**Learning.**  <1–2 sentences, in his words.>

## Rooms I Was In

<Events attended. Name + host + public link, then one or two sentences
on the single most interesting thing. Never the guest list, never a
diligence read on anyone there. Omit the section entirely if the week
had no events.>

## Top of Mind for Founders

<🔴 HUMAN — VERBATIM. ONE item. Hand-written by Bruce, for now. Draft 1
leaves this as a prompt. Never write three lessons synthesized from the
week's events — that was the old shape and it's retired.>

## On the Bench

<3–4 technologies or concepts queued to vet or learn, pulled from the
intake registry. One line each: what it is, and why it's queued —
preferably tying back to something earlier in this weekly. Frame as
LEARNING, never as fund evaluation. Never say what was concluded about
one, never say what zone or layer it sits in, never imply a decision.
Omit the section on a week with nothing new queued.>

## Next

<ONE OR TWO sentences, drawn from his calendar for the FOLLOWING week
plus anything he says is planned but not yet on it. What the shape of it
is — not a to-do list and not aspirational. Names and companies get
scrubbed; counts and shape survive. Don't get fancy here.

Two things that belong here when true: the PREP owed before the
meetings, and any meeting that FEEDS the build work — that loop between
who he talks to and what he builds is the most interesting thing the
section can say, and it survives scrubbing because it needs no names.

Never frame a meeting-heavy week as less building. He builds regardless;
saying otherwise is wrong about him.>

---

_<N> events this week.  Build stats at the top of [Building](#building)._
_Part of a [no-break career break](../roles.md). How these are made: [fnr/README.md](README.md)._
```

### Section rules

- **Always include `Building` and `Top of Mind for Founders.`**  They're the spine.  A quiet week says so in one honest line — it does not skip the header.
- **`Fund & Advisory` is the fund lane, not the fund repo.**  Intake, people, and how he's thinking about the work.  If the paragraph could sit under `Building` without anyone noticing, it's in the wrong section.  Sources: `intake.processed` and `intake.outbox` for what got queued, the event prep files for who was met, the forward draft for everything git can't see.
- **`On the Bench` runs as long as the week's intake earns.**  Roughly 3–5 bullets, but **listing the tech he's seeing IS the point of the section** — don't trim it to look tidy.  Group items that arrived as a cohort into one bullet (the Ray Summit batch is one bullet, not five); that keeps it readable without dropping anything real.
- **Framing decides whether `On the Bench` reads as curiosity or as a leaked pipeline.**  "I want to know where the durability lives" is learning; "evaluating for the infra thesis" is not.  Never publish `lab.experiment`, `track.zone`, `registry_layer`, or any conclusion.
- **`Top of Mind for Founders` is ONE thing, hand-written.**  Not two, not three, not a list.  Bruce writes it; draft 1 leaves a prompt and draft 2 transcribes.  ("For now" — if he later wants help drafting it, he'll say so.)

  **The recurring seam is talent** — how to get the most out of people, how to motivate, hire, grow, and keep a culture alive.  What works at 2–5 people differs from 1–5k, but the underlying principles are the same.  That's the thread the section pulls on week over week, and it's the thing he has 26 years of earned right to say.  When prompting him for this block, prompt *into* that seam: what did this week's advisory conversations surface about people, hiring, motivation, or culture?
- **`Rooms I Was In` is conditional** on having attended something.  Drop the whole section on a week with no events rather than writing "no events this week".
- **Stats go at the top of `Building`,** as an italic line: commits, PRs, repo count, and the tech/fund split.
  - **Keep it to figures.  No prose in the stat line.**  It is a quick glance before the part that matters, which is what he built.  Shape: `<N> commits · <N> PRs · <N> open · ~<N>/day`.  Caveats belong here in the skill, not in the line.
  - **Commits:** `commits_publishable_primary` (mainline).  Squash-merging collapses a 39-commit branch into one, so it undercounts effort — but it is stable across machines, which `commits_publishable` (all refs) is not.  Publish it, don't defend it.
  - **PRs:** `prs_merged_publishable`, gh-backed.  **Not** the subject-parsed `prs` list — that scrapes `#NN` from commit subjects and catches cross-repo references and mentions (W34: it read 37 where GitHub said 24).  Keep that list for *naming* PRs in a catchup.
  - **Open:** `prs_open_now_publishable`.  In-progress work is real work; without it a week spent deep inside something large reads as a light week.
  - **Per-day:** mainline commits ÷ 7.
  - **Lines changed: usually don't.**  Checked for W34 and it was +700k in the tech repo, of which 411k was `corpus/labs` — generated research output, plus the repo split moving files between repos. It measures generation and migration, not authorship. Only include it on a week where the number would mean something, and never as a headline.
  - **Work repos only** (`lane` of `build` or `fund`).  The line sits under **Building**; the writing lane isn't building.
  - If the commit split and the PR split disagree materially, that belongs in the prose above, not in the line.  W34 was 72/28 by commits and 24/24 by PRs — the tech PRs were simply much larger.
- **`disclosure` and `public_stats` are different questions.**  `disclosure` governs whether a repo may be NAMED; `public_stats` governs whether its volume feeds the stat line.  The personal repo is `described` and `public_stats: false` — nameable in moderation, never counted.  Don't infer one from the other.

  | Stat | Field |
  |---|---|
  | commits | `totals.commits_publishable_primary` |
  | PRs | `totals.prs_publishable` |
  | repos | `totals.repos_publishable` |
  | split | `totals.by_lane_publishable_primary` |

  Two filters are doing work there, and dropping either one publishes something wrong.  **Publishable** excludes `hidden` repos — the delta between that and `commits_all` reveals that hidden work exists and how much, and `repos_active` counts hidden repos in the repo count for the same reason.  **Primary** counts only what's reachable from the mainline ref, so a squash-merged branch is counted once rather than once per pre-squash commit — and the number holds on whichever machine runs the pull, which the all-refs count does not.  Repo *count* is fine; repo *names* are not.
- **Never name what he's building.**  Not the repo, not the project, not the GitHub URL, not a feature set that identifies it.  This is the single rule most likely to be violated by accident, because the work is genuinely interesting and the names are right there in the commits.  Research subjects it evaluates are a per-mention allowance, not a standing one — keep them sparse, since a list of subjects plus the shape of the tooling lets a reader infer the product.

### Voice

Direct, first person, past tense, active voice.  Two spaces after a period (repo convention).  Bruce's register: concrete, a little dry, willing to say what didn't work.

**Keep his insider vocabulary.**  `portcos`, `deal flow`, `intake`, `the loop` — he wants the jargon, and it signals he's inside this world rather than commenting on it.  Don't expand shorthand into plain English for an imagined general reader; the people he's writing for already speak it, and the ones who don't can infer it.  This is a special case of the transcribe rule: his word beats your clearer word.  **Don't editorialize** — "shipped the eval harness" not "excited to share that I shipped the eval harness."  No LinkedIn cadence, no "thrilled", no rhetorical questions as section openers.  Bold sparingly, for the one thing that actually mattered.

**The update is short; the learning is the point.**  Bruce's own words on the format: keep the update concise, then one or two sentences of learning.  `Building` and `Fund & Advisory` each end with a bold `**Learning.**` paragraph — that's the part he values and the part a reader remembers.  Resist letting the update swell to fill the section.

Length: **a rule of thumb, not a limit.**  Draft 2 tends to land around 700–1100 words.  If a dense week runs to 1100 or beyond, that's fine — **never cut good content to hit a number.**  The number exists to stop padding, not to force trimming.  Cut a line because it's weak, repetitive, or says nothing; never because the total is inconvenient.  A quiet week should be genuinely short rather than inflated, for the same reason.

The only section with a real cap is `Top of Mind for Founders` — one item, because he says so.  `On the Bench` runs as long as the intake earns.

---

## Step 6.5 — Read it back before handing it over

Draft 2 is where it reads well or doesn't.  Run these against the whole file, in order.  Every one of them came from a real defect in W34.

### Balance — the stat line is the check

**The section weights should roughly track the week's own numbers.**  W34 ran `24 PRs tech / 24 fund` — dead even — while the prose ran **447 words of Building against 136 of Fund & Advisory**, better than 3:1.  One of those is wrong, and it isn't the PR count.  When a section is a third the size of another that did comparable work, the small one is under-reported, not genuinely quiet.

Rough shape for a normal week: `Building` is the biggest section and shouldn't exceed ~40% of the total.  If it's pushing half, it has absorbed material that belongs elsewhere.

### Does each section set up its own learning?

`Fund & Advisory` in W34 was entirely repo mechanics — typed requests, coverage computability — and then closed on a learning about **how many events he can attend and the advisory/rest balance.**  The update and the learning were about different subjects, so the learning arrived unsupported.

A `**Learning.**` that doesn't grow out of the paragraphs above it means one of the two is wrong: either the update omitted the week's real story in that lane, or the learning belongs in a different section.  Usually the former — advisory *conversations* are invisible in git, so the update defaults to repo work and the lane's actual substance goes missing.  **Go looking for it** in the event prep files and the forward draft's running notes.

### Vagueness — the intensifier test

**"Shored up the research and execution agents significantly"** was the weakest line in W34, sitting between paragraphs that were specific.  `significantly` carries no information; strip it and the sentence says the agents changed, which the reader already assumed.

Search the draft for `significantly`, `a lot`, `much better`, `substantially`, `heavily`, `improved`.  Each one is either hiding a fact worth naming or padding a line that should be cut.  Named things: a number, a before/after, a mechanism, a decision.

### Aphorism budget — two or three, not five

W34 landed five principle-lines: *which side is allowed to write* · *what is this spec for* · *ledger, not a verdict* · *a claim may not assert currency against evidence it predates* · *a finding nobody was waiting for is a note.*  Individually good.  Five in a thousand words is dense enough that they stop landing and start sounding like a style.

Keep the two or three that earned it — the ones tied to something he actually did that week — and let the rest be plain description.  The best one goes near the end of its section, not buried mid-paragraph.

### Repetition

Say a thing once.  W34 mentions the unchosen transport binding in `Building` (as a correction) and again in `On the Bench` (as queued work).  That's defensible — different tense, different purpose — but check that the second mention adds something.  If it doesn't, cut the second.

### Attachment — does every paragraph belong to what precedes it?

In `Rooms I Was In`, the prep paragraph ("The part that did work…") is about the a16z dinner but sits as its own paragraph after it, so it reads as a comment on all three rooms.  Any trailing paragraph in a list-shaped section needs to be visibly attached to its item or folded into it.

### The footer earns nothing

W34's footer read `3 events this week.  Build stats at the top of Building.` — one number already implied by the section above it, and a pointer to something ten lines up.  Keep the footer to the two standing links.  Don't restate stats there.

### Last pass: what would a stranger not understand?

Read it as someone who doesn't know the work.  Vague-but-fine is normal here — the scrub guarantees it.  **Vague-and-pointless is the failure**: a sentence that survived scrubbing with nothing left in it.  Cut those rather than shipping a hollowed-out line.

---

## Step 7 — Report back

After draft 2, tell Bruce:

1. Path to the public file and each source-repo catchup written
2. What changed between draft 1 and draft 2 — which facts he corrected, which learnings came from him
3. **The scrub delta** — what was in the private layer and did *not* make it out, at category level ("held 3 company names, 1 deal decision, the whole personal lane").  He should never have to diff the files to know what was withheld.
4. **Anything flagged** — borderline calls the policy says cut but that he might want.  Surface these rather than silently dropping them.

Don't commit or open a PR unless he asks.

---

## Step 8 — Start the coming week's file

**Monday does two things: it closes last week and opens this one.**

After draft 1 goes out, create `fnr/.private/drafts/<YYYY-WNN>.wip.md` for the week *now beginning* — it lives in the private repo, so **commit and push it there**, and forward-looking.  Bruce wants to think about what outcomes he's after **before** the week runs, not reconstruct them afterward.

Sections:

- **Outcomes I want this week** — 🔴 his, left empty with a prompt.  Two or three, concrete enough to check on Friday.  Outcomes, not tasks: "transport binding chosen and the cohort comparison run", not "look at MCP libraries".
- **Carried over** — open threads from last week's catchups.  Machine-filled.
- **Known shape of the week** — the calendar table plus prep owed, and anything he's said is planned but unconfirmed.  Machine-filled.
- **Running notes** — empty, for him to append during the week.  The things a commit can't reconstruct: what a conversation surfaced, where an idea arrived, what felt wrong.  By Friday that material is gone unless it was written down, and it's the single biggest quality gap in draft 1.
- **Against the outcomes** — filled *next* Monday.  Did the stated outcomes happen?  What replaced them, and was the replacement better or just louder?

**This closes the loop.**  Next Monday, draft 1 reads this file first and opens by comparing intent to result.  That comparison is the thing a pure retrospective can never produce, and over a few months it's the honest answer to whether the career break is working.

---

## Conventions

- **Filename:** `<YYYY-WNN>.md`, ISO week, so the directory sorts chronologically.  Filenames are internal — Bruce always asks in plain English.
- **Cadence:** Monday morning — publish the week that just closed, and open the WIP file for the week now starting (Step 8).
- **Index:** `fnr/README.md` explains the format and the pun.  Don't maintain a table of contents there — `ls` is the TOC.
- **Backfill order:** chronological, so each week can lean on the prior week's state.
- **Don't repeat adjacent weeks.**  Assume someone reads in order.

## Common pitfalls

- **Publishing the raw pull.**  The public file is derived from the Step 3 catchups, not from `/tmp/fnr_week.json`.  Skipping the middle layer is how names leak.
- **Wrong ISO year at boundaries.**  Always `%G-W%V`.
- **Counting the hidden lane in public totals.**  See the stats footer rule.
- **Treating commit volume as importance.**  A 371-commit week can be one idea explored 371 times; a 12-commit week can be the week something clicked.  Read the subjects.
- **Quoting event prep notes.**  They read like public event write-ups.  They are not — they're diligence, about named people, written for an audience of one.
- **Writing a learning he didn't write.**  The failure mode this whole workflow exists to prevent.  Synthesizing a reflection out of a commit message produces something that sounds like insight, reads as publishable, and is fabricated.  Leave the slot empty and ask.
- **Paraphrasing his reflections into house style.**  His raw phrasing is the asset.  "The vampire is real" survives; "it's important to maintain work-life balance" is what's left after a well-meaning rewrite.
- **Smoothing the uncomfortable parts.**  He wrote that a room felt awkward and that his name tag still said Netflix.  An earlier draft had "recommend it."  The awkward version is the one worth publishing — don't sand it.
- **Trusting commits over his correction.**  If he says the fund repo predates the week and the commits suggest otherwise, the commits are missing context.  He's right.
- **Writing `Top of Mind for Founders` at all.**  It's his, and it's one item.  Producing three tidy synthesized lessons is the most seductive version of the fabrication problem, because they read like the best section on the page.
