#!/usr/bin/env python3
"""
Catchup entity store -- the durable half of the catchup.

A catchup has two passes. The first turns a week of raw commits into ENTITIES:
the things actually worth tracking -- a meeting, a partner, a technical thread, a
decision, a correction. The second writes the week's summary FROM those entities.
The entity is what persists; the summary is a rendering of it.

That split is what buys the history. A thread that runs for four weeks is ONE
entity file with four weekly notes on it, not four disconnected bullets in four
files -- so "what happened with X" is answerable by reading one file, and the
same entity maps to exactly one DeepVista context card that accumulates.

The store lives at `<output.dir>/entities/<id>.json`, one file per entity, so it
diffs cleanly in git and a human can hand-edit any single entity.

This script is the mechanical half: it validates, merges, and queries. It makes
no judgments -- deciding what counts as an entity is the model's job, and it
arrives here as JSON.

Usage:
    entities.py upsert --week 2026-W35 < extraction.json
    entities.py list [--week W] [--category C] [--status S] [--json]
    entities.py show <id>
    entities.py week 2026-W35            # summary scaffold, grouped by category
    entities.py validate
    entities.py stats
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter

CONFIG_RELPATH = os.path.join(".claude", "catchup.config.json")
DEFAULT_OUTPUT_DIR = os.path.join(".claude", "catchups")

CATEGORY_ORDER = ["meeting", "technical", "other"]
DEFAULT_TITLES = {
    "meeting": "Meeting / Partner Notes",
    "technical": "Technical Notes",
    "other": "Other",
}

# What an entity can be. Deliberately short: these are the shapes that recur
# across repos. `thread` is the workhorse -- a line of work with a beginning and
# an end. Anything that does not fit is `other`, not a new type.
ENTITY_TYPES = [
    "meeting",     # a specific conversation, dated: a 1x1, a partner call, an event
    "person",      # a human worth tracking across weeks
    "org",         # a company, fund, team, or vendor
    "thread",      # a line of technical work: a feature, a migration, a refactor
    "decision",    # a choice made, with its reason
    "correction",  # something found wrong and put right -- the highest-signal type
    "other",
]

STATUSES = ["active", "done", "parked", "dropped"]

WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def die(msg, code=1):
    print(f"entities: {msg}", file=sys.stderr)
    sys.exit(code)


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s or "entity")[:64]


def load_config(repo_path):
    path = os.path.join(repo_path, CONFIG_RELPATH)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        die(f"cannot read config {path}: {e}")


def store_dir(repo_path, cfg):
    out = (cfg.get("output") or {}).get("dir", DEFAULT_OUTPUT_DIR)
    return os.path.join(repo_path, out, "entities")


def weeks_dir(repo_path, cfg):
    """Where week records live: stats + which entities a week touched.

    Separate from the entity store because they answer different questions. An
    entity is "what is this thing, across time"; a week record is "how big was
    this week, and what did it touch" -- and it is the only machine-readable
    thing a cross-repo roll-up can add up. Without it, stats exist only inside
    prose and have to be re-derived by re-walking every repo's git log.
    """
    out = (cfg.get("output") or {}).get("dir", DEFAULT_OUTPUT_DIR)
    return os.path.join(repo_path, out, "weeks")


def category_titles(cfg):
    titles = dict(DEFAULT_TITLES)
    for key, over in (cfg.get("categories") or {}).items():
        if key in titles and isinstance(over, dict) and over.get("title"):
            titles[key] = over["title"]
    return titles


def entity_path(sdir, eid):
    return os.path.join(sdir, f"{eid}.json")


def load_all(sdir):
    if not os.path.isdir(sdir):
        return []
    out = []
    for name in sorted(os.listdir(sdir)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(sdir, name)
        try:
            with open(p) as fh:
                e = json.load(fh)
        except (json.JSONDecodeError, OSError) as err:
            print(f"entities: skipping unreadable {p}: {err}", file=sys.stderr)
            continue
        e["_path"] = p
        out.append(e)
    return out


def content_hash(e):
    """Hash of everything a DeepVista card would carry.

    The sync compares this to what it last pushed, so an unchanged entity costs
    no API call and no credit. Deliberately excludes the `deepvista` block, which
    the sync itself writes -- otherwise every push would dirty its own input.
    """
    payload = {k: v for k, v in e.items()
               if k not in ("deepvista", "_path", "updated_at")}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def normalize(raw, week):
    """Coerce one extraction record into a full entity. Raises ValueError on junk."""
    if not isinstance(raw, dict):
        raise ValueError("entity must be an object")

    title = (raw.get("title") or "").strip()
    if not title:
        raise ValueError("entity needs a title")

    eid = (raw.get("id") or slugify(title)).strip().lower()
    if not ID_RE.match(eid):
        raise ValueError(f"bad id {eid!r} -- lowercase letters, digits, hyphens; 2-64 chars")

    etype = (raw.get("type") or "thread").strip().lower()
    if etype not in ENTITY_TYPES:
        raise ValueError(f"bad type {etype!r} -- one of {', '.join(ENTITY_TYPES)}")

    cat = (raw.get("category") or "").strip().lower()
    if cat not in CATEGORY_ORDER:
        raise ValueError(f"bad category {cat!r} -- one of {', '.join(CATEGORY_ORDER)}")

    status = (raw.get("status") or "active").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r} -- one of {', '.join(STATUSES)}")

    note = (raw.get("note") or "").strip()
    if not note:
        raise ValueError(f"{eid}: needs a `note` -- what happened this week")

    return {
        "id": eid,
        "type": etype,
        "category": cat,
        "title": title,
        "summary": (raw.get("summary") or note).strip(),
        "status": status,
        "tags": sorted({str(t).strip().lower() for t in (raw.get("tags") or []) if str(t).strip()}),
        "links": sorted({str(l).strip().lower() for l in (raw.get("links") or []) if str(l).strip()}),
        "week_entry": {
            "note": note,
            "commits": sorted({str(c)[:9] for c in (raw.get("commits") or [])}),
            "prs": sorted({int(p) for p in (raw.get("prs") or []) if str(p).isdigit()}),
            "paths": sorted({str(p) for p in (raw.get("paths") or []) if str(p).strip()}),
            "people": sorted({str(p).strip() for p in (raw.get("people") or []) if str(p).strip()}),
            "date": raw.get("date"),
        },
        "_week": week,
    }


def merge(existing, incoming):
    """Fold one week's record into an entity, idempotently.

    Re-running a week REPLACES that week's block rather than appending to it, so
    a corrected extraction overwrites cleanly instead of double-counting. Fields
    that describe current state (summary, status) take the newest value; fields
    that describe identity (first_seen, type) hold.
    """
    week = incoming["_week"]
    if existing is None:
        e = {
            "id": incoming["id"],
            "type": incoming["type"],
            "category": incoming["category"],
            "title": incoming["title"],
            "summary": incoming["summary"],
            "status": incoming["status"],
            "tags": incoming["tags"],
            "links": incoming["links"],
            "first_seen": week,
            "last_seen": week,
            "weeks": {},
            "deepvista": {"card_id": None, "synced_at": None, "content_hash": None},
        }
    else:
        e = dict(existing)
        e.pop("_path", None)
        # Current-state fields follow the newest week seen; a late correction to
        # an older week must not rewrite the entity's present tense.
        if week >= e.get("last_seen", ""):
            e["title"] = incoming["title"]
            e["summary"] = incoming["summary"]
            e["status"] = incoming["status"]
            e["category"] = incoming["category"]
            e["type"] = incoming["type"]
        e["tags"] = sorted(set(e.get("tags", [])) | set(incoming["tags"]))
        e["links"] = sorted(set(e.get("links", [])) | set(incoming["links"]))
        e["first_seen"] = min(e.get("first_seen", week), week)
        e["last_seen"] = max(e.get("last_seen", week), week)
        e.setdefault("weeks", {})
        e.setdefault("deepvista", {"card_id": None, "synced_at": None, "content_hash": None})

    e["weeks"][week] = incoming["week_entry"]
    e["weeks"] = {k: e["weeks"][k] for k in sorted(e["weeks"])}
    e["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return e


def write_entity(sdir, e):
    os.makedirs(sdir, exist_ok=True)
    body = {k: v for k, v in e.items() if not k.startswith("_")}
    with open(entity_path(sdir, e["id"]), "w") as fh:
        json.dump(body, fh, indent=2, sort_keys=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_upsert(args, repo, cfg, sdir):
    if not WEEK_RE.match(args.week or ""):
        die(f"--week must look like 2026-W35, got {args.week!r}")

    src = sys.stdin if args.file in (None, "-") else open(args.file)
    try:
        data = json.load(src)
    except json.JSONDecodeError as e:
        die(f"input is not valid JSON: {e}")
    finally:
        if src is not sys.stdin:
            src.close()

    records = data.get("entities") if isinstance(data, dict) else data
    if not isinstance(records, list):
        die("expected a JSON array of entities, or an object with an `entities` array")

    normed, errors = [], []
    for i, raw in enumerate(records):
        try:
            normed.append(normalize(raw, args.week))
        except ValueError as e:
            errors.append(f"  [{i}] {e}")
    if errors:
        die("rejected extraction:\n" + "\n".join(errors))

    seen = {}
    for n in normed:
        if n["id"] in seen:
            die(f"duplicate id in one extraction: {n['id']}")
        seen[n["id"]] = n

    created, updated = [], []
    for n in normed:
        p = entity_path(sdir, n["id"])
        old = None
        if os.path.isfile(p):
            with open(p) as fh:
                old = json.load(fh)
        merged = merge(old, n)
        if args.dry_run:
            (updated if old else created).append(merged["id"])
            continue
        write_entity(sdir, merged)
        (updated if old else created).append(merged["id"])

    print(json.dumps({
        "week": args.week,
        "store": os.path.relpath(sdir, repo),
        "dry_run": bool(args.dry_run),
        "created": sorted(created),
        "updated": sorted(updated),
        "total": len(normed),
    }, indent=2))


def _filter(ents, args):
    out = ents
    if getattr(args, "week", None):
        out = [e for e in out if args.week in (e.get("weeks") or {})]
    if getattr(args, "category", None):
        out = [e for e in out if e.get("category") == args.category]
    if getattr(args, "status", None):
        out = [e for e in out if e.get("status") == args.status]
    if getattr(args, "type", None):
        out = [e for e in out if e.get("type") == args.type]
    return out


def cmd_list(args, repo, cfg, sdir):
    ents = _filter(load_all(sdir), args)
    ents.sort(key=lambda e: (CATEGORY_ORDER.index(e.get("category", "other"))
                             if e.get("category") in CATEGORY_ORDER else 9,
                             e.get("id", "")))
    if args.json:
        print(json.dumps([{k: v for k, v in e.items() if k != "_path"} for e in ents], indent=2))
        return
    if not ents:
        print("no entities match")
        return
    titles = category_titles(cfg)
    cur = None
    for e in ents:
        if e.get("category") != cur:
            cur = e.get("category")
            print(f"\n## {titles.get(cur, cur)}")
        weeks = sorted((e.get("weeks") or {}))
        span = weeks[0] if len(weeks) < 2 else f"{weeks[0]}..{weeks[-1]}"
        card = (e.get("deepvista") or {}).get("card_id")
        print(f"  {e['id']:<40} {e.get('type',''):<11} {e.get('status',''):<8} "
              f"{span:<18} {len(weeks):>2}w {'[dv]' if card else ''}")
    print(f"\n{len(ents)} entities")


def cmd_show(args, repo, cfg, sdir):
    p = entity_path(sdir, args.id)
    if not os.path.isfile(p):
        die(f"no such entity: {args.id}")
    with open(p) as fh:
        print(fh.read().rstrip())


def cmd_week(args, repo, cfg, sdir):
    """The summary scaffold: everything the week touched, grouped by category.

    This is what pass 2 writes from. It is deliberately not prose -- the model
    turns it into prose, and having the raw grouping separate means the summary
    can be rewritten later without re-deriving the facts.
    """
    if not WEEK_RE.match(args.week or ""):
        die(f"week must look like 2026-W35, got {args.week!r}")
    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    titles = category_titles(cfg)

    if args.json:
        grouped = {k: [] for k in CATEGORY_ORDER}
        for e in ents:
            grouped.setdefault(e.get("category", "other"), []).append(
                {k: v for k, v in e.items() if k != "_path"})
        print(json.dumps({"week": args.week, "titles": titles,
                          "categories": grouped,
                          "count": len(ents)}, indent=2))
        return

    if not ents:
        print(f"no entities recorded for {args.week}")
        return

    print(f"# {args.week} — entity scaffold ({len(ents)} entities)\n")
    for key in CATEGORY_ORDER:
        group = [e for e in ents if e.get("category") == key]
        if not group:
            continue
        print(f"## {titles[key]}  ({len(group)})\n")
        for e in sorted(group, key=lambda x: x["id"]):
            w = e["weeks"][args.week]
            weeks = sorted(e.get("weeks") or {})
            cont = "" if len(weeks) < 2 else f"  [running since {weeks[0]}, {len(weeks)} weeks]"
            print(f"### {e['title']}  ({e['type']} · {e['status']}){cont}")
            print(f"    id: {e['id']}")
            print(f"    {w['note']}")
            bits = []
            if w.get("prs"):
                bits.append("PRs " + ", ".join(f"#{p}" for p in w["prs"]))
            if w.get("commits"):
                bits.append(f"{len(w['commits'])} commits")
            if w.get("people"):
                bits.append("people: " + ", ".join(w["people"]))
            if w.get("date"):
                bits.append(str(w["date"]))
            if bits:
                print("    " + " · ".join(bits))
            print()


def cmd_record_week(args, repo, cfg, sdir):
    """Store the week's stats beside its entities, from a pull_week.py blob."""
    src = sys.stdin if args.pull in (None, "-") else open(args.pull)
    try:
        blob = json.load(src)
    except json.JSONDecodeError as e:
        die(f"--pull input is not valid JSON: {e}")
    finally:
        if src is not sys.stdin:
            src.close()

    weeks = blob.get("weeks") if isinstance(blob, dict) else None
    if not weeks:
        die("--pull input has no `weeks` -- expected pull_week.py output")
    w = next((x for x in weeks if x.get("week") == args.week), None)
    if w is None:
        if len(weeks) == 1:
            w = weeks[0]
            if w.get("week") != args.week:
                die(f"--week {args.week} but the pull covers {w.get('week')}")
        else:
            die(f"{args.week} not in the pull, which covers "
                f"{', '.join(x.get('week', '?') for x in weeks)}")

    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    by_cat = {k: sorted(e["id"] for e in ents if e.get("category") == k)
              for k in CATEGORY_ORDER}

    rec = {
        "week": args.week,
        "start": w.get("start"),
        "end": w.get("end"),
        "partial": w.get("partial"),
        "repo": w.get("repo_label"),
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "stats": {
            # `commits` is the honest headline: real work, bookkeeping removed.
            # `commits_primary` is what to publish when only one number fits;
            # `commits_wide` spans all refs and is machine-specific.
            "commits": w.get("commit_count"),
            "commits_primary": w.get("commit_count_primary"),
            "commits_wide": (w.get("commit_count") or 0) + (w.get("ignored_count") or 0),
            "ignored": w.get("ignored_count"),
            "ignored_reasons": w.get("ignored_reasons"),
            "prs_merged": w.get("prs_merged"),
            "prs_open_now": w.get("prs_open_now"),
            "pr_numbers": [p["number"] for p in (w.get("pr_details") or [])] or w.get("prs"),
            "pr_body_chars": w.get("pr_body_chars_total"),
            "authors": w.get("authors"),
            "author_categories": w.get("author_categories"),
            "unknown_authors": w.get("unknown_authors"),
            # How the CLASSIFIER split the commits. Distinct from the record's
            # `entities` block, which is what extraction actually decided -- the
            # two differ whenever pass 1 overrode a guess, and both are worth
            # keeping so that disagreement stays visible.
            "commit_categories": {k: (w.get("categories") or {}).get(k, {}).get("count")
                                  for k in CATEGORY_ORDER},
            "top_dirs": w.get("top_dirs"),
        },
        "entities": by_cat,
        "entity_count": len(ents),
        "entity_types": dict(sorted(
            Counter(e.get("type") for e in ents).items())),
        "corrections": sorted(e["id"] for e in ents if e.get("type") == "correction"),
        "carried_over": sorted(e["id"] for e in ents
                               if len(e.get("weeks") or {}) > 1
                               and min(e["weeks"]) < args.week),
        "summary_path": w.get("output_path"),
    }

    wdir = weeks_dir(repo, cfg)
    os.makedirs(wdir, exist_ok=True)
    path = os.path.join(wdir, f"{args.week}.json")
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)
        fh.write("\n")
    print(json.dumps({"wrote": os.path.relpath(path, repo),
                      "entities": rec["entity_count"],
                      "stats": rec["stats"]}, indent=2))


