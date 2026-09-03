#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Move a skill between its source of truth and a target repo.

The skill is edited in one place and copied into the repos that run it. Copies
drift -- so this goes BOTH ways, because in practice defects are found where the
skill RUNS, not where it is edited, and a one-way deploy turns every such fix
into a manual transcription.

    deploy.py <repo>                    # source -> repo
    deploy.py <repo> --branch <name>    # ...into a worktree of <repo> on branch <name>
    deploy.py <repo> --config           # ...and seed the config file if absent
    deploy.py <repo> --check            # compare only; exit 1 if they differ
    deploy.py <repo> --pull-back        # repo -> source (the reverse review)
    deploy.py <repo> --dry-run
    deploy.py --check-all <repo> [<repo> ...]

A deploy WRITES into a checkout and does nothing else: no commit, no branch.
Whatever it leaves behind is the caller's to commit -- and when the checkout
was on its default branch, nobody did. Three repos were found weeks later with
an uncommitted skill sitting in their main checkout, and the rescue was three
pull requests of files nobody could date. So this script refuses to write into
a checkout that is on its default branch, in EITHER direction, and `--branch`
makes the right shape the easy one: a worktree under `.claude/worktrees/<name>`
on a fresh branch, which is the only edit surface an agent session should have.
"""

import argparse
import datetime as dt
import filecmp
import hashlib
import json
import os
import shutil
import subprocess
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
# whole class of bug this script exists for gets reintroduced. The two copies of
# THIS file are kept identical by hand; `diff` them when either changes.
SKILL_NAME = os.path.basename(SRC_SKILL)
PARTS = ["SKILL.md", "assets", "reference", "scripts"]
# The slash-command file travels with the skill when the source has one. It
# lives outside the skill directory, so it is compared on its own.
COMMAND_REL = os.path.join(".claude", "commands", f"{SKILL_NAME}.md")
WORKTREES_REL = os.path.join(".claude", "worktrees")

# What the last deploy put there, hashed. Without it a deploy cannot tell which
# side is newer -- it sees only that two files differ -- so it happily
# overwrites work the target gained after the copy. That is not hypothetical: a
# deploy run straight after merging a branch into a consuming repo destroyed the
# two fixes that merge existed to bring in, and the merge commit still looked
# clean because the files it touched were the ones the deploy replaced.
#
# The manifest is meant to be COMMITTED in the target. Ignored, it exists only
# on the machine that deployed, and every other clone is back to "unknown".
# It records the source by commit, never by path: a path is machine-local and
# says nothing about which version of the skill this is.
MANIFEST = ".deployed.json"


def die(msg, code=1):
    print(f"deploy: {msg}", file=sys.stderr)
    sys.exit(code)


# --- git ---------------------------------------------------------------------

def git(repo, *args, ok_fail=False):
    """stdout of a git command in `repo`, stripped; None on failure if ok_fail."""
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if p.returncode != 0:
        if ok_fail:
            return None
        die(f"git {' '.join(args)} failed in {repo}: {p.stderr.strip()}")
    return p.stdout.strip()


def current_branch(repo):
    """Branch name, or None on a detached HEAD."""
    return git(repo, "symbolic-ref", "--short", "-q", "HEAD", ok_fail=True) or None


def default_branch(repo):
    """What `origin/HEAD` points at, else main/master if either exists, else None."""
    ref = git(repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", ok_fail=True)
    if ref:
        return ref.split("/", 1)[1] if "/" in ref else ref
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", ok_fail=True):
            return name
    return None


def guard_branch(repo, what):
    """Refuse to write into a checkout on its default branch, or on no branch.

    The point of the whole script is that a deploy is reviewable: it lands on a
    branch, gets committed there, and arrives on main through a pull request
    like any other change. Written straight into the main checkout it is none
    of those things -- it is uncommitted cruft that `git status` shows and
    nobody reads, until a later session finds it and has to guess where it came
    from. There is no flag to override this; the branch is the fix.
    """
    branch = current_branch(repo)
    if branch is None:
        die(f"REFUSING to {what} {repo}: detached HEAD. Check out a branch first.")
    default = default_branch(repo)
    if default and branch == default:
        rel = os.path.join(WORKTREES_REL, "<name>")
        die(f"REFUSING to {what} {repo}: its checkout is on '{default}', the default branch.\n"
            "  A deploy leaves uncommitted files behind, and on the default branch those\n"
            "  are cruft nobody will find until they get in the way. Put it on a branch:\n"
            f"    {SELF_NAME} {repo} --branch <name>      # worktree at {rel}\n"
            "  or hand it a worktree you made yourself:\n"
            f"    git -C {repo} worktree add -b <name> {rel}\n"
            f"    {SELF_NAME} {os.path.join(repo, rel)}")
    return branch


def dirty(repo, paths):
    """Uncommitted changes (tracked or not) under `paths`, as porcelain lines."""
    existing = [p for p in paths if os.path.exists(os.path.join(repo, p))]
    if not existing:
        return []
    out = git(repo, "status", "--porcelain", "--untracked-files=all", "--", *existing,
              ok_fail=True) or ""
    return [ln for ln in out.splitlines() if ln.strip()]


def is_ignored(repo, rel):
    p = subprocess.run(["git", "-C", repo, "check-ignore", "-q", rel], capture_output=True)
    return p.returncode == 0


def ensure_worktree(repo, name):
    """A worktree of `repo` at .claude/worktrees/<name> on branch <name>.

    Reused if it already exists. Otherwise created from origin's default branch
    when that ref is known (after a best-effort fetch), else from HEAD -- so a
    deploy starts from what main actually is, not from wherever the primary
    checkout happened to be left.
    """
    path = os.path.join(repo, WORKTREES_REL, name)
    if os.path.isdir(path) and os.path.exists(os.path.join(path, ".git")):
        print(f"worktree: using existing {os.path.relpath(path, repo)} "
              f"(branch {current_branch(path) or 'DETACHED'})")
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", ok_fail=True):
        git(repo, "worktree", "add", path, name)
        print(f"worktree: checked out existing branch {name} at {os.path.relpath(path, repo)}")
    else:
        subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], capture_output=True)
        default = default_branch(repo)
        base = f"origin/{default}" if default and git(
            repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{default}",
            ok_fail=True) else "HEAD"
        git(repo, "worktree", "add", "-b", name, path, base)
        print(f"worktree: created {os.path.relpath(path, repo)} on new branch {name} from {base}")
    if not is_ignored(repo, os.path.join(WORKTREES_REL, name)):
        print(f"  WARNING: {WORKTREES_REL}/ is not ignored in {repo}, so the worktree itself")
        print("           shows up as an untracked directory in the main checkout.")
        print(f"           Add `/{WORKTREES_REL}` to its .gitignore.")
    return path


def source_stamp():
    """Which version of the skill this is -- by commit, never by path."""
    return {
        "skill": SKILL_NAME,
        "commit": git(SRC_ROOT, "rev-parse", "--short=12", "HEAD", ok_fail=True),
        "branch": current_branch(SRC_ROOT),
        "dirty": bool(dirty(SRC_ROOT, [os.path.relpath(SRC_SKILL, SRC_ROOT)])),
    }


# --- comparing ---------------------------------------------------------------

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
            "source": source_stamp(),
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


def command_state(target):
    """How the slash-command file compares: None (same or n/a), 'missing', 'differs'."""
    src = os.path.join(SRC_ROOT, COMMAND_REL)
    if not os.path.isfile(src):
        return None
    dst = os.path.join(target, COMMAND_REL)
    if not os.path.isfile(dst):
        return "missing in target"
    return None if filecmp.cmp(src, dst, shallow=False) else "differs"


def report(tskill, target):
    d = differences(tskill)
    if d is None:
        print(f"not deployed: {tskill}")
        return 1
    only_src, only_tgt, changed = d
    cmd = command_state(target)
    local = local_changes(tskill)
    if not (only_src or only_tgt or changed or cmd):
        print(f"in sync: {target}")
        return 0
    if local:
        print(f"{target} is AHEAD — changed since it was last deployed to:")
        for rel, how in local:
            print(f"  {how:<22} {rel}")
        print()
        print(f"  Carry it home:  {SELF_NAME} {target} --pull-back")
        print("  A deploy would overwrite these.")
        return 1
    print(f"DRIFT between source and {target}:")
    for r in changed:
        print(f"  differs           {r}")
    for r in only_src:
        print(f"  missing in target {r}")
    for r in only_tgt:
        print(f"  only in target    {r}")
    if cmd:
        print(f"  {cmd:<17} {COMMAND_REL}")
    print()
    print(f"  source -> target:  {SELF_NAME} {target} --branch <name>")
    print(f"  target -> source:  {SELF_NAME} {target} --pull-back")
    return 1


# --- moving ------------------------------------------------------------------

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
    cmd = command_state(target)
    if not (only_src or only_tgt or changed or cmd):
        print("already in sync — nothing to pull back")
        return
    # The source is a checkout too, and a pull-back writes into it. Same rule.
    if not dry:
        guard_branch(SRC_ROOT, "pull back into the source at")
    print(f"pull back: {target} -> source")
    for r in changed:
        print(f"  differs        {r}")
    for r in only_tgt:
        print(f"  new in target  {r}")
    for r in only_src:
        print(f"  WOULD DELETE   {r}  (present in source, absent in target)")
    if cmd == "differs":
        print(f"  differs        {COMMAND_REL}")

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
    if cmd == "differs":
        copy_part(os.path.join(target, COMMAND_REL), os.path.join(SRC_ROOT, COMMAND_REL), dry)

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
    print(f"    git -C {SRC_ROOT} diff -- .claude/skills/{SKILL_NAME} {COMMAND_REL}")


def check_runtime_pointer(target):
    """Whether another agent runtime can reach what was just deployed."""
    ag = os.path.join(target, ".agents", "skills")
    agents_md = os.path.join(target, "AGENTS.md")
    if os.path.islink(ag):
        print(f"  codex: .agents/skills -> {os.readlink(ag)} "
              "(pointer — picks this up automatically)")
    elif os.path.isdir(ag):
        print("  WARNING: .agents/skills is a COPIED DIRECTORY, not a symlink.")
        print("           Codex reads that stale copy, not what was just deployed.")
        print("             rm -rf .agents/skills && ln -s ../.claude/skills .agents/skills")
    elif os.path.exists(agents_md):
        try:
            routed = ".claude/skills" in open(agents_md, encoding="utf-8", errors="replace").read()
        except OSError:
            routed = False
        if routed:
            print("  codex: no .agents/skills pointer, but AGENTS.md routes to .claude/skills")
            print("         (text, not a symlink — it works while that sentence stays true)")
        else:
            print("  note: AGENTS.md exists but neither points at .claude/skills nor has an")
            print("        .agents/skills symlink — Codex cannot see this skill until one is added.")


def check_hygiene(target):
    """What running the skill here will leave behind, and whether git will notice."""
    pyc = os.path.join(".claude", "skills", SKILL_NAME, "scripts", "__pycache__", "x.pyc")
    if os.path.isdir(os.path.join(SRC_SKILL, "scripts")) and not is_ignored(target, pyc):
        print("  WARNING: __pycache__/ is not ignored here. Running the scripts writes")
        print(f"           .claude/skills/{SKILL_NAME}/scripts/__pycache__/, which then sits")
        print("           untracked in the checkout. Add `__pycache__/` to .gitignore.")
    if is_ignored(target, os.path.join(".claude", "skills", SKILL_NAME, MANIFEST)):
        print(f"  WARNING: {MANIFEST} is ignored here. It is the record of what was deployed;")
        print("           ignored, a fresh clone cannot tell a deploy from a local edit and")
        print("           the next deploy overwrites whatever it finds. Commit it.")


def do_deploy(target, tskill, want_config, dry, force=False):
    if dry:
        b, d = current_branch(target), default_branch(target)
        if b is None or (d and b == d):
            print(f"  note: a real run would REFUSE — {target} is on "
                  f"{'no branch' if b is None else repr(b)}, and deploys need a branch.")
    else:
        guard_branch(target, "deploy into")

    touched = [os.path.join(".claude", "skills", SKILL_NAME), COMMAND_REL,
               os.path.join(".claude", f"{SKILL_NAME}.config.json")]
    uncommitted = dirty(target, touched)

    # A deploy overwrites. If the target changed since it was last deployed to,
    # those changes are newer than the source and this would destroy them --
    # which is what happens right after a merge lands work in a consuming repo.
    if os.path.isdir(tskill):
        local = local_changes(tskill)
        if local is None and uncommitted and not force:
            print(f"REFUSING: {target} has uncommitted changes here and no deploy manifest,")
            print("  so nothing can say whether they are an old deploy or someone's fix:")
            for ln in uncommitted[:20]:
                print(f"    {ln}")
            print()
            print(f"  If they are fixes:      {SELF_NAME} {target} --pull-back")
            print("  If they are cruft:      commit or discard them, then re-run")
            print("  Or overwrite anyway:    add --force")
            return 1
        if local is None:
            print("  note: no deploy manifest here, so local changes cannot be")
            print("        detected. This deploy will overwrite whatever is there.")
        elif local and not force:
            print(f"REFUSING: {target} has changes since it was last deployed to.")
            for rel, how in local:
                print(f"  {how:<22} {rel}")
            print()
            print("  These are NEWER than the source and a deploy would destroy them.")
            print(f"  Carry them home first:  {SELF_NAME} {target} --pull-back")
            print("  Or overwrite anyway:    add --force")
            return 1
        elif uncommitted:
            print("  note: the previous deploy here was never committed; overwriting it.")

    print(f"deploy {SKILL_NAME} -> {target}")
    if not dry:
        os.makedirs(os.path.join(target, ".claude", "skills"), exist_ok=True)
        os.makedirs(os.path.join(target, ".claude", "commands"), exist_ok=True)
        if os.path.isdir(tskill):
            shutil.rmtree(tskill)
        shutil.copytree(SRC_SKILL, tskill,
                        ignore=shutil.ignore_patterns(SELF_NAME, "__pycache__"))
        cmd = os.path.join(SRC_ROOT, COMMAND_REL)
        if os.path.isfile(cmd):
            shutil.copy2(cmd, os.path.join(target, COMMAND_REL))
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
    check_hygiene(target)
    print(f"done: .claude/skills/{SKILL_NAME} in {target}")
    if not dry:
        left = dirty(target, touched)
        print()
        if left:
            print(f"  {len(left)} file(s) now uncommitted on branch "
                  f"'{current_branch(target)}'. This deploy is not done until they")
            print("  are committed and on a pull request:")
            print(f"    git -C {target} add {' '.join(touched)}")
            print(f"    git -C {target} commit -m 'sync {SKILL_NAME} skill'")
        else:
            print("  nothing changed in the target — it already matched.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="target repo(s)")
    ap.add_argument("--branch", metavar="NAME",
                    help=f"deploy into a worktree of the target at {WORKTREES_REL}/NAME "
                         "on branch NAME (created from origin's default branch if new)")
    ap.add_argument("--config", action="store_true",
                    help=f"seed .claude/{SKILL_NAME}.config.json if absent")
    ap.add_argument("--check", action="store_true", help="compare only; exit 1 on drift")
    ap.add_argument("--check-all", action="store_true", help="check every target, exit 1 if any drift")
    ap.add_argument("--pull-back", action="store_true", help="target -> source (reverse review)")
    ap.add_argument("--force", action="store_true",
                    help="deploy even when the target has changes of its own")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.pull_back and (args.check or args.check_all):
        die("--pull-back and --check are opposite directions; pick one")
    if args.branch and (args.pull_back or args.check or args.check_all):
        die("--branch is for deploys; point --check / --pull-back at the worktree path")
    if len(args.targets) > 1 and not args.check_all:
        die("multiple targets only make sense with --check-all")

    rc = 0
    for t in args.targets:
        target = resolve_target(t)
        if args.branch:
            target = ensure_worktree(target, args.branch)
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
