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

Both files are gitignored and live in the about-me repo:

- `fnr/.private/repos.json` — which repos to read, where they are, and each one's `disclosure` level (`named` / `described` / `hidden`)

  **`disclosure` governs naming, not importance or reading depth.**  `described` means describe it without naming it — it says nothing about how central the repo is.  The most important repo in the registry is currently `described`, and it still drives most of every weekly.  Read every non-`hidden` repo closely regardless of its level; read `hidden` ones too, for the private catchup only.
- `fnr/.private/scrub_policy.md` — **read this in full every run.** It is the judgment layer: green/yellow/red categories, the five-question test, and the standing exceptions.

If `repos.json` is missing, stop and say so — there is nothing to read without it.  If `scrub_policy.md` is missing, fall back to the most conservative reading (name nothing, abstract everything) and tell Bruce the policy file is gone.

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
- Read existing `.claude/catchups/` in the source repos if the week is already summarized there — aifund has run this convention since May 2026; don't redo work
- Check `git log` in about-me itself for writing done that week
- **Read `fnr/.private/drafts/<this-week>.wip.md` if it exists** — the forward draft he started last Monday.  Its stated outcomes and running notes are the highest-value input you have, because they contain what he was *trying* to do and what happened outside version control.  Open draft 1 by comparing intent against result.
- **Pull the vetting queue** for `On the Bench` from **two** sources — read both, the second one especially:

  1. `findingalphas/evaluator/intake/intake.json`, `items[]` — the *processed* queue.  Filter `candidate_type == "technology"` and `track.status == "intake"`, sort `date_in` descending.  Read `candidate` for the one-liner; **`lab.experiment`, `track.zone`, and `registry_layer` are internal reasoning and never get published**.
  2. `aifund/fund1/deal_flow/outbox/requests.jsonl` — **the `findingalphas-request/v1` outbox, and usually the more important of the two.**  Event-driven intake lands here first and sits *unprocessed*, so it's the freshest picture of what he's actually just encountered.  Filter by `requested_at` inside or just before the week.

  **The outbox schema does the scrubbing for you — use it.**  Every record carries a `public_summary` written to be publishable; that field, lightly edited, is the item's line.  Everything else is private by construction: `id` encodes watchlist status and the private company it hangs off (`gcap:watchlist:<company>:<thing>`), `source_uri` is an internal path, and `private_source: true` says so outright.  **Never publish `id`, `source_uri`, or anything implying a company is on a watchlist.**  Name the public technology, drop the fund context that put it in the queue.

  **Reading a conference program is itself an intake source, separate from attending one.**  A batch of records sharing a `requested_at` and a common subject usually means he worked through an event's talk list, not that he was in the room — and whether he attends is irrelevant to what the research turned up.  Say "researching the Ray Summit program turned up a cohort", never "landed off Ray Summit", which implies attendance he may not have.

  Pick 3–4 and **strongly prefer ones that tie back to something already in this week's weekly** — an item that traces to an event or a build decision earns its place; a random pull from a 90-item queue doesn't.  Related items can be grouped into one bullet when they arrived as a cohort.
- **Pull his calendar for the week *after* the one being reflected on** — that's the raw material for `Next`.  Use the Google Calendar MCP (`list_events`, `startTime`/`endTime` bounding the following Mon–Sun, `orderBy: startTime`).  Count the one-on-ones, note any public events, note anything recurring, and reduce it to one or two sentences about the *shape* of the week.  Every attendee name, company, and email is red-list — the sentence carries counts and character, nothing else.
  - **The calendar is incomplete.**  He tracks events he's still deciding on outside it.  Ask what's planned but unconfirmed rather than assuming the calendar is the whole week.  **If an unconfirmed event is public, name it** — "still thinking about attending Ray Summit", not "probably one more event I'm still working out."  Vagueness about a public conference protects nothing and reads evasive; the only reason to abstract an event is that it isn't public.
  - **Check whether next week's meetings connect to this week's build work** — and get the direction right.  Cross-reference attendees against the research subjects and outcomes in the Step 3 catchups.  The link usually runs **build → meeting**: he researches a company *in preparation for* talking to its founder, so the week's tech is prep, not a downstream consequence.  Getting this backwards ("the meetings fed the build") inverts how he works.  Say it without naming anyone: "tech built this week was in prep for meeting two portco founders, and will hopefully make those meetings richer."  That tie is the point of the section.

**The private catchups in Step 3 name everything; the public file in Step 4 names almost nothing about the build.**  That asymmetry is the design, not an oversight — don't "improve" the public file by restoring detail from the catchup.

**The events output deliberately omits `entities[].note` and `entities[].disposition`.**  Those are diligence judgments about real people who were in a social room with Bruce.  Read them from the prep file when you need context; they are red-list and never publish, not even paraphrased.

---

