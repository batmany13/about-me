#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Catchup week pull -- gather one ISO week of activity for ONE repo.

Repo-agnostic by construction. Run it inside any git repo and it works with no
configuration at all; drop a `.claude/catchup.config.json` beside the repo to
teach it that repo's people and its category vocabulary. Nothing about any
particular repo is compiled into this file.

Emits a single JSON blob on stdout. Data collection only -- it classifies and
counts, it does not judge or summarise. The skill does that.

Two things about the counts, because they decide what gets written:

  * The week is decided by AUTHOR date, not committer date. Squash merges rewrite
    committer dates, and git's --since/--until filter on those, so the raw filter
    cuts the week in the wrong place. We query a padded window and re-filter.
  * Every commit count comes in two flavours. `commit_count` spans all refs and
    includes pre-squash worktree branches, so it is inflated and differs between
    machines depending on which local branches exist. `commit_count_primary`
    counts only what is reachable from the mainline ref -- stable everywhere the
    repo is cloned.

Usage:
    pull_week.py                      # last closed week, cwd repo
    pull_week.py 2026-W34
    pull_week.py --this-week
    pull_week.py 2026-W35 --repo /path/to/repo
    pull_week.py --weeks 2026-W33,2026-W34
    pull_week.py --list-weeks         # every week with commits (for backfill)
"""

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

CONFIG_RELPATH = os.path.join(".claude", "catchup.config.json")
DEFAULT_OUTPUT_DIR = os.path.join(".claude", "catchups")

# How late a squash may land and still be counted against the week it was authored in.
DATE_PAD_DAYS = 30

# A path rule wins outright at this share of the commit's files, or at this many
# files regardless of share. Below both, the subject gets the next word.
PATH_SHARE_MIN = 0.25
PATH_COUNT_MIN = 3

PR_RE = re.compile(r"#(\d+)")
MERGE_RE = re.compile(r"^Merge pull request #(\d+)")

# ---------------------------------------------------------------------------
# Categories. Three, fixed -- the vocabulary is the point of the format, so a
# repo may retitle a category or extend its rules, but may not invent a fourth.
# Precedence is meeting -> technical -> other: a meeting note ABOUT a technical
# subject is still a meeting note, so `meeting` is tested first and wins ties.
# ---------------------------------------------------------------------------
CATEGORY_ORDER = ["meeting", "technical", "other"]

# Commits that are bookkeeping rather than work. They are not dropped -- they are
# flagged, excluded from the category counts, and reported as a number, because a
# catchup that silently swallows 60 of a week's 330 commits is lying about the
# week. Kept generic: these are conventions of the tooling, not of any one repo.
DEFAULT_IGNORE = {
    "paths": [
        "**/.claude/transcripts/**",
        "**/.claude/catchups/**",
        "**/*.lock",
        "**/package-lock.json",
    ],
    "subjects": [
        r"^chore\(?(transcripts?|catchups?)\)?:",
        r"^Merge (branch|remote-tracking)",
        r"^(Revert )?\"?(bump|pin) (deps|dependencies)",
    ],
}

DEFAULT_CATEGORIES = {
    "meeting": {
        "title": "Meeting / Partner Notes",
        "paths": [
            "**/meetings/**", "**/meeting/**", "**/1x1*/**", "**/1on1*/**",
            "**/partners/**", "**/partner/**", "**/network/**", "**/people/**",
            "**/events/**", "**/calls/**", "**/interviews/**", "**/founders/**",
            "**/contacts/**", "**/crm/**", "**/intros/**", "**/notes/**",
        ],
        "keywords": [
            "meeting", "met with", "1x1", "1:1", "one-on-one", "call with",
            "partner", "intro to", "intro with", "sync with", "founder",
            "investor", "dinner", "lunch", "coffee", "conference", "summit",
            "attended", "notes from", "demo day", "panel", "office hours",
            "standup", "retro", "kickoff", "debrief", "roundtable", "workshop",
        ],
    },
    "technical": {
        "title": "Technical Notes",
        "paths": [
            "src/**", "lib/**", "libs/**", "app/**", "apps/**", "pkg/**",
            "cmd/**", "internal/**", "service/**", "services/**", "server/**",
            "client/**", "api/**", "web/**", "website/**", "frontend/**",
            "backend/**", "test/**", "tests/**", "spec/**", "specs/**",
            "scripts/**", "tools/**", "migrations/**", "schema/**", "infra/**",
            "deploy/**", "terraform/**", "charts/**", ".github/**",
            "**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.go",
            "**/*.rs", "**/*.java", "**/*.rb", "**/*.sh", "**/*.sql",
            "**/*.tf", "**/*.yml", "**/*.yaml", "**/*.toml", "**/*.lock",
            "**/Dockerfile", "**/Makefile",
        ],
        "keywords": [
            "fix", "fixes", "fixed", "bug", "refactor", "implement", "rewrite",
            "migrate", "migration", "test", "tests", "ci", "build", "deploy",
            "endpoint", "api", "schema", "perf", "performance", "cache",
            "optimize", "revert", "upgrade", "bump", "dependency", "lint",
            "type", "types", "regression", "crash", "leak", "race", "patch",
            "harden", "wire", "port", "scaffold", "benchmark", "profil*",
        ],
    },
    "other": {
        "title": "Other",
        "paths": [],
        "keywords": [],
    },
}


def die(msg, code=1):
    print(f"pull_week: {msg}", file=sys.stderr)
    sys.exit(code)


def run(args, cwd=None, timeout=60):
    """Run a command, return stdout or '' on any failure."""
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# ---------------------------------------------------------------------------
# Week math
# ---------------------------------------------------------------------------

def iso_week_bounds(year, week):
    """Monday and Sunday dates for an ISO week."""
    try:
        monday = dt.date.fromisocalendar(year, week, 1)
    except ValueError:
        die(f"no such ISO week: {year}-W{week:02d} (that year has 52 weeks, not 53)")
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

    A catchup is read to find out what happened while you were away, so the
    honest default is the last week that actually finished. Publishing a partial
    week as if it were whole is the one thing this format must not do -- ask for
    `--this-week` explicitly when that is what you want.
    """
    return (today - dt.timedelta(days=today.weekday() + 7)).isocalendar()[:2]


