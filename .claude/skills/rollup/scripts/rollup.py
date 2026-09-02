#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Rollup -- read every repo's week record and merge them into one cross-repo view.

This is the summary-of-summaries layer. Each repo produces its own catchup
(entities + a week record) through the `catchup` skill; this script reads those
products across repos and adds them up. It does NOT walk git logs -- if a repo's
week record is missing, the answer is to run catchup there, not to re-derive the
week here. One producer per fact.

    per-repo:   git -> catchup -> entities/<id>.json + weeks/<W>.json + <W>.md
    here:       weeks/<W>.json x N repos -> one merged view
    downstream: the public weekly, after the scrub policy

Repo names and paths come from the private registry and are never written into
this file or any committed file in this repo. The script prints whatever the
registry gives it; keeping that output private is the caller's job.

Usage:
    rollup.py                          # last closed week
    rollup.py 2026-W35
    rollup.py 2026-W35 --table         # human stats table
    rollup.py --weeks 2026-W34,2026-W35
    rollup.py 2026-W35 --registry /path/to/repos.json
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", "..", ".."))
def find_registry():
    """Where the registry is, which depends on which repo this is running in.

    Deployed into the private repo the registry sits at its root; run from the
    public repo it is in the gitignored clone. Both are normal, so the script
    looks rather than assuming -- and the private location wins, because that is
    the copy being edited when both exist.
    """
    here = os.path.join(REPO_ROOT, "repos.json")
    if os.path.isfile(here):
        return here
    return os.path.join(REPO_ROOT, "fnr", ".private", "repos.json")


DEFAULT_REGISTRY = find_registry()
PRIVATE_DIR = os.path.dirname(DEFAULT_REGISTRY)
# Only a fallback. Where a repo's output actually lives is that repo's own
# decision, recorded in its catchup config -- see repo_output_dir().
DEFAULT_OUTPUT_DIR = "catchup"

CATEGORY_ORDER = ["meeting", "technical", "other"]
WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


def die(msg, code=1):
    print(f"rollup: {msg}", file=sys.stderr)
    sys.exit(code)


def _common_git_dir(path):
    """The shared .git directory, which is identical across a repo's worktrees."""
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute",
                            "--git-common-dir"], capture_output=True, text=True, timeout=20)
        return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def same_repo(a, b):
    """Whether two paths are the same git repository, worktrees included."""
    ga, gb = _common_git_dir(a), _common_git_dir(b)
    return bool(ga) and ga == gb


def resolve_path(p):
    p = os.path.expanduser(p or "")
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(REPO_ROOT, p))


def parse_week(arg, today):
    m = re.fullmatch(r"(?:(\d{4})-)?W(\d{1,2})", arg.strip(), re.I)
    if not m:
        die(f"cannot parse week {arg!r} -- expected YYYY-WNN (e.g. 2026-W35)")
    year = int(m.group(1)) if m.group(1) else today.isocalendar()[0]
    return f"{year}-W{int(m.group(2)):02d}"


def default_week(today):
    """The most recently closed week -- never the current, incomplete one."""
    y, w, _ = (today - dt.timedelta(days=today.weekday() + 7)).isocalendar()
    return f"{y}-W{w:02d}"


def load_registry(path):
    if not os.path.isfile(path):
        die(f"registry not found: {path}\n"
            "  If fnr/.private/ is absent it was never cloned into this checkout --\n"
            "  it is a separate private repo, not lost. Clone it; never reconstruct it:\n"
            "    git clone https://github.com/batmany13/about-me-private.git fnr/.private")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        die(f"cannot read registry {path}: {e}")


def repo_output_dir(repo_path, registry_entry):
    """Where THIS repo keeps its catchup output.

    Read from the repo's own catchup config, because that is the only authority:
    the registry cannot know, and a default cannot either. Repos legitimately
    differ -- one moves its output to the top level while another is held back
    by work in flight -- and guessing produces the worst possible failure, which
    is a rollup that reports a reporting repo as silent.
    """
    hint = registry_entry.get("catchup_dir") or registry_entry.get("catchup_output_dir")
    cfg = os.path.join(repo_path, ".claude", "catchup.config.json")
    declared = None
    if os.path.isfile(cfg):
        try:
            with open(cfg) as fh:
                declared = (json.load(fh).get("output") or {}).get("dir")
        except (json.JSONDecodeError, OSError):
            declared = None
    # The repo's own config wins. The registry's hint is a convenience that goes
    # stale the moment a repo moves its output -- which has happened -- and a
    # stale hint makes a reporting repo look silent, the worst answer an
    # aggregator can give.
    if declared and hint and declared.strip("/") != hint.strip("/"):
        print(f"rollup: {registry_entry.get('name')}: registry says catchup_dir "
              f"{hint!r}, repo says {declared!r} -- using the repo's. "
              f"Update repos.json.", file=sys.stderr)
    return declared or hint or DEFAULT_OUTPUT_DIR