def cmd_validate(args, repo, cfg, sdir):
    ents = load_all(sdir)
    problems = []
    ids = {e.get("id") for e in ents}
    for e in ents:
        eid = e.get("id") or "(no id)"
        base = os.path.splitext(os.path.basename(e["_path"]))[0]
        if eid != base:
            problems.append(f"{base}: id {eid!r} does not match filename")
        if e.get("type") not in ENTITY_TYPES:
            problems.append(f"{eid}: bad type {e.get('type')!r}")
        if e.get("category") not in CATEGORY_ORDER:
            problems.append(f"{eid}: bad category {e.get('category')!r}")
        if e.get("status") not in STATUSES:
            problems.append(f"{eid}: bad status {e.get('status')!r}")
        if not (e.get("weeks") or {}):
            problems.append(f"{eid}: no weeks recorded")
        for w in (e.get("weeks") or {}):
            if not WEEK_RE.match(w):
                problems.append(f"{eid}: bad week key {w!r}")
        for link in e.get("links") or []:
            if link not in ids:
                problems.append(f"{eid}: link to unknown entity {link!r}")
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print(f"ok — {len(ents)} entities valid")


def cmd_stats(args, repo, cfg, sdir):
    ents = load_all(sdir)
    weeks, cats, types, statuses = {}, {}, {}, {}
    synced = 0
    for e in ents:
        for w in (e.get("weeks") or {}):
            weeks[w] = weeks.get(w, 0) + 1
        cats[e.get("category")] = cats.get(e.get("category"), 0) + 1
        types[e.get("type")] = types.get(e.get("type"), 0) + 1
        statuses[e.get("status")] = statuses.get(e.get("status"), 0) + 1
        if (e.get("deepvista") or {}).get("card_id"):
            synced += 1
    print(json.dumps({
        "store": os.path.relpath(sdir, repo),
        "entities": len(ents),
        "synced_to_deepvista": synced,
        "weeks": dict(sorted(weeks.items())),
        "categories": cats,
        "types": types,
        "statuses": statuses,
    }, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repo to operate on (default: cwd)")
    # --repo is accepted on either side of the subcommand. Both orders read
    # naturally, and a flag that works in only one position is a papercut every
    # caller hits once.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", dest="repo_sub", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("upsert", parents=[common], help="merge an extraction into the store")
    p.add_argument("--week", required=True)
    p.add_argument("--file", default="-", help="JSON file, or - for stdin")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_upsert)

    p = sub.add_parser("list", parents=[common], help="list entities")
    p.add_argument("--week")
    p.add_argument("--category", choices=CATEGORY_ORDER)
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--type", choices=ENTITY_TYPES)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", parents=[common], help="print one entity")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("week", parents=[common], help="summary scaffold for one week")
    p.add_argument("week")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_week)

    p = sub.add_parser("record-week", parents=[common],
                       help="store the week's stats beside its entities")
    p.add_argument("--week", required=True)
    p.add_argument("--pull", default="-", help="pull_week.py JSON, or - for stdin")
    p.set_defaults(fn=cmd_record_week)

    p = sub.add_parser("validate", parents=[common], help="schema-check the store")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("stats", parents=[common], help="store overview")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    repo = os.path.abspath(os.path.expanduser(args.repo_sub or args.repo))
    if not os.path.isdir(repo):
        die(f"no such directory: {repo}")
    cfg = load_config(repo)
    args.fn(args, repo, cfg, store_dir(repo, cfg))


if __name__ == "__main__":
    main()
