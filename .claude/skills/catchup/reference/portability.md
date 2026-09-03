# Running this skill under more than one agent runtime

This skill is written to be runtime-neutral, but it does not live in a neutral
place. `.claude/skills/` is a Claude Code convention, and other runtimes —
Codex in particular — look somewhere else. The skill works under both; what
takes care is making sure both are reading *the same copy*.

## The shape that works

**`.claude/` is the authored canon.** One source, edited in one place. Other
runtimes reach it through a pointer the repository owns:

```
.claude/skills/catchup/     <- authored here, always
.agents/skills -> ../.claude/skills   <- a TRACKED symlink, not a copy
AGENTS.md                   <- a compact router pointing at the canon
```

The symlink is committed (git mode `120000`), so a clone gets it and no
external importer has to synthesize one.

## Why not a copy

Because a copy is a fork that nobody declared. It works on the day it is made
and diverges silently from then on — the copy is what the other runtime reads,
so edits to canon simply stop taking effect, with no error and no signal. This
is not hypothetical: it is the observed failure mode when an external importer
owns the directory instead of the repository.

`deploy.py` therefore checks the state of `.agents/skills` after every deploy
and says which of the three cases the repo is in:

| State | Meaning |
|---|---|
| symlink | Fine. The pointer picks up whatever was just deployed. |
| **copied directory** | **Broken.** The other runtime reads the stale copy, not canon. |
| absent, `AGENTS.md` routes to `.claude/skills/` | Works — by prose, so it holds only while that sentence stays true. `deploy.py` says so |
| absent, `AGENTS.md` silent | The other runtime cannot see the skill at all yet. |

`deploy.py` also writes a `.deployed.json` manifest into the target recording
what it put there. On the next run it compares against that, so it can tell a
target that is merely *different* from one that is *ahead* — and refuses rather
than overwriting work the target gained after the copy.

**Commit the manifest.** It names the source by commit, never by path, so it
carries nothing machine-specific — and ignored, it exists only on the machine
that deployed, which puts every other clone back to "unknown" and lets the next
deploy there overwrite whatever it finds. `deploy.py` warns when a target
ignores it.

## A deploy lands on a branch, never in a main checkout

`deploy.py` writes files and nothing else. It does not commit, so whatever it
leaves in the target is the caller's to commit and put on a pull request — and
when the target checkout was on its default branch, nobody did: three repos
were found weeks later with an uncommitted skill sitting in their main checkout,
and the rescue was three pull requests of files nobody could date.

So the script **refuses to write into a checkout that is on its default branch**,
in either direction (a `--pull-back` writes into the source, and the source is a
checkout too). There is no override; the branch is the fix, and `--branch <name>`
makes it the easy one — a worktree under `.claude/worktrees/<name>` on a fresh
branch from origin's default, created if needed and reused if not:

```bash
uv run .claude/skills/catchup/scripts/deploy.py <repo> --branch catchup-sync
```

After a deploy the script lists what is now uncommitted and the commands to
land it. Two more things it checks in the target, because both are how a repo
quietly accumulates untracked files: `__pycache__/` must be ignored (running
the scripts writes one), and `.claude/worktrees/` must be ignored (or the
worktree itself shows up as an untracked directory in the main checkout).

The fix for a copied directory is always the same:

```bash
rm -rf .agents/skills && ln -s ../.claude/skills .agents/skills
```

## What this skill avoids depending on

So that it runs the same under either runtime:

- **No runtime-specific tool calls in the scripts.** They are plain Python 3 over
  `git` and `gh`, runnable from any shell, and the skill can be followed by hand.
- **The slash command is a convenience, not the interface.** `/catchup` is a
  Claude Code affordance; a runtime without slash commands invokes the skill by
  name or follows `SKILL.md` directly. Nothing in the workflow requires it.
- **One optional runtime dependency, declared:** the DeepVista sync calls MCP
  tools, which the *model* calls, not the scripts. `plan` and `record` stay
  deterministic and shell-runnable either way, and the sync is off by default.
- **Config, not code, carries repo specifics** — so a repo needs no per-runtime
  variant of the skill itself.

## Custom agents are a different problem

Skills are files and a pointer resolves them. Custom agent definitions are not
portable that way — they carry frontmatter (tools, permissions, sandbox mode)
that each runtime spells differently, so they need *generated adapters* with
recorded provenance and a check that the generated form has not drifted from
its source. That is out of scope here; this skill defines no custom agents,
which is one reason it stays portable.
