# CLAUDE.md — AI Instructions for about-me

## What is this repo?

This is Bruce Wang's personal leadership knowledge base. Bruce is an Engineering Director at Netflix in the Games Engineering group, a startup advisor, and seed investor. The repo documents his leadership philosophy, frameworks, 360 feedback history, speaking engagements, and reflections on growth.

**Audience**: Mentees, potential collaborators, hiring partners, engineering leaders, and anyone interested in leadership practices.

**Purpose**: A living document that Bruce updates over time — not a static site. Think of it as a public "operating manual" for how Bruce leads and thinks.

## Content Map

| File | What it contains |
|------|-----------------|
| `README.md` | Core leadership philosophy (trusting teams, seeking excellence, driving customer delight), personal values, reading list |
| `roles.md` | Overview of Bruce's three professional roles: Netflix leader, seed investor, external speaker |
| `leadership/feedback/self_eval.md` | Personal passions, unique advantages, and growth areas (last updated 2022) |
| **leadership/** | |
| `leadership/managing.md` | People leadership guide: culture, growing/retaining/hiring/parting with people |
| `leadership/1x1s.md` | Detailed 1x1 methodology with 5 types of 1x1s and sample agendas |
| `leadership/thriving_team.md` | What skills and characteristics define a thriving team |
| `leadership/okrs.md` | OKRs framework overview |
| `leadership/feedback/` | 360 review themes by year (2021-2025) with strengths and opportunities |
| **netflix/** | |
| `netflix/games_engineering.md` | Netflix Games Platform Engineering org — team missions and structure |
| `netflix/interview.md` | Interview process documentation for API Systems |
| `netflix/pursuit_of_impact/` | Conference talk tips: designing teams, hiring, learning environment |
| **investing/** | |
| `investing/README.md` | Seed-stage AI investment thesis: what Bruce looks for, how he helps founders |
| `investing/investments.md` | Public-facing portfolio of AI Fund companies — name, field, short description (no confidential data) |
| **speaking/** | |
| `speaking/external_presence.md` | Complete index of talks, blogs, podcasts, panels (2016-2026) |
| `speaking/events/` | Q&A from talks and sessions |
| **other/** | |
| `ideas/` | Work-in-progress concepts (API Reliability Engineering, Four Laws of Software Engineering, AI-assisted leadership reflections) |
| `netflix/past/` | Legacy role descriptions (Product Edge Systems, Consumer Server Foundations) |
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
2. Add a new H2 section below the existing ones: `## YYYY Netflix 360s Theme`
3. Add `__Strengths__` and `__Opportunities__` subsections with bullet points
4. Note any long-running feedback themes with `(long-running feedback)` prefix

### Updating self_eval.md
- Update the "last updated" date at the top
- Keep the three sections: Passions, Unique Advantages, Growth Areas
- Be honest and reflective — this is meant to be transparent

### Updating netflix/games_engineering.md
- This reflects the current org structure at Netflix Games
- Update team names, missions, and descriptions as the org evolves

### Adding a new portfolio company to investing/investments.md
1. Determine the category: AI Infrastructure, Vertical AI Applications, Developer Productivity, or Other
2. Add under the correct section heading
3. Format: `**Company Name** — Field/Focus Area` followed by a 1-2 sentence public description
4. Keep descriptions public-friendly — no valuations, fit ratings, or internal analysis
5. Update `investing/README.md` if the new company represents a thesis evolution

### Updating roles.md
- Update when Bruce's role, responsibilities, or focus areas change
- Keep the three-role structure (Netflix leader, investor, speaker) unless a new role emerges
- Update the speaking break status when it changes

## What NOT to change without explicit ask
- The core leadership philosophy in README.md (Trusting Teams, Seeking Excellence, Driving Customer Delight)
- The "About Me Personally" section and its subsections
- The reading list — only add, don't remove or reorganize
- 360 feedback content (it's historical record)

## How to help Bruce improve this repo
- Suggest new content based on themes in his talks or feedback
- Help keep speaking/external_presence.md current
- Help keep investing/investments.md current when new portfolio companies are added
- Flag outdated information (e.g., role changes, stale links)
- Help draft new ideas/ entries based on talks or discussions
- Synthesize patterns across 360 feedback years
- Suggest books/articles that align with his philosophy
