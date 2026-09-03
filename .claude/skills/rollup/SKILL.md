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

## Where this runs

**In the private repo.** Everything it needs is there — the registry that names
the repos, and the scrub policy that decides what may leave. Running it from the
public repo means reaching into a gitignored clone for both; running it where
they live means the working system never has to.

The skill's **source of truth stays in the public repo**, and it is deployed
here like any other:

```bash
uv run .claude/skills/rollup/scripts/deploy.py <private-repo> --branch <name>   # into a worktree, on a branch
uv run .claude/skills/rollup/scripts/deploy.py <private-repo> --check           # drifted?
uv run .claude/skills/rollup/scripts/deploy.py <private-repo> --pull-back       # carry a fix home
```

The same rule as the catchup deploy: it lands on a branch, never in the
private repo's main checkout, and the script refuses the latter.

It finds the registry by looking rather than assuming: `repos.json` at the repo
root when running inside the private repo, `fnr/.private/repos.json` when
running from the public one. Both are normal.

**The public weekly is a copy, made last.** The draft, its sources and every
unscrubbed note stay here; only the finished, scrubbed file is copied into the
public repo. Nothing is published by running this.

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

An entry with `"role": "aggregator"` is skipped — it reads the others rather
than producing a catchup of its own, and reporting it as a missing source would
name a gap that is the design.

**The repo's own `catchup.config.json` decides where its output lives**, not the
registry's `catchup_dir`, which is a convenience that goes stale the moment a
repo moves its output. When they disagree the rollup says so and uses the repo's;
a stale hint makes a reporting repo look silent, which is the worst answer an
aggregator can give.

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

**Snapshot the sources**, every run — `--snapshot rollups` files every week
record, summary and entity set the numbers came from under `rollups/<W>/<repo>/`,
with hashes. A snapshot that already exists is **kept**: a source that has
moved on since capture is reported as `drift` and left as captured, because
the rollup was built from the captured copy and a silent replacement rewrites
its provenance. `--recapture` is the deliberate act of taking a new one.

## Step 2b: The control — DeepVista

The skills here produce the record. DeepVista is the **control**: each syncing
repo has pushed its entities there as cards, and reading those cards back
gives a second reader of the same evidence. The aggregator runs that read for
every repo in one pass, because the question it answers — *what did each
summary leave out, and did both leave out the same thing* — is a cross-repo
question.

```bash
uv run .claude/skills/rollup/scripts/rollup.py 2026-W35 --snapshot rollups --control deepvista --table
```

Nothing is re-derived: for each repo whose config has `deepvista.enabled`, this
runs *that repo's* deployed `deepvista_cards.py fetch` and, once a summary
exists, its `compare`, and files the results beside the sources they are the
control for:

Machine files stay with the snapshot; everything a person reads goes in
`drafts/`, beside the manual draft, so the whole DeepVista version of a week
is in one place:

| File | Produced by | What it is |
|---|---|---|
| `rollups/<W>/<repo>/deepvista-cards.json` | `fetch` (headless) | What DeepVista holds for the week: card bodies plus a fidelity read per card — tracer intact/escaped/missing, body matches/cosmetic/differs — and the repo's unpushed entities and orphan cards |
| `drafts/<W>.deepvista.<repo>.md` | **you**, by hand | That repo's week written from the cards **alone**, in the catchup's shape. Write it before opening the local summary or the store, or it is not a control. (The rollup also accepts it at `rollups/<W>/<repo>/deepvista-summary.md`, for a repo running the read on its own) |
| `rollups/<W>/<repo>/deepvista-compare.json` | `compare` | Coverage diff: covered by both, only local, only DeepVista, neither |
| `drafts/<W>.deepvista-draft1.md` | **you**, by hand | The sum-up: the weekly's draft 1 written from the cards alone, in the same three-part shape as the manual `drafts/<W>.draft1.md` — raw material, scrub delta, public candidate with the human blocks left as prompts — and a **delta against the manual draft** at the end. This is what "the DeepVista version" means to a reader of the weekly; the per-repo files are its inputs |

So the command runs **twice**: once to fetch (it reports `no deepvista-summary.md
yet`), then again after the summaries are written, to compare. The cards file
is reused on the second run — `--refetch` to pull again.

**Read the control in this order:**

1. **The fidelity row first.** Unpushed entities, orphan cards and `differs`
   bodies are defects in the *sync*, and they bound what the summary comparison
   can mean — a card that was never pushed cannot be covered by the DeepVista
   summary, and scoring that as the local writer's win is wrong.
2. **`covered_by_neither`** — in the store, in no summary. Two writers passed
   over it independently: agreement that it does not matter, or a shared blind
   spot. Say which.
3. **`only_deepvista`** — the local summary left it out. Judgment or omission?
   Pull the better version *by entity* into the local summary in the source
   repo; never edit the summary here.
4. `only_ours` is usually the push not carrying something. Rarely interesting.

The control's own findings go in the rollup under `## Control: DeepVista`, and
the per-repo fixes go back to the repo that owns the entity.

**Then write the weekly's draft 1 from the cards**, as `drafts/<W>.deepvista-draft1.md`
in the private repo, following the fnr skill's draft-1 rules exactly — same
template, human blocks left as prompts, never a finished learning in his voice —
and close it with the delta against the manual draft: what the cards
reconstructed, what they got wrong (a card is only as current as the last
push), and what no card could carry (the personal lane, the calendar, the
intake queue, him). The two drafts side by side are the control's real output;
the compare buckets are how you got there.

## Write from the rollup, never from the session

**The single most likely way to get this wrong: describing the work of the
session you are in, rather than the week you were asked about.** An agent that
has just spent hours building something will reach for that when asked what
happened, and the result is fluent, confident, and about the wrong week. It
happened on the first real run — the Building section described the tooling
being built *that day* while the week's actual work, 68% of its commits, went
unmentioned.

Two guards, and use both:

- **Open the themes and read their `weight` before writing a word.** Every theme
  carries the share of the week it actually carried. The Building section should
  be the top one or two by weight, and if what you are about to write is not in
  that list, it is not this week's story.
- **Check the dates.** A week is seven days that have closed. Work you did while
  producing the summary belongs to the week you are in, not the one you are
  describing, and those are rarely the same week.

If a theme deserves the lead, its weight says so. If nothing in the rollup
supports the sentence you are writing, delete the sentence.

## Step 3: Read across, not down

The per-repo summaries already exist — restating them is not the job. What this
layer can see that no single repo can:

- **`cross_repo_entities`** — the same entity id in more than one repo. A
  subject that is a research thread in one repo and a tracked relationship in
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

## Control: DeepVista
| Repo | Cards | Tracer | Body | Both | Only local | Only DV | Neither |
(from the control table; then what the buckets mean, read across repos)
- <sync defects found: unpushed, orphans, differs — and the fix, per repo>
- <what both summaries left out, and whether that is agreement or a blind spot>
- <what the card-only summary carried that the local one dropped>

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
If the control ran, give its one-line verdict per repo — sync defects first,
then the coverage buckets — and name what goes back to which repo.

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
- **Writing the control summary with the local one open.** A card-only summary
  that has seen the local file is a copy with the names changed, and the
  coverage diff then measures nothing.
- **Reading the coverage diff before the fidelity row.** An entity that was
  never pushed is absent from the DeepVista summary by construction, not by
  judgment.
- **Reading a compare whose store has moved on.** The fetch and compare run
  against the *live* repo; the snapshot is kept as captured. When the two have
  parted, the control row says `store moved on since capture` — either
  `--recapture` so both sides are current, or read the buckets as
  live-store-vs-captured-summary and say so in the rollup.