def week_label(year, week):
    return f"{year}-W{week:02d}"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(repo_path, explicit=None):
    """Read the repo's catchup config, or return the zero-config defaults.

    A missing config is the normal case, not an error: the skill must work in a
    repo that has never heard of it.
    """
    path = explicit or os.path.join(repo_path, CONFIG_RELPATH)
    cfg, source = {}, None
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                cfg = json.load(fh)
            source = path
        except (json.JSONDecodeError, OSError) as e:
            die(f"cannot read config {path}: {e}")
    elif explicit:
        die(f"config not found: {explicit}")

    # Merge categories over the defaults so a repo can extend one category
    # without restating the other two.
    cats = {}
    user_cats = cfg.get("categories") or {}
    for key in CATEGORY_ORDER:
        base = dict(DEFAULT_CATEGORIES[key])
        over = user_cats.get(key) or {}
        merged = dict(base)
        merged["title"] = over.get("title", base["title"])
        # `paths`/`keywords` extend the defaults; `paths_replace`/`keywords_replace`
        # discard them. Extending is right far more often, so it is the default.
        if "paths_replace" in over:
            merged["paths"] = list(over["paths_replace"])
        else:
            merged["paths"] = list(base["paths"]) + list(over.get("paths", []))
        if "keywords_replace" in over:
            merged["keywords"] = list(over["keywords_replace"])
        else:
            merged["keywords"] = list(base["keywords"]) + list(over.get("keywords", []))
        cats[key] = merged
    cfg["categories"] = cats

    ign = cfg.get("ignore") or {}
    merged_ign = {}
    for field in ("paths", "subjects"):
        if f"{field}_replace" in ign:
            merged_ign[field] = list(ign[f"{field}_replace"])
        else:
            merged_ign[field] = list(DEFAULT_IGNORE[field]) + list(ign.get(field, []))
    cfg["ignore"] = merged_ign

    cfg["_source"] = source
    return cfg


