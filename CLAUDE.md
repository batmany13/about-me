# CLAUDE.md — AI Instructions for about-me

## What is this repo?

This is Bruce Wang's personal leadership knowledge base. Bruce spent nearly seven years at Netflix (2020–2026, 6 years 8 months), most recently as an Engineering Director in Games Engineering leading Games Platform Engineering. **He left in August 2026** and is now on what he calls a "no-break career break": building, advising founders, seed investing, and learning. The repo documents his leadership philosophy, frameworks, 360 feedback history, speaking engagements, reflections on growth, and — since W34 2026 — a weekly published reflection in `fnr/`.

**Netflix is a past role.** Never write about it in the present tense or imply he still works there. The `past/netflix/` directory preserves that work as a historical record; content inside it is written in the present tense of its own moment and should stay that way.

**Audience**: Mentees, potential collaborators, hiring partners, engineering leaders, and anyone interested in leadership practices.

**Purpose**: A living document that Bruce updates over time — not a static site. Think of it as a public "operating manual" for how Bruce leads and thinks.

## Working in this repo

**Worktrees are the only edit surface for agent sessions.** Leave the main
checkout on `main`, untouched. Create a dedicated feature branch in a worktree
under `.claude/worktrees/<name>` and make every change there.

```bash
git -C <repo> pull origin main
git -C <repo> worktree add -b <branch> .claude/worktrees/<name>
```

- **Never commit or push directly to `main`.** Commit incrementally on the
  feature branch, then push that branch.
- **Open or update a PR for every change**, and keep its title and body matching
  the branch's actual scope.
- **Agents never merge pull requests.** Stop at the open PR and hand it over;
  merging is a human action.
- Clean the worktree up after the PR lands: `git worktree remove <path>`.

### Python runs through `uv`

**`uv run <script>`, never `python3 <script>`** — matching the source repos.

```bash
uv run .claude/skills/catchup/scripts/pull_week.py --repo . --list-weeks
```

