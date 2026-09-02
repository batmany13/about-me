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
| `meeting` | **Meeting / Partner Notes** | Conversations with people: 1x1s, customer and partner calls, design reviews, events attended, intros, interviews. Anything whose subject is a *person or a room*. |
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
uv run $SKILL/pull_week.py --repo . --list-weeks | head -40
```

Config is optional and lives at `.claude/catchup.config.json` in the target
repo — the single place anything repo-specific belongs. With no config the skill
still works; it just cannot name people, know the repo's own vocabulary, or find
the artifacts that describe its subjects.

| Block | What the repo declares |
|---|---|
| `authors` · `categories` · `summary` | people, vocabulary, length budget |
| `learnings.grades` | its own evidence ladder, if it has one |
| `themes.confirm_share` / `thin_share` | what share of a week makes a theme |
| `subjects.artifacts` | **where its findings about subjects live** — see Step 2b |
| `method_notes.path` | where it keeps its own catchup lessons |

See `reference/config.md`; a ready-to-copy starting point is in
`assets/catchup.config.example.json`.

If the repo has no config and the week's classification comes out mostly
`other`, say so and offer to write one. Don't silently accept a bad split.

**Read the repo's own method notes if it has any.** Config may point at them with
`method_notes.path`; the convention is `<out>/method-notes.md`. That is where a
repo keeps what it has learned about running *its own* catchups — which themes
recur, which past summaries went wrong and why. It is deliberately not in this
skill: the skill is portable and those specifics are not.

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
uv run $SKILL/pull_week.py --repo . 2026-W35 > /tmp/week.json
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
length correlates with substance.

**That correlation inverts for relationship work, and it inverts hardest on the
weeks most worth reading.** When a repo's convention is that a conversation lands
in a file, the PR carrying it has almost nothing to say — the substance is in the
artifact, and the body is a sentence pointing at it. On one 20-PR week the two
shortest bodies in the week (1,209 and 539 characters, ranked 17th and 20th of
20) were the week's two most consequential conversations, and both were dropped
from the summary entirely. **Never rank a PR's importance by its body length alone. Cross-check
against the subject artifacts it touched** — which is what the `NEW` rows in
`propose` are for. `--pr-body-limit N` truncates, `0` disables the
cap, `--no-prs` skips them entirely when you only need counts.

## Step 2b: Read the code — mandatory, not optional

**A commit subject is what someone said they did. A PR body is what they meant.
The diff is what exists.** Those diverge, and they diverge hardest on exactly the
work worth reporting. Skipping this step produces a catchup of intentions.

The pull hands you four things for this, and you must use all four:

| Field | The question it answers |
|---|---|
| `structure.added` | **What was built.** New files are the closest mechanical proxy for construction |
| `structure.deleted` / `renamed` | **What moved or was retired** — a deletion is a decision |
| `modified` | **What changed inside files that already existed** — see below |
| `hot_files` | **Where the week's argument happened** — a file touched by 20 commits is contested |
| `biggest_commits` | Where the mass is, by lines rather than by subject |

**`modified` is the field most easily skipped and the one that hides the most.**
New files announce themselves; a module rewritten in place looks exactly like a
module with one line touched, in every other view. Each row carries insertions,
deletions, commit count, the file's current length, and two ratios:

- **`churn_ratio`** = deletions ÷ total churn. Near `0` the file only grew; near
  `0.5` it was reworked line for line; near `1` it was stripped.
- **`replaced_share`** = deletions ÷ current length — the cheapest answer to
  *rewritten or merely edited*. A 400-line change to a 4,000-line module and the
  same change to a 500-line one are different events and identical raw numbers.

A `current_lines` of `null` means the file no longer exists on the ref: it was
modified during the week and removed later, which is its own signal and not an
error.

The shape to look for is a file at, say, **+1,156 / −191 over 13 commits** with
a `churn_ratio` near 0.1 — a module that grew by half its size, purely
additively, appearing in no added-file list and in no commit subject. Opening one
of those is routinely how you find that a component quietly took on a second job.
See the repo's method notes for the real case.

Then **actually open things**:

```bash
git show --stat <sha>            # shape of one commit
git show <sha> -- <path>         # the change itself
git diff <base>..<head> -- <dir> # a subsystem across the week
sed -n '1,80p' <new-file>        # read what was built, not its commit message
```

Read the **new files first**, then the top of `modified` — in that order,
because construction is easier to read than accretion and it tells you what the
accretion was for. A week that added a store interface with two
implementations, a migration and an acceptance script built something; a week of
200 modifications to prose did not, and the commit log renders them identically.
The failure this prevents is reporting the plan instead of the thing: a PR body
saying a piece of work was "activated and scoped" while the diff contains a
working component with two implementations, a migration and a proof script.
**An extraction that reads only PR bodies reports intentions.** The real case is
in the repo's method notes.

Beware size as a proxy for substance in the other direction: one week's largest
commit was `+42,926 / -0` across three files, and it was a pinned reference document.
Check `files` against `insertions` before believing a number.

Also read `git show --stat <sha>` for any commit whose subject is ambiguous.

Two things in that output decide how much to trust it:

- **`category_why`** records the rule that classified each commit.
  `path:` is strong evidence, `keyword:` is weaker, **`path-weak:`** means a rule
  matched a small share of the diff and `default` means nothing matched at all.
  Re-classify those yourself in pass 1 — the script's guess is a starting point,
  not a verdict. Categories are tested in precedence order (meeting, technical,
  other) and the first to clear the evidence bar wins, so a broad glob cannot
  outvote a narrower one nested inside it.
- **`commits` carries only what is reachable from the mainline ref.** A
  pre-squash branch commit and the mainline commit it became share a subject but
  not a sha, and the branch copy is reachable from nothing after the merge — it
  exists in the local clone until git prunes it, and in no other clone at all.
  Anything dropped is reported in `off_primary_count` / `off_primary_reasons`,
  never silently. `commit_count_all_refs` is the all-refs figure and is
  machine-specific: it exists so the drop stays visible, not to be published.
- **`prs` is bounded by GitHub's `mergedAt`**, so it is the set that actually
  merged inside the week. Numbers scraped from commit subjects that merged in
  some other week appear under `prs_mentioned_outside_week` — a commit
  *mentioning* a PR never puts that PR in the week. Without `gh` there is no
  authority to bound against and `prs_source` says so.
- **`structure`, `modified`, `hot_files` and `biggest_commits`** are the code-mining inputs —
  see Step 2b. They are not optional colour: they are the only fields that
  describe what the week *built* rather than what it *said*.
- **Weeks are UTC.** Git renders author dates in the author's local zone, so
  slicing the date off `%aI` gave a local week that disagreed with GitHub's UTC
  `mergedAt` — work done on a Sunday evening in Pacific belongs to the Monday,
  and three PRs have been observed landing in the wrong week because of it.
- **`fetched`** — the pull runs `git fetch origin` first, because the primary
  count is measured against `origin/HEAD` and a stale remote ref silently
  *undercounts* the week. On one real 20-PR week a stale ref reported 12 commits
  instead of 55, and nothing in the output looked wrong. If `fetched` is `false`
  the fetch failed and the primary number is suspect; `null` means `--no-fetch`.

If the week has 0 commits, say so and stop. Don't write an empty file.

## Step 3 (pass 1): Themes first — hypothesise, then weigh

**The output has three sections, and they answer three different questions.**
Getting them mixed is the failure this format keeps falling into.

| Section | Question | Types | Ranked by |
|---|---|---|---|
| **Themes** | What moved? | `theme`, owning `thread` / `decision` / `correction` | **weight** |
| **Meetings & Notes** | Who did we meet, what did they show? | `meeting` · `org` · `person` | date |
| **What we learned** | What do we now know? | `concept` | evidence **grade** |

**Weight and grade are different axes and must never be merged.** A small
self-contained fix grades at the top of the ladder trivially — you ran it, you
saw it — and weighs almost nothing. Under one combined ranking those findings
displace the week's actual movements every time. Weight is for work we did;
grade is for claims about the world.

### 3a · Hypothesise, from the clustering rather than from memory

```bash
uv run $SKILL/entities.py propose 2026-W35 --repo . --pull /tmp/week.json
```

This reports where the mass actually went — directories by commits and churn,
and every merged PR with the directories it touched. **Name 2–5 candidate themes
from it.** Do not skip to writing: reading the week and then deciding what
mattered reliably surfaces whatever is easiest to phrase, because a
self-contained fix has one commit and a crisp lesson while a redesign spanning
nine PRs has neither.

PR titles are the best seed in the file. Someone already decided those commits
belonged together and wrote down why.

### 3b · Weigh every candidate before writing any of it down

```bash
uv run $SKILL/entities.py weigh 2026-W35 --repo . --pull /tmp/week.json \
  --label "<your candidate theme>" --prs 12,14,17,21
