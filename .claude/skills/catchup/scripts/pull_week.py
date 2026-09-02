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

Three things about the week, because they decide what gets written:

  * The week is decided by AUTHOR date, not committer date. Squash merges rewrite
    committer dates, and git's --since/--until filter on those, so the raw filter
    cuts the week in the wrong place. We query a padded window and re-filter.
  * That date is read in UTC. Git renders author dates in the author's own zone,
    so slicing `%aI` gave a LOCAL week -- while GitHub's `mergedAt` is UTC, so the
    commit half and the PR half of the same pull disagreed about where the week
    ended and the answer changed with the caller's timezone.
  * `commits` carries only what is reachable from the mainline ref. A pre-squash
    branch commit and the mainline commit it became share a subject but not a
    sha, and the branch copy is reachable from nothing once the PR merges -- it
    lives in one clone until git prunes it. What is dropped is reported by count
    and reason. `commit_count_all_refs` is the all-refs figure, kept as a stat
    because it is machine-specific and is not the number to publish.

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
# Output is CONTENT, not tooling. It lives at the top level, beside the rest of
# what the repo is for, because a weekly summary is something people read -- and
# `.claude/` is where a repo keeps its agent configuration. Burying readable
# output under a dotted tooling directory hides it from everyone who is not
# already looking for it, and couples the record to the tool that happened to
# write it. `output.dir` overrides; a repo that already has a home for it should
# say so.
DEFAULT_OUTPUT_DIR = "catchup"

# How late a squash may land and still be counted against the week it was authored in.
DATE_PAD_DAYS = 30

# A path rule wins outright at this share of the commit's files, or at this many
# files regardless of share. Below both, the subject gets the next word.
# How many paths to carry per commit before truncating (the count is kept).
PATHS_PER_COMMIT = 25

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
        # Legacy: output used to default under `.claude/`. A repo that has since
        # moved it still has history under the old path, and dropping this rule
        # would make those weeks retroactively count their own summaries as work.
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


def utc_date(iso):
    """The UTC calendar date of a git `%aI` timestamp.

    Git renders author dates in the AUTHOR's local zone (`2026-08-30T21:46:13-07:00`),
    so slicing the first ten characters yields a LOCAL date. That silently moves
    work across the week boundary: three PRs merged early on a Monday in UTC were
    all counted into the previous week because Pacific time still read Sunday.
    GitHub's own `mergedAt` is UTC, so the two halves of the same pull disagreed
    about which week a PR belonged to, and the answer changed with the timezone of
    whoever ran it.

    Deciding the week in UTC makes it the same number for every caller, whatever
    zone they are in.
    """
    try:
        return dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc).date().isoformat()
    except (ValueError, TypeError):
        return (iso or "")[:10]


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

    # The catchup's own output is bookkeeping in the week it describes -- writing
    # a summary is not work the summary should count. This rule FOLLOWS
    # output.dir rather than naming a fixed path: hardcoding one means that the
    # day a repo moves its output, the catchup silently starts counting itself.
    out_dir = (cfg.get("output") or {}).get("dir", DEFAULT_OUTPUT_DIR).strip("/")

    ign = cfg.get("ignore") or {}
    merged_ign = {}
    for field in ("paths", "subjects"):
        if f"{field}_replace" in ign:
            merged_ign[field] = list(ign[f"{field}_replace"])
        else:
            merged_ign[field] = list(DEFAULT_IGNORE[field]) + list(ign.get(field, []))
    if out_dir:
        merged_ign["paths"].append(f"{out_dir}/**")
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


