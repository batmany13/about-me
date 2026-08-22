# fnr — Field Notes & Reflections

A weekly, published Mondays, about the week that just closed.

## What FNR stands for

**F**ield **N**otes & **R**eflections.  It is also, deliberately, a pun on **F&R** — Freedom & Responsibility, the two words at the center of the Netflix culture I spent six years inside.

The joke is the point.  I have a great deal of freedom right now and no employer attached to it, which turns out to be a genuinely interesting test of how much of that model I'd internalized versus how much was scaffolding.  Freedom without an org around it is just unstructured time.  Responsibility without a manager is just a promise to yourself.  This file is where I keep the promise: a public, weekly, dated record that the freedom is producing something.

I ran a weekly internal newsletter at Netflix called Fast Takes for years.  I'm leaving that name where it was made.  This is the same habit, rebuilt for a different life.

## What's in one

Every week gets five sections:

- **Building** — what I made, and what I got wrong making it
- **Fund & Advisory** — the investing and founder work, in shape rather than in names
- **Rooms I Was In** — events I attended and the one interesting thing from each
- **Top of Mind for Founders** — leadership lessons surfacing from advisory conversations, anonymized to the pattern.  The section that ages best
- **Next** — what's queued, honestly

Plus a stats line: commits, repos, PRs, events, and roughly how the week split between building and fund work.

## How these are made

Mostly automatically, and that's part of what I'm testing.

A [skill](../.claude/skills/fnr/SKILL.md) reads the week's actual commits across several repos — most of them private — along with the calendar events I attended.  It writes a full, unscrubbed catchup into each source repo, where the real record lives.  Then it derives this public file from those, running every line through a scrub policy.

**Two layers, on purpose:**

| | Where | Who reads it | What's in it |
|---|---|---|---|
| Ground truth | inside each source repo, gitignored | me | everything |
| This | `fnr/`, committed | you | what survives the scrub |

The scrub policy is itself private, which I recognize is a slightly funny thing to say in public.  The short version: research subjects that are already public get named, problem classes and techniques get described, my own mistakes get published generously, and anything that belongs to a founder, a portfolio company, a person who was in a room with me, or my family does not appear here at all.

What you're getting is real but partial.  You should be able to tell from a year of these whether I'm someone you want to work with.  You should not be able to reconstruct what I'm building.

## The point of doing it in public

Two reasons, one respectable and one not.

The respectable one: I've told engineering leaders for years that they should be hands-on with the tools they're asking their teams to adopt.  This is me checking whether I can still do the thing I keep advising.

The other one: a private journal is very easy to skip.  A public one, with a date on it, is not.

---

_Files are named by ISO week — `2026-W34.md` — so they sort chronologically.  `ls` is the table of contents._

_See also: [what I'm doing now](../roles.md) · [investment thesis](../investing/README.md) · [ideas](../ideas/)_