```

| Share of commits | Verdict |
|---|---|
| ≥ 15% | **CONFIRMED** — big enough to lead |
| 5–15% | **THIN** — real work, but supporting detail |
| < 5% | **DROPPED** — record the hypothesis, do not lead with it |

A theme with no measured weight is an opinion about the week, and `upsert`
refuses one: a `confirmed` theme requires `weight`, `moved` and
`why_it_matters`. **A dropped hypothesis is still recorded** — as a theme with
`disposition: dropped`, which renders as one line under `Other`. "We thought X
was a theme and it was four commits" is a real result, and deleting it hides
that the question was ever asked.

Then read the code behind each confirmed theme (Step 2b) and record what proves
it in `evidence[]`.

### 3c · Everything else hangs off a theme

Threads, decisions and corrections carry `theme: <id>` — a directed parent edge,
so the renderer groups them under the arc instead of listing leaves side by side.
Anything genuinely outside every theme goes to `Other`.

`why_it_matters` is required on a confirmed theme and is the line the reader
actually needs: one sentence, no jargon, for someone who was not here.

**Meetings, orgs and people are their own section** and are not themes, however
interesting the evening was — a five-company event that is 9% of commits and 2%
of churn is a real evening and not a movement.

**A conversation is a `meeting` entity. It is not a field on the company.** The
company is `org`, the humans are `person`, and the dated conversation between
them is its own record with its own date — which is what the section is ranked
by. Folding the meeting into the org looks harmless and costs three things: two
conversations with the same company in different weeks collapse into one record;
a conversation with no company — an event, an intro, a 1x1 — has nowhere to live;
and, worst, **a company whose week was *only* a conversation produces no entity
at all**, because there was no company-state change to justify an `org`. A real
week created eight conversation logs, wrote zero `meeting` entities, and lost the
two conversations that had no other news attached. If someone sat
down with someone, there is a `meeting`.

**Name every person, including the ones who were only researched.** A `person` is
warranted by the repo doing work on them, not by their being the headline of a
meeting — someone who got a full profile written about them this week is tracked;
someone named only in passing is not. The test is whether the repo now knows
something durable about that human.

**But never render a researched person and a met person the same way.** They are
different relationships, and flattening them turns a roster into a claim of
contact nobody made: three people from one organization were once listed beside
the people actually met, on a record whose own notes said no contact had happened
yet. The states are: **met**, **contacted — meeting
upcoming**, **contacted — not met**, **meeting prepped but outcome unrecorded**,
and **tracked — no contact**. None of those middle rungs is pedantic. A prep note
is written before the room and is no evidence anyone was in it; an open intro
that nobody has answered is the thing that most quietly expires; and a name the
repo researched but never wrote to is not a relationship at all.

**Who was met is derived from the meeting's own attendee list — never asserted on
the person.** (The pre-meeting rungs come from the person's own `contacted` /
`meeting-upcoming` tags, because before a meeting exists there is nothing to
derive from — and saying an email went out cannot overstate contact in the
direction that matters.) The renderer reads it from the `meeting` entities, so the only way
to mark someone met is to record the meeting. That is deliberate: the two cannot
drift, and a person who shows as not-met either genuinely wasn't, or the meeting
is missing from the store. **Both of those are findings.** The second one is how
you discover that a conversation happened and was never written down — which,
in a repo whose convention is that conversations live in files, also means the
evaluation is still carrying open questions the conversation may already have
answered. Say so, and say which records are now stale.

### Altitude: a learning is about the subject, not about a defect in it

The subject rule keeps out maxims. It does not, on its own, keep the **altitude**
right — and getting that wrong is the more common failure, because a defect is
concrete, quotable and feels like a finding.

**The question a learning answers is "what can this now do that it could not?"**
Not what state our evidence is in.

| Too low | The altitude that is useful |
|---|---|
| "its egress policy fails open on one code path" | "a live VM can now be forked, checkpointed, moved and forked again — warm roots compose instead of being one-shot" |
| "four repositories it cites are private 404s" | "the lab shipped an agent harness, not a model, and its plugin substrate is a third-party framework nobody was tracking" |
| "its value sits behind an account we do not have" | "a cache hit became a validated computation rather than a key lookup, so changing the transform logic invalidates correctly" |

The three on the left are all true and all **evidence-status notes** — they say
where our access stopped. Those belong on the subject's own record, not in a
learnings section. A defect belongs **inside** a learning as its evidence, never
as its headline.

The test: *would this sentence help someone decide whether to use, buy, or build
on this thing?* A bug found while looking usually would not; a capability that
did not exist last month usually would.

**Where capability deltas actually live.** Subject artifacts commonly carry a
release or changelog table — a `what changed` column per version. That table is
the single densest capability source in a repo, and it is what a commit log and a
PR body are both incapable of reproducing, because they describe changes to the
*evaluation* rather than to the *thing evaluated*. Read it first.

**New subjects are themselves a learning.** A week that pulled forty new
candidates into the corpus learned about an area, not just about its own
pipeline. Ask what entered that nobody was tracking, and whether several arrivals
describe one architecture — three separate rows on cache tiering, phase
disaggregation and cache-aware routing are not three findings, they are one
account of how a serving stack is now built.

**Read the repo's own artifacts about the subject — not the commits that changed
them.** A commit log and a PR body describe *what changed in the repository*; if
the repo produces evaluations, research bundles, reports, benchmarks or design
documents *about* something, those describe **the subject**. A catchup mined only
from PR bodies reports which files moved in the evaluation, not what the
evaluation found.

This is not left to memory. A repo declares where those live under
`subjects.artifacts` in config, and `propose` then lists the ones the week
touched, **ranked by how much each moved**, with the repo's own `read_first`
hint:

```
## Subject artifacts this week touched — READ THESE for learnings
   3,166  research/<subject>/README.md
   1,071  evaluations/<date>_<subject>/findings.json
