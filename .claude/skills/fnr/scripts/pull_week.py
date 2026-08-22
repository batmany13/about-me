#!/usr/bin/env python3
"""
FNR week pull — gather one ISO week of raw material for the weekly reflection.

Reads the private repo registry (fnr/.private/repos.json), walks each repo's git
log for the week, pulls attended calendar events from the fund repo's event
registry, and emits a single JSON blob on stdout.

This script does data collection ONLY. It applies no scrub policy and makes no
judgments -- that is the skill's job. Its output is private by construction.

Usage:
    pull_week.py                 # default week (see --help)
    pull_week.py 2026-W34
    pull_week.py --last-week
    pull_week.py 2026-W34 --repos-json /path/to/repos.json
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter

DEFAULT_REGISTRY = "fnr/.private/repos.json"
PR_RE = re.compile(r"#(\d+)")
MERGE_RE = re.compile(r"^Merge pull request #(\d+)")


def die(msg, code=1):
    print(f"pull_week: {msg}", file=sys.stderr)
    sys.exit(code)


def run(args, cwd=None, timeout=30):
    """Run a command, return stdout or '' on any failure."""
    try:
        r = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def iso_week_bounds(year, week):
    """Monday and Sunday dates for an ISO week."""
    monday = dt.date.fromisocalendar(year, week, 1)
    return monday, monday + dt.timedelta(days=6)


def parse_week(arg, today):
    """Resolve a week argument to (year, week). Accepts 2026-W34 or W34."""
    m = re.fullmatch(r"(?:(\d{4})-)?W(\d{1,2})", arg.strip(), re.I)
    if not m:
        die(f"cannot parse week {arg!r} -- expected YYYY-WNN (e.g. 2026-W34)")
    year = int(m.group(1)) if m.group(1) else today.isocalendar()[0]
    return year, int(m.group(2))


def default_week(today):
    """
    Default: the most recently CLOSED week.

    The weekly is written Monday morning about the week that just ended, so on a
    Monday the answer is emphatically last week -- the current week is hours old.
    Any other day, still last week: the current week isn't done, and publishing a
    partial week as if it were whole is the one thing this format must not do.
    """
    return (today - dt.timedelta(days=today.weekday() + 7)).isocalendar()[:2]


def collect_repo(repo, start, end, emails):
    """Walk one repo's git log for the week."""
    path = repo["path"]
    out = {
        "name": repo["name"],
        "lane": repo.get("lane"),
        "disclosure": repo.get("disclosure", "hidden"),
        "public_name": repo.get("public_name"),
        "note": repo.get("note"),
        "url": repo.get("url"),
        "available": False,
        "commits": [],
        "commit_count": 0,
        "prs": [],
        "top_dirs": [],
        "authors": {},
    }

    if not os.path.isdir(os.path.join(path, ".git")):
        out["error"] = f"not a git repo: {path}"
        return out
    out["available"] = True

    since, until = f"{start} 00:00", f"{end} 23:59:59"
    # --all: work lands on worktree branches and gets squash-merged later.
    fmt = "%H%x1f%aI%x1f%ae%x1f%s"
    log = run(
        ["git", "log", "--all", "--no-merges", f"--format={fmt}",
         f"--since={since}", f"--until={until}", "--reverse"],
        cwd=path,
    )

    seen = set()
    for line in log.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, when, email, subject = parts
        if sha in seen:
            continue
        seen.add(sha)
        out["authors"][email] = out["authors"].get(email, 0) + 1
        if emails and email not in emails:
            continue
        out["commits"].append(
            {"sha": sha[:9], "date": when[:10], "email": email, "subject": subject}
        )

    out["commit_count"] = len(out["commits"])

    # PR numbers: squash-merge subjects carry (#NN); merge commits carry their own form.
    prs = {int(n) for c in out["commits"] for n in PR_RE.findall(c["subject"])}
    merges = run(
        ["git", "log", "--all", "--merges", "--format=%s",
         f"--since={since}", f"--until={until}"],
        cwd=path,
    )
    for line in merges.splitlines():
        m = MERGE_RE.match(line)
        if m:
            prs.add(int(m.group(1)))
    out["prs"] = sorted(prs)

    # Which parts of the repo moved -- the cheapest signal for "what was this week about".
    dirs = Counter()
    for c in out["commits"]:
        for f in run(["git", "show", "--name-only", "--format=", c["sha"]],
                     cwd=path).splitlines():
            f = f.strip()
            if not f:
                continue
            top = f.split("/")[0] if "/" in f else "(root)"
            second = "/".join(f.split("/")[:2]) if f.count("/") >= 1 else top
            dirs[second if top not in (".claude", ".codex", "(root)") else top] += 1
    out["top_dirs"] = [{"dir": d, "files": n} for d, n in dirs.most_common(12)]
    return out