def path_hits(files, matchers):
    """How many of `files` each category owns, by MOST SPECIFIC matching pattern.

    A file is owned once, by the longest pattern that matches it -- so a file
    under `notes/events/` counts for whichever category declared
    `**/notes/events/**`, not also for one that declared the broader `notes/**`.
    Without that, a broad glob inflates its own count using files a narrower rule
    already claims, and the broader category always looks bigger than the
    specific one nested inside it.
    """
    hits = {}
    for f in files:
        best_key, best_pat = None, ""
        for key in CATEGORY_ORDER:
            for pat, rx in matchers[key]["paths"]:
                if rx.match(f) and len(pat) > len(best_pat):
                    best_key, best_pat = key, pat
        if best_key:
            matched, first = hits.get(best_key, (0, None))
            hits[best_key] = (matched + 1, first or best_pat)
    return hits


def classify(subject, files, matchers):
    """Assign one commit to a category, and record which rule decided it.

    Paths outrank keywords: what a commit touched is harder evidence than how its
    subject was worded.

    Among paths, CATEGORY_ORDER decides -- meeting, then technical, then other --
    and the FIRST category to clear the evidence bar wins. It used to be whichever
    category matched the most files, which quietly inverted the documented rule
    ("a meeting note ABOUT a technical subject is still a meeting note") whenever
    one category's glob contained another's. Any repo that gives one category a
    broad glob and another a narrower one nested inside it hits this: the narrow
    category can never win a commit, however specific its rule. Observed on a
    real week whose headline was an event -- 268 of 270 commits went to the broad
    category and ZERO to the narrow one.

    The evidence bar itself is unchanged, and still does its own job: a commit
    that merely brushes one file of a category is not about that category, so a
    category must own a real share of the diff -- or an uncontested few files --
    before precedence gets to speak for it.
    """
    hits = path_hits(files, matchers)

    for key in CATEGORY_ORDER:
        if key not in hits:
            continue
        matched, pat = hits[key]
        share = matched / max(1, len(files))
        if share >= PATH_SHARE_MIN or matched >= PATH_COUNT_MIN:
            return key, f"path:{pat} ({matched}/{len(files)} files, {share:.0%})"

    for key in CATEGORY_ORDER:
        for kw, rx in matchers[key]["keywords"]:
            if rx.search(subject):
                return key, f"keyword:{kw}"

    if hits:
        # Nothing cleared the bar and no keyword fired. Fall back to weight, with
        # CATEGORY_ORDER breaking ties toward `meeting`.
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