Every script here carries a [PEP 723](https://peps.python.org/pep-0723/) header
declaring `requires-python` and its dependencies, so `uv run` resolves an
interpreter and an environment on its own. There is no virtualenv to activate,
no project to install, and nothing to keep in sync — which is what makes these
scripts safe to copy into another repo and run there unchanged.

They are deliberately **stdlib-only**. A skill that has to be copied between
repos should not carry a dependency list that has to be copied with it, so
`dependencies = []` is a constraint on the code, not a description of it. If a
script ever needs a third-party package, declare it in that script's own header
rather than adding a project file to this repo.

This mirrors the rule already codified in the source repos the weekly reads, and
it is the same rule here — a public repo is the last place to be editing `main`
directly.

## Content Map

| File | What it contains |
|------|-----------------|
| `README.md` | Core leadership philosophy (trusting teams, seeking excellence, driving customer delight), personal values, reading list |
| `roles.md` | What he's doing now: the no-break career break — building, founder advisory, seed investing, learning — plus the engineering-leader through-line and speaking history |
| `leadership/feedback/self_eval.md` | Personal passions, unique advantages, and growth areas (last updated 2022) |
| **fnr/** | |
| `fnr/README.md` | What Field Notes & Reflections is, the F&R pun, and the two-layer public/private model |
| `fnr/<YYYY-WNN>.md` | One public weekly per ISO week, published Mondays about the week that just closed |
| `fnr/.private/` | **A separate private repo** — [about-me-private](https://github.com/batmany13/about-me-private) — cloned into this gitignored path. Holds `repos.json` (which repos the weekly reads), `scrub_policy.md` (what may be published), and the unscrubbed drafts. Never commit its contents here, never quote it in public files |
| **.claude/skills/** | |
| `.claude/skills/catchup/` | **Source of truth** for the repo-agnostic `catchup` skill, deployed into other repos with its `deploy.py`. Two passes: extract entities from a week, then summarize from them. Nothing repo-specific lives in it — that goes in each repo's `.claude/catchup.config.json` |
| `.claude/skills/rollup/` | The summary-of-summaries: reads every registered repo's week records and entities and merges them into one cross-repo view. Private output only |
| `.claude/skills/fnr/` | The public weekly — see **Writing the weekly** below |
| **leadership/** | |
| `leadership/managing.md` | People leadership guide: culture, growing/retaining/hiring/parting with people |
| `leadership/1x1s.md` | Detailed 1x1 methodology with 5 types of 1x1s and sample agendas |
| `leadership/thriving_team.md` | What skills and characteristics define a thriving team |
| `leadership/okrs.md` | OKRs framework overview |
| `leadership/feedback/` | 360 review themes by year (2021-2025) with strengths and opportunities |
| **past/** | |
| `past/README.md` | Closed chapters — why they're preserved as-is |
| `past/netflix/README.md` | Netflix 2020–2026, framed as a finished chapter, plus what he took from it |
| `past/netflix/games_engineering.md` | Games Platform Engineering org and team missions (as of 2026) |
| `past/netflix/interview.md` | Interview process design for API Systems |
| `past/netflix/pursuit_of_impact/` | Conference talk tips: designing teams, hiring, learning environment |
| `past/netflix/earlier_roles/` | ARES, Product Edge Systems, Consumer Server Foundations |
| **investing/** | |
| `investing/README.md` | Seed-stage AI investment thesis: what Bruce looks for, how he helps founders |
| `investing/investments.md` | Public-facing portfolio of AI Fund companies — name, field, short description (no confidential data) |
| **speaking/** | |
| `speaking/external_presence.md` | Complete index of talks, blogs, podcasts, panels (2016-2026) |
| `speaking/events/` | Q&A from talks and sessions |
| **other/** | |
| `ideas/` | Work-in-progress concepts (Four Laws of Software Engineering, AI-assisted leadership reflections) |
| `rsrc/` | Images, PDFs, and presentation materials |

## Conventions

### Formatting
- Markdown with GitHub-flavored extensions
- H1 (`#`) for page title, H2/H3 for sections
- Bold (`**text**`) for emphasis on concepts
- `Toolbelt:` sections in the README provide actionable advice tied to each philosophy point
- Links use relative paths for internal files, full URLs for external resources
- Trailing spaces (`   `) used for line breaks in some lists (GitHub markdown style)

### Dates in external_presence.md
- Entries are organized by year (H3), newest year first
- Format within a year: `[Date] Event Name — Description | [link type](url)`
- Some entries use brackets `[Date]`, others don't — both are fine
- Completed vs pending/cancelled sections exist for some years

### Writing style
- First person, conversational tone
- Practical and actionable — every philosophy point has a "Toolbelt" with concrete steps
- References books, articles, and frameworks frequently
- Transparent about personal failings and growth areas
- Optimistic but grounded

## Common Tasks

### Adding a new talk/blog to speaking/external_presence.md
1. Find the correct year section (or create one if it's a new year)
2. Add entry under `__Completed__` or at the top of the year section
3. Follow the format: `Date - Event Name | [link type](url)`
4. Include recording/slides links when available

### Adding a new year of 360 feedback
1. Open `leadership/feedback/README.md`
2. Add a new H2 section below the existing ones. The 2021–2025 sections are Netflix 360s and are a closed historical set — a new year would come from somewhere else, so title it for its actual source (`## YYYY <Source> Feedback Theme`)
3. Add `__Strengths__` and `__Opportunities__` subsections with bullet points
4. Note any long-running feedback themes with `(long-running feedback)` prefix

### Updating self_eval.md
- Update the "last updated" date at the top
- Keep the three sections: Passions, Unique Advantages, Growth Areas
- Be honest and reflective — this is meant to be transparent

### Catching up on a repo, and rolling up across repos

Three layers, each with one producer. Don't let a later layer re-derive what an
earlier one already established — two producers of the same number is how they
start disagreeing.

| Layer | Skill | Reads | Writes |
|---|---|---|---|
| Per repo | `catchup` | that repo's git log + merged PRs | `<output.dir>/entities/*.json`, `weeks/<W>.json`, `<W>.md` — **in that repo**, top level by default |
| Across repos | `rollup` | each repo's week records + entities | `fnr/.private/rollups/<W>.md` — **private** |
| Public | `fnr` | the rollup, under the scrub policy | `fnr/<W>.md` — public |

`catchup` is **deployed** into other repos, not run from here:

```bash
.claude/skills/catchup/scripts/deploy.py /path/to/repo --config
```

Edit it here and redeploy — but **the copies go both ways**, because defects
turn up where the skill *runs*, not where it is edited:

```bash
.claude/skills/catchup/scripts/deploy.py <repo> --check      # has it drifted?
.claude/skills/catchup/scripts/deploy.py <repo> --pull-back  # carry a fix home
```

`--pull-back` overwrites canon with the copy, so review the resulting `git diff`
before committing — pulling back from a target that is *behind* would regress
the source. Never let another runtime hold a second copy either: `.agents/skills`
must be a symlink, not a directory, and `deploy.py` reports which state a repo
is in after every deploy.

`rollup` output carries repo names and unscrubbed notes, so it is **private by
construction**. Repo names live in `fnr/.private/repos.json` and nowhere else in
this repo.

### Writing the weekly (fnr/)
Use the **fnr** skill (`.claude/skills/fnr/SKILL.md`) or `/fnr`. Don't hand-write these — the skill exists so the scrub policy is applied consistently.

0. If `fnr/.private/` is missing, it was never cloned into this checkout — not lost:
   `git clone https://github.com/batmany13/about-me-private.git fnr/.private`.
   **Never reconstruct `repos.json` or `scrub_policy.md` from memory or from a conversation** — clone the reviewed copy.
1. Read `fnr/.private/repos.json` and `fnr/.private/scrub_policy.md`, and check that repo for uncommitted or unpushed work first (a nested repo in an ignored path is invisible to `git status` here)
2. Run `.claude/skills/fnr/scripts/pull_week.py <YYYY-WNN>` for commits + attended events
3. Write the **unscrubbed** catchup into each source repo's `<output.dir>/<week>.md` (`catchup/` by default)
4. Derive the **scrubbed** public file at `fnr/<YYYY-WNN>.md` from those catchups
5. Report the scrub delta — what was held back, by category

Default week is the **last closed week**, not the current one.

### Touching past/netflix/
Don't update it as if it were live. It's a record of 2020–2026. Fix broken links and typos; don't refresh org structure, and don't convert its prose to past tense — the historical banners at the top of each file carry that job.

### Adding a new portfolio company to investing/investments.md
1. Determine the category: AI Infrastructure, Vertical AI Applications, Developer Productivity, or Other
2. Add under the correct section heading
3. Format: `**Company Name** — Field/Focus Area` followed by a 1-2 sentence public description
4. Keep descriptions public-friendly — no valuations, fit ratings, or internal analysis
5. Update `investing/README.md` if the new company represents a thesis evolution

### Updating roles.md
- Update when Bruce's role, responsibilities, or focus areas change
- Keep the current structure — the no-break career break framing (building, founder advisory, seed investing, learning), the engineering-leader through-line, and speaking — unless the situation actually changes
- If he takes a new role, `roles.md` gets restructured and the career-break framing moves to `past/`
- Update the speaking break status when it changes

## What NOT to change without explicit ask
- The core leadership philosophy in README.md (Trusting Teams, Seeking Excellence, Driving Customer Delight)
- The "About Me Personally" section and its subsections
- The reading list — only add, don't remove or reorganize
- 360 feedback content (it's historical record)
- Anything under `past/` — it's a preserved record, not a living document
- Published `fnr/` weeklies from prior weeks (fix typos and broken links only; don't retro-edit the record)
- The scrub policy in `fnr/.private/scrub_policy.md` — Bruce owns that file; propose changes, don't make them

## How to help Bruce improve this repo
- Suggest new content based on themes in his talks or feedback
- Help keep speaking/external_presence.md current
- Help keep investing/investments.md current when new portfolio companies are added
- Flag outdated information (e.g., role changes, stale links)
- Help draft new ideas/ entries based on talks or discussions
- Synthesize patterns across 360 feedback years
- Suggest books/articles that align with his philosophy
- Flag any remaining present-tense Netflix framing as a bug
- Netflix tenure is "nearly seven years" (6 years 8 months, 2020–2026) — not "six years"
- Watch for scrub leaks: a public `fnr/` file should never carry a portfolio company name, an investment decision, an event attendee list, or anything from the personal repo