def collect_events(cfg, repos_by_name, start, end):
    """Attended calendar events for the week, from the fund repo's registry."""
    src = repos_by_name.get(cfg.get("source_repo", ""))
    if not src:
        return {"available": False, "error": "event source repo not in registry"}
    reg = os.path.join(src["path"], cfg.get("registry", ""))
    if not os.path.isfile(reg):
        return {"available": False, "error": f"registry not found: {reg}"}

    try:
        with open(reg) as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        return {"available": False, "error": f"cannot read registry: {e}"}

    s, e_ = str(start), str(end)
    events = []
    for ev in data.get("events", []):
        date = ev.get("date", "")
        if not (s <= date <= e_):
            continue
        prep = ev.get("prep_file")
        prep_path = os.path.join(src["path"], prep) if prep else None
        events.append({
            "date": date,
            "slug": ev.get("slug"),
            "name": ev.get("name"),
            "host": ev.get("host"),
            "venue": ev.get("venue"),
            "format": ev.get("format"),
            "url": ev.get("url"),
            "state": ev.get("state"),
            "why": ev.get("why"),
            "entity_counts": Counter(
                x.get("kind", "?") for x in ev.get("entities", [])
            ),
            # Deliberately NOT inlined: entities[].note / .disposition are
            # diligence judgments about real people. The skill reads the prep
            # file directly when it needs them, so they never sit in a blob
            # that might get pasted somewhere.
            "prep_file": prep_path if prep_path and os.path.isfile(prep_path) else None,
        })
    events.sort(key=lambda x: x["date"])
    for ev in events:
        ev["entity_counts"] = dict(ev["entity_counts"])
    return {
        "available": True,
        "registry": reg,
        "events": events,
        "attended": [e for e in events if e["state"] == "attended"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("week", nargs="?", help="ISO week, e.g. 2026-W34. Default: last closed week.")
    ap.add_argument("--last-week", action="store_true", help="explicit alias for the default")
    ap.add_argument("--this-week", action="store_true", help="current (incomplete) week")
    ap.add_argument("--repos-json", default=None, help=f"registry path (default {DEFAULT_REGISTRY})")
    ap.add_argument("--today", default=None, help="override today's date, YYYY-MM-DD (testing)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()

    if args.week:
        year, week = parse_week(args.week, today)
    elif args.this_week:
        year, week = today.isocalendar()[:2]
    else:
        year, week = default_week(today)

    start, end = iso_week_bounds(year, week)
    partial = end >= today

    registry_path = args.repos_json or DEFAULT_REGISTRY
    if not os.path.isfile(registry_path):
        die(f"registry not found: {registry_path}\n"
            f"  Expected the private repo list. Create it from the template in the fnr skill,\n"
            f"  or pass --repos-json. Without it there is nothing to read.")
    with open(registry_path) as fh:
        registry = json.load(fh)

    emails = set(registry.get("author_emails", []))
    repos = registry.get("repos", [])
    by_name = {r["name"]: r for r in repos}

    collected = [collect_repo(r, start, end, emails) for r in repos]
    events = collect_events(registry.get("events", {}), by_name, start, end)

    publishable = [r for r in collected if r["disclosure"] != "hidden"]
    lanes = Counter()
    for r in collected:
        if r["disclosure"] != "hidden":
            lanes[r["lane"] or "other"] += r["commit_count"]

    print(json.dumps({
        "week": f"{year}-W{week:02d}",
        "start": str(start),
        "end": str(end),
        "span": f"{start:%b %-d}–{end:%-d}, {end:%Y}" if start.month == end.month
                else f"{start:%b %-d}–{end:%b %-d}, {end:%Y}",
        "partial": partial,
        "generated_for_date": str(today),
        "repos": collected,
        "events": events,
        "totals": {
            "commits_all": sum(r["commit_count"] for r in collected),
            "commits_publishable": sum(r["commit_count"] for r in publishable),
            "prs_publishable": sum(len(r["prs"]) for r in publishable),
            "repos_active": sum(1 for r in collected if r["commit_count"]),
            "by_lane_publishable": dict(lanes),
            "events_attended": len(events.get("attended", [])) if events.get("available") else 0,
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
