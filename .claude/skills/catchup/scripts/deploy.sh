#!/usr/bin/env bash
# Deploy the catchup skill into any repo.
#
# about-me is the source of truth. This copies the skill and its slash command
# into a target repo, and seeds a config only if that repo has none -- an
# existing config is a repo's own tuning and is never overwritten.
#
#   deploy.sh /path/to/repo            # copy skill + command
#   deploy.sh /path/to/repo --config   # also seed catchup.config.json if absent
#   deploy.sh /path/to/repo --dry-run
set -euo pipefail

SRC_SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="$(cd "$SRC_SKILL/../../.." && pwd)"

TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "usage: deploy.sh <target-repo> [--config] [--dry-run]" >&2; exit 2; }
shift || true

WANT_CONFIG=0; DRY=0
for a in "$@"; do
  case "$a" in
    --config)  WANT_CONFIG=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "deploy: unknown flag $a" >&2; exit 2 ;;
  esac
done

TARGET="$(cd "$TARGET" 2>/dev/null && pwd)" || { echo "deploy: no such directory: $1" >&2; exit 1; }
[ -d "$TARGET/.git" ] || [ -f "$TARGET/.git" ] || { echo "deploy: not a git repo: $TARGET" >&2; exit 1; }
[ "$TARGET" != "$SRC_ROOT" ] && : || { echo "deploy: target is the source repo" >&2; exit 1; }

run() { if [ "$DRY" = 1 ]; then echo "  would: $*"; else "$@"; fi; }

echo "deploy catchup -> $TARGET"
run mkdir -p "$TARGET/.claude/skills" "$TARGET/.claude/commands"
run rm -rf "$TARGET/.claude/skills/catchup"
run cp -R "$SRC_SKILL" "$TARGET/.claude/skills/catchup"
run cp "$SRC_ROOT/.claude/commands/catchup.md" "$TARGET/.claude/commands/catchup.md"

# The deploy script itself is only meaningful in the source repo.
run rm -f "$TARGET/.claude/skills/catchup/scripts/deploy.sh"

CFG="$TARGET/.claude/catchup.config.json"
if [ "$WANT_CONFIG" = 1 ]; then
  if [ -f "$CFG" ]; then
    echo "  config exists, left alone: .claude/catchup.config.json"
  else
    run cp "$SRC_SKILL/assets/catchup.config.example.json" "$CFG"
    echo "  seeded .claude/catchup.config.json — edit repo.label and authors.people"
  fi
fi

# --- agent-runtime portability ---------------------------------------------
# `.claude/` is the authored canon; this script only ever writes there. Other
# runtimes are expected to REACH that canon rather than hold a second copy of
# it, so the one thing worth checking is whether this repo's `.agents/skills`
# is a pointer or a duplicate. A duplicate silently shadows everything we just
# deployed, and drifts from the day it is made.
AG="$TARGET/.agents/skills"
if [ -L "$AG" ]; then
  echo "  codex: .agents/skills -> $(readlink "$AG") (pointer — picks this up automatically)"
elif [ -d "$AG" ]; then
  echo "  WARNING: .agents/skills is a COPIED DIRECTORY, not a symlink."
  echo "           Codex will read that stale copy, not what was just deployed."
  echo "           Replace it with a tracked pointer:"
  echo "             rm -rf .agents/skills && ln -s ../.claude/skills .agents/skills"
elif [ -e "$TARGET/AGENTS.md" ]; then
  echo "  note: AGENTS.md exists but there is no .agents/skills pointer —"
  echo "        Codex cannot see this skill until one is added."
fi

echo "done. Try: cd $TARGET && python3 .claude/skills/catchup/scripts/pull_week.py --list-weeks"
