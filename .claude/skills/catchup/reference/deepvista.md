# DeepVista sync

Pushes catchup **entities** into [DeepVista](https://deepvista.ai) as context
cards. Off unless a repo's config sets `deepvista.enabled: true`.

Status: **live, both directions.** The push was exercised against a live
account on 2026-09-02 (see *First live push*), and the read-back — `fetch`,
headless through the proxy — the same day, on 74 cards across two repos (see
*Reading the week back*). Both directions now use an explicit, command-owned
proxy; no host-level MCP registration is needed.

## Why one card per entity

DeepVista's own core concept decides this:

> "Context card captures **entities.** Every team member, customer, meeting note,
> file, and session is stored within a context card."

So the unit is the entity — not the week (which would collapse the categories
into one blob that search can't tell apart) and not the bullet (which isn't an
entity, and would turn a 12-bullet week into 12 cards against a 100-credit
monthly tier). A thread running four weeks is **one card that accumulates**,
which is the same thing the local entity store does, and is DeepVista's own
"context that compounds" pitch rather than a fight with it.

The card body carries the whole week-by-week timeline, not just the current
summary. That is deliberate: the reason to push entities instead of a finished
writeup is so DeepVista has enough to compose a catchup *itself*. A card that
only said "here is the latest" could not.

## Transport

Hosted MCP server, Streamable HTTP:

```
https://api.deepvista.ai/mcp
```

No trailing slash. Scoped automatically to the account's **currently active
project**. It exposes context-card read, search, create, update and delete.

**No API key is needed.** The server implements the MCP OAuth flow with dynamic
client registration, so the client registers itself and the browser does the rest.

**Do not register it at project or user scope.** MCP hosts start registered
servers when a session is created, so either scope makes an optional catchup
integration contact DeepVista during unrelated analysis. The bridge instead
starts the pinned proxy only inside `push --apply` and `fetch`, then tears it
down.

```bash
uv run scripts/deepvista_cards.py doctor --repo .
uv run scripts/deepvista_cards.py push --repo . --week 2026-W35       # local preview
uv run scripts/deepvista_cards.py push --repo . --week 2026-W35 --apply
```

The first applied command may print an authorization URL and wait for the human
browser flow. The proxy caches the resulting OAuth token under `~/.mcp-auth`;
later explicit commands are headless. A dry push never starts the proxy.

### Which repo does the pushing

**The repo that owns the entity pushes it.** Not a central pusher.

`record` writes `card_id` and the content hash back onto the entity file, and
that write-back is what makes the next run's create-vs-update-vs-skip decision
possible. A central pusher would have to write into other repos' working trees —
producing uncommitted changes in repos it does not own — or keep the sync state
somewhere other than the entity, in which case re-running catchup in the source
repo would not know a card already exists and would create duplicates.

This is the same one-producer rule the rollup follows: it reads other repos'
products and never re-derives them. Sync state is a product of the entity, so it
belongs with the entity.

The cost of that choice is that credit spend is spread across repos rather than
visible in one place. `entities.py stats` reports `synced_to_deepvista` per repo,
which is the per-repo half; there is no aggregate view yet.

### Why no key

OAuth is the route this was built and verified against. Confirmed by probing the
live endpoints:

| Probe | Result |
|---|---|
| `POST /mcp` unauthenticated | `401` + `WWW-Authenticate: Bearer resource_metadata="…"` |
| that resource metadata | `authorization_servers: [<supabase>/auth/v1]`, `bearer_methods_supported: ["header"]` |
| the authorization-server metadata | `registration_endpoint` present — **dynamic client registration** — plus `authorization_code` and `refresh_token` grants |

That is the standard MCP OAuth discovery chain, complete and working, which is
why no manual credential is required.

One field is easy to misread: `deepvista auth login` writes an `api_key` into
`~/.config/deepvista/credentials.default.json`, and the source documents it as
the Supabase *anon* key used to refresh the session — a public client value, not
a bearer credential. It is not the thing to reach for here.

`rm -rf ~/.mcp-auth` clears a stuck auth cache.

## The cycle

`plan` and dry `push` are deterministic previews. Only the `--apply` form opens
the MCP connection and writes cards; it records each returned id immediately so
a partial run can resume without duplicating completed creates.

```bash
uv run scripts/deepvista_cards.py plan --repo . --week 2026-W35
uv run scripts/deepvista_cards.py push --repo . --week 2026-W35
uv run scripts/deepvista_cards.py push --repo . --week 2026-W35 --apply
```

Each plan item carries `action`:

| Action | When | Cost |
|---|---|---|
| `create` | entity has no `card_id` yet | one call |
| `update` | entity has a `card_id` and its content changed | one call |
| `skip` | content hash matches the last push | **nothing** |

The free tier is 100 credits a month, so `skip` is load-bearing, not an
optimization. Re-pushing an unchanged card spends a credit to change nothing.
`--force` overrides it; use it when a card was edited or deleted on the
DeepVista side and needs re-establishing.

The applied push writes `card_id`, `synced_at`, and the content hash back onto
the entity file after each successful call. `record` remains a manual recovery
command for a card created before local write-back completed.

## Card shape

| Field | Source |
|---|---|
| `card_type` | entity type, mapped below |
| `title` | entity title |
| `description` | markdown: summary, metadata line, per-week timeline, related entities |
| `tags` | `catchup`, `repo:<label>`, `category:<key>`, `entity:<id>`, plus the entity's own |
| `status` | `active` (`deepvista.card_status`) — see the gotcha |

Entity type → DeepVista `card_type`. The right-hand column is DeepVista's fixed
vocabulary, so the mapping is lossy on purpose:

| Entity type | Card type | Note |
|---|---|---|
| `meeting` | `note` | DeepVista has no meeting type; its docs file meeting notes as notes |
| `person` | `person` | |
| `org` | `organization` | |
| `thread` | `topic` | |
| `decision` | `keypoint` | |
| `correction` | `keypoint` | |
| `other` | `note` | |

DeepVista's full card vocabulary: `person`, `organization`, `message`, `email`,
`todo`, `topic`, `keypoint`, `file`, `note`, `session`, `skill`, `run_log`,
`schedule_job`, `task`, `conversation_starter`, `artifact`. Override the mapping
per repo with `deepvista.card_types`.

The body ends with an HTML comment `<!-- catchup-entity: <id> -->`, so a card
can be traced back to its entity even if its title is edited in the product.

## The gotcha

**Agent-created cards default to `unconfirmed`, and search filters those out** —
so a card pushed without an explicit status exists but is not findable. Every
card this bridge sends therefore sets an explicit status — `active` by default,
which is the served enum's "live" value and is searchable. (`confirmed`, which
the first draft of this bridge sent, is *not* in the enum; a config still
saying it is mapped to `active`.) Leave `deepvista.card_status` alone unless
you specifically want cards staged for review.

