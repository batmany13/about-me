# TODOs

Things queued for this repo.  Not a backlog — if something sits here for months it should be deleted rather than carried.

---

## Publish about-me as a small Astro site

**Status:** queued, ~1–2 weeks out (noted 2026-08-22)

Right now this repo *is* the site: people read it on GitHub.  That's fine for a leadership doc and increasingly wrong for [fnr/](fnr/), which is a weekly publication and deserves to look like one.

**What already exists:** a Netlify site, `iridescent-meerkat-f04954`, on my personal account, already connected to this repo.  It currently 404s because there's no build — Netlify has nothing to serve from a pile of markdown.  So the plumbing is done; only the site is missing.

### Rough shape

- **Astro, content collections over the existing markdown.**  Don't restructure the repo to suit the site.  The markdown stays the source of truth and stays readable on GitHub; Astro reads it where it lives.  If the site ever requires moving files around, the site is wrong.
- **Three surfaces, different jobs:**
  - `fnr/` → the weekly.  Index page, individual entries, chronological archive.  This is the part that most needs to stop being a directory listing.
  - `README.md` + `leadership/` + `ideas/` → the evergreen material.  Slow-changing, deep-linkable.
  - `past/` → archive.  Present, findable, visibly not current.
- **A feed is the point, not a nice-to-have.**  A weekly with no RSS/Atom is a folder people forget to check.  This is most of the argument for building the site at all.
- **Rename the Netlify site.**  `iridescent-meerkat-f04954` was auto-generated and never touched.  Decide on a custom domain at the same time, or explicitly decide not to.

### Watch out for

- **`fnr/.private/` must never reach the build output.**  It's gitignored so it won't be in a clean checkout, but any local build would see it.  Add an explicit exclude rather than relying on gitignore, and check `dist/` before the first deploy.
- **Don't break inbound GitHub links.**  Plenty of things point at `github.com/batmany13/about-me/...` — talks, the LinkedIn profile, `speaking/external_presence.md`.  The repo staying readable is a feature; the site is additive.
- **Keep the weekly's authoring flow untouched.**  The [fnr skill](.claude/skills/fnr/SKILL.md) writes markdown to `fnr/<YYYY-WNN>.md`.  The site should build from that with no extra step, or the habit acquires friction and dies.

### Open questions

- Custom domain, or live on a Netlify subdomain for now?
- Does the weekly want an email list eventually, or is a feed enough?
- Anything here that shouldn't be on a real website — the site makes this material meaningfully more discoverable than a GitHub repo does, and that's worth one deliberate pass before launch rather than after.
