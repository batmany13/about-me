# catchup.config.json

Optional, per repo, at `<repo>/.claude/catchup.config.json`. **The skill runs
with no config at all** — this file only teaches it things it cannot infer:
who the people are, and what this repo's own vocabulary looks like.

A starting point to copy: [`../assets/catchup.config.example.json`](../assets/catchup.config.example.json).

## `repo`

| Key | Default | Meaning |
|---|---|---|
| `label` | the directory name | How the repo is named in summaries and in DeepVista tags |

## `output`

| Key | Default | Meaning |
|---|---|---|
| `dir` | `catchup` | Summaries land here; entities in `<dir>/entities/`, week records in `<dir>/weeks/` |

**Output is content, so it lives at the top level** — beside the rest of what the
repo is for, not under `.claude/`, which is where a repo keeps its agent
configuration. A weekly summary is something people read; burying it in a dotted
tooling directory hides it from everyone not already looking, and couples the
record to the tool that happened to write it. Point `dir` somewhere else if the
repo already has a home for this kind of thing.

The bookkeeping ignore rule **follows this setting** — writing a summary is not
work the summary should count — so moving `dir` moves the exclusion with it.

## `authors`

| Key | Default | Meaning |
|---|---|---|
| `split` | `false` | Render a per-person split in the summary |
| `people[]` | `[]` | `{ "name": ..., "emails": [...] }` — maps commit emails to display names |

Turn `split` on only for a repo with more than one real contributor. Any email
not listed shows up in the pull's `unknown_authors`; the skill surfaces those
rather than guessing, because attributing someone's work to someone else is the
one error a catchup must not make.

## `categories`

Three keys, fixed: `meeting`, `technical`, `other`. Retitle them freely; you
cannot add a fourth. The point of the vocabulary is that it is the same in every
repo — if it drifted per repo, cross-repo reading would stop working.

| Key | Meaning |
|---|---|
| `title` | Heading text in the summary |
| `paths[]` | Globs that **extend** the built-in rules. `**` spans directories, `*` one segment |
| `keywords[]` | Subject words that **extend** the built-ins. Matched on word boundaries; a trailing `*` means prefix (`deploy*` catches deploys/deployed/deployment) |
| `paths_replace[]` / `keywords_replace[]` | Same, but **discard** the built-ins first |

Extending is right far more often than replacing — reach for `_replace` only
when a built-in rule is actively wrong for the repo, e.g. a docs repo where
`**/*.py` should not imply technical work because the only Python is tooling.

**How a commit gets classified.** Paths outrank keywords: what a commit touched
is harder evidence than how its subject was worded. Within paths, the category
matching the most files wins, and it must match at least 25% of the diff (or 3+
files) to win outright — otherwise the subject gets the next word and the result
is marked `path-weak` so the extraction pass knows not to trust it. Ties go to
`meeting`, then `technical`.

## `summary`

| Key | Default | Meaning |
|---|---|---|
| `bullets` | `"6-12"` | Target bullet count for the week's summary |
| `words` | `"150-250"` | Target word count for the whole document |
| `sections{}` | — | Per-section word budgets, keyed by section |

**Prefer `sections` once a summary has more than one job.** A single total
governs a one-list summary fine, but a document whose sections answer different
questions cannot be trimmed against one number — hitting it means cutting
whichever section is easiest rather than whichever is weakest, and the section
that survives is the one that was already too long.

```json
"summary": {
  "words": "1800-2400",
  "sections": { "themes": "500-800", "meetings": "400-700",
                "learnings": "500-800", "other": "50-150" }
}
```

A section's budget is **either a word range or a bullet count**, whichever the
section is actually felt in:

```json
"sections": {
  "themes":    "500-800",           
  "meetings":  { "bullets": "24-40" },
  "learnings": "500-800",
  "other":     "50-150"
}
```

Words govern prose. **Bullets govern a section whose unit is countable** — one
bullet per conversation, say, where a reader feels the number of conversations
and lengths vary too much for a word range to mean anything. A repo can mix the
two across sections; the question is what the section's unit is.

Declare every section a repo actually renders. `sections` is read per key, so a
partial map leaves the undeclared ones governed only by the overall `words` —
which is the single-number problem the split exists to avoid, reintroduced for
whichever sections were left out.

Weight-proportionality is a rule *within* a section, not across them. An evening
that is 2% of a week's churn can still deserve a third of the summary, because
"what moved" is not the question every section answers.

The default is sized for a normal week. A repo that routinely runs hundreds of
commits should raise it rather than overflow it every week — an unmeetable
budget is guidance nobody follows.

### `summary.stats` — what this repo counts