def read_week_record(repo_path, week, out_dir):
    p = os.path.join(repo_path, out_dir, "weeks", f"{week}.json")
    if not os.path.isfile(p):
        return None, p
    try:
        with open(p) as fh:
            return json.load(fh), p
    except (json.JSONDecodeError, OSError) as e:
        return {"_error": str(e)}, p


def read_entities(repo_path, week, out_dir, ids):
    """Load the entity files a week record names. Missing ones are reported."""
    edir = os.path.join(repo_path, out_dir, "entities")
    found, missing = [], []
    for eid in ids:
        p = os.path.join(edir, f"{eid}.json")
        if not os.path.isfile(p):
            missing.append(eid)
            continue
        try:
            with open(p) as fh:
                e = json.load(fh)
            e["_week_note"] = (e.get("weeks") or {}).get(week, {}).get("note")
            found.append(e)
        except (json.JSONDecodeError, OSError):
            missing.append(eid)
    return found, missing


def collect(week, registry, args):
    repos, missing_records = [], []
    for r in registry.get("repos", []) or []:
        path = resolve_path(r.get("path"))
        # This repo is the AGGREGATOR, not a source. It does not run a catchup on
        # itself -- it reads the others and summarises them -- so listing it as a
        # missing source would report a gap that is the design.
        #
        # Compared by git identity, not by path: this skill routinely runs from a
        # worktree, whose path differs from the registry's while being the same
        # repository. A path comparison silently fails in exactly the setup the
        # work actually happens in.
        if r.get("role") == "aggregator" or same_repo(path, REPO_ROOT):
            continue
        out_dir = repo_output_dir(path, r)
        rec, rec_path = read_week_record(path, week, out_dir)

        entry = {
            "name": r.get("name"),
            "lane": r.get("lane"),
            "disclosure": r.get("disclosure", "hidden"),
            "public_stats": r.get("public_stats",
                                  r.get("disclosure", "hidden") != "hidden"),
            "public_name": r.get("public_name"),
            "note": r.get("note"),
            "path": path,
            "available": os.path.isdir(path),
            "record_path": rec_path,
            "has_record": rec is not None and "_error" not in (rec or {}),
        }
        if not entry["available"]:
            entry["error"] = "repo path does not exist in this checkout"
        elif rec is None:
            entry["error"] = "no week record -- run catchup in this repo first"
            missing_records.append(r.get("name"))
        elif "_error" in rec:
            entry["error"] = f"unreadable week record: {rec['_error']}"
        else:
            ids = [i for cat in CATEGORY_ORDER for i in (rec.get("entities") or {}).get(cat, [])]
            ents, missing_ents = read_entities(path, week, out_dir, ids)
            summary = os.path.join(path, rec.get("summary_path") or "")
            entry.update({
                "stats": rec.get("stats") or {},
                "entity_count": rec.get("entity_count", 0),
                "entity_types": rec.get("entity_types") or {},
                "entities_by_category": rec.get("entities") or {},
                "corrections": rec.get("corrections") or [],
                "carried_over": rec.get("carried_over") or [],
                "partial": rec.get("partial"),
                "summary_path": summary if os.path.isfile(summary) else None,
                "entities": ents,
                "missing_entity_files": missing_ents,
            })
        repos.append(entry)

    live = [r for r in repos if r.get("has_record")]

    def total(key):
        vals = [(r["stats"] or {}).get(key) for r in live]
        vals = [v for v in vals if isinstance(v, int)]
        return sum(vals) if vals else 0

    # Stat lines get published, so keep the two populations apart from the start:
    # every repo that reported, and only those cleared to feed public counts.
    pub = [r for r in live if r.get("public_stats")]

    def total_pub(key):
        vals = [(r["stats"] or {}).get(key) for r in pub]
        return sum(v for v in vals if isinstance(v, int))

    cat_totals = Counter()
    type_totals = Counter()
    for r in live:
        for cat in CATEGORY_ORDER:
            cat_totals[cat] += len((r.get("entities_by_category") or {}).get(cat, []))
        for t, n in (r.get("entity_types") or {}).items():
            type_totals[t] += n

    # An entity id appearing in more than one repo is the thing a per-repo
    # catchup structurally cannot see, and the main reason this layer exists.
    by_id = defaultdict(list)
    for r in live:
        for e in r.get("entities") or []:
            by_id[e["id"]].append(r["name"])
    cross = {eid: sorted(set(names)) for eid, names in by_id.items() if len(set(names)) > 1}

    # Matching on id alone misses the case most worth catching. Two repos
    # writing about the same company name it differently -- one files it as the
    # idea it produced, the other as the conversation it came from -- so the ids
    # diverge and the id check reports nothing while the subject is plainly in
    # both. Tags catch it, at the cost of also catching shared TOPICS, which are
    # not the same thing. Reported separately and never merged into `cross`: one
    # is a fact, the other is a list to look at.
    # Token = the id AND every tag, because repos do not tag alike: one files a
    # subject under its own name, another tags it by what it IS and carries the
    # name only in the id. Matching tag-to-tag misses exactly that pair, which is
    # the same subject in two repos wearing two vocabularies.
    by_tag = defaultdict(set)
    for r in live:
        for e in r.get("entities") or []:
            for t in {e["id"]} | set(e.get("tags") or []):
                by_tag[t].add(r["name"])
    generic = {"correction", "convention", "ci", "testing", "agents", "lifecycle",
               "research", "architecture", "events", "in-flight"}
    candidates = {t: sorted(v) for t, v in by_tag.items()
                  if len(v) > 1 and t not in generic and not t.startswith(("repo:", "category:", "entity:", "contact:", "met:"))}

    tags = Counter()
    for r in live:
        for e in r.get("entities") or []:
            tags.update(e.get("tags") or [])

    return {
        "week": week,
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "repos": repos,
        "repos_reporting": len(live),
        "repos_registered": len(repos),
        "missing_records": missing_records,
        "totals": {
            "commits": total("commits"),
            "commits_primary": total("commits_primary"),
            "ignored": total("ignored"),
            "prs_merged": total("prs_merged"),
            "prs_open_now": total("prs_open_now"),
            "entities": sum(r.get("entity_count", 0) for r in live),
            "entities_by_category": dict(cat_totals),
            "entities_by_type": dict(type_totals),
            "corrections": sum(len(r.get("corrections") or []) for r in live),
            "carried_over": sum(len(r.get("carried_over") or []) for r in live),
        },
        "public_totals": {
            "repos": len(pub),
            "commits_primary": total_pub("commits_primary"),
            "prs_merged": total_pub("prs_merged"),
            "prs_open_now": total_pub("prs_open_now"),
        },
        "cross_repo_entities": cross,
        "cross_repo_candidates": dict(sorted(candidates.items())),
        "top_tags": dict(tags.most_common(20)),
    }


