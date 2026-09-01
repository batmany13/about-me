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
| `dir` | `.claude/catchups` | Summaries land here; entities in `<dir>/entities/` |

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

Weight-proportionality is a rule *within* a section, not across them. An evening
that is 2% of a week's churn can still deserve a third of the summary, because
"what moved" is not the question every section answers.

The default is sized for a normal week. A repo that routinely runs hundreds of
commits should raise it rather than overflow it every week — an unmeetable
budget is guidance nobody follows.

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
`.claude/transcripts/`, `.claude/catchups/`, lockfiles, and subjects matching
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
| `card_status` | `"confirmed"` | Leave this alone — see [`deepvista.md`](deepvista.md) |
| `card_types{}` | built-in map | Override entity-type → DeepVista card_type |

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
