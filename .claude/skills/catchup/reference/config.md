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
| `from` | A dotted path into the week record — `stats.commits`, `stats.prs_merged`, `stats.ignored`, `stats.prs_open_now`, `stats.pr_body_chars`, `stats.subjects_new` |
| `count` | How many of the week's entities match a filter |

A `count` filter takes any of `type`, `category`, `tag`, `status`, and `new`.
**`new: true` means first seen this week** — the difference between how many
relationships exist and how many the week *added*, which one number silently
conflates.

**`stats.subjects_new` counts how many subjects ARRIVED** — files added this
week matching `subjects.artifacts`. A new subject artifact is a new subject, so
the number needs no tagging discipline to stay true: a repo that declared where
its subjects live has already said everything required to count them. What it
*means* is the repo's own — intake for one, new customers or new experiments for
another — which is why it is a field here and a label in `summary.stats` rather
than a fixed word in the format.

It is `null`, not `0`, for a repo that declares no `subjects.artifacts`, and the
stat line omits it. "Never said where its subjects live" and "none arrived" are
different answers and the line must not report the first as the second.

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
| `databases[]` | `[]` | Database cards this repo fills the rows of — see below |

**`card_status` is checked against the served enum** — `pending`,
`not_started`, `in_progress`, `completed`, `for_review`, `active`, `archived` —
and a value outside it fails at the first card with the vocabulary printed,
rather than being accepted and quietly discarded by a server that ignores
unknown keys. An older `confirmed` is mapped to `active`; it came from a
REST-era search-visibility flag and was never a member of this enum.

### `databases[]` — the rows of a database card

A DeepVista **database** card renders a grid, and its rows are a *typed* edge:
`rel_type: "row_of"`. Ids passed as ordinary relations mean only "generally
related" and **do not appear in the grid**. Each entry names one database card
and the entities that are its rows:

```json
"databases": [
  {
    "$comment": "Every tracked organization is a row of the tracker card.",
    "card_id": "<database card id>",
    "title": "<human label, for command output only>",
    "types": ["org"],
    "tags_any": ["tracked"],
    "weeks": "all"
  }
]
```

| Key | Default | Meaning |
|---|---|---|
| `card_id` | — | **Required.** The database card whose rows these are |
| `title` | `null` | Label in command output; never sent |
| `types[]` | any | Entity types eligible as rows |
| `categories[]` | any | Entity categories eligible as rows |
| `tags_any[]` | any | Entity must carry at least one |
| `tags_all[]` | none | Entity must carry all |
| `weeks` | `"all"` | `"all"` for the whole store, `"week"` for one week's entities (then `--week` is required) |

Every clause narrows, so a spec with no selectors takes the repo's whole store
— which is what a per-week database wants, bounded by `weeks: "week"`.

**A database belongs to exactly one repo's config.** The row list has replace
semantics per relation type, so two repos writing the same database would
delete each other's rows by turns. This is the one place the "the repo that
owns the entity pushes it" rule does not extend: the write lands on the
database card, not on the row.

Selector keys are closed and validated locally, because a typo is silent at
the endpoint — it selects nothing, the union writes back what was already
there, and the grid stays empty with no error anywhere.

## `git`

| Key | Default | Meaning |
|---|---|---|
| `commit` | `false` | Commit the summary and entities after writing |
| `pr` | `false` | Open a PR rather than committing to the current branch |

Both default off. A catchup is a working artifact; when it lands is the user's
call, not the skill's.

## `summary.layout` — the sections a reader of this repo wants

The default summary answers three questions in a fixed order — what moved
(Themes), who did we meet (Meetings & Notes), what do we now know (What we
learned) — with dropped hypotheses under Other. A repo whose reader asks
different questions declares its own sections, rendered in that order:

```json
"summary": {
  "layout": [
    { "title": "Customers",       "section": "orgs", "tags_any": ["customer"] },
    { "title": "Prospects",       "section": "orgs", "rest": true },
    { "title": "Meetings / Notes","section": "meetings" },
    { "title": "Learnings",       "section": "learnings" }
  ]
}
```

| `section` | Renders | Options |
|---|---|---|
| `themes` | confirmed themes with their children | — |
| `orgs` | one entry per company, its people as a `Who:` clause | `tags_any` selects by tag; `rest: true` takes every company no other `orgs` section claimed (people attached to no company are not rendered in a declared layout); `types` admits other entity types by tag — `["org", "thread"]` with `tags_any: ["shipped"]` puts the thread that shipped a page under the section its subject belongs to; `groups: [{lead_tags_all | lead, tags_any?, title?}]` renders one banner per group — the lead entity (usually a batch decision; `lead_tags_all` selects every decision carrying those tags, `lead` names one by id) as the line, the companies its record links to as sub-bullets |
| `meetings` | one entry per conversation, with owed and asks | — |
| `learnings` | the concepts, by rank then grade | `first: {title, tags_any}` renders one strand first — every concept carrying those tags — and when none landed says so and lists what moved in that strand instead of skipping it; `top` caps the rest (default 4: three or four is what a reader keeps; the remainder are named, never dropped); `rest_title` labels the remainder (default "Elsewhere") |
| `other` | dropped hypotheses and unattached decisions | — |

Two things follow from declaring one. **Anchors apply across sections.** A
company that was in a room this week is anchored to that meeting, so its line
under Customers or Prospects is one sentence — the standing `summary` —
plus "See *the meeting* under Meetings / Notes", with no note, no `Who:` and
no owed/asks, because all of that lives on the meeting. A company gets its
full entry only when its week happened without a conversation: a round
announced, a divestiture learned from the buyer, an investor update. Any
entity can declare `anchor: <id>` by hand for the same treatment. So keep a
company's `summary` to one sentence, and put the week's data on the anchor. And
**a type no section claims stays out of the prose** — themes in a layout without
a `themes` section are still weighed, still in the store and the week record,
and simply not rendered. That is the point: that repo's reader does not want the
repo's own plumbing in the week.

## `ship` — where this repo publishes, so a shipped PR gets an address

```json
"ship": {
  "paths": ["site/**"],
  "hosts": { "site": "https://example.com" }
}
```

| Key | What it does |
|---|---|
| `paths[]` | Globs; a PR touching one is *shipped* even if its text never says so |
| `hosts` | Repo directory → production origin. Only URLs on these origins count as shipped addresses (a PR body is full of other people's links), and a path quoted in the body (`` `/reports/8a1f2c/` ``) resolves against the origin of the directory the PR touched |

`propose` lists shipped PRs with their resolved addresses; `record-week` stores
them under `stats.prs_shipped`; `check-summary` fails if the prose never cites
one, and warns about every merged PR the prose never mentions.

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