def render_table(d):
    w = d["week"]
    out = [f"# {w} — cross-repo rollup",
           f"  {d['repos_reporting']}/{d['repos_registered']} repos reporting"]
    if d["missing_records"]:
        out.append(f"  MISSING week records: {', '.join(d['missing_records'])}"
                   " — run catchup in each before trusting the totals")
    out.append("")
    hdr = f"  {'repo':<22}{'lane':<14}{'disc':<11}{'commits':>8}{'PRs':>6}{'ents':>6}{'corr':>6}"
    out += [hdr, "  " + "-" * (len(hdr) - 2)]
    for r in d["repos"]:
        if not r.get("has_record"):
            out.append(f"  {str(r['name']):<22}{str(r.get('lane') or ''):<14}"
                       f"{str(r.get('disclosure') or ''):<11}  {r.get('error', '?')}")
            continue
        s = r["stats"]
        out.append(f"  {str(r['name']):<22}{str(r.get('lane') or ''):<14}"
                   f"{str(r.get('disclosure') or ''):<11}"
                   f"{s.get('commits_primary', 0):>8}{s.get('prs_merged') or 0:>6}"
                   f"{r.get('entity_count', 0):>6}{len(r.get('corrections') or []):>6}")
    t = d["totals"]
    out += ["  " + "-" * (len(hdr) - 2),
            f"  {'TOTAL':<47}{t['commits_primary']:>8}{t['prs_merged']:>6}"
            f"{t['entities']:>6}{t['corrections']:>6}", ""]
    p = d["public_totals"]
    out.append(f"  publishable subset ({p['repos']} repos): "
               f"{p['commits_primary']} commits, {p['prs_merged']} PRs merged, "
               f"{p['prs_open_now']} open")
    out.append(f"  entities by category: " +
               ", ".join(f"{k} {v}" for k, v in t["entities_by_category"].items()))
    out.append(f"  carried over from earlier weeks: {t['carried_over']}")
    if d["cross_repo_entities"]:
        out += ["", "  same entity id in more than one repo:"]
        for eid, names in sorted(d["cross_repo_entities"].items()):
            out.append(f"    {eid}: {', '.join(names)}")
    if d.get("cross_repo_candidates"):
        out += ["", "  same SUBJECT, different ids — check these by hand:"]
        for t, names in d["cross_repo_candidates"].items():
            out.append(f"    {t}: {', '.join(names)}")
    return "\n".join(out)