```

A repo that declares none gets told to, because there is no generic way to guess
where a repository keeps its findings. Look for the summary or headline field
those artifacts carry — usually someone's considered one-sentence answer written
with the whole subject in front of them, and better than anything reconstructible
from a diff.

**A blocked result is a finding.** Where an evaluation stopped — an account, a
credential, a budget, a human decision — is often the most decision-relevant
thing in it, because it names exactly what would have to be true to know more.
Record it as a learning, not as an absence.

**A `concept` must name a `subject`** — the technology, company or architecture
it is about. That single required field is what keeps general engineering maxims
out. *"A test that accepts either outcome is not a test"* names no subject, was true
before this week and will be true after it, and is not something the week taught
anyone. What belongs here is what the work found out about the world: someone's
published number that did not survive your own measurement, a service granting more
authority than it documents, a dependency that turns out to be someone else's.

**Cite what landed under `prs`, and what did not under `open_prs`.** The
validator holds `prs` to PRs that actually merged in that week, because a
catchup reports what shipped. Work that happened but is still on a branch is
still the week's work — put its PR in `open_prs` and it stays checkable while
open. Never cite a branch commit: it is reachable from nothing once the PR
merges, so it becomes a reference no other clone can resolve.

**Reuse ids.** Check the store before creating anything; themes especially
accumulate across weeks, and a new id for continuing work silently forks the
arc.

```bash
uv run $SKILL/entities.py list
uv run $SKILL/entities.py upsert --repo . --week 2026-W35 < extraction.json
uv run $SKILL/entities.py validate --repo .
```

**Types:** `theme` · `meeting` · `person` · `org` · `thread` · `decision` ·
`correction` · `concept` · `other`. **Statuses:** `active` · `done` · `parked` ·
`dropped`.

**Less is more, and it is a hard rule rather than a preference.** Aim for
**2–4 themes, at most 3–4 children each, and 20–25 entities total**, of which
**at most 8–10 are learnings**. A reader takes away two or three things from a
week; a list of fourteen guarantees none of them lands. Fifty entities means
commits are being transcribed rather than entities extracted, and an
over-decomposed week buries its own movements.

The discipline is to drop the weakest, not to shorten everything. A learning that
survives is worth its full paragraph; one that does not belongs in the store,
unrendered, where the summary can name it in a clause.

## Step 3b: Record the week's stats

```bash
uv run $SKILL/entities.py record-week --repo . --week 2026-W35 --pull /tmp/week.json
```

Writes `<out>/weeks/<YYYY-WNN>.json`: commit and PR counts, what was ignored and
why, per-author and per-category splits, top directories, the entity ids the week
touched, its corrections, and which entities carried over from earlier weeks.

**This is the only machine-readable record of the week's size.** Prose cannot be
added up. Anything reading across repos — a cross-repo roll-up, a quarterly, a
stat line — reads these files, and without one a week is invisible to every
layer above this skill even though its summary reads fine.

Run it *after* the entity upsert, so the record captures the entity ids.

## Step 4 (pass 2): Render the summary

```bash
uv run $SKILL/entities.py render 2026-W35 --repo . --no-open > /tmp/body.md
```

The three sections are **derived**, not composed. Write only the title line and
the one-sentence week theme above them, and the `Open threads` and stat lines
below. If something belongs in the summary and is not in the render, the fix is
to add the entity — never to write it in beside the derived text, which is how
the prose and the store drifted apart before.

```markdown
# <YYYY-WNN> — <Mon D–D, YYYY> (<N> commits, <N> PRs)