def gh_merged_numbers(path, start, end_exclusive):
    """The set of PR numbers actually merged inside the week, or None without gh.

    The authority for which week a PR belongs to. `mergedAt` is UTC, which is why
    the commit side of the pull converts to UTC before deciding a week -- when the
    two used different clocks they disagreed, and a PR merged at 02:43 UTC on the
    Monday was filed under the Sunday that had just ended in Pacific time.

    None means "no authority available", which is different from "nothing merged"
    and must not be read as an empty week.
    """
    raw = run(["gh", "pr", "list", "--state", "merged", "--limit", "300",
               "--json", "number,mergedAt", "--jq",
               f'[.[] | select(.mergedAt >= "{start}" and .mergedAt < "{end_exclusive}") '
               f'| .number] | @json'],
              cwd=path, timeout=45).strip()
    if not raw:
        return None
    try:
        return {int(n) for n in json.loads(raw)}
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


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
    """One pass over the padded window returning [(sha, iso, email, subject, files, adds, dels)].

    One `git log --numstat` call, not one `git show` per commit: a 400-commit
    week is a real week, and N subprocesses would make the pull the slow part.

    `--numstat` rather than `--name-only` because a commit's SIZE is most of what
    decides whether it is worth opening. A subject line cannot tell a rename from
    a rewrite, and the extraction has to know which commits carry the logic
    before it can go read any of them.
    """
    fmt = "\x1e%H\x1f%aI\x1f%ae\x1f%s"
    log = run(["git", "log", "--all", "--no-merges", f"--format={fmt}",
               "--numstat", f"--since={since}", f"--until={until}"], cwd=path,
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
        files, adds, dels, per_file = [], 0, 0, {}
        for ln in rest.splitlines():
            cols = ln.split("\t")
            if len(cols) != 3:
                continue
            a, d, f = cols
            # "-" is git's marker for a binary file: countable as touched, not as lines.
            fa = int(a) if a.isdigit() else 0
            fd = int(d) if d.isdigit() else 0
            adds += fa
            dels += fd
            f = f.strip()
            files.append(f)
            pa, pd = per_file.get(f, (0, 0))
            per_file[f] = (pa + fa, pd + fd)
        rows.append((sha, when, email, subject, files, adds, dels, per_file))
    return rows


def rewritten_files(path, ref, structure, ins_by_file, del_by_file, touched, top=20):
    """Pre-existing files ranked by how much of them changed.

    `churn_ratio` is deletions over total churn: near 0 the file only grew, near
    0.5 it was reworked line for line, near 1 it was stripped. `replaced_share`
    compares the deletions to the file's CURRENT length, which is the closest
    cheap answer to "was this rewritten or merely edited" -- a 40-line change to
    a 4,000-line module and the same change to a 60-line one are different events
    and identical numbers.
    """
    born = set(structure.get("added") or []) | set(structure.get("renamed") or [])
    gone = set(structure.get("deleted") or [])
    rows = []
    for f, ins in ins_by_file.items():
        if f in born or f in gone:
            continue
        dels = del_by_file.get(f, 0)
        rows.append((ins + dels, f, ins, dels))
    rows.sort(reverse=True)

    out = []
    for churn, f, ins, dels in rows[:top]:
        size = None
        blob = run(["git", "show", f"{ref}:{f}"], cwd=path, timeout=30) if ref else ""
        if blob:
            size = blob.count("\n") + 1
        out.append({
            "file": f,
            "insertions": ins,
            "deletions": dels,
            "commits": touched.get(f, 0),
            "current_lines": size,
            "churn_ratio": round(dels / churn, 2) if churn else 0.0,
            "replaced_share": round(min(dels / size, 1.0), 2) if size else None,
        })
    return out


def pr_commit_map(path, ref, since, until):
    """{sha: pr_number} for everything each merge brought in.

    Scraping `#NN` from commit subjects only catches the commits that happen to
    mention their PR, which is a minority -- so PR-to-work attribution was mostly
    empty and any grouping built on it was guesswork. A merge commit knows
    exactly what it merged: `rev-list <merge>^1..<merge>` is the set. One call per
    merge, and it makes "which PR did this commit belong to" answerable instead
    of approximate.
    """
    out = {}
    if not ref:
        return out
    raw = run(["git", "log", ref, "--merges", "--format=%H\x1f%s",
               f"--since={since}", f"--until={until}"], cwd=path, timeout=120)
    for line in raw.splitlines():
        sha, _, subject = line.partition("\x1f")
        m = MERGE_RE.match(subject)
        if not m:
            continue
        num = int(m.group(1))
        brought = run(["git", "rev-list", f"{sha}^1..{sha}"], cwd=path, timeout=60).split()
        for b in brought:
            out.setdefault(b, num)
    return out


def read_structure(path, ref, since, until, lo, hi):
    """What the week ADDED, DELETED and RENAMED on the mainline ref.

    "What did we build" is not answerable from subject lines, and it is the
    question a reader most wants answered — a week of 200 modifications and a
    week that shipped four new contracts read identically in a commit log. Added
    files are the closest mechanical proxy for construction; deletions and
    renames are the closest one for what moved.
    """
    out = {"added": [], "deleted": [], "renamed": []}
    if not ref:
        return out
    filters = {"added": "A", "deleted": "D", "renamed": "R"}
    for key, flt in filters.items():
        fmt = "\x1e%H\x1f%aI"
        raw = run(["git", "log", ref, "--no-merges", f"--format={fmt}",
                   "--name-only", f"--diff-filter={flt}", "-M",
                   f"--since={since}", f"--until={until}"], cwd=path, timeout=180)
        seen = set()
        for rec in raw.split("\x1e"):
            if not rec.strip():
                continue
            head, _, rest = rec.partition("\n")
            bits = head.split("\x1f")
            if len(bits) != 2 or not (lo <= utc_date(bits[1]) <= hi):
                continue
            for ln in rest.splitlines():
                f = ln.strip()
                if f and f not in seen:
                    seen.add(f)
                    out[key].append(f)
    # A file added and then deleted inside one week built nothing.
    churn = set(out["added"]) & set(out["deleted"])
    out["added"] = [f for f in out["added"] if f not in churn]
    out["deleted"] = [f for f in out["deleted"] if f not in churn]
    return out


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
            d = dt.date.fromisoformat(utc_date(line))
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

    pr_of = pr_commit_map(path, ref, since, until)
    names = people_index(cfg)
    ign = build_ignore(cfg)
    seen, rows = set(), []
    for sha, when, email, subject, files, adds, dels, per_file in read_log(path, since, until):
        day = utc_date(when)
        if not (lo <= day <= hi):
            continue
        if sha in seen:
            continue
        seen.add(sha)
        rows.append((when, day, sha, email, subject, files, adds, dels, per_file))

    rows.sort()  # author-date order, oldest first

    # A pre-squash branch commit and the mainline commit it became share a
    # subject but not a sha. Cite the one that survives: everything reachable
    # from the mainline ref is durable, and everything else exists only in this
    # clone until git prunes it. On one real week five entity citations were
    # dangling objects on no ref at all, each with an identical-subject twin on
    # the mainline that went uncited. If nothing is reachable -- a local-only
    # repo, or no remote --
    # keep the lot rather than emitting an empty week.
    on_primary_subjects = {r[4] for r in rows if r[2] in on_primary}
    keep, dropped = [], []
    for when, day, sha, email, subject, files, adds, dels, per_file in rows:
        if not on_primary or sha in on_primary:
            keep.append((when, day, sha, email, subject, files, adds, dels, per_file))
        else:
            dropped.append({
                "sha": sha[:9],
                "date": day,
                "subject": subject,
                "reason": ("superseded-on-" + ref if subject in on_primary_subjects
                           else "not-reachable-from-" + ref),
            })
    rows = keep

    dirs = Counter()
    touched = Counter()
    ins_by_file, del_by_file = {}, {}
    by_cat = defaultdict(list)
    author_counts = Counter()
    author_cats = defaultdict(Counter)

    ignored = []
    for when, day, sha, email, subject, files, adds, dels, per_file in rows:
        who = names.get(email.lower(), email)
        skip = is_ignored(subject, files, ign)
        commit = {
            "sha": sha[:9],
            "date": day,
            "email": email,
            "author": who,
            "known_author": email.lower() in names,
            "subject": subject,
            "files": len(files),
            # Size and paths, so the extraction can decide WHICH commits to open
            # and read. A subject line cannot distinguish a rename from a rewrite,
            # and a catchup built only on subjects is a catchup of what people
            # said they did.
            "insertions": adds,
            "deletions": dels,
            # Which PR actually carried this commit, from the merge that brought
            # it in -- not scraped from the subject, which usually says nothing.
            "pr": pr_of.get(sha),
            "paths": sorted(files)[:PATHS_PER_COMMIT],
            "paths_truncated": max(0, len(files) - PATHS_PER_COMMIT),
            "on_primary": (not on_primary) or sha in on_primary,
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
            touched[f] += 1
            fa, fd = per_file.get(f, (0, 0))
            ins_by_file[f] = ins_by_file.get(f, 0) + fa
            del_by_file[f] = del_by_file.get(f, 0) + fd
            seg = f.split("/")
            if len(seg) == 1:
                dirs["(root)"] += 1
            elif len(seg) == 2 or seg[0].startswith("."):
                dirs[seg[0]] += 1
            else:
                dirs["/".join(seg[:2])] += 1

    # `commits` now carries only what is reachable from the mainline ref, so the
    # two counts agree by construction; `commit_count_primary` stays for readers
    # that already publish it. The all-refs figure is kept as a stat because it
    # is the only place the dropped duplicates are still visible.
    out["commit_count"] = len(out["commits"])
    out["commit_count_primary"] = len(out["commits"])
    out["commit_count_all_refs"] = len(out["commits"]) + len(ignored) + len(dropped)
    # Reported, never hidden -- same rule as the bookkeeping commits below.
    out["off_primary_count"] = len(dropped)
    out["off_primary_reasons"] = dict(Counter(c["reason"] for c in dropped).most_common())
    out["off_primary"] = dropped if keep_ignored else []
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

    # "What did we build" and "what moved" -- neither is answerable from subject
    # lines, and both are what a reader actually wants from a week.
    out["structure"] = read_structure(path, ref, since, until, lo, hi)
    out["structure_counts"] = {k: len(v) for k, v in out["structure"].items()}
    # The files the week kept coming back to. A file touched by nine commits is
    # where the week's argument actually happened; open that, not the biggest diff.
    out["hot_files"] = [{"file": f, "commits": n} for f, n in touched.most_common(15)]
    # What changed INSIDE files that already existed. Without this, a module
    # rewritten in place and a module with one line touched are the same entry in
    # every view -- the added/deleted lists only see files appearing and
    # disappearing, so a week of substantial rework reads as a quiet week.
    out["modified"] = rewritten_files(path, ref, out["structure"], ins_by_file,
                                      del_by_file, touched)
    out["biggest_commits"] = [
        {"sha": c["sha"], "subject": c["subject"],
         "insertions": c["insertions"], "deletions": c["deletions"], "files": c["files"]}
        for c in sorted(out["commits"],
                        key=lambda c: -(c["insertions"] + c["deletions"]))[:15]]

    scraped = {int(n) for c in out["commits"] for n in PR_RE.findall(c["subject"])}
    merges = run(["git", "log", "--all", "--merges", "--format=%aI\x1f%s",
                  f"--since={since}", f"--until={until}"], cwd=path, timeout=120)
    for line in merges.splitlines():
        when, _, subject = line.partition("\x1f")
        if not (lo <= utc_date(when) <= hi):
            continue
        m = MERGE_RE.match(subject)
        if m:
            scraped.add(int(m.group(1)))

    end_excl = (end + dt.timedelta(days=1)).isoformat()
    merged, opened = gh_pr_counts(path, str(start), end_excl)
    out["prs_merged"] = merged
    out["prs_open_now"] = opened

    out["pr_details"] = (gh_pr_details(path, str(start), end_excl, pr_body_limit)
                         if pr_bodies else [])
    out["pr_body_chars_total"] = sum(p["body_chars"] for p in out["pr_details"])

    # A scraped `#NN` says a commit MENTIONED a PR, never that the PR belongs to
    # this week: a subject that merely cites "the PR #64 session" pulls #64 into
    # this week even when #64 merged in the next one. GitHub's `mergedAt` is the only
    # authority on which week a PR landed in, so `prs` is now that set and the
    # rest is reported separately rather than blended in. Without gh there is no
    # authority to bound against, so the scraped set stands and says so.
    in_week = gh_merged_numbers(path, str(start), end_excl)
    if in_week is None:
        out["prs"] = sorted(scraped)
        out["prs_source"] = "commit-subjects (gh unavailable -- NOT week-bounded)"
        out["prs_mentioned_outside_week"] = []
    else:
        out["prs"] = sorted(scraped & in_week)
        out["prs_source"] = "gh mergedAt within the week"
        out["prs_mentioned_outside_week"] = sorted(scraped - in_week)

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
