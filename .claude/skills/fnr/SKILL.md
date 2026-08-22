---
name: fnr
description: >
  Write Bruce's weekly Field Notes & Reflections (FNR). Pulls a week of commits
  across his private repos plus the calendar events he attended, writes a
  detailed private catchup into each source repo, then publishes a scrubbed
  public reflection to `fnr/<YYYY-WNN>.md` in the about-me repo. Sections cover
  what he built, fund and advisory work, rooms he was in, and the leadership
  lessons top of mind for founders. Use when he wants to write, draft, or
  backfill a weekly. Accepts natural args: "this week", "last week",
  "last 2 weeks", "the week of Aug 17", "backfill". Triggers: "/fnr",
  "write my weekly", "field notes", "what did I do last week",
  "weekly reflection", "time for the weekly".
---

# FNR — Field Notes & Reflections

The Monday-morning weekly.  Bruce left Netflix in August 2026 and is on a "no-break career break": building, advising founders, seed investing, learning.  FNR is the public record of that experiment — and the name is a pun on Netflix's Freedom & Responsibility, which is the joke and also the point.

**Two layers, and the distinction is the whole design:**

| Layer | Where | Audience | Contains |
|---|---|---|---|
| **Ground truth** | `.claude/catchups/<week>.md` inside each source repo | Bruce only | Everything. Names, decisions, hashes, dispositions. |
| **Public weekly** | `fnr/<week>.md` in about-me | The internet | What survives the scrub policy. |

The source-repo catchups are the record.  The public file is a *derivative* of them — never write the public file from the raw pull directly, because the intermediate step is where the thinking happens.

---

## Step 0 — Read the private config

Both files are gitignored and live in the about-me repo:

- `fnr/.private/repos.json` — which repos to read, where they are, and each one's `disclosure` level (`named` / `described` / `hidden`)
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
- Read the event **prep files** (`prep_file` in the events output).  These carry the actual conversations, questions, and follow-ups — the richest source for the founders section, and also the most sensitive material in the whole corpus
- Read existing `.claude/catchups/` in the source repos if the week is already summarized there — aifund has run this convention since May 2026; don't redo work
- Check `git log` in about-me itself for writing done that week

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

## Step 4 — Write the public weekly

Save to `fnr/<YYYY-WNN>.md` in about-me.  **Derive it from the Step 3 catchups**, running every line through `scrub_policy.md`.

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY>

**<One sentence: the theme of the week. Concrete, not a mood.>**

<2–4 sentences of framing. What the week was actually about, and why it
mattered. This is the part a human reads if they read nothing else.>

## Building

<What got built and what was learned building it. Name public research
subjects and problem classes freely; abstract unshipped specifics. 3–5
bullets or short paragraphs. Corrections and refuted assumptions belong
here and are the most credible thing in the document.>

## Fund & Advisory

<The investing and founder-advisory side. Shape, not names — unless the
company is already public. 2–4 bullets.>

## Rooms I Was In

<Events attended. Name + host + public link. One line each on what was
actually interesting — an idea, a shift in how people are talking about
something. Never the guest list, never a diligence read on anyone there.
Omit the section entirely if the week had no events.>

## Top of Mind for Founders

<The leadership section. 2–3 lessons surfacing from the week's advisory
conversations, anonymized to the pattern. This is the section that ages
best and gets read most — give it real weight, not a throwaway line.
Each one: the pattern, why it bites, what to do instead.>

## Next

<2–4 lines on what's queued. Honest, not aspirational.>

---

_<N> commits across <N> repos · <N> PRs · <N> events · <split, e.g. "~70% building, ~30% fund">_
_Part of a [no-break career break](../roles.md). How these are made: [fnr/README.md](README.md)._
```

### Section rules

- **Always include `Building` and `Top of Mind for Founders.`**  They're the spine.  A quiet week says so in one honest line — it does not skip the header.
- **`Rooms I Was In` is conditional** on having attended something.  Drop the whole section on a week with no events rather than writing "no events this week".
- **`Top of Mind for Founders` needs real sourcing.**  Draw from the week's advisory conversations, event prep files, and founder-facing notes.  If the evidence is thin, say so and ask Bruce for one or two — don't invent a leadership lesson to fill a slot.  A fabricated lesson is worse than a short section.
- **The stats footer uses publishable totals only.**  `commits_publishable`, never `commits_all` — the difference is the `hidden` repos, and publishing the delta reveals that hidden work exists and how much.

### Voice

Direct, first person, past tense, active voice.  Two spaces after a period (repo convention).  Bruce's register: concrete, a little dry, willing to say what didn't work.  **Don't editorialize** — "shipped the eval harness" not "excited to share that I shipped the eval harness."  No LinkedIn cadence, no "thrilled", no rhetorical questions as section openers.  Bold sparingly, for the one thing that actually mattered.

Length: 600–900 words.  Five sections with real content don't fit in less, and padding to reach a number is worse than either bound.  A launch week or an unusually dense one may run to ~1000; a quiet week should be genuinely short rather than inflated.

---

## Step 5 — Report back

Tell Bruce:

1. Path to the public file and each source-repo catchup written
2. The week's headline in one sentence
3. **The scrub delta** — what was in the private layer and did *not* make it out, at category level ("held 3 company names, 1 deal decision, the whole personal lane").  He should never have to diff the files to know what was withheld.
4. **Anything flagged** — borderline calls the policy says cut but that he might want.  The policy's escalation rule: surface these under `## Flagged for review` in the private draft rather than silently dropping them.

Don't commit or open a PR unless he asks.

---

## Conventions

- **Filename:** `<YYYY-WNN>.md`, ISO week, so the directory sorts chronologically.  Filenames are internal — Bruce always asks in plain English.
- **Cadence:** Monday morning, about the week that just closed.
- **Index:** `fnr/README.md` explains the format and the pun.  Don't maintain a table of contents there — `ls` is the TOC.
- **Backfill order:** chronological, so each week can lean on the prior week's state.
- **Don't repeat adjacent weeks.**  Assume someone reads in order.

## Common pitfalls

- **Publishing the raw pull.**  The public file is derived from the Step 3 catchups, not from `/tmp/fnr_week.json`.  Skipping the middle layer is how names leak.
- **Wrong ISO year at boundaries.**  Always `%G-W%V`.
- **Counting the hidden lane in public totals.**  See the stats footer rule.
- **Treating commit volume as importance.**  A 371-commit week can be one idea explored 371 times; a 12-commit week can be the week something clicked.  Read the subjects.
- **Quoting event prep notes.**  They read like public event write-ups.  They are not — they're diligence, about named people, written for an audience of one.
- **Letting `Top of Mind for Founders` decay into platitudes.**  "Hire slowly" is not a lesson.  "Two founders this week both discovered their eval suite was measuring the thing they already knew" is.
