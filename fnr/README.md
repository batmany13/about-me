# fnr — Field Notes & Reflections

A weekly, published Mondays, about the week that just closed.

## What FNR stands for

**F**ield **N**otes & **R**eflections.  It is also, deliberately, a pun on **F&R** — Freedom & Responsibility, the two words at the center of the Netflix culture I spent nearly seven years inside.

The joke is the point.  I have a great deal of freedom right now and no employer attached to it, which turns out to be a genuinely interesting test of how much of that model I'd internalized versus how much was scaffolding.  Freedom without an org around it is just unstructured time.  Responsibility without a manager is just a promise to yourself.  This file is where I keep the promise: a public, weekly, dated record that the freedom is producing something.

I ran a weekly internal newsletter at Netflix called Fast Takes for years.  I'm leaving that name where it was made.  This is the same habit, rebuilt for a different life.

## What's in one

Every week gets up to six sections:

- **Building** — what I made and what I got wrong making it, then the week's learning
- **Fund & Advisory** — the investing and founder work, in shape rather than in names, then its learning
- **Rooms I Was In** — events I attended and the one interesting thing from each
- **Top of Mind for Founders** — leadership lessons surfacing from advisory conversations, anonymized to the pattern.  The section that ages best
- **On the Bench** — technologies and concepts queued to vet or learn, and why they got queued
- **Next** — what's queued, honestly

`Building` and `Top of Mind for Founders` are in every week, including the quiet ones.  `Rooms I Was In` and `On the Bench` only appear when the week earned them — a week with no events and nothing new queued drops those headers rather than writing "nothing this week".

Plus a stats line — commits, PRs, repo count, and roughly how the week split between building and fund work.  Counts, not names.

The updates are deliberately short.  The one or two sentences of learning at the end of each are the part I actually write these for.

## How these are made

Half automatically, in two passes, and the split between them is the part I find interesting.

A [skill](../.claude/skills/fnr/SKILL.md) reads the week's actual commits across several repos — most of them private — along with the calendar events I attended, and writes a full unscrubbed catchup into each source repo where the real record lives.  From those it drafts this file.

**That first draft exists to remind me what I did.**  After a week heads-down across several repos I genuinely don't remember the shape of it, and reading it back is what produces the reaction.  Then I correct it — the facts are usually wrong in small ways the commits can't show — and write the learnings myself.  The second pass folds my words in and rewrites the summary around them.

So: the machine reconstructs, I reflect, the machine revises.  The facts come from the data; the meaning doesn't.  A draft that invented the learnings for me would read fine and be worthless, which is a decent description of the whole risk with this technology.

**Two layers, on purpose:**

| | Where | Who reads it | What's in it |
|---|---|---|---|
| Ground truth | inside each source repo, gitignored | me | everything |
| This | `fnr/`, committed | you | what survives the scrub |

The scrub policy is itself private, which I recognize is a slightly funny thing to say in public.  The short version: problem classes and techniques get described, my own mistakes get published generously, and none of it names the thing I'm building.  Anything belonging to a founder, a portfolio company, a person who was in a room with me, or my family doesn't appear here at all.

What you're getting is real but partial.  You should be able to tell from a year of these whether I'm someone you want to work with.  You should not be able to reconstruct what I'm building.

## The point of doing it in public

Two reasons, one respectable and one not.

The respectable one: I've told engineering leaders for years that they should be hands-on with the tools they're asking their teams to adopt.  This is me checking whether I can still do the thing I keep advising.

The other one: a private journal is very easy to skip.  A public one, with a date on it, is not.

---

_Files are named by ISO week — `2026-W34.md` — so they sort chronologically.  `ls` is the table of contents._

_See also: [what I'm doing now](../roles.md) · [investment thesis](../investing/README.md) · [ideas](../ideas/)_