## First live push — 2026-09-02, verified

The runbook below was run in order against a live account, and this is what
it found. Everything above the `plan` output is now exercised.

| Question | Answer |
|---|---|
| Tool name and shape | `upsert_context_card` — `card_id` (null to create), `properties` (`type`, `title`, `description`, `tags`, `status`), `related_context_card_ids`. One tool for create and update. |
| `card_type` key | Wrong: the key is `type`, and unknown keys are silently ignored. The values (`note`, `topic`, `keypoint`, `person`, `organization`) were right. |
| `status: confirmed` | Not in the enum. `active` is, and it is searchable. |
| Card renders | Markdown body, timeline and all, returned byte-for-byte on create. |
| Findable by search | The pushed card was the top hit for a paraphrase of its own summary. |
| `record` → `skip` | Held: after `record`, `plan --include-skipped` showed the entity as `skip` and a full run reported `create: 0, update: 0, skip: 54`. |
| Graph edges | `related_context_card_ids` is mirrored by the server: `list_related_context_cards` on a meeting card returns the company, the people met, and the owed-follow-up thread, each tagged `RELATED`. |
| Credit cost | Not measurable from the MCP surface — there is no balance tool. The account was on a 2,000-credit tier for this run; 54 creates plus 42 link passes plus 41 repairs went through without a refusal. Check the balance in the product. |

What surprised: the links-only pass (see the gotchas). What the first push of
54 W35 entities produced: 10 meetings, 15 people, 13 organizations, 8 topics,
8 keypoints, and 42 of them carrying graph edges.

**The contract this was built against is the `deepvista-cli` source** (Apache-2.0),
specifically its `/create_context_card` and `/update_context_card` calls. Prefer
it over the rendered API reference, and reconcile against the live MCP tool list
once connected.

## Reading the week back, and comparing

Once a week's cards are pushed, DeepVista holds the same entities the local
store does — which makes it a second reader of the same evidence, and a way to
find out what the local summary missed.