def people_index(cfg):
    """email -> display name, from config. Empty when the repo declares no people."""
    idx = {}
    for person in (cfg.get("authors") or {}).get("people", []) or []:
        for email in person.get("emails", []) or []:
            idx[email.lower()] = person.get("name") or email
    return idx


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def glob_re(pat):
    """Compile a path glob to a regex. Supports ** (any depth) and * (one segment)."""
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                if pat[i:i + 1] == "/":   # '**/' also matches zero directories
                    i += 1
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.I)


def keyword_re(kw):
    """Compile a subject keyword to a word-boundary regex.

    Substring matching is a precision trap that only shows up on real data:
    plain `in` makes "prototype" match "type", "important" match "port", and
    "prefix" match "fix". A trailing `*` opts into a prefix match, so a stem like
    `profil*` still catches profile/profiling/profiler without that cost.
    """
    kw = kw.strip().lower()
    if kw.endswith("*"):
        return re.compile(r"\b" + re.escape(kw[:-1]) + r"\w*", re.I)
    return re.compile(r"\b" + re.escape(kw).replace(r"\ ", r"\s+") + r"\b", re.I)


def build_ignore(cfg):
    subs = []
    for pat in cfg["ignore"]["subjects"]:
        try:
            subs.append((pat, re.compile(pat, re.I)))
        except re.error as e:
            die(f"bad ignore.subjects regex {pat!r}: {e}")
    return {
        "paths": [(p, glob_re(p)) for p in cfg["ignore"]["paths"]],
        "subjects": subs,
    }


def is_ignored(subject, files, ign):
    """True when a commit is bookkeeping.

    Subject rules fire on their own. Path rules require EVERY touched file to
    match -- a commit that edits a lockfile on its way through real work is real
    work, and only a commit that is nothing but bookkeeping is bookkeeping.
    """
    for pat, rx in ign["subjects"]:
        if rx.search(subject):
            return f"subject:{pat}"
    if files and ign["paths"]:
        hit = None
        for f in files:
            m = next((p for p, rx in ign["paths"] if rx.match(f)), None)
            if m is None:
                return None
            hit = hit or m
        return f"path:{hit}"
    return None


def build_matchers(cfg):
    return {
        key: {
            "paths": [(p, glob_re(p)) for p in cfg["categories"][key]["paths"]],
            "keywords": [(k, keyword_re(k)) for k in cfg["categories"][key]["keywords"]],
        }
        for key in CATEGORY_ORDER
    }


def classify(subject, files, matchers):
    """Assign one commit to a category, and record which rule decided it.

    Paths outrank keywords: what a commit touched is harder evidence than how its
    subject was worded. Within paths, the category with the most matching files
    wins, so a commit that brushes one config file on its way through the service
    layer still reads as technical.
    """
    hits = {}
    for key in CATEGORY_ORDER:
        pats = matchers[key]["paths"]
        if not pats:
            continue
        matched, first = 0, None
        for f in files:
            for pat, rx in pats:
                if rx.match(f):
                    matched += 1
                    if first is None:
                        first = pat
                    break
        if matched:
            hits[key] = (matched, first)

    if hits:
        # max() over CATEGORY_ORDER position breaks ties toward `meeting`.
        best = max(hits, key=lambda k: (hits[k][0], -CATEGORY_ORDER.index(k)))
        matched, pat = hits[best]
        # A commit that merely brushes one file of a category is not about that
        # category. Require either a real share of the diff or an uncontested
        # small one, otherwise fall through to the subject.
        share = matched / max(1, len(files))
        if share >= PATH_SHARE_MIN or matched >= PATH_COUNT_MIN:
            return best, (f"path:{pat} ({matched}/{len(files)} files, "
                          f"{share:.0%})")

    for key in CATEGORY_ORDER:
        for kw, rx in matchers[key]["keywords"]:
            if rx.search(subject):
                return key, f"keyword:{kw}"

    if hits:
        best = max(hits, key=lambda k: (hits[k][0], -CATEGORY_ORDER.index(k)))
        matched, pat = hits[best]
        return best, f"path-weak:{pat} ({matched}/{len(files)} files)"

    return "other", "default"


# ---------------------------------------------------------------------------
# Git collection
# ---------------------------------------------------------------------------