**<One sentence: what this week was.>**

<the render output: Themes / Meetings & Notes / What we learned / Other>

PRs merged: <#NN, …>

Open threads: <what is mid-flight going into next week>

---
*Stats: …*
```

Check it before committing:

```bash
uv run $SKILL/entities.py check-summary 2026-W35 --repo .
```

It fails on any `#NN` the prose cites that no entity carries.

**Length:** the repo's `summary` budget, which is **per section** — one total
number cannot govern three sections doing three different jobs, because trimming
to hit it cuts whichever section is easiest rather than whichever is weakest.
When a section is over, tighten its entity fields rather than the render: the
store should carry the shorter text too. Never trim by dropping a confirmed
theme or a graded learning.

**Weight-proportionality is a rule inside Themes, not across sections.** An
evening that is 2% of a week's churn can still earn a third of the summary,
because "who did we meet and what did they show" is not the question Themes
answers. Do not shrink a section because its subject was a small share of the
commits.

**Always close with the stat line**, every figure taken from `weeks/<W>.json`
rather than counted by hand.

**One shape, everywhere.** `##` for the sections; `###` only for a theme, which
is the one unit that carries a body, a why-it-matters line and children of its
own and so cannot be a single bullet. **Every leaf is `- **Title** — text`** —
meetings, learnings, theme children, Other, all identical. A section that invents
its own formatting reads as a different document stapled in, which is exactly how
Meetings looked when it briefly used sub-headings and paragraphs while everything
around it used bullets.