**The stat line is derived, not written.** It is the one part of a summary meant
to be mechanically checkable, so composing it by hand is backwards — and it
showed: two repos running this skill reported different figures from *identical*
week records, because two sessions picked different fields.

But what a repo counts is genuinely its own. Commits and PRs are universal;
`events`, `deals`, `learnings` and `people met` are not, and no default can guess
them. So the **fields are declared here** and the **arithmetic is done by the
skill**.

```json
"summary": {
  "stats": [
    { "label": "commits",    "from": "stats.commits" },
    { "label": "PRs merged", "from": "stats.prs_merged" },
    { "label": "events",     "singular": "event", "count": { "type": "meeting" } },
    { "label": "learnings",  "singular": "learning", "count": { "type": "concept" } },
    { "label": "people met this week", "count": { "type": "person", "new": true } }
  ]
}
```

Each entry resolves one of two ways:

| Key | Resolves to |
|---|---|
| `from` | A dotted path into the week record — `stats.commits`, `stats.prs_merged`, `stats.ignored`, `stats.prs_open_now`, `stats.pr_body_chars` |
| `count` | How many of the week's entities match a filter |

A `count` filter takes any of `type`, `category`, `tag`, `status`, and `new`.
**`new: true` means first seen this week** — the difference between how many
relationships exist and how many the week *added*, which one number silently
conflates.

`singular` is opt-in and used when the value is 1. No rule guesses it: stripping
an "s" would turn "bookkeeping commits excluded" into nonsense.

Omit `stats` entirely and the line reports mechanical facts only — commits, PRs,
entities, bookkeeping — because those are the ones true of every repo.

Regenerate with `entities.py stat-line <week>`; `render` appends it
automatically.

## `ignore`

Bookkeeping commits: flagged, excluded from the category counts, and **reported
as a number** rather than dropped. A catchup that silently swallows a fifth of
the week's commits is lying about the week.

| Key | Meaning |
|---|---|
| `paths[]` | Globs that **extend** the built-in ignores |
| `subjects[]` | Regexes matched against the commit subject, extending the built-ins |
| `paths_replace[]` / `subjects_replace[]` | Same, but discard the built-ins |

Built-in ignores cover tooling conventions rather than any one repo's habits:
`.claude/transcripts/`, the configured `output.dir`, lockfiles, and subjects matching
`chore(transcripts):`, `Merge branch`, or dependency bumps.

**A subject rule fires on its own; a path rule requires every touched file to
match.** A commit that edits a lockfile on its way through real work is real
work — only a commit that is nothing but bookkeeping is bookkeeping.

## `deepvista`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Whether Step 5 runs at all |
| `project_id` | `null` | Target project; unset means the account's active project |
| `tags[]` | `["catchup"]` | Base tags on every card |
| `card_status` | `"active"` | Must be one of the values the server serves |
| `card_types{}` | built-in map | Override entity-type → DeepVista card_type |

**`card_status` is checked against the served enum** — `pending`,
`not_started`, `in_progress`, `completed`, `for_review`, `active`, `archived` —
and a value outside it fails at the first card with the vocabulary printed,
rather than being accepted and quietly discarded by a server that ignores
unknown keys. An older `confirmed` is mapped to `active`; it came from a
REST-era search-visibility flag and was never a member of this enum.

## `git`

| Key | Default | Meaning |
|---|---|---|
| `commit` | `false` | Commit the summary and entities after writing |
| `pr` | `false` | Open a PR rather than committing to the current branch |

Both default off. A catchup is a working artifact; when it lands is the user's
call, not the skill's.

## `subjects` — where this repo's findings live

The altitude rule in Step 2b says a learning is about the subject, not about a
defect in it. That is unenforceable unless the skill can find what the repo
writes *about* its subjects, and there is no generic way to guess.

| Key | Default | What it does |
|---|---|---|
| `noun` | — | What a subject *is* here: "a technology under evaluation", "a customer", "a service" |
| `artifacts[]` | none | Globs for the files that describe subjects — research bundles, evaluation reports, benchmarks, design docs |
| `read_first` | — | Which field in those files carries the considered answer, e.g. a summary headline or a verdict line |

`propose` lists whichever of those the week touched, ranked by how much each
moved, so the read is a checklist rather than a reminder. Declare none and the
command says so — a repo with no declared artifacts will get a catchup written
from commit messages, which is a catchup of what changed rather than what was
found.

## `method_notes` — what this repo learned about its own catchups

| Key | Default | What it does |
|---|---|---|
| `path` | `<out>/method-notes.md` | Where the repo keeps its accumulated catchup lessons |

Deliberately outside the skill directory. Which themes recur here, which past
summary went wrong and why, what the classifier keeps mis-filing — all of that is
worth writing down and none of it travels to another repo.