def refresh_remote(path):
    """Fetch before counting, because the mainline ref decides a published number.

    `commit_count_primary` is what gets published, and it is computed against
    `origin/HEAD`. A checkout whose remote ref is stale reports a smaller week
    than actually happened -- on a real 20-PR week this read 12 instead of 55,
    and nothing about the output looked wrong. Cheap insurance; failure is
    non-fatal because an offline pull should still produce a week.
    """
    r = subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=path,
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def primary_ref(path):
    """The ref standing for the repo's mainline -- i.e. what is actually pushed."""
    head = run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
               cwd=path).strip()
    if head.startswith("refs/remotes/"):
        return head[len("refs/remotes/"):]
    for cand in ("origin/main", "origin/master", "main", "master"):
        if run(["git", "rev-parse", "--verify", "--quiet", cand], cwd=path).strip():
            return cand
    return "HEAD"


def gh_pr_details(path, start, end_exclusive, body_limit):
    """Merged-in-week PRs with their titles and bodies.

    The single richest source in the pull, and the one a commit log cannot
    replace. A commit subject is one line written in passing; a PR body is the
    considered writeup -- what was learned, what was wrong, what a slide actually
    said. Extraction that reads only subjects reconstructs a week's mechanics and
    loses its findings.

    One `gh` call for the whole week. Degrades to [] without gh, never raises.
    """
    raw = run(["gh", "pr", "list", "--state", "merged", "--limit", "300",
               "--json", "number,title,body,mergedAt,url,author,labels"],
              cwd=path, timeout=120)
    try:
        items = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        return []
    out = []
    for pr in items:
        merged = pr.get("mergedAt") or ""
        if not (start <= merged < end_exclusive):
            continue
        body = (pr.get("body") or "").strip()
        truncated = body_limit > 0 and len(body) > body_limit
        out.append({
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("url"),
            "merged_at": merged,
            "author": ((pr.get("author") or {}).get("login")),
            "labels": [l.get("name") for l in (pr.get("labels") or [])],
            "body_chars": len(body),
            "body_truncated": truncated,
            "body": (body[:body_limit] + "\n\n…[truncated -- re-pull with "
                     "--pr-body-limit 0 for the full body]") if truncated else body,
        })
    out.sort(key=lambda p: p["number"] or 0)
    return out


def gh_pr_counts(path, start, end_exclusive):
    """Merged-in-week and currently-open PR counts, straight from GitHub.

    The subject-parsed `prs` list is unreliable as a count: it scrapes #NN out of
    commit subjects, so it picks up cross-repo references, PRs merely mentioned,
    and the same PR twice. A PR is one unit of work however it was merged, so
    these are the figures worth publishing. Never raises -- a missing gh must
    degrade the stat line, not break the week.
    """
    merged = run(["gh", "pr", "list", "--state", "merged", "--limit", "300",
                  "--json", "number,mergedAt", "--jq",
                  f'[.[] | select(.mergedAt >= "{start}" and .mergedAt < "{end_exclusive}")] | length'],
                 cwd=path, timeout=45).strip()
    opened = run(["gh", "pr", "list", "--state", "open", "--limit", "300",
                  "--json", "number", "--jq", "length"], cwd=path, timeout=45).strip()
    try:
        return int(merged), int(opened)
    except ValueError:
        return None, None


def read_log(path, since, until):
    """One pass over the padded window returning [(sha, iso, email, subject, files)].

    One `git log --name-only` call, not one `git show` per commit: a 400-commit
    week is a real week, and N subprocesses would make the pull the slow part.
    """
    fmt = "\x1e%H\x1f%aI\x1f%ae\x1f%s"
    log = run(["git", "log", "--all", "--no-merges", f"--format={fmt}",
               "--name-only", f"--since={since}", f"--until={until}"], cwd=path,
              timeout=300)
    rows = []
    for rec in log.split("\x1e"):
        if not rec.strip():
            continue
        head, _, rest = rec.partition("\n")
        parts = head.split("\x1f")
        if len(parts) != 4:
            continue
        sha, when, email, subject = parts
        files = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        rows.append((sha, when, email, subject, files))
    return rows


