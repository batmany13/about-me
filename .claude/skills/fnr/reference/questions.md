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
      "memory": "<what the private side shows him for this block>",
      "default": "<where the machine version comes from>",
      "question": "<the one thing to ask>" },
    { "key": "lane_a", "title": "<Title>",  "owner": "machine", "source": "<what it is written from>",
      "memory": "<e.g. by outcome -> step: goal, plan changes, step states, PRs>", "budget": "<length>" },
    { "key": "lane_a_learning", "title": "Learning.", "under": "lane_a", "owner": "owner", "default": "...", "question": "..." },
    { "key": "finds",  "title": "<Title>",  "owner": "pick",
      "candidates": "<where the list comes from, and what excludes an item>", "question": "..." },
    { "key": "events", "title": "<Title>",  "owner": "owner",   "conditional": "events", "question": "..." },
    { "key": "the_one", "title": "<Title>", "owner": "owner",   "required": true, "default": null,
      "nudge": "<what to show him from the unredacted draft>", "question": "..." }
  ],
  "footer": "<the standing footer line>",
  "examples": { "<key>": [ { "week": "...", "verdict": "kept|rewritten|cut", "text": "...", "became": "...", "why": "...", "rule": "..." } ] }
}
```

| Field | Meaning |
|---|---|
| `owner` | `machine` — written from the record, scrubbed, never asked · `owner` — asked; the candidate holds the machine version · `pick` — asked; he picks from a candidate list, and only what he picks is published |
| `memory` | what the **unredacted** side shows for this section, as free text describing the shape (by outcome → step; by contact; …). The memory aid is the product: rich, unscrubbed, organized for recall. Optional; without it, the section's memory is the record's own detail |
| `default` | where the machine version of an owner block comes from — the fallback he can keep, and the eval baseline. Never an invented reflection in his voice. **`null` = no machine version**: the block holds a placeholder, Keep is refused, and the block has no baseline |
| `candidates` | for a `pick` section: where the list comes from and what excludes an item. The list goes in the **unredacted** block; the candidate block holds only a placeholder |
| `source` | what a machine section is written from |
| `budget` | a machine section's length |
| `stats` | the section carries the stat line |
| `under` | the section this block sits inside (a titled sub-block) |
| `required` | the weekly cannot publish until this block is *answered* (Skip and Keep refused) |
| `conditional` | dropped for a week without that material (`state.py init --without <key>`) |
| `nudge` | what to show alongside the question, drawn from the unredacted draft |
| `question` | the one thing asked, verbatim |

**Backward compatible.** A config without `memory`, `candidates` or any
`pick` section works as before: every `owner` block is asked, every `machine`
section is written.

## The loop

After the whole draft exists — never before — the `owner` and `pick` blocks
are asked **in config order, one per turn.** Each question shows **the block
from the memory aid** (the unredacted side, names and numbers intact — for a
pick block, the candidate list), then the `nudge` if there is one, then the
`question`. **It does not show the machine version.** He writes first:
seeing the machine's prose first does the reflecting for him and anchors the
answer. Replies:

- **Words** — his, verbatim; grammar and spelling only. For a pick block: the
  items he named, exactly as listed.
- **Keep** — the machine version stands. Refused on the required block, on a
  pick block, and where `default` is null.
- **Reveal** — only when he asks to see the machine version before deciding.
  `state.py reveal` shows it and records that it did; the answer that follows
  carries `revealed_before_answer: true`.
- **Skip** — the block comes out of the page (a pick block's section with
  it). **Refused on a required block.**

The answer goes straight into the candidate (`state.py answer`, then
`state.py paste`). It is never scrubbed, because he wrote it knowing where it
goes, and it never overwrites the memory aid. After he answers, `state.py
compare` shows his block beside the machine's with a similarity score — for
him to look at if he wants, never to steer a rewrite of what he wrote.

Every reply stores a `verdict` — `kept`, `rewritten` (his words), `skipped` —
beside the untouched machine version. `state.py pairs` turns them into the
eval dataset.

**Stopping is fine.** The state file (`drafts/<W>.state.json`) remembers where
the conversation is; the next session starts at the next pending question. If
the owner stops before a required block, the draft is saved and nothing
publishes. Commit and push the private branch after every answer.

**After the last block**, one more question — the delta's flagged list, which
is borderline scrub calls on *machine* text only — with two options: publish,
or hold. **Only an answer containing the word "publish" is publish.** His
decisions on the flagged items are applied to the candidate and the question
is asked again; anything else is hold. `state.py publish --decision publish`
requires his words quoted and refuses without the word; `state.py release`
is the only command that writes the public path.

## Under Claude

Each question is one `AskUserQuestion` with the memory-aid block in the
question body and the legal replies as options; "Words" is the free-text path,
recorded with `state.py answer <W> <key> --file`. A required block offers
Words and Hold, never Skip or Keep.

## Under Codex, or any runtime without a question tool

The turn ends with the memory-aid block, the nudge, and the single question,
and nothing else. The owner's reply is the answer. Record it the same way. Do
not batch questions to save turns — one per turn is the design, because the
owner answers each with that block's notes in front of him.

## What the machine may never do

- Ask a question before the whole draft exists.
- Show the machine version with the question, unless he asks (`reveal`).
- List a pick item he did not pick.
- Name a section or a question in this public skill — they live in the config.
- Edit an answered block. A re-render pastes answered blocks back from the
  state file byte for byte (`state.py paste`); `state.py check` fails if the
  file and the state disagree.
- Scrub an answer. Grammar and spelling only, with the owner's wording kept.
- Publish while a required block is unanswered.