**Meetings & Notes is one synthesised entry per conversation — not one bullet per
entity.** The store keeps `meeting`, `org` and `person` apart because each
accumulates across weeks and they are genuinely different records. The summary is
a *view*, and printing all three verbatim tells the same conversation three times:
the meeting narrates it, the company restates it as company state, and the person
restates it again as what they are like. Grouping them under a shared parent fixes
the layout and not the redundancy — the company still appears twice inside its own
group, saying nearly the same thing.

So the meeting's `note` **is** the synthesis, and what the company and the people
contributed belongs inside it. A reader needs three things from a conversation:
**who was in it** (the title carries the names), **the one thing that came out**,
and **what is now owed or still to ask** — which go in the entity's `owed[]` and
`asks[]` and render as two sub-bullets. That last part is the half that expires,
and it was the half being dropped while three overlapping narrations were kept.

**Read the repo's own follow-up sections to fill them.** A repo that keeps meeting
notes almost always already has this — a "Support / follow-up" list, an action
list, a checklist. It is the densest part of the artifact and a commit log cannot
reproduce it.

Companies nobody sat down with get one entry, and their people become a **`Who:`**
contact clause rather than bullets of their own — someone unmet on live work is
an action item, not a profile. **Every entity appears exactly once.**

**Voice:** direct, terse, past tense, active. The reader was not here and does
not have the context; a bullet that only makes sense to someone who lived the
week is a bullet that failed.

## Step 5 (optional): Sync entities to DeepVista

Only when config sets `deepvista.enabled: true`. See
[`reference/deepvista.md`](reference/deepvista.md) for the full prototype —
endpoint, auth, and the one gotcha that makes cards invisible if you miss it.

**Register the server from the skill, not by hand.** The requirement travels
with the code that has it:

```bash
uv run $SKILL/deepvista_cards.py install-mcp --repo .            # writes .mcp.json
uv run $SKILL/deepvista_cards.py install-mcp --repo . --scope user   # prints the once-per-machine command
```

Idempotent, writes **no credentials** — the server does OAuth 2.1 with dynamic
client registration, so a repo file holds a name, a transport and a URL and
nothing else. It refuses to overwrite a conflicting entry.