def list_weeks(path):
    """Every ISO week that has at least one commit, oldest first."""
    log = run(["git", "log", "--all", "--no-merges", "--format=%aI"], cwd=path,
              timeout=120)
    weeks = Counter()
    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = dt.date.fromisoformat(line[:10])
        except ValueError:
            continue
        y, w, _ = d.isocalendar()
        weeks[week_label(y, w)] += 1
    return [{"week": w, "commits": n} for w, n in sorted(weeks.items())]


def collect(path, year, week, cfg, matchers, keep_ignored=False,
            pr_bodies=True, pr_body_limit=6000, fetch=True):
    """Walk one repo's git log for one week and classify it."""
    start, end = iso_week_bounds(year, week)
    label = week_label(year, week)
    today = dt.date.today()

    out = {
        "week": label,
        "start": str(start),
        "end": str(end),
        "partial": start <= today <= end,
        "repo_path": os.path.abspath(path),
        "repo_label": (cfg.get("repo") or {}).get("label") or os.path.basename(os.path.abspath(path)),
        "config_source": cfg.get("_source"),
        "available": False,
        "commits": [],
        "commit_count": 0,
        "commit_count_primary": 0,
        "primary_ref": None,
        "prs": [],
        "prs_merged": None,
        "prs_open_now": None,
        "authors": {},
        "categories": {},
        "top_dirs": [],
    }

    if not os.path.isdir(os.path.join(path, ".git")):
        # A worktree or submodule has .git as a file, not a directory.
        if not os.path.isfile(os.path.join(path, ".git")):
            out["error"] = f"not a git repo: {path}"
            return out
    out["available"] = True

    pad = dt.timedelta(days=DATE_PAD_DAYS)
    since, until = f"{start - pad} 00:00", f"{end + pad} 23:59:59"
    lo, hi = str(start), str(end)

    out["fetched"] = refresh_remote(path) if fetch else None
    ref = primary_ref(path)
    out["primary_ref"] = ref
    on_primary = set(run(["git", "log", ref, "--no-merges", "--format=%H",
                          f"--since={since}", f"--until={until}"],
                         cwd=path, timeout=120).split())

    names = people_index(cfg)
    ign = build_ignore(cfg)
    seen, rows = set(), []
    for sha, when, email, subject, files in read_log(path, since, until):
        if not (lo <= when[:10] <= hi):
            continue
        if sha in seen:
            continue
        seen.add(sha)
        rows.append((when, sha, email, subject, files))

    rows.sort()  # author-date order, oldest first

    dirs = Counter()
    by_cat = defaultdict(list)
    author_counts = Counter()
    author_cats = defaultdict(Counter)

    ignored = []
    for when, sha, email, subject, files in rows:
        who = names.get(email.lower(), email)
        skip = is_ignored(subject, files, ign)
        commit = {
            "sha": sha[:9],
            "date": when[:10],
            "email": email,
            "author": who,
            "known_author": email.lower() in names,
            "subject": subject,
            "files": len(files),
            "on_primary": sha in on_primary,
        }
        if skip:
            commit["ignored"] = skip
            ignored.append(commit)
            continue

        cat, why = classify(subject, files, matchers)
        commit["category"] = cat
        commit["category_why"] = why
        author_counts[who] += 1
        author_cats[who][cat] += 1
        out["commits"].append(commit)
        by_cat[cat].append(commit["sha"])
        for f in files:
            seg = f.split("/")
            if len(seg) == 1:
                dirs["(root)"] += 1
            elif len(seg) == 2 or seg[0].startswith("."):
                dirs[seg[0]] += 1
            else:
                dirs["/".join(seg[:2])] += 1

    out["commit_count"] = len(out["commits"])
    out["commit_count_primary"] = sum(1 for c in out["commits"] if c["on_primary"])
    # Reported, never hidden: the summary should be able to say "plus N
    # bookkeeping commits" rather than quietly showing a smaller week.
    out["ignored_count"] = len(ignored)
    out["ignored_reasons"] = dict(Counter(c["ignored"] for c in ignored).most_common())
    out["ignored"] = ignored if keep_ignored else []
    out["authors"] = dict(author_counts.most_common())
    out["author_categories"] = {a: dict(c) for a, c in author_cats.items()}
    out["unknown_authors"] = sorted({c["email"] for c in out["commits"]
                                     if not c["known_author"]})
    out["categories"] = {
        key: {
            "title": cfg["categories"][key]["title"],
            "count": len(by_cat.get(key, [])),
            "shas": by_cat.get(key, []),
        }
        for key in CATEGORY_ORDER
    }
    out["top_dirs"] = [{"dir": d, "files": n} for d, n in dirs.most_common(12)]

    prs = {int(n) for c in out["commits"] for n in PR_RE.findall(c["subject"])}
    merges = run(["git", "log", "--all", "--merges", "--format=%aI\x1f%s",
                  f"--since={since}", f"--until={until}"], cwd=path, timeout=120)
    for line in merges.splitlines():
        when, _, subject = line.partition("\x1f")
        if not (lo <= when[:10] <= hi):
            continue
        m = MERGE_RE.match(subject)
        if m:
            prs.add(int(m.group(1)))
    out["prs"] = sorted(prs)

    end_excl = (end + dt.timedelta(days=1)).isoformat()
    merged, opened = gh_pr_counts(path, str(start), end_excl)
    out["prs_merged"] = merged
    out["prs_open_now"] = opened

    out["pr_details"] = (gh_pr_details(path, str(start), end_excl, pr_body_limit)
                         if pr_bodies else [])
    out["pr_body_chars_total"] = sum(p["body_chars"] for p in out["pr_details"])

    out["output_path"] = os.path.join(
        (cfg.get("output") or {}).get("dir", DEFAULT_OUTPUT_DIR), f"{label}.md")
    out["exists"] = os.path.isfile(os.path.join(path, out["output_path"]))
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("week", nargs="?", help="ISO week, e.g. 2026-W34. Default: last closed week.")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--last-week", action="store_true", help="explicit alias for the default")
    when.add_argument("--this-week", action="store_true", help="current (incomplete) week")
    when.add_argument("--weeks", help="comma-separated list, e.g. 2026-W33,2026-W34")
    when.add_argument("--list-weeks", action="store_true",
                      help="list every week with commits and exit (for backfill)")
    ap.add_argument("--repo", default=".", help="repo to read (default: cwd)")
    ap.add_argument("--config", default=None, help=f"config path (default: <repo>/{CONFIG_RELPATH})")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip `git fetch origin` (offline; primary counts may be stale)")
    ap.add_argument("--no-prs", action="store_true",
                    help="skip fetching PR titles and bodies (faster, much less context)")
    ap.add_argument("--pr-body-limit", type=int, default=6000,
                    help="truncate each PR body to N chars; 0 for no limit (default 6000)")
    ap.add_argument("--show-ignored", action="store_true",
                    help="include the bookkeeping commits themselves, not just their count")
    ap.add_argument("--today", default=None, help="override today's date, YYYY-MM-DD (testing)")
    args = ap.parse_args()

    path = os.path.abspath(os.path.expanduser(args.repo))
    if not os.path.isdir(path):
        die(f"no such directory: {path}")

    if args.list_weeks:
        print(json.dumps({"repo_path": path, "weeks": list_weeks(path)}, indent=2))
        return

    if args.today:
        try:
            today = dt.date.fromisoformat(args.today)
        except ValueError:
            die(f"cannot parse --today {args.today!r} -- expected YYYY-MM-DD")
    else:
        today = dt.date.today()

    cfg = load_config(path, args.config)
    matchers = build_matchers(cfg)

    if args.weeks:
        targets = [parse_week(w, today) for w in args.weeks.split(",") if w.strip()]
    elif args.week:
        targets = [parse_week(args.week, today)]
    elif args.this_week:
        targets = [today.isocalendar()[:2]]
    else:
        targets = [default_week(today)]

    weeks = [collect(path, y, w, cfg, matchers, args.show_ignored,
                     pr_bodies=not args.no_prs, pr_body_limit=args.pr_body_limit,
                     fetch=not args.no_fetch)
             for y, w in targets]
    print(json.dumps({
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "today": str(today),
        "category_order": CATEGORY_ORDER,
        "category_titles": {k: cfg["categories"][k]["title"] for k in CATEGORY_ORDER},
        "weeks": weeks,
    }, indent=2))


if __name__ == "__main__":
    main()
