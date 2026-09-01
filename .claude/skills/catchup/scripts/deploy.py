#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Move the catchup skill between its source of truth and a target repo.

The skill is edited in one place and copied into the repos that run it. Copies
drift -- so this goes BOTH ways, because in practice defects are found where the
skill RUNS, not where it is edited, and a one-way deploy turns every such fix
into a manual transcription.

    deploy.py <repo>              # source -> repo
    deploy.py <repo> --config     # ...and seed catchup.config.json if absent
    deploy.py <repo> --check      # compare only; exit 1 if they differ
    deploy.py <repo> --pull-back  # repo -> source (the reverse review)
    deploy.py <repo> --dry-run
    deploy.py --check-all <repo> [<repo> ...]
"""

import argparse
import filecmp
import os
import shutil
import sys

SCRIPT = os.path.abspath(__file__)
SRC_SKILL = os.path.dirname(os.path.dirname(SCRIPT))
SRC_ROOT = os.path.abspath(os.path.join(SRC_SKILL, "..", "..", ".."))

# This script means nothing outside the source repo: it is never copied into a
# target, and never counts as drift in either direction.
SELF_NAME = os.path.basename(SCRIPT)
PARTS = ["SKILL.md", "assets", "reference", "scripts"]


def die(msg, code=1):
    print(f"deploy: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_target(path):
    t = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(t):
        die(f"no such directory: {path}")
    if not os.path.exists(os.path.join(t, ".git")):
        die(f"not a git repo: {t}")
    if t == SRC_ROOT:
        die("target is the source repo")
    return t


def walk(root):
    """Every file under root, relative, excluding this script."""
    out = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            rel = os.path.relpath(os.path.join(base, f), root)
            if os.path.basename(rel) == SELF_NAME:
                continue
            out.add(rel)
    return out


def differences(tskill):
    """(only_in_source, only_in_target, differing_content) -- all relative paths."""
    if not os.path.isdir(tskill):
        return None
    a, b = walk(SRC_SKILL), walk(tskill)
    diff = sorted(
        r for r in (a & b)
        if not filecmp.cmp(os.path.join(SRC_SKILL, r), os.path.join(tskill, r), shallow=False)
    )
    return sorted(a - b), sorted(b - a), diff


def report(tskill, target):
    d = differences(tskill)
    if d is None:
        print(f"not deployed: {tskill}")
        return 1
    only_src, only_tgt, changed = d
    if not (only_src or only_tgt or changed):
        print(f"in sync: {target}")
        return 0
    print(f"DRIFT between source and {target}:")
    for r in changed:
        print(f"  differs           {r}")
    for r in only_src:
        print(f"  missing in target {r}")
    for r in only_tgt:
        print(f"  only in target    {r}")
    print()
    print(f"  source -> target:  deploy.py {target}")
    print(f"  target -> source:  deploy.py {target} --pull-back")
    return 1


def copy_part(src, dst, dry):
    if dry:
        print(f"  would: copy {os.path.relpath(src, os.path.dirname(src))} -> {dst}")
        return
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    elif os.path.exists(dst):
        os.remove(dst)
    if os.path.isdir(src):
        # Build artifacts are not part of the skill and must not travel in
        # either direction -- a pulled-back __pycache__ would land compiled
        # bytecode in the source repo.
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.pyo"))
    else:
        shutil.copy2(src, dst)


def do_pull_back(target, tskill, dry):
    d = differences(tskill)
    if d is None:
        die(f"nothing deployed at {tskill}")
    only_src, only_tgt, changed = d
    if not (only_src or only_tgt or changed):
        print("already in sync — nothing to pull back")
        return
    print(f"pull back: {target} -> source")
    for r in changed:
        print(f"  differs        {r}")
    for r in only_tgt:
        print(f"  new in target  {r}")
    for r in only_src:
        print(f"  WOULD DELETE   {r}  (present in source, absent in target)")

    # Preserve this script by CONTENT. Restoring it from git would silently
    # discard uncommitted edits to deploy.py itself -- which is exactly what the
    # first version of this path did.
    keep = None
    if not dry and os.path.isfile(SCRIPT):
        with open(SCRIPT, "rb") as fh:
            keep = fh.read()

    for part in PARTS:
        s = os.path.join(tskill, part)
        if os.path.exists(s):
            copy_part(s, os.path.join(SRC_SKILL, part), dry)

    if keep is not None:
        os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
        with open(SCRIPT, "wb") as fh:
            fh.write(keep)
        os.chmod(SCRIPT, 0o755)

    print()
    print("  Now REVIEW before committing — this overwrote canon with a copy,")
    print("  and a target that is BEHIND source would regress it:")
    print(f"    git -C {SRC_ROOT} diff -- .claude/skills/catchup")


def check_runtime_pointer(target):
    """Whether another agent runtime can reach what was just deployed."""
    ag = os.path.join(target, ".agents", "skills")
    if os.path.islink(ag):
        print(f"  codex: .agents/skills -> {os.readlink(ag)} "
              "(pointer — picks this up automatically)")
    elif os.path.isdir(ag):
        print("  WARNING: .agents/skills is a COPIED DIRECTORY, not a symlink.")
        print("           Codex reads that stale copy, not what was just deployed.")
        print("             rm -rf .agents/skills && ln -s ../.claude/skills .agents/skills")
    elif os.path.exists(os.path.join(target, "AGENTS.md")):
        print("  note: AGENTS.md exists but there is no .agents/skills pointer —")
        print("        Codex cannot see this skill until one is added.")


def do_deploy(target, tskill, want_config, dry):
    print(f"deploy catchup -> {target}")
    if not dry:
        os.makedirs(os.path.join(target, ".claude", "skills"), exist_ok=True)
        os.makedirs(os.path.join(target, ".claude", "commands"), exist_ok=True)
        if os.path.isdir(tskill):
            shutil.rmtree(tskill)
        shutil.copytree(SRC_SKILL, tskill,
                        ignore=shutil.ignore_patterns(SELF_NAME, "__pycache__"))
        shutil.copy2(os.path.join(SRC_ROOT, ".claude", "commands", "catchup.md"),
                     os.path.join(target, ".claude", "commands", "catchup.md"))
    else:
        print(f"  would: copy skill -> {tskill} (excluding {SELF_NAME})")

    cfg = os.path.join(target, ".claude", "catchup.config.json")
    if want_config:
        if os.path.isfile(cfg):
            print("  config exists, left alone: .claude/catchup.config.json")
        elif dry:
            print("  would: seed .claude/catchup.config.json")
        else:
            shutil.copy2(os.path.join(SRC_SKILL, "assets",
                                      "catchup.config.example.json"), cfg)
            print("  seeded .claude/catchup.config.json — edit repo.label and authors.people")

    check_runtime_pointer(target)
    print(f"done. Try: cd {target} && uv run .claude/skills/catchup/scripts/pull_week.py --list-weeks")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="target repo(s)")
    ap.add_argument("--config", action="store_true", help="seed catchup.config.json if absent")
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 on drift")
    ap.add_argument("--check-all", action="store_true", help="check every target, exit 1 if any drift")
    ap.add_argument("--pull-back", action="store_true", help="target -> source (reverse review)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.pull_back and (args.check or args.check_all):
        die("--pull-back and --check are opposite directions; pick one")
    if len(args.targets) > 1 and not args.check_all:
        die("multiple targets only make sense with --check-all")

    rc = 0
    for t in args.targets:
        target = resolve_target(t)
        tskill = os.path.join(target, ".claude", "skills", "catchup")
        if args.check or args.check_all:
            rc |= report(tskill, target)
        elif args.pull_back:
            do_pull_back(target, tskill, args.dry_run)
        else:
            do_deploy(target, tskill, args.config, args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