1. Fetch the week's cards — scripted, and headless once the proxy has a token:

```bash
uv run scripts/deepvista_cards.py fetch --repo . --week 2026-W35 --out deepvista-cards.json
```

2. Have a summary written from that file **alone**, in the format `SKILL.md`
   describes, without the local summary or the store open. Save it beside it.
3. Diff the coverage:

```bash
uv run scripts/deepvista_cards.py compare 2026-W35 --repo . --against deepvista-summary.md
```

### How `fetch` reads headlessly

`fetch` spawns `npx -y mcp-remote <endpoint>` itself and speaks JSON-RPC to it
over stdio. That works without a human because the proxy
caches its OAuth token under `~/.mcp-auth` after one browser sign-in; from then
on any process that starts it gets a session. Three things learned making it
run:

- **The cache can be half-finished.** `~/.mcp-auth/mcp-remote-v1/` held a
  `_client_info.json` and a `_code_verifier` but no `_tokens.json` — a sign-in
  that was started and never completed. That looks cached and is not. The
  tokens file is the thing to look for; when it is absent, the proxy prints the
  authorization URL and waits, and `fetch` surfaces that URL rather than timing
  out silently.
- **PATH's `npx` is not necessarily the one that can run it.** The machine this
  was built on had npm 6's `npx` first on PATH and npm 11's under Homebrew.
  `fetch` resolves an `npx` of version 7+ across PATH and the well-known install
  locations for its *own* subprocess — that path is never written into a repo
  file, so it can be machine-specific without creating ambient configuration.
- **A session can go missing between `initialize` and the first call.** The
  client re-initializes once on the same proxy before giving up, and the output
  records `session_reinits` so a run that needed it is distinguishable from one
  that did not.

### What the read reports, and what each state means

The read is a fidelity check on the push as much as a second summary. Per card:

| Field | States | Meaning |
|---|---|---|
| `tracer` | `intact` / `escaped` / `missing` | Whether the `<!-- catchup-entity -->` comment still points at its entity. `escaped` is the links-only pass's HTML-escaping (see the gotchas) — still the right card, no longer byte-identical |
| `body` | `matches` / `cosmetic` / `differs` | Against what the entity renders to now. `cosmetic` is markdown escaping and blank lines the bridge did not send (`*[grade]*` back as `*\[grade\]*`) — content-identical, normalised away. `differs` with `store_current: true` is the one to look at; with the store moved on it is the ordinary post-push edit and `plan` will say `update` |

And per repo: **unpushed** entities of the week, **orphans** — cards under the
`repo:` tag that no entity points at — and cards that no longer exist.

The orphan case is the instructive one: an entity renamed locally after a push
leaves the store with an entity that has no card and DeepVista with a card that
has no entity, and the next push creates the twin. **A rename after a push needs
the card id carried across** (`record` on the new id) or the old card deleted;
`fetch` lists both halves so the pair is visible.

Findings from actual runs — counts, which entities, what the product did on a
given day — belong in the private layer, not here.

It reports four buckets, and only the last two are interesting:

| Bucket | What it means |
|---|---|
| Covered by both | Agreement. Skip. |
| Only the local summary | Either the push did not carry it, or the card reader dropped it. |
| **Only the DeepVista summary** | The local summary left it out. Was that judgment, or an omission? |
| **Covered by neither** | In the store, in no summary. Two writers independently passed over it — shared agreement it does not matter, or a shared blind spot. |

**Neither side is assumed correct.** The comparison is on *coverage*, not style,
because coverage is checkable and style is not. Pull the better version by
entity: if the card-derived summary carries something real that the local one
dropped, add the entity's material to the local summary rather than replacing
prose wholesale — the local file is the one under version control and the one
the scrub policy has been applied to.

## First applied run

Run the sequence in order and stop at the first surprise:

1. `doctor` checks the local runtime and performs an explicit endpoint probe.
2. `plan --limit 1 --show-body` renders one complete card locally.
3. `push --limit 1` previews the exact write locally and says that no call ran.
4. `push --limit 1 --apply` starts the proxy, completes OAuth if needed, writes
   one card, and records its id.
5. Re-run `plan --include-skipped`; the entity must now say `skip`.
6. Only then apply the rest, optionally one category at a time.

The first applied run is where to verify rendering, search visibility, and
credit cost. The served tool contract was reconciled on 2026-09-01; a future
schema mismatch should fail loudly before local write-back rather than be
papered over with a host-level MCP registration.

---