def snapshot(d, out_dir):
    """Copy everything the rollup read into one directory beside its output.

    Provenance: a rollup is a claim about several repos on one date, and the
    repos keep moving. Without the sources beside it, "where did this number
    come from" is answerable only by re-running against a tree that has since
    changed -- which is not an answer. Weeks accumulate here, so later rollups
    can read further back than the current state of anyone's working tree.
    """
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"week": d["week"], "captured": d["generated"],
                "repos_reporting": d["repos_reporting"],
                "repos_registered": d["repos_registered"],
                "totals": d["totals"], "public_totals": d["public_totals"],
                "sources": []}
    for r in d["repos"]:
        if not r.get("has_record"):
            manifest["sources"].append({"name": r["name"], "captured": False,
                                        "reason": r.get("error")})
            continue
        rd = os.path.join(out_dir, r["name"])
        os.makedirs(rd, exist_ok=True)
        src_files = {}
        try:
            with open(r["record_path"]) as fh:
                rec = fh.read()
            with open(os.path.join(rd, "week.json"), "w") as fh:
                fh.write(rec)
            src_files["week.json"] = {"from": r["record_path"],
                                      "sha256": hashlib.sha256(rec.encode()).hexdigest()[:16]}
        except OSError:
            pass
        if r.get("summary_path"):
            try:
                with open(r["summary_path"]) as fh:
                    body = fh.read()
                with open(os.path.join(rd, "summary.md"), "w") as fh:
                    fh.write(body)
                src_files["summary.md"] = {"from": r["summary_path"],
                                           "sha256": hashlib.sha256(body.encode()).hexdigest()[:16]}
            except OSError:
                pass
        ents = r.get("entities") or []
        if ents:
            blob = json.dumps(ents, indent=2, sort_keys=True)
            with open(os.path.join(rd, "entities.json"), "w") as fh:
                fh.write(blob + "\n")
            src_files["entities.json"] = {"count": len(ents),
                                          "sha256": hashlib.sha256(blob.encode()).hexdigest()[:16]}
        manifest["sources"].append({
            "name": r["name"], "captured": True, "lane": r.get("lane"),
            "disclosure": r.get("disclosure"), "public_stats": r.get("public_stats"),
            "path": r["path"], "files": src_files,
        })
    with open(os.path.join(out_dir, "sources.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("week", nargs="?", help="ISO week, e.g. 2026-W35. Default: last closed week.")
    ap.add_argument("--weeks", help="comma-separated list of weeks")
    ap.add_argument("--registry", default=None, help=f"default {DEFAULT_REGISTRY}")
    ap.add_argument("--table", action="store_true", help="human stats table instead of JSON")
    ap.add_argument("--no-entities", action="store_true",
                    help="omit full entity bodies from JSON output (stats only)")
    ap.add_argument("--snapshot", default=None,
                    help="copy every source read into this directory, with hashes")
    ap.add_argument("--today", default=None, help="override today's date (testing)")
    args = ap.parse_args()

    today = dt.date.today()
    if args.today:
        try:
            today = dt.date.fromisoformat(args.today)
        except ValueError:
            die(f"cannot parse --today {args.today!r}")

    registry = load_registry(args.registry or DEFAULT_REGISTRY)

    if args.weeks:
        weeks = [parse_week(x, today) for x in args.weeks.split(",") if x.strip()]
    elif args.week:
        weeks = [parse_week(args.week, today)]
    else:
        weeks = [default_week(today)]

    results = [collect(w, registry, args) for w in weeks]
    if args.no_entities:
        for d in results:
            for r in d["repos"]:
                r.pop("entities", None)

    if args.snapshot:
        for d in results:
            m = snapshot(d, os.path.join(args.snapshot, d["week"]))
            print(f"snapshot: {os.path.join(args.snapshot, d['week'])} "
                  f"({sum(1 for s in m['sources'] if s['captured'])} sources captured)",
                  file=sys.stderr)

    if args.table:
        print("\n\n".join(render_table(d) for d in results))
    else:
        print(json.dumps(results[0] if len(results) == 1 else results, indent=2))


if __name__ == "__main__":
    main()
