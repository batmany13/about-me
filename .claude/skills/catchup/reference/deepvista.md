# DeepVista sync

Pushes catchup **entities** into [DeepVista](https://deepvista.ai) as context
cards. Off unless a repo's config sets `deepvista.enabled: true`.

Status: **live, both directions.** The push was exercised against a live
account on 2026-09-02 (see *First live push*), and the read-back — `fetch`,
headless through the proxy — the same day, on 74 cards across two repos (see
*Reading the week back*). The push half is still model-driven; the read half
is a script.

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

**Register it once at user scope, not per repo:**

```bash
claude mcp add --transport http deepvista-server https://api.deepvista.ai/mcp
```

Then, **in an interactive session**, run `/mcp`, pick `deepvista`, and complete
the browser sign-in. A non-interactive session cannot do this — there is no
prompt to answer.

User scope makes the server available in every repo without a `.mcp.json`
committed anywhere. Since auth is OAuth rather than a key, there is no secret to
place and nothing repo-specific to keep in sync — which is the whole reason to
prefer it over N copies of the same five-line config.

A project-scoped `.mcp.json` works too and is right when a repo's collaborators
should all get the server. For a personal integration, user scope is less to
maintain and leaves no trace in the repo:

```json
{ "mcpServers": { "deepvista": { "type": "http", "url": "https://api.deepvista.ai/mcp" } } }
```

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

### If a bearer key is used instead

Follow the local-secrets convention rather than putting it in a repo file: keep
it in `~/.config/secrets.env` as `DEEPVISTA_API_KEY`, never printed (transcripts
get committed), and export it before starting the session so `.mcp.json` can
interpolate `${DEEPVISTA_API_KEY}` inside a `headers` block:

```bash
set -a; . ~/.config/secrets.env; set +a
```

`.mcp.json` interpolates from the environment of the process that *starts* the
server, so a key present in the file but never exported surfaces as an
authentication failure rather than as a missing variable.

## The cycle

`plan` and `record` are deterministic and live in a script. The MCP calls in
between are made by the model, because MCP tools are model-called — a shell
script cannot make them.

```bash
uv run scripts/deepvista_cards.py plan --repo . --week 2026-W35
#   → [model calls the DeepVista MCP card tool per item]
uv run scripts/deepvista_cards.py record --repo . --id <entity> --card-id <returned>
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

`record` writes `card_id`, `synced_at`, and the content hash back onto the
entity file, which is what makes the next run's `skip` decision possible. **If
record is skipped, the next run creates a duplicate card** — the entity has no
memory of having been pushed.

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
over stdio — the same proxy the `.mcp.json` entry names, started by the script
rather than by the host app. That works without a human because the proxy
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
  file, so it can be machine-specific in a way `.mcp.json` cannot.
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

## Test run — the procedure for the first live push

Nothing below this line has been exercised. Run it in order and stop at the
first surprise; the point is to find out where the inferred contract is wrong,
not to get cards in.

**1. Register the server** — from the skill, so the requirement travels with the
code that has it rather than being re-derived per repo:

```bash
uv run <skill>/scripts/deepvista_cards.py install-mcp --repo .
```

Idempotent, refuses to overwrite a conflicting entry, and writes **no
credentials** — the server does OAuth 2.1 with dynamic client registration, so
the entry is a name, a transport and a URL. `--scope user` instead prints the
vendor's own one-liner, which registers once for every repo on the machine:

```bash
claude mcp add --transport http deepvista-server https://api.deepvista.ai/mcp
```

**2. Authenticate — and this is the step to plan around, not discover.**

**There is no headless path today.** Every client the vendor documents ends in a
browser OAuth flow: Cursor restarts and runs *MCP: Connect to server*, Claude
Desktop quits and reopens, Claude Code runs `/mcp`. The docs also list API-key
auth — `Authorization: Bearer <key>` from *Settings → Security & Access* — which
would be headless, but **that setting is not exposed in the product yet**
(checked 2026-09-01). Until it is, OAuth is the only route.

**Which config you choose decides who runs the OAuth, and that is the whole
question.** `type: http` hands it to the host app's MCP client — needs nothing
installed, but the app must expose a connect flow you can reach. The
`mcp-remote` form runs a local stdio proxy that does the OAuth **itself** and
caches the token under `~/.mcp-auth`, so one browser sign-in makes every later
session headless, agent runs included — at the cost of a **Node 18+**
dependency, since `npx` runs the proxy.

`install-mcp` **chooses between them against the runtime that is actually
present** (`--transport auto`, the default), and `--transport mcp-remote|http`
overrides it. Prefer the proxy where Node can run it; the http form is a genuine
fallback rather than a downgrade, because DeepVista serves the discovery
metadata a native MCP client needs — verified live 2026-09-01:

| Probe | Result |
|---|---|
| `POST /mcp` unauthenticated | `401` + `WWW-Authenticate: Bearer resource_metadata=…` (RFC 9728) |
| Protected-resource metadata | `resource: https://api.deepvista.ai/mcp`, auth server `…supabase.co/auth/v1` |
| Authorization-server metadata | authorize + token + **`registration_endpoint`** (dynamic client registration), PKCE `S256` |

So the sequence is:

1. **Node 18+ only if you take the proxy form** — `npx` runs it, and nothing
   works without it. This is a *conditional* prerequisite, not an absolute one;
2. a **fresh** session, because MCP servers connect at start-up and one added to
   `.mcp.json` mid-session is invisible to that session;
3. the first launch opens a browser once. After that the cached token carries.

**Check it before the session start-up does**, which is the step whose absence
caused the 2026-09-01 break — `install-mcp` wrote an `npx` entry onto a machine
with no Node, reported success, and the failure appeared a session later as
`deepvista (ENOENT): Executable not found in $PATH: npx`, naming neither the
file nor the command responsible:

```bash
uv run <skill>/scripts/deepvista_cards.py doctor --repo .
```

It reports the runtime, the registered entry and the endpoint separately, exits
non-zero when the registration cannot work as written, and — for the exact
ENOENT case — prints the start-up error it is predicting, so the two are
recognisable as one problem.

An agent run can do everything up to the handoff — `install-mcp`, then `plan`,
which renders every card — and nothing past it. Plan for a human at step 2 rather
than discovering it there.

Do not reach for `deepvista auth login` to shortcut this; see the gotcha below.

**3. Dump the tool list before pushing anything.**

This step is not optional and the vendor docs are why. As of 2026-09-01 they
publish the setup command and the auth model and **nothing else** — no tool
names, no parameters, no `card_type` enum, no `status` field. The linked
OpenAPI specification is still Mintlify's stock plant-store example. So every
field this bridge sends is inferred from the CLI's REST calls and none of it is
confirmed against a served contract.

Ask for the DeepVista MCP tool list verbatim and reconcile it against what this
bridge emits. The card fields here — `card_type`, `title`, `description`,
`tags`, `status` — were read off the CLI's REST calls, **not off a connected
server**, so this is the step most likely to find a mismatch. Two things to check
specifically:

- Is there a `status` parameter at all? If the MCP tool does not expose it,
  cards will land `unconfirmed` and search will not surface them — which changes
  the plan from "push everything" to "push, then confirm in the UI".
- Does `card_type` accept the value being sent (`note`, `topic`, `keypoint`,
  `person`, `organization`)?

**4. Plan exactly one card.**

```bash
uv run .claude/skills/catchup/scripts/deepvista_cards.py plan --repo . --week 2026-W35 --limit 1 --show-body
```

Read the markdown body before it goes anywhere.

**5. Push that one**, by calling the MCP create tool with the `card` object.

**6. Check three things in the product**, in this order:

| Check | Why it matters |
|---|---|
| The card renders — timeline and all | The body is markdown; if it lands as a wall of text the format is wrong |
| **It is findable by search** | This is the `confirmed` test. If it does not appear, step 3's status question was the answer |
| Credit balance moved by how much | The free tier is 100/month; 25 entities at an unknown per-card cost is the actual budget question |

**7. Record the id and prove the skip works.**

```bash
uv run .claude/skills/catchup/scripts/deepvista_cards.py record --repo . --id <entity-id> --card-id <returned-id>
uv run .claude/skills/catchup/scripts/deepvista_cards.py plan --repo . --week 2026-W35 --include-skipped
```

That entity must now say `skip`. If it says `create`, the write-back did not
take and a full run would duplicate every card.

**8. Only then** push the rest — and consider `--category meeting` first, since
those entities are the ones whose value compounds.

**What to report back:** the tool list, which step surprised you, the credit
delta for one card, and whether search found it.

---