## Step 3 — Write the detailed catchup into each source repo

For every repo with commits that week, write `<repo>/.claude/catchups/<YYYY-WNN>.md`.  **Unscrubbed** — this is Bruce's own record on his own machine.

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY> (<N> commits, <N> PRs)

**<One-line theme for this repo's week.>**

### <Area — 3–6 words>
- <what shipped, what it replaced, what it enables>
- <PR numbers as `(#NN)`; paths as relative paths; name everything>

### Corrections
- <what got refuted, reverted, or found wrong — track these, they're the best signal>

Open threads: <what's mid-flight going into next week>
```

6–12 bullets, ~150–250 words.  Group aggressively on a 300-commit week; signal, not completeness.  Skip typo fixes and intra-feature steps.

If a repo already has a catchup for that week, update it rather than duplicating.

These repos are private, and aifund already commits its catchups — so committing is fine and often right.  Just don't do it unattended: write the file, tell Bruce, let him decide.

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

<1–2 short paragraphs. Shape, not names.>

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
- **`On the Bench` runs as long as the week's intake earns.**  Roughly 3–5 bullets, but **listing the tech he's seeing IS the point of the section** — don't trim it to look tidy.  Group items that arrived as a cohort into one bullet (the Ray Summit batch is one bullet, not five); that keeps it readable without dropping anything real.
- **Framing decides whether `On the Bench` reads as curiosity or as a leaked pipeline.**  "I want to know where the durability lives" is learning; "evaluating for the infra thesis" is not.  Never publish `lab.experiment`, `track.zone`, `registry_layer`, or any conclusion.
- **`Top of Mind for Founders` is ONE thing, hand-written.**  Not two, not three, not a list.  Bruce writes it; draft 1 leaves a prompt and draft 2 transcribes.  ("For now" — if he later wants help drafting it, he'll say so.)

  **The recurring seam is talent** — how to get the most out of people, how to motivate, hire, grow, and keep a culture alive.  What works at 2–5 people differs from 1–5k, but the underlying principles are the same.  That's the thread the section pulls on week over week, and it's the thing he has 26 years of earned right to say.  When prompting him for this block, prompt *into* that seam: what did this week's advisory conversations surface about people, hiring, motivation, or culture?
- **`Rooms I Was In` is conditional** on having attended something.  Drop the whole section on a week with no events rather than writing "no events this week".
- **Stats go at the top of `Building`,** as an italic line: commits, PRs, repo count, and the tech/fund split.  **Use publishable totals only** — `commits_publishable`, never `commits_all`.  The difference is the `hidden` repos, and publishing the delta reveals that hidden work exists and how much.  Repo *count* is fine; repo *names* are not.
- **Never name what he's building.**  Not the repo, not the project, not the GitHub URL, not a feature set that identifies it.  This is the single rule most likely to be violated by accident, because the work is genuinely interesting and the names are right there in the commits.  Research subjects it evaluates are a per-mention allowance, not a standing one — keep them sparse, since a list of subjects plus the shape of the tooling lets a reader infer the product.

### Voice

Direct, first person, past tense, active voice.  Two spaces after a period (repo convention).  Bruce's register: concrete, a little dry, willing to say what didn't work.

**Keep his insider vocabulary.**  `portcos`, `deal flow`, `intake`, `the loop` — he wants the jargon, and it signals he's inside this world rather than commenting on it.  Don't expand shorthand into plain English for an imagined general reader; the people he's writing for already speak it, and the ones who don't can infer it.  This is a special case of the transcribe rule: his word beats your clearer word.  **Don't editorialize** — "shipped the eval harness" not "excited to share that I shipped the eval harness."  No LinkedIn cadence, no "thrilled", no rhetorical questions as section openers.  Bold sparingly, for the one thing that actually mattered.

**The update is short; the learning is the point.**  Bruce's own words on the format: keep the update concise, then one or two sentences of learning.  `Building` and `Fund & Advisory` each end with a bold `**Learning.**` paragraph — that's the part he values and the part a reader remembers.  Resist letting the update swell to fill the section.

Length: **a rule of thumb, not a limit.**  Draft 2 tends to land around 700–1100 words.  If a dense week runs to 1100 or beyond, that's fine — **never cut good content to hit a number.**  The number exists to stop padding, not to force trimming.  Cut a line because it's weak, repetitive, or says nothing; never because the total is inconvenient.  A quiet week should be genuinely short rather than inflated, for the same reason.

The only section with a real cap is `Top of Mind for Founders` — one item, because he says so.  `On the Bench` runs as long as the intake earns.

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

After draft 1 goes out, create `fnr/.private/drafts/<YYYY-WNN>.wip.md` for the week *now beginning* — gitignored, private, and forward-looking.  Bruce wants to think about what outcomes he's after **before** the week runs, not reconstruct them afterward.

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
