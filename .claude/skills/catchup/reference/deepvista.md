# DeepVista sync — prototype

Pushes catchup **entities** into [DeepVista](https://deepvista.ai) as context
cards. Off unless a repo's config sets `deepvista.enabled: true`.

Status: **prototype.** The card shape and the create/update/skip cycle are
built and tested locally; what has not been exercised is a live account. The
open questions are listed at the bottom.

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
client registration, so the client registers itself and the browser does the
rest. Add this to the target repo's `.mcp.json` — note there is no `headers`
block:

```json
{
  "mcpServers": {
    "deepvista": {
      "type": "http",
      "url": "https://api.deepvista.ai/mcp"
    }
  }
}
```

Then, **in an interactive session**, run `/mcp`, pick `deepvista`, and complete
the browser sign-in. A non-interactive session cannot do this — there is no
prompt to answer — so authenticate once interactively and the stored credentials
carry over.

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
python3 scripts/deepvista_cards.py plan --repo . --week 2026-W35
#   → [model calls the DeepVista MCP card tool per item]
python3 scripts/deepvista_cards.py record --repo . --id <entity> --card-id <returned>
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
| `status` | `confirmed` — see the gotcha |

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
card this bridge sends therefore sets `status: "confirmed"`. Leave
`deepvista.card_status` alone unless you specifically want cards staged for
review.

## What is not verified yet

Honest list, so nothing here reads as tested when it isn't:

1. **A live account.** No card has been pushed. Everything below the `plan`
   output is unexercised.
2. **The MCP tool names and their exact parameters.** The field names above come
   from the `deepvista-cli` source (`/create_context_card`, `/update_context_card`),
   which is the REST contract the MCP server sits in front of. The MCP tools
   almost certainly mirror it, but read the tool list once connected and adjust
   the mapping if it differs.
3. ~~Whether a bearer key is needed.~~ **Resolved: OAuth is the route**, and its
   discovery chain is verified live. The *authenticated* session beyond the 401
   challenge is still untested.
4. **Whether `status: confirmed` is settable through MCP.** It is a REST field;
   the MCP tool may not expose it. If it doesn't, cards will need confirming in
   the UI, and that is worth knowing before a bulk push.
5. **Credit cost per card write.** Unmeasured. Push one entity first and check
   the balance before running a backfill.

**The contract this was built against is the `deepvista-cli` source** (Apache-2.0),
specifically its `/create_context_card` and `/update_context_card` calls. Prefer
it over the rendered API reference, and reconcile against the live MCP tool list
once connected.

## First run, in order

1. Add the `.mcp.json` entry (no headers), then run `/mcp` in an **interactive**
   session and complete the browser sign-in. There is no key to obtain.
2. Confirm the connection and **dump the MCP tool list** — reconcile it against
   the field names above before pushing anything.
3. `plan --week <week>` and read one full body with `--show-body`.
4. Push **one** entity. Check it renders in DeepVista, is findable in search
   (this is the `confirmed` test), and note the credit cost.
5. `record` its card id, re-run `plan`, and confirm it now says `skip`.
6. Only then push the rest.
