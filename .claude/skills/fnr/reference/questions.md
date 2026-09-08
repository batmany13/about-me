# The questions — one per turn

**Which blocks exist, what they are called, which are the owner's, which one
is required, and what each question asks are all declared in the private
config** — `fnr/.private/fnr.config.json`, `sections[]`. This file describes
only the mechanism. Nothing here names a section, because this file is public
and the sections are the owner's.

```json
{
  "contract": "fnr-config/v1",
  "sections": [
    { "key": "blurb",  "title": null,       "owner": "owner",   "required": false,
      "default": "<where the machine default comes from>",
      "question": "<the one thing to ask>" },
    { "key": "lane_a", "title": "<Title>",  "owner": "machine", "source": "<what it is written from>" },
    { "key": "lane_a_learning", "title": "Learning.", "under": "lane_a", "owner": "owner", "required": false, "default": "...", "question": "..." },
    { "key": "events", "title": "<Title>",  "owner": "owner",   "conditional": "events", "question": "..." },
    { "key": "the_one", "title": "<Title>", "owner": "owner",   "required": true, "nudge": "<what to show him from the unredacted draft>", "question": "..." }
  ],
  "footer": "<the standing footer line>"
}
```

| Field | Meaning |
|---|---|
| `owner` | `machine` — written from the record, never asked · `owner` — filled with a machine default, then asked |
| `required` | the weekly cannot publish until this block is *answered* (Skip is refused) |
| `conditional` | dropped for a week without that material (`state.py init --without <key>`) |
| `default` | where the machine default for an owner block comes from — it is never an invented reflection |
| `nudge` | what to show alongside the question, drawn from the unredacted draft |
| `question` | the one thing asked, verbatim |

## The loop

After the whole draft exists — never before — the owner blocks are asked
**in config order, one per turn.** Every question shows the same two things
first: **the unredacted section** (the memory jog, names and numbers intact)
and **the scrubbed section** (exactly what will publish), then the `nudge` if
the block has one, then the `question`. Options on every question:

- **Keep** — the machine default stands.
- **Edit** — the owner's words replace it, verbatim; grammar and spelling only.
- **Skip** — not answered; the machine default stands. **Refused on a required block.**

The answer goes straight into the scrubbed file (`state.py answer`, then
`state.py paste`) and is mirrored into the unredacted one. It is never
scrubbed, because the owner wrote it knowing where it goes.

**Stopping is fine.** The state file (`drafts/<W>.state.json`) remembers where
the conversation is; the next session starts at the next pending question. If
the owner stops before a required block, the draft is saved and nothing
publishes.

**After the last block**, one more question — the delta's flagged list
(borderline scrub calls) and its reads-confusing list (machine paragraphs that
need the reader to know the system, each with the plain sentence proposed), both on *machine* text only — with two options: publish,
or hold. **Only an answer containing the word "publish" is publish.** His
decisions on the flagged items are applied to the candidate and the question
is asked again; anything else is hold. `state.py publish --decision publish`
requires his words quoted and refuses without the word; `state.py release`
is the only command that writes the public path.

## Under Claude

Each question is one `AskUserQuestion` with the options above and the two
sections in the question body. "Edit" is the free-text path; record the text
with `state.py answer <W> <key> --file`. A required block offers Edit and Hold,
never Skip.

## Under Codex, or any runtime without a question tool

The turn ends with the two sections, the nudge, and the single question, and
nothing else. The owner's reply is the answer. Record it the same way. Do not
batch questions to save turns — one per turn is the design, because the
owner answers each with the section in front of him.

## What the machine may never do

- Ask a question before the whole draft exists.
- Name a section or a question in this public skill — they live in the config.
- Edit an answered block. A re-render pastes answered blocks back from the
  state file byte for byte (`state.py paste`); `state.py check` fails if the
  file and the state disagree.
- Scrub an answer. Grammar and spelling only, with the owner's wording kept.
- Publish while a required block is unanswered.