It prefers the **`mcp-remote` proxy form**: that proxy runs the OAuth itself and
caches the token under `~/.mcp-auth`, so one browser sign-in makes every later
session headless — agent runs included. Handing the flow to the host app's own
MCP client instead (`type: http`) means it can only be done wherever that app
exposes a connect UI. The proxy costs a **Node 18+** dependency, since `npx`
runs it.

That preference is now **conditional on the runtime being there**. It used to be
unconditional, which meant `install-mcp` would write an `npx` entry onto a
machine with no Node, report success, and leave the failure to surface a session
later as `deepvista (ENOENT): Executable not found in $PATH: npx`. `--transport
auto` (the default) picks the form this machine can actually start;
`--transport mcp-remote|http` forces one. Verify before trusting it:

```bash
uv run $SKILL/deepvista_cards.py doctor --repo .    # runtime + entry + endpoint; exits 1 on a break
```

The first sign-in is still a human step, and a *fresh* session is required
because MCP servers connect at start-up. Sequence the work accordingly: an agent
does `install-mcp` and `plan`, a human does the one browser flow, then an agent
pushes — every time after that, an agent can do all of it.

**No API key is required** — the server does MCP OAuth with dynamic client
registration. Add the `.mcp.json` entry with no `headers`, then run `/mcp` in an
**interactive** session and sign in through the browser; a non-interactive
session has no prompt to answer. If a key path ever appears, it belongs in
`~/.config/secrets.env`, exported before the session — never in a repo file and
never read into the transcript.

```bash
uv run $SKILL/deepvista_cards.py plan --repo . --week 2026-W35
```

Emits one item per entity with `action: create | update | skip`. Call the
DeepVista MCP card tool for each, then record what came back:

```bash
uv run $SKILL/deepvista_cards.py record --repo . --id <entity-id> --card-id <returned>
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

## Relationship to FNR

This catchup is the **ground truth** for this repo in one week: unscrubbed,
names and all. The public weekly at `about-me/fnr/<week>.md` is *derived* from
these across several repos and run through a scrub policy. Write freely here —
the scrubbing happens downstream, never in this file.

---

## Keeping the copies honest

This skill is edited in one repo and pointed at from the others. When a copy
does exist, a fix found in the copy has to travel back to canon — never
hand-transcribed between them, because the two then differ in ways nobody
diffed.

> **Note:** earlier versions of this document described a `scripts/deploy.py`
> with `--check` / `--pull-back` / `--check-all`. **That script is not part of
> this skill.** If a repo has one, it is that repo's own tooling; if you need the
> behaviour, write it there rather than assuming it ships here.

## Running under another agent runtime

`.claude/skills/` is the authored canon; a second runtime should **point at it**,
never hold a copy. A copied `.agents/skills/` directory works the day it is made
and diverges silently from then on, because the copy is what that runtime reads.
`deploy.py` reports which state a repo is in after every deploy. Details and the
one-line fix: [`reference/portability.md`](reference/portability.md).

The scripts are plain Python over `git` and `gh` with no runtime-specific calls,
and `/catchup` is a convenience rather than the interface — the skill can be
followed directly. The only model-called dependency is the optional DeepVista
sync, which is off by default.

---

## Common pitfalls

- **Wrong ISO week-year at boundaries.** Always `%G-W%V`, never `%Y-W%V`.
- **Publishing the wide commit count.** `commit_count_all_refs` spans all refs
  and differs between machines. Publish `commit_count`.
- **Citing a sha the extractor was handed but nobody else can resolve.** Run
  `entities.py validate` before committing: it checks every cited sha against
  the mainline ref and every cited PR against the week it merged in. Pre-squash
  branch shas resolve on the machine that made them and nowhere else, and each
  usually has an identical-subject twin on the mainline that went uncited.
- **Putting a PR in the week because a commit mentioned it.** A subject reading
  "…from the PR #NN session" is a mention, not membership; PR weeks come from
  GitHub's `mergedAt`. `validate` fails on this now.
- **Forking an entity that already exists.** The most damaging failure here,
  because it is silent: the history just stops accumulating. Check `list` first.
- **Transcribing commits as entities.** If an entity's note could only ever be
  written once, it is evidence, not an entity.
- **Commit count is not importance.** A 300-commit week can be one idea explored
  300 times; a 4-commit week can close a quarter of work.
- **Letting `other` absorb everything.** A repo whose weeks are 70% `other` needs
  category rules in its config. Say so rather than shipping a vague summary.
