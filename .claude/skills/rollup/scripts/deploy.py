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
import datetime as dt
import filecmp
import hashlib
import json
import os
import shutil
import sys

SCRIPT = os.path.abspath(__file__)
SRC_SKILL = os.path.dirname(os.path.dirname(SCRIPT))
SRC_ROOT = os.path.abspath(os.path.join(SRC_SKILL, "..", "..", ".."))

# This script means nothing outside the source repo: it is never copied into a
# target, and never counts as drift in either direction.
SELF_NAME = os.path.basename(SCRIPT)
# Which skill is being moved. Defaults to the one this script ships inside, so
# the common case needs no flag -- but the rollup skill has the same problem and
# now lives in a second repo, and a copy nobody can check for drift is how the
# whole class of bug this script exists for gets reintroduced.
SKILL_NAME = os.path.basename(SRC_SKILL)
PARTS = ["SKILL.md", "assets", "reference", "scripts"]

# What the last deploy put there, hashed. Without it a deploy cannot tell which
# side is newer -- it sees only that two files differ -- so it happily
# overwrites work the target gained after the copy. That is not hypothetical: a
# deploy run straight after merging a branch into a consuming repo destroyed the
# two fixes that merge existed to bring in, and the merge commit still looked
# clean because the files it touched were the ones the deploy replaced.
MANIFEST = ".deployed.json"


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
    """Every file under root, relative, excluding this script and the manifest."""
    out = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            rel = os.path.relpath(os.path.join(base, f), root)
            if os.path.basename(rel) in (SELF_NAME, MANIFEST):
                continue
            out.add(rel)
    return out


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def write_manifest(tskill):
    """Record what this deploy put there, so the next one can tell it apart."""
    body = {"deployed": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": SRC_ROOT,
            "files": {r: digest(os.path.join(tskill, r)) for r in sorted(walk(tskill))}}
    with open(os.path.join(tskill, MANIFEST), "w") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


def local_changes(tskill):
    """Files the TARGET changed since it was last deployed to.

    The direction a plain file comparison cannot give. `None` means there is no
    manifest -- an older deploy, or a copy made by hand -- and the honest answer
    is then "unknown", never "unchanged".
    """
    mpath = os.path.join(tskill, MANIFEST)
    if not os.path.isfile(mpath):
        return None
    try:
        with open(mpath) as fh:
            known = (json.load(fh) or {}).get("files") or {}
    except (json.JSONDecodeError, OSError):
        return None
    changed = []
    for rel in sorted(walk(tskill)):
        was = known.get(rel)
        now = digest(os.path.join(tskill, rel))
        if was is None:
            changed.append((rel, "added in the target"))
        elif was != now:
            changed.append((rel, "modified in the target"))
    for rel in sorted(set(known) - walk(tskill)):
        changed.append((rel, "deleted in the target"))
    return changed


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
    local = local_changes(tskill)
    if not (only_src or only_tgt or changed):
        print(f"in sync: {target}")
        return 0
    if local:
        print(f"{target} is AHEAD — changed since it was last deployed to:")
        for rel, how in local:
            print(f"  {how:<22} {rel}")
        print()
        print(f"  Carry it home:  deploy.py {target} --pull-back")
        print("  A deploy would overwrite these.")
        return 1
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

    # Source and target now match, so the manifest has to say so -- otherwise
    # the refusal the pull-back was run to clear survives it, and the documented
    # recovery does not actually recover.
    if not dry:
        write_manifest(tskill)

    print()
    print("  Now REVIEW before committing — this overwrote canon with a copy,")
    print("  and a target that is BEHIND source would regress it:")
    print(f"    git -C {SRC_ROOT} diff -- .claude/skills/{SKILL_NAME}")


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


def do_deploy(target, tskill, want_config, dry, force=False):
    # A deploy overwrites. If the target changed since it was last deployed to,
    # those changes are newer than the source and this would destroy them --
    # which is what happens right after a merge lands work in a consuming repo.
    if os.path.isdir(tskill):
        local = local_changes(tskill)
        if local is None:
            print("  note: no deploy manifest here, so local changes cannot be")
            print("        detected. This deploy will overwrite whatever is there.")
        elif local and not force:
            print(f"REFUSING: {target} has changes since it was last deployed to.")
            for rel, how in local:
                print(f"  {how:<22} {rel}")
            print()
            print("  These are NEWER than the source and a deploy would destroy them.")
            print(f"  Carry them home first:  deploy.py {target} --pull-back")
            print("  Or overwrite anyway:    add --force")
            return 1

    print(f"deploy {SKILL_NAME} -> {target}")
    if not dry:
        os.makedirs(os.path.join(target, ".claude", "skills"), exist_ok=True)
        os.makedirs(os.path.join(target, ".claude", "commands"), exist_ok=True)
        if os.path.isdir(tskill):
            shutil.rmtree(tskill)
        shutil.copytree(SRC_SKILL, tskill,
                        ignore=shutil.ignore_patterns(SELF_NAME, "__pycache__"))
        cmd = os.path.join(SRC_ROOT, ".claude", "commands", f"{SKILL_NAME}.md")
        if os.path.isfile(cmd):
            shutil.copy2(cmd, os.path.join(target, ".claude", "commands",
                                           f"{SKILL_NAME}.md"))
    else:
        print(f"  would: copy skill -> {tskill} (excluding {SELF_NAME})")

    cfg = os.path.join(target, ".claude", f"{SKILL_NAME}.config.json")
    example = os.path.join(SRC_SKILL, "assets", f"{SKILL_NAME}.config.example.json")
    if want_config and not os.path.isfile(example):
        print(f"  note: {SKILL_NAME} ships no config example; nothing to seed")
    elif want_config:
        if os.path.isfile(cfg):
            print(f"  config exists, left alone: .claude/{SKILL_NAME}.config.json")
        elif dry:
            print(f"  would: seed .claude/{SKILL_NAME}.config.json")
        else:
            shutil.copy2(example, cfg)
            print(f"  seeded .claude/{SKILL_NAME}.config.json")

    if not dry:
        write_manifest(tskill)
    check_runtime_pointer(target)
    print(f"done: .claude/skills/{SKILL_NAME} in {target}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="target repo(s)")
    ap.add_argument("--config", action="store_true", help="seed catchup.config.json if absent")
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 on drift")
    ap.add_argument("--check-all", action="store_true", help="check every target, exit 1 if any drift")
    ap.add_argument("--pull-back", action="store_true", help="target -> source (reverse review)")
    ap.add_argument("--force", action="store_true",
                    help="deploy even when the target has changes of its own")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.pull_back and (args.check or args.check_all):
        die("--pull-back and --check are opposite directions; pick one")
    if len(args.targets) > 1 and not args.check_all:
        die("multiple targets only make sense with --check-all")

    rc = 0
    for t in args.targets:
        target = resolve_target(t)
        tskill = os.path.join(target, ".claude", "skills", SKILL_NAME)
        if args.check or args.check_all:
            rc |= report(tskill, target)
        elif args.pull_back:
            do_pull_back(target, tskill, args.dry_run)
        else:
            rc |= do_deploy(target, tskill, args.config, args.dry_run, args.force) or 0
    sys.exit(rc)


if __name__ == "__main__":
    main()
