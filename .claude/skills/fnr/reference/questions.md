# The questions — one per turn

Six blocks are the owner's. Each is asked once, in this order, one per turn,
after the machine has written the whole draft. Every question shows the same
two things first — **the unredacted section** (the memory jog, names and
numbers intact) and **the scrubbed section** (exactly what will publish) —
then asks one thing. The answer goes straight into the scrubbed file,
verbatim; it is never scrubbed, because the owner wrote it knowing where it
goes.

Options on every question: **Keep** (the machine text stands) · **Edit** (the
owner's words replace it) · **Skip** (not answered; machine text stands). One
question refuses Skip.

| # | key | Block | Ask | Required |
|---|---|---|---|---|
| 1 | `blurb` | The opening under the title | "That's how the week reads from the record. How did it actually feel, and what was it *for*? Keep, or say it in your words." | no |
| 2 | `building_learning` | `Building` → **Learning.** | "The machine's learning is the top-ranked one from the tech catchup. Is that the thing you'd tell someone about this week's building — or is it something else?" | no |
| 3 | `fund_learning` | `Fund & Advisory` → **Learning.** | Same, from the fund catchup. Prompt into the week's conversations: what did they surface that the record can't show? | no |
| 4 | `rooms` | `Rooms I Was In` | Only when the week had events. "The registry says what the room was planned to be. What was it actually like?" | no |
| 5 | `top_of_mind` | `Top of Mind for Founders` | **One item.** Shown with the talent seam from this week's unredacted conversations as the nudge — hiring, motivating, growing, keeping a culture alive — and the reminder that nothing in the nudge may appear by name. "What's the one thing you'd say to a founder this week?" | **yes** |
| 6 | `next` | `Next` | "The calendar gives this shape for next week. Anything planned but not on it? If it's a public event, name it." | no |
| 7 | `publish` | — | The machine's flagged list — borderline scrub calls on *machine* text only — shown once. "Publish, or hold?" | yes, but only after 5 |

**Stopping is fine.** The state file remembers where the conversation is;
the next session starts at the next pending question. If the owner stops
before `top_of_mind`, the draft is saved and nothing publishes — that is the
one block the weekly cannot go out without.

## Under Claude

Each question is one `AskUserQuestion` with three options — Keep / Edit /
Skip — and the two sections in the question body. "Edit" is the free-text
path; the owner's text is recorded with `state.py answer <W> <key> --file`.
`top_of_mind` gets two options, Edit only plus a hold, never Skip.

## Under Codex, or any runtime without a question tool

The turn ends with the two sections and the single question, and nothing
else. The owner's reply is the answer. Record it the same way. Do not batch
questions to save turns — one per turn is the design, because the owner
answers each with the section in front of them.

## What the machine may never do

- Ask a question before the whole draft exists.
- Edit an answered block. A re-render pastes answered blocks back from the
  state file byte for byte (`state.py paste`), and `state.py check` fails if
  the file and the state disagree.
- Scrub an answer. Grammar and spelling only, and only with the owner's
  wording kept — the verbatim rule in `SKILL.md`.
- Publish without `top_of_mind`.
