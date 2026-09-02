#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
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
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

CONFIG_RELPATH = os.path.join(".claude", "catchup.config.json")
# See pull_week.py: output is content and belongs at the top level, not under
# the agent-configuration directory. `output.dir` overrides.
DEFAULT_OUTPUT_DIR = "catchup"

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
    # A technical idea, mechanism, or composition -- the thing that was LEARNED,
    # as opposed to the meeting where it was said or the vendor who said it.
    # Every other type on this list is a unit of activity or of actor, so a week
    # that produced knowledge had nowhere to put it except inside some company's
    # note, where it comes out as "what they showed" instead of "what is now
    # understood". The worked example is an event week: the brief written from it
    # carried a five-stage composition and a seam table with evidence grades, and
    # what survived into entities was four company records plus the story of our
    # own drafting. Concepts outlive the vendors that evidence them, which is also
    # why they are the entities most worth accumulating across weeks.
    "concept",
    # An arc of work large enough to be the answer to "what moved this week".
    # Themes exist because every other type is a LEAF: nothing could hold "the
    # research pipeline was rebuilt" as one thing owning the radar work, the tier
    # ladder, the product lens and the fast-vet retirement, so the reader had to
    # assemble it from twenty fragments and the summary led with whatever was
    # easiest to state. A theme must carry measured weight -- share of the week's
    # commits and churn -- which is the gate that stops an easily-phrased trifle
    # from outranking 58% of the work.
    "theme",
    "other",
]

# Themes are ranked by WEIGHT, learnings by GRADE. Keeping those apart is the
# point: a test-harness fix can be perfectly `measured` and weigh nothing, and
# under one combined ranking it outranked a redesign spanning nine PRs.
THEME_DISPOSITIONS = ["confirmed", "merged", "dropped"]

STATUSES = ["active", "done", "parked", "dropped"]

# How strongly a claim is held, weakest first. The DEFAULT ladder is deliberately
# generic -- it has to mean something in a product repo, a marketing repo and an
# evaluation corpus alike. A repo whose own surfaces already grade evidence should
# override it in config with the words it actually uses, so the catchup grades a
# learning the way that repo does rather than introducing a second scale nobody
# reconciles. `measured` is the only grade that survives someone else disagreeing
# with you, whatever the rungs below it are called.
DEFAULT_GRADES = ["asserted", "reported", "observed", "verified", "measured"]
DEFAULT_GRADE_MARKS = {
    "asserted": "asserted",
    "reported": "reported",
    "observed": "seen",
    "verified": "verified",
    "measured": "MEASURED",
}

# What share of a week's commits a candidate must carry to lead it. Defaults, not
# law: a repo of many tiny commits and one of few large ones do not agree about
# what 15% means, so both are tunable per repo.
DEFAULT_THEME_SHARES = {"confirm": 0.15, "thin": 0.05}

# How long a theme child's line may run before it is probably a finding.
CHILD_NOTE_CHARS = 260


def grade_scale(cfg):
    """(ladder, marks) for this repo -- config first, generic default otherwise."""
    lc = (cfg or {}).get("learnings") or {}
    grades = [str(g).strip().lower() for g in (lc.get("grades") or []) if str(g).strip()]
    if not grades:
        return list(DEFAULT_GRADES), dict(DEFAULT_GRADE_MARKS)
    marks = dict(lc.get("grade_marks") or {})
    return grades, {g: marks.get(g, g) for g in grades}


def theme_shares(cfg):
    tc = (cfg or {}).get("themes") or {}
    out = dict(DEFAULT_THEME_SHARES)
    for k in list(out):
        v = tc.get(k + "_share")
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out

WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
PR_NUM_RE = re.compile(r"#(\d+)")


def die(msg, code=1):
    print(f"entities: {msg}", file=sys.stderr)
    sys.exit(code)


def utc_now():
    """Timestamps written into the store are UTC, and say so.

    Same reason the week boundary is UTC: a naive local timestamp means a
    different instant on every machine, and this project dates its artifacts by
    UTC — evening-Pacific work belongs to the next UTC day.
    """
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


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


def normalize(raw, week, grades=None):
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

    claim = (raw.get("claim") or "").strip()
    grade = (raw.get("grade") or "").strip().lower()
    subject = (raw.get("subject") or "").strip()
    grades = grades or DEFAULT_GRADES
    if etype == "concept":
        if not claim:
            raise ValueError(f"{eid}: a concept needs a `claim` -- one sentence of what is now true")
        if grade not in grades:
            raise ValueError(f"{eid}: a concept needs a `grade` -- one of {', '.join(grades)}")
        # The bar that keeps aphorisms out. A learning is ABOUT something -- a
        # technology, a company, an architecture. "A test that accepts either
        # outcome is not a test" names no subject, was true before this week, and
        # will be true after it; it is not something the week taught anyone.
        if not subject:
            raise ValueError(
                f"{eid}: a concept needs a `subject` -- the technology, company or "
                f"architecture it is about. If you cannot name one, it is a general "
                f"engineering maxim rather than something this week taught.")
    if grade and grade not in grades:
        raise ValueError(f"bad grade {grade!r} -- one of {', '.join(grades)}")

    # Concepts live in Learnings and nowhere else. Allowing one under a theme is
    # how the two sections came to say the same thing twice: the theme restated
    # the finding as part of the work, and the learning stated it again as the
    # finding. A theme's children are units of WORK -- what changed. What the work
    # taught is a concept, one section down.
    if etype == "concept" and (raw.get("theme") or "").strip():
        raise ValueError(
            f"{eid}: a concept cannot hang off a theme -- learnings are their own "
            f"section. Put the WORK under the theme and let the concept carry what "
            f"it taught, or the two sections will repeat each other.")

    moved = (raw.get("moved") or "").strip()
    why = (raw.get("why_it_matters") or "").strip()
    weight = raw.get("weight") or {}
    disposition = (raw.get("disposition") or "confirmed").strip().lower()
    if etype == "theme":
        if disposition not in THEME_DISPOSITIONS:
            raise ValueError(f"{eid}: bad disposition {disposition!r} -- "
                             f"one of {', '.join(THEME_DISPOSITIONS)}")
        if not moved:
            raise ValueError(f"{eid}: a theme needs `moved` -- what advanced this week")
        if disposition == "confirmed":
            if not why:
                raise ValueError(f"{eid}: a confirmed theme needs `why_it_matters` -- "
                                 f"one line, for a reader who was not here")
            if not isinstance(weight, dict) or not weight.get("commits"):
                raise ValueError(f"{eid}: a confirmed theme needs a measured `weight` "
                                 f"(run `entities.py weigh`) -- a theme nobody weighed "
                                 f"is an opinion about the week")

    entry = {
        # A theme's four parts: what advanced, why a reader should care, what it
        # weighed, and what proves it happened.
        "moved": moved or None,
        "why_it_matters": why or None,
        "weight": weight or None,
        "evidence": [str(x).strip() for x in (raw.get("evidence") or []) if str(x).strip()] or None,
        "disposition": disposition if etype == "theme" else None,
        # The learning, in the four parts a learning actually has. Prose in a
        # single `note` cannot be compressed by a renderer -- it can only be
        # re-narrated at the same length, which is why the summary read as a lot
        # of text and few learnings. Structured, the markdown becomes derived.
        "claim": claim or None,
        "grade": grade or None,
        "subject": subject or None,
        "so_what": (raw.get("so_what") or "").strip() or None,
        "open": (raw.get("open") or "").strip() or None,
        "note": note,
        "commits": sorted({str(c)[:9] for c in (raw.get("commits") or [])}),
        "prs": sorted({int(p) for p in (raw.get("prs") or []) if str(p).isdigit()}),
        # Work that happened but has not landed. `prs` is what merged, and the
        # validator holds it to that; without a separate field, in-flight work
        # could only be recorded as prose with no resolvable evidence at all --
        # so a real thread sitting on an open branch looked like an unevidenced
        # claim. Cite the PR here and it stays checkable while it is still open.
        "open_prs": sorted({int(p) for p in (raw.get("open_prs") or []) if str(p).isdigit()}),
        "paths": sorted({str(p) for p in (raw.get("paths") or []) if str(p).strip()}),
        "people": sorted({str(p).strip() for p in (raw.get("people") or []) if str(p).strip()}),
        # WHO WAS IN THE ROOM, as entity ids. Distinct from `links`, which is
        # relatedness -- a meeting links its company, the people discussed in
        # it, and any commitment it created. Deriving attendance from `links`
        # marks everyone mentioned as met: it once reported an absent
        # mentor and an explicitly-unmet CTO as both having been in the room.
        "attendees": sorted({str(a).strip() for a in (raw.get("attendees") or []) if str(a).strip()}),
        # What the conversation PRODUCED, kept apart from what it said. A
        # meeting note that only narrates is a transcript; the reason anyone
        # re-reads one before the next call is to find what they promised and
        # what they still have to ask. Repos that keep meeting notes almost
        # always already have this -- a "Support / follow-up" section, an
        # action list, a checklist -- and rendering the narration while
        # dropping it is how a summary ends up long and useless at once.
        "owed": [str(x).strip() for x in (raw.get("owed") or []) if str(x).strip()],
        "asks": [str(x).strip() for x in (raw.get("asks") or []) if str(x).strip()],
        "date": raw.get("date"),
    }
    return {
        "id": eid,
        "type": etype,
        "category": cat,
        "title": title,
        "summary": (raw.get("summary") or note).strip(),
        "status": status,
        "tags": sorted({str(t).strip().lower() for t in (raw.get("tags") or []) if str(t).strip()}),
        "links": sorted({str(l).strip().lower() for l in (raw.get("links") or []) if str(l).strip()}),
        # A DIRECTED parent edge, unlike `links`, so the renderer can group work
        # under the arc it belongs to instead of listing leaves side by side.
        "theme": (raw.get("theme") or "").strip().lower() or None,
        "week_entry": {k: v for k, v in entry.items() if v is not None},
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
            "theme": incoming.get("theme"),
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
            if incoming.get("theme"):
                e["theme"] = incoming["theme"]
        e["tags"] = sorted(set(e.get("tags", [])) | set(incoming["tags"]))
        e["links"] = sorted(set(e.get("links", [])) | set(incoming["links"]))
        e["first_seen"] = min(e.get("first_seen", week), week)
        e["last_seen"] = max(e.get("last_seen", week), week)
        e.setdefault("weeks", {})
        e.setdefault("deepvista", {"card_id": None, "synced_at": None, "content_hash": None})

    e["weeks"][week] = incoming["week_entry"]
    e["weeks"] = {k: e["weeks"][k] for k in sorted(e["weeks"])}
    e["updated_at"] = utc_now()
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
            normed.append(normalize(raw, args.week, grade_scale(cfg)[0]))
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

    # Two lenses across all three categories, not a fourth category. Concepts
    # lead, because they are what the week is FOR: a reader with none of the
    # context needs the idea before the room it was said in or the vendor that
    # said it. A week with meetings and no concepts is the signature of a
    # procedural extraction -- something was presented and nothing was learned.
    concepts = [e for e in ents if e.get("type") == "concept"]
    if concepts:
        print(f"## Concepts — what the week taught  ({len(concepts)})\n")
        for e in sorted(concepts, key=lambda x: x["id"]):
            weeks = sorted(e.get("weeks") or {})
            cont = "" if len(weeks) < 2 else f"  [building since {weeks[0]}, {len(weeks)} weeks]"
            print(f"### {e['title']}{cont}")
            print(f"    id: {e['id']}  ({titles.get(e.get('category'), e.get('category'))})")
            print(f"    stands as: {e.get('summary', '').strip()}")
            print(f"    this week: {e['weeks'][args.week]['note']}")
            if e.get("links"):
                print(f"    evidenced by: {', '.join(e['links'])}")
            print()
    elif any(e.get("category") == "meeting" for e in ents):
        print("## Concepts — what the week taught  (0)\n")
        print("    The week has meeting entities and no concepts. Check that the")
        print("    extraction did not stop at who presented and what we did.\n")


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
        "generated": utc_now(),
        "stats": {
            # `commits` is the honest headline: real work on the mainline ref,
            # bookkeeping removed. `commits_primary` is the same number, kept for
            # readers that already publish it. `commits_wide` spans all refs and
            # is machine-specific — it exists so the commits dropped as
            # off-mainline stay visible, never as something to publish.
            "commits": w.get("commit_count"),
            "commits_primary": w.get("commit_count_primary"),
            "commits_wide": w.get("commit_count_all_refs"),
            "ignored": w.get("ignored_count"),
            "ignored_reasons": w.get("ignored_reasons"),
            "off_primary": w.get("off_primary_count"),
            "off_primary_reasons": w.get("off_primary_reasons"),
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
        "concepts": sorted(e["id"] for e in ents if e.get("type") == "concept"),
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


def git(repo, args, timeout=120):
    r = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def mainline_shas(repo):
    """Every commit reachable from the mainline ref, or None if there is no ref.

    Provenance has to survive leaving this machine. A pre-squash branch commit
    and the mainline commit it became share a subject but not a sha, and the
    branch copy is reachable from nothing once the PR merges -- it lives in the
    local object store until git prunes it and does not exist in a fresh clone.
    Five of W35's citations were exactly that: dangling objects, each with an
    identical-subject twin on main that went uncited.
    """
    head = git(repo, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"]).strip()
    ref = head[len("refs/remotes/"):] if head.startswith("refs/remotes/") else None
    if not ref:
        for cand in ("origin/main", "origin/master", "main", "master"):
            if git(repo, ["rev-parse", "--verify", "--quiet", cand]).strip():
                ref = cand
                break
    if not ref:
        return None, None
    return ref, set(git(repo, ["rev-list", ref]).split())


def merged_pr_weeks(repo):
    """{pr_number: 'YYYY-Www'} by UTC merge date, or None without gh.

    `mergedAt` is UTC and is the only authority on which week a PR landed in. A
    scraped `#NN` says a commit mentioned a PR, not that the PR belongs to the
    week -- `align-block4` cited #64 in W35, and #64 merged on 2026-08-31, W36.
    """
    raw = subprocess.run(
        ["gh", "pr", "list", "--state", "merged", "--limit", "500",
         "--json", "number,mergedAt"],
        cwd=repo, capture_output=True, text=True, timeout=60)
    if raw.returncode != 0 or not raw.stdout.strip():
        return None
    try:
        items = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return None
    out = {}
    for pr in items:
        when = (pr.get("mergedAt") or "").replace("Z", "+00:00")
        try:
            d = dt.datetime.fromisoformat(when).astimezone(dt.timezone.utc).date()
        except (ValueError, TypeError):
            continue
        y, w, _ = d.isocalendar()
        out[pr["number"]] = f"{y}-W{w:02d}"
    return out


def cmd_validate(args, repo, cfg, sdir):
    ents = load_all(sdir)
    problems = []
    notes = []
    ids = {e.get("id") for e in ents}

    ref, reachable = mainline_shas(repo)
    if reachable is None:
        notes.append("no mainline ref found — commit provenance NOT checked")
    pr_weeks = None if args.no_gh else merged_pr_weeks(repo)
    if pr_weeks is None:
        notes.append("gh unavailable or skipped — PR weeks NOT checked")

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
        for wk, entry in (e.get("weeks") or {}).items():
            if not WEEK_RE.match(wk):
                problems.append(f"{eid}: bad week key {wk!r}")
                continue
            for sha in (entry.get("commits") or []):
                if reachable is None:
                    break
                if not any(full.startswith(sha) for full in reachable):
                    problems.append(
                        f"{eid} [{wk}]: commit {sha} is not reachable from {ref} — "
                        f"a citation nobody else can resolve")
            for n in (entry.get("open_prs") or []):
                if pr_weeks is None:
                    break
                if pr_weeks.get(int(n)) is not None:
                    problems.append(
                        f"{eid} [{wk}]: PR #{n} is listed as open but has merged — "
                        f"move it to `prs`")
            for n in (entry.get("prs") or []):
                if pr_weeks is None:
                    break
                got = pr_weeks.get(int(n))
                if got is None:
                    problems.append(
                        f"{eid} [{wk}]: PR #{n} is not a merged PR here "
                        f"(if it is still open, cite it under `open_prs`)")
                elif got != wk:
                    problems.append(
                        f"{eid} [{wk}]: PR #{n} merged in {got}, not {wk}")
        for link in e.get("links") or []:
            if link not in ids:
                problems.append(f"{eid}: link to unknown entity {link!r}")

    for n in notes:
        print(f"note: {n}")
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print(f"ok — {len(ents)} entities valid")


def _load_pull(arg):
    src = sys.stdin if arg in (None, "-") else open(arg)
    try:
        blob = json.load(src)
    except json.JSONDecodeError as e:
        die(f"--pull input is not valid JSON: {e}")
    finally:
        if src is not sys.stdin:
            src.close()
    weeks = blob.get("weeks") or []
    if not weeks:
        die("--pull input has no weeks")
    return weeks


def _week_from_pull(arg, week):
    for w in _load_pull(arg):
        if w.get("week") == week:
            return w
    die(f"--pull input does not contain {week}")


def _commit_prs(commit):
    """Every PR this commit can be attributed to, best source first."""
    out = set()
    if commit.get("pr"):
        out.add(int(commit["pr"]))
    out |= {int(n) for n in PR_NUM_RE.findall(commit.get("subject", ""))}
    return out


def _path_matches(path, pattern):
    """A `--paths` entry matches as a glob when it looks like one, else as a prefix.

    Every other path input in this skill -- category rules, ignore rules,
    subject artifacts -- is a glob, so a glob is what a caller reaches for here
    too. Prefix-only matching turned `src/**` into zero hits and the weigh
    verdict then read `DROPPED -- too small to be a theme`, which is a confident
    wrong answer to a question the caller did not ask. Both forms work now.
    """
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/") + "/*")
    return path.startswith(pattern)


def _match(commit, paths, prs):
    if prs and (_commit_prs(commit) & prs):
        return True
    return any(_path_matches(p, pat) for p in commit.get("paths", []) for pat in paths)


def _unmatched_patterns(commits, paths):
    """Patterns that matched nothing anywhere in the week.

    Reported separately from the weight, because "your hypothesis is too small"
    and "your pattern is wrong" are different answers and only one of them means
    the theme should be dropped.
    """
    seen = {p for c in commits for p in c.get("paths", [])}
    return [pat for pat in paths
            if not any(_path_matches(p, pat) for p in seen)]


def _weigh(commits, paths, prs):
    hit = [c for c in commits if _match(c, paths, prs)]
    lines = sum(c.get("insertions", 0) + c.get("deletions", 0) for c in hit)
    total_lines = sum(c.get("insertions", 0) + c.get("deletions", 0) for c in commits) or 1
    return {
        "commits": len(hit),
        "share": round(len(hit) / len(commits), 2) if commits else 0.0,
        "lines": lines,
        "line_share": round(lines / total_lines, 2),
        "prs": sorted({n for c in hit for n in _commit_prs(c)}),
        "days": sorted({c["date"] for c in hit}),
    }, hit


def cmd_propose(args, repo, cfg, sdir):
    """Cluster the week mechanically, so the theme hypothesis starts from data.

    The first pass used to be recall: read everything, then decide what mattered.
    That reliably surfaced whatever was easiest to phrase -- a self-contained test
    fix has one commit and a crisp lesson, while a redesign spanning nine PRs has
    neither. Clustering first means the hypothesis starts from where the work
    actually went, and the model's job is to NAME the cluster rather than to
    remember the week.

    Nothing here decides anything. It reports where the mass is; `weigh` then
    tests a named hypothesis against it.
    """
    w = _week_from_pull(args.pull, args.week)
    commits = w.get("commits") or []
    if not commits:
        die(f"no commits in {args.week}")

    dirs, dir_lines = Counter(), Counter()
    for c in commits:
        churn = c.get("insertions", 0) + c.get("deletions", 0)
        for d in {"/".join(p.split("/")[:2]) if p.count("/") > 1 else p.split("/")[0]
                  for p in c.get("paths", [])}:
            dirs[d] += 1
            dir_lines[d] += churn

    print(f"# {args.week} — where the work went ({len(commits)} mainline commits)\n")
    print("## Directories by commits touching them\n")
    print(f"{'dir':<42} {'commits':>8} {'share':>7} {'lines':>10}")
    for d, n in dirs.most_common(18):
        print(f"{d:<42} {n:>8} {n / len(commits):>6.0%} {dir_lines[d]:>10,}")

    # PRs are already a human grouping of work -- the best hypothesis seed there
    # is, because someone decided those commits belonged together and wrote why.
    prs = {p["number"]: p for p in (w.get("pr_details") or [])}
    by_pr = defaultdict(list)
    for c in commits:
        for n in _commit_prs(c):
            if n in prs:
                by_pr[n].append(c)
    print(f"\n## Merged PRs, largest first — read these titles for candidate themes\n")
    rows = sorted(prs.values(), key=lambda p: -p.get("body_chars", 0))
    for p in rows:
        hits = by_pr.get(p["number"], [])
        top = Counter("/".join(x.split("/")[:2]) if x.count("/") > 1 else x.split("/")[0]
                      for c in hits for x in c.get("paths", []))
        where = ", ".join(d for d, _ in top.most_common(3)) or "—"
        print(f"  #{p['number']:<3} {p.get('body_chars', 0):>6}ch  {p['title'][:62]:<64} {where}")

    # The subject artifacts this repo declares, and which of them the week moved.
    # Without this the altitude rule is a reminder: a commit log says what changed
    # in the repo, and only these say anything about the thing being evaluated.
    # A catchup that never opens them reports which files moved in an evaluation
    # rather than what the evaluation found.
    sub = (cfg or {}).get("subjects") or {}
    globs = [g for g in (sub.get("artifacts") or []) if str(g).strip()]
    if globs:
        # Ranked by how much each artifact MOVED, not alphabetically. A truncated
        # alphabetical list drops whatever sorts last, which is how the product-view
        # runs -- the ones carrying the actual product-level findings -- fell off
        # the end of this very list the first time it ran.
        churn = Counter()
        for c in commits:
            per = c.get("insertions", 0) + c.get("deletions", 0)
            paths = c.get("paths", [])
            share = per / max(1, len(paths))
            for p in paths:
                if any(fnmatch.fnmatch(p, g) for g in globs):
                    churn[p] += share
        # An artifact that was ADDED is a NEW SUBJECT, and outranks any amount of
        # churn on one that already existed. Ranking purely by size buries it:
        # a first conversation with a company is one small new file, while a
        # re-scored profile is a big edit, and under one size ranking the small
        # new file falls past the cut and is never opened. Two conversations
        # were lost exactly that way -- their artifacts sorted 26th and 31st,
        # their PR bodies were the two shortest of the week (the substance had
        # gone into the file), and nothing in the output said they existed.
        added = {p for p in ((w.get("structure") or {}).get("added") or [])
                 if any(fnmatch.fnmatch(p, g) for g in globs)}
        hits = sorted(churn, key=lambda p: (p not in added, -churn[p], p))
        print(f"\n## Subject artifacts this week touched — READ THESE for learnings\n")
        if sub.get("noun"):
            print(f"  (a subject here is {sub['noun']}; NEW subjects first, then most-changed)\n")
        shown, n_added = hits[:25], len(added)
        for p in shown:
            print(f"  {'NEW ' if p in added else '    '}{int(churn[p]):>7,}  {p}")
        if n_added:
            print(f"\n  {n_added} of these did not exist before this week. A new subject "
                  f"artifact is\n  a new subject: open every one, whatever its size.")
        if len(hits) > 25:
            missed = sum(1 for p in hits[25:] if p in added)
            tail = f"  … {len(hits) - 25} more, smaller"
            print(tail + (f" ({missed} of them NEW — raise the cap)" if missed else ""))
        if not hits:
            print("  none matched — either a quiet week for subjects, or the globs in")
            print("  `subjects.artifacts` no longer match where this repo keeps them.")
        if sub.get("read_first"):
            print(f"\n  Read first: {sub['read_first']}")
    else:
        print("\n## Subject artifacts\n")
        print("  This repo declares none. If it produces evaluations, research bundles or")
        print("  reports ABOUT something, list them under `subjects.artifacts` in config —")
        print("  they are where subject-level learnings come from, and commit logs are not.")

    print("\nNext: name 2-5 candidate themes from the clusters above, then test each with")
    print("`entities.py weigh` before writing a single one down. A candidate that cannot be")
    print("weighed is a hypothesis that failed, and that is a result worth recording.")


def cmd_weigh(args, repo, cfg, sdir):
    """Test one named theme hypothesis against the week's actual mass.

    This is the gate. A theme is an assertion that a real share of the week went
    somewhere, and until it is weighed it is an opinion -- which is how "22 files
    were deleted" once led a summary over a redesign touching 58% of the commits.
    """
    w = _week_from_pull(args.pull, args.week)
    commits = w.get("commits") or []
    paths = tuple(p.strip() for p in (args.paths or "").split(",") if p.strip())
    prs = {int(n) for n in (args.prs or "").replace("#", "").split(",") if n.strip().isdigit()}
    if not paths and not prs:
        die("give --paths and/or --prs to weigh")

    weight, hit = _weigh(commits, paths, prs)
    # A pattern that matches nothing is a typo, not a verdict. Surfaced before
    # the weight so it cannot be read as "the theme is too small".
    stray = _unmatched_patterns(commits, paths)
    weight["unmatched_patterns"] = stray
    if args.json:
        print(json.dumps(weight, indent=2))
        return
    if stray:
        print(f"  !! matched no file in this week: {', '.join(stray)}")
        print("     Check the pattern before believing the verdict below —")
        print("     these contributed nothing to the weight.\n")
    print(f"{args.week} · hypothesis: {args.label or '(unnamed)'}")
    print(f"  commits      {weight['commits']} of {len(commits)}  ({weight['share']:.0%} of the week)")
    print(f"  lines        {weight['lines']:,}  ({weight['line_share']:.0%} of the week's churn)")
    print(f"  PRs          {', '.join('#' + str(n) for n in weight['prs']) or '—'}")
    print(f"  active on    {len(weight['days'])} of 7 days")
    sh = theme_shares(cfg)
    verdict = ("CONFIRMED — big enough to lead" if weight["share"] >= sh["confirm"]
               else "THIN — real work, but supporting detail rather than a theme"
               if weight["share"] >= sh["thin"] else
               "DROPPED — too small to be a theme; record it as `dropped` so the "
               "hypothesis is not silently forgotten")
    print(f"  verdict      {verdict}")
    print(f"\n  the commits that carry it (largest first):")
    for c in sorted(hit, key=lambda c: -(c.get("insertions", 0) + c.get("deletions", 0)))[:12]:
        churn = c.get("insertions", 0) + c.get("deletions", 0)
        print(f"    {c['sha']}  {churn:>7,}  {c['subject'][:70]}")


def cmd_learned(args, repo, cfg, sdir):
    """Render the week's learnings as markdown, DERIVED from the concept fields.

    The section this produces used to be written by hand beside the entities,
    which meant two prose renderings of the same thing at the same length -- and
    no compression anywhere, because a paragraph in `note` gives a renderer
    nothing to compress. With claim/grade/so_what/open as fields, the markdown is
    a projection: the claim leads, the grade is a word rather than a clause, and
    everything that is not the learning is dropped.

    Ordered by evidence, strongest first. What was MEASURED should be read before
    what somebody put on a slide, and sorting by grade is the cheapest way to
    stop those two reading alike.
    """
    if not WEEK_RE.match(args.week or ""):
        die(f"week must look like 2026-W35, got {args.week!r}")
    ents = [e for e in load_all(sdir)
            if e.get("type") == "concept" and args.week in (e.get("weeks") or {})]
    if not ents:
        print(f"no concepts recorded for {args.week}")
        return

    grades, marks = grade_scale(cfg)

    def rank(e):
        g = (e["weeks"][args.week] or {}).get("grade")
        return (-(grades.index(g) if g in grades else -1), e["id"])

    graded = [e for e in ents if (e["weeks"][args.week] or {}).get("claim")]
    ungraded = [e for e in ents if not (e["weeks"][args.week] or {}).get("claim")]

    shown = sorted(graded, key=rank)
    held = []
    if args.top and len(shown) > args.top:
        # Cutting by grade, not by taste: what was MEASURED survives a trim and
        # what somebody asserted does not. The remainder is named, never dropped
        # silently, so the summary can say what it left in the store.
        #
        # The cut SNAPS TO A GRADE BOUNDARY rather than landing wherever N falls.
        # Inside one band the order is only a tiebreak, so slicing mid-band drops
        # findings for alphabetical reasons -- which is exactly how the week's
        # largest build lost its place to a sort key. `--top` is a target, and
        # the boundary wins.
        cut = args.top
        grade_at = lambda i: (shown[i]["weeks"][args.week] or {}).get("grade")
        while cut < len(shown) and grade_at(cut) == grade_at(cut - 1):
            cut += 1
        shown, held = shown[:cut], shown[cut:]

    for e in shown:
        w = e["weeks"][args.week]
        claim = (w.get("claim") or "").strip().rstrip(".")
        grade = w.get("grade")
        bits = []
        if w.get("so_what"):
            bits.append(w["so_what"].strip())
        if w.get("open") and not args.no_open:
            bits.append("**Open:** " + w["open"].strip())
        refs = ", ".join(f"#{p}" for p in (w.get("prs") or []))
        tail = f" ({refs})" if refs and not args.no_refs else ""
        mark = f" *[{marks.get(grade, grade)}]*" if grade else ""
        print(f"- **{claim}.**{mark} " + " ".join(bits) + tail)
    if held:
        print()
        by_grade = Counter((e["weeks"][args.week] or {}).get("grade") for e in held)
        tally = ", ".join(f"{by_grade[g]} {g}" for g in reversed(grades) if by_grade.get(g))
        print(f"*{len(held)} more concepts stay in the store and not here ({tally}): "
              + ", ".join(f"`{e['id']}`" for e in held) + ".*")
    if not args.no_refs:
        print()
        counts = Counter((e["weeks"][args.week] or {}).get("grade") for e in graded)
        line = " · ".join(f"{counts[g]} {g}" for g in reversed(grades) if counts.get(g))
        print(f"*{len(graded)} of {len(ents)} concepts carry a graded claim — {line}.*")
    if ungraded:
        # Never emit an empty bullet for one. A concept that is prose-only is a
        # concept nothing can compress, which is the whole failure this command
        # exists to make visible -- so it is reported as a gap, by name.
        print(f"\n<!-- {len(ungraded)} concept(s) carry prose but no claim/grade and are "
              f"NOT rendered above: {', '.join(sorted(e['id'] for e in ungraded))} -->",
              file=sys.stderr)


def cmd_render(args, repo, cfg, sdir):
    """The whole summary, derived: Themes, Meetings & Notes, What we learned.

    Three sections because a reader asks three different questions -- what moved,
    who did we meet, what do we now know -- and they rank on different axes.
    Themes rank by WEIGHT, learnings by evidence GRADE. Running them on one scale
    is what let a 4-commit test fix outrank a redesign carrying 80% of the week's
    churn: forensic findings grade `measured` trivially, and grade was standing in
    for importance.

    Dropped theme hypotheses land in `Other`, one line each. They are kept because
    "we thought X was a theme and it was four commits" is a real result about the
    week, and deleting it hides that the question was asked.
    """
    if not WEEK_RE.match(args.week or ""):
        die(f"week must look like 2026-W35, got {args.week!r}")
    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    if not ents:
        die(f"no entities recorded for {args.week}")
    here = lambda e: e["weeks"][args.week]

    themes = [e for e in ents if e.get("type") == "theme"]
    live = [t for t in themes if (here(t) or {}).get("disposition", "confirmed") == "confirmed"]
    dropped = [t for t in themes if (here(t) or {}).get("disposition") in ("dropped", "merged")]
    live.sort(key=lambda t: -((here(t).get("weight") or {}).get("share") or 0))

    print("## Themes\n")
    for t in live:
        w = here(t)
        wt = w.get("weight") or {}
        share = f"{wt.get('share', 0):.0%} of the week's commits"
        churn = f" · {wt['line_share']:.0%} of its churn" if wt.get("line_share") else ""
        print(f"### {t['title']}  ·  {share}{churn}\n")
        print(w["moved"].strip() + "\n")
        print(f"**Why it matters:** {w['why_it_matters'].strip()}\n")
        kids = [e for e in ents if e.get("theme") == t["id"] and e is not t]
        for k in sorted(kids, key=lambda e: e["id"]):
            mark = " *(correction)*" if k.get("type") == "correction" else ""
            note = " ".join(here(k).get("note", "").split())
            # A theme child says what changed, in a line. When it runs long it is
            # usually because a finding crept in, and the finding belongs in
            # Learnings -- so the overflow is flagged rather than printed.
            if len(note) > CHILD_NOTE_CHARS:
                cut = note[:CHILD_NOTE_CHARS].rsplit(" ", 1)[0]
                note = cut + f" …[{len(note) - len(cut)} chars trimmed — if this is a finding, it belongs in Learnings]"
            print(f"- **{k['title']}**{mark} — {note}")
        if kids:
            print()

    meets = [e for e in ents if e.get("type") in ("meeting", "org", "person")]
    if meets:
        print("## Meetings & Notes\n")
        # Meetings lead and run in DATE order -- the section's whole contract is
        # "who did we meet, in what order", and an id sort renders a week of
        # conversations alphabetically by company, which is not a chronology of
        # anything. Undated meetings sort last rather than to the top, so a
        # missing date is visible instead of silently leading the section.
        def meet_key(e):
            if e.get("type") == "meeting":
                return (0, here(e).get("date") or "9999-99-99", e["id"])
            return (1, e.get("type"), e["id"])

        # WHO WAS ACTUALLY MET is derived from the meeting entities, never
        # asserted on the person. A person tracked because the repo researched
        # them and a person tracked because someone sat down with them are
        # different relationships, and rendering them identically turns a
        # roster into a claim of contact nobody made -- three founders of one
        # company were listed beside the people they had never met, on a deal
        # whose own notes said no contact had happened yet. Deriving it from the
        # meeting's own attendee list means the two cannot drift: to mark
        # someone met, record the meeting.
        # A meeting tagged `prep` is a note written BEFORE the room, and it is
        # not evidence anyone was in it. Counting it as contact is the same
        # error one level down: the artifact exists, so the meeting is assumed
        # to have happened and gone the way the prep imagined. It stays a
        # separate state until the note is updated with what actually occurred.
        all_meetings = [x for x in ents if x.get("type") == "meeting"]
        met_on, prepped = {}, {}
        for m in all_meetings:
            is_prep = "prep" in (m.get("tags") or [])
            for wk in (m.get("weeks") or {}).values():
                d = wk.get("date") or ""
                for pid in (wk.get("attendees") or []):
                    tgt = prepped if is_prep else met_on
                    tgt[pid] = max(tgt.get(pid, ""), d)
        def contact(e):
            if e.get("type") != "person":
                return ""
            if e["id"] in met_on:
                d = met_on[e["id"]]
                return f" *(met{' ' + d if d else ''})*"
            if e["id"] in prepped:
                d = prepped[e["id"]]
                return f" *(meeting prepped{' for ' + d if d else ''} — outcome unrecorded)*"
            # Before a meeting exists there is nothing to derive from, so the
            # pre-contact states come from the person's own tags. That is not
            # the assertion this guards against: the danger is claiming someone
            # was MET without a meeting to show for it. Saying an email went out
            # cannot overstate contact in that direction, and the distinction
            # between a live thread and a cold name is the one a relationship
            # repo most needs -- an open intro is exactly the thing that
            # quietly expires.
            tags = set(e.get("tags") or [])
            if "meeting-upcoming" in tags:
                return " *(contacted — meeting upcoming)*"
            if "contacted" in tags:
                return " *(contacted — not met)*"
            return " *(tracked — no contact)*"

        # ONE ENTRY PER CONVERSATION, synthesised -- not one bullet per entity.
        #
        # The store keeps meeting, org and person apart because each accumulates
        # across weeks and they are genuinely different records. The SUMMARY is
        # a view, and printing all three verbatim tells the same conversation
        # three times: the meeting narrates it, the company restates it as
        # company state, and the person restates it again as what they are like.
        # Grouping them under a shared parent fixed the layout and not the
        # redundancy -- a company still appeared twice inside its own group,
        # once as the meeting and once as the company, saying nearly the same
        # thing. The fix is not more nesting: it is that the meeting's `note`
        # must be the synthesis, and what the company and the people
        # contributed belongs inside it.
        #
        # What a reader actually needs from a conversation is three things --
        # who was in it, the one thing that came out, and what is now owed or
        # still to ask. The last of those is the part that expires, and it was
        # the part being dropped while three overlapping narrations were kept.
        def body(e):
            # `summary` defaults to `note` at write time when none is given, so
            # printing both renders the same paragraph twice. The standing
            # description leads when there IS one; otherwise the week's note is
            # the whole entry.
            s = " ".join((e.get("summary") or "").split())
            n = " ".join(here(e).get("note", "").split())
            if s and (s == n or n.startswith(s)):
                s = ""
            return " ".join(x for x in (s, n) if x)

        def actions(e):
            w = here(e)
            for label, key in (("Owed", "owed"), ("Ask", "asks")):
                items = [" ".join(str(i).split()) for i in (w.get(key) or [])]
                if items:
                    print(f"  - **{label}:** " + " · ".join(items))

        done, by_id = set(), {x["id"]: x for x in ents}

        def linked(seed, kind):
            return sorted((x for x in meets
                           if x.get("type") == kind and x["id"] not in done
                           and (x["id"] in (seed.get("links") or [])
                                or seed["id"] in (x.get("links") or []))),
                          key=lambda x: x["id"])

        # Conversations, in date order. The company and the humans in the room
        # are absorbed into the entry rather than re-listed under it.
        for m in sorted((x for x in meets if x.get("type") == "meeting"), key=meet_key):
            done.add(m["id"])
            orgs = linked(m, "org")
            for o in orgs:
                done.add(o["id"])
            for o in orgs:
                for person in linked(o, "person"):
                    done.add(person["id"])
            for person in linked(m, "person"):
                done.add(person["id"])
            print(f"- **{m['title']}** — {body(m)}")
            actions(m)

        # Companies nobody sat down with. Their people become a contact clause
        # rather than bullets of their own -- someone unmet on live work
        # is an action item, not a profile.
        for o in sorted((x for x in meets if x.get("type") == "org" and x["id"] not in done),
                        key=lambda x: x["id"]):
            done.add(o["id"])
            folk = linked(o, "person")
            for person in folk:
                done.add(person["id"])
            note = f"- **{o['title']}** — {body(o)}"
            if folk:
                who = " · ".join(f"{x['title'].split(' — ')[0].split(',')[0]}"
                                 f"{contact(x).replace(' *(', ' (').replace(')*', ')')}"
                                 for x in folk)
                note += f" **Who:** {who}."
            print(note)
            actions(o)

        # Anyone attached to neither -- a network contact with no company here.
        for e in sorted((x for x in meets if x["id"] not in done), key=lambda x: x["id"]):
            done.add(e["id"])
            print(f"- **{e['title']}**{contact(e)} — {body(e)}")
            actions(e)
        print()

    concepts = [e for e in ents if e.get("type") == "concept" and here(e).get("claim")]
    if concepts:
        grades, marks = grade_scale(cfg)
        rank = lambda e: (-(grades.index(here(e).get("grade")) if here(e).get("grade") in grades else -1), e["id"])
        print("## What we learned\n")
        shown = sorted(concepts, key=rank)
        held = []
        if args.learnings_top and len(shown) > args.learnings_top:
            shown, held = shown[:args.learnings_top], shown[args.learnings_top:]
        for e in shown:
            w = here(e)
            mark = marks.get(w.get("grade"), w.get("grade"))
            bits = [w["so_what"].strip()] if w.get("so_what") else []
            if w.get("open") and not args.no_open:
                bits.append("**Open:** " + w["open"].strip())
            refs = ", ".join(f"#{p}" for p in (w.get("prs") or []))
            tail = f" ({refs})" if refs else ""
            subj = f"*{w['subject']}* · " if w.get("subject") else ""
            print(f"- **{w['claim'].strip().rstrip('.')}.** *[{mark}]* {subj}"
                  + " ".join(bits) + tail)
        if held:
            # Named, never silently dropped -- a learning cut for length is still
            # a thing the week established, and the store is where it lives.
            subjects = []
            for e in held:
                sub = (here(e).get("subject") or e["id"])
                if sub not in subjects:
                    subjects.append(sub)
            print(f"\n*{len(held)} more learnings are in the store and not here, on "
                  + ", ".join(subjects) + ".*")
        print()

    other = [e for e in ents if e.get("type") in ("decision", "other")
             and not e.get("theme")]
    if dropped or other:
        print("## Other\n")
        for t in dropped:
            w = here(t)
            wt = w.get("weight") or {}
            why = (f"{wt.get('commits', 0)} commits, {wt.get('line_share', 0):.0%} of the week's churn"
                   if wt else "not weighed")
            print(f"- *Considered as a theme and dropped* — **{t['title']}**: {why}. "
                  + (w.get("moved") or "").strip())
        for e in sorted(other, key=lambda e: e["id"]):
            print(f"- **{e['title']}** — {here(e).get('note', '').strip()}")
        print()

    # Derived, not written. See stat_line().
    wpath = os.path.join(weeks_dir(repo, cfg), f"{args.week}.json")
    if os.path.isfile(wpath):
        try:
            with open(wpath) as fh:
                line = stat_line(cfg, json.load(fh), ents, args.week)
            if line:
                print("---")
                print(line)
        except (json.JSONDecodeError, OSError):
            pass


# What a stat line reports when a repo has not said. Mechanical facts only --
# every repo has commits and PRs, and no repo's DOMAIN counts can be guessed.
DEFAULT_STATS = [
    {"label": "commits", "from": "stats.commits"},
    {"label": "PRs merged", "from": "stats.prs_merged"},
    {"label": "entities", "singular": "entity", "count": {}},
    {"label": "bookkeeping commits excluded", "from": "stats.ignored"},
]


def _dig(blob, path):
    """Resolve a dotted path like `stats.prs_merged` against the week record."""
    cur = blob
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _count_entities(ents, week, spec):
    """How many of this week's entities match a stat spec.

    `new` means first seen THIS week, which is the difference between "how many
    relationships exist" and "how many did this week add" -- two different
    questions that a single count silently conflates.
    """
    n = 0
    for e in ents:
        if spec.get("type") and e.get("type") != spec["type"]:
            continue
        if spec.get("category") and e.get("category") != spec["category"]:
            continue
        if spec.get("tag") and spec["tag"] not in (e.get("tags") or []):
            continue
        if spec.get("status") and e.get("status") != spec["status"]:
            continue
        if spec.get("new") and min(e.get("weeks") or {week: 1}) != week:
            continue
        n += 1
    return n


def stat_line(cfg, record, ents, week):
    """The stat line, DERIVED.

    It used to be prose the writer composed, and two repos running the same
    skill reported different things from identical week records -- not because
    their data differed but because two sessions picked different fields. The
    stat line is the one part of a summary meant to be mechanically checkable,
    so composing it by hand is exactly backwards.

    What a repo counts is genuinely its own, though: commits and PRs are
    universal, and `events`, `deals`, `learnings` or `people met` are not. So
    the FIELDS are declared per repo in `summary.stats` and the ARITHMETIC is
    done here.
    """
    spec = ((cfg.get("summary") or {}).get("stats")) or DEFAULT_STATS
    parts = []
    for item in spec:
        if not isinstance(item, dict) or item.get("label", "").startswith("$"):
            continue
        label = item.get("label") or "?"
        if "from" in item:
            val = _dig(record, item["from"])
        elif "count" in item:
            val = _count_entities(ents, week, item.get("count") or {})
        else:
            continue
        if val is None:
            continue
        # "1 events" reads as a typo and undermines a line whose whole job is to
        # look mechanically exact. `singular` is opt-in because no rule guesses
        # right -- stripping an "s" would turn "bookkeeping commits excluded"
        # into nonsense.
        if val == 1 and item.get("singular"):
            label = item["singular"]
        val = f"{val:,}" if isinstance(val, int) else str(val)
        parts.append(f"{val} {label}")
    return "*Stats: " + " · ".join(parts) + ".*" if parts else ""


def cmd_stat_line(args, repo, cfg, sdir):
    """Print the derived stat line for one week."""
    wpath = os.path.join(weeks_dir(repo, cfg), f"{args.week}.json")
    if not os.path.isfile(wpath):
        die(f"no week record at {os.path.relpath(wpath, repo)} -- run `record-week` first")
    with open(wpath) as fh:
        record = json.load(fh)
    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    line = stat_line(cfg, record, ents, args.week)
    if not line:
        die("no stats resolved -- check `summary.stats` in config")
    print(line)


def cmd_check_summary(args, repo, cfg, sdir):
    """Every citation in the week's prose must be carried by some entity.

    The format's core claim is that the entities are the record and the summary
    is a rendering of them -- so anything the prose can cite that the store
    cannot is a rendering of something else. W35 is what that looks like in
    practice: seventeen PR numbers in the prose, seven in the entities, twelve
    belonging to neither. The summary read fine, and re-generating it from the
    store would have quietly lost every one of them.

    Deliberately one-directional. An entity the summary chose not to mention is
    editing; a citation the store cannot back is drift.
    """
    if not WEEK_RE.match(args.week or ""):
        die(f"week must look like 2026-W35, got {args.week!r}")
    out = (cfg.get("output") or {}).get("dir", DEFAULT_OUTPUT_DIR)
    path = os.path.join(repo, out, f"{args.week}.md")
    if not os.path.isfile(path):
        die(f"no summary at {os.path.relpath(path, repo)}")
    prose = open(path).read()

    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    held_prs, held_shas = set(), set()
    for e in ents:
        entry = e["weeks"][args.week]
        held_prs |= {int(p) for p in (entry.get("prs") or [])}
        held_shas |= {str(s) for s in (entry.get("commits") or [])}

    # Only the citation forms the template defines: `(#NN)` groups, and the
    # `PRs merged:` line. A bare `#NN` mid-sentence is prose -- W35 says a
    # benchmark came "rank #1", and #1 is also a real PR in this repo, so no
    # amount of cross-checking against GitHub separates the two. The format
    # decides what a citation looks like; the check follows the format.
    cited_prs = set()
    for group in re.findall(r"\(([^()]*)\)", prose):
        cited_prs |= {int(n) for n in re.findall(r"#(\d+)", group)}
    for line in prose.splitlines():
        if line.strip().lower().startswith("prs merged:"):
            cited_prs |= {int(n) for n in re.findall(r"#(\d+)", line)}
    # A sha needs a digit: `defaced` is seven characters of valid hex.
    cited_shas = {s for s in re.findall(r"\b[0-9a-f]{7,40}\b", prose)
                  if any(c.isdigit() for c in s)}

    problems = []
    for n in sorted(cited_prs - held_prs):
        problems.append(f"PR #{n} is cited in the summary but carried by no entity")
    for s in sorted(cited_shas):
        if not any(h.startswith(s) or s.startswith(h) for h in held_shas):
            problems.append(f"commit {s} is cited in the summary but carried by no entity")

    if problems:
        print(f"{args.week}: {len(problems)} citation(s) the entity store cannot back:")
        for p in problems:
            print("  " + p)
        print("\nAdd the missing entities — do not delete the citations.")
        sys.exit(1)
    print(f"ok — {args.week}: every citation in the summary is carried by an entity "
          f"({len(cited_prs)} PRs, {len(cited_shas)} shas, {len(ents)} entities)")


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

    p = sub.add_parser("validate", parents=[common],
                       help="schema-check the store, and verify its provenance")
    p.add_argument("--no-gh", action="store_true",
                   help="skip the PR-week check (offline, or no gh)")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("propose", parents=[common],
                       help="cluster the week so the theme hypothesis starts from data")
    p.add_argument("week")
    p.add_argument("--pull", help="pull_week.py JSON, or - for stdin")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("weigh", parents=[common],
                       help="test one theme hypothesis against the week's mass")
    p.add_argument("week")
    p.add_argument("--pull", help="pull_week.py JSON, or - for stdin")
    p.add_argument("--paths", help="comma-separated path globs or prefixes")
    p.add_argument("--prs", help="comma-separated PR numbers")
    p.add_argument("--label", help="what you are calling this hypothesis")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_weigh)

    p = sub.add_parser("learned", parents=[common],
                       help="the week's learnings as markdown, derived from the concept fields")
    p.add_argument("week")
    p.add_argument("--no-refs", action="store_true", help="omit PR refs and the grade tally")
    p.add_argument("--top", type=int, metavar="N",
                   help="strongest N by evidence grade; the rest are named, not dropped")
    p.add_argument("--no-open", action="store_true",
                   help="omit the `open` clause — the store keeps it, a length-bound summary may not")
    p.set_defaults(fn=cmd_learned)

    p = sub.add_parser("render", parents=[common],
                       help="the whole summary, derived: Themes / Meetings / Learnings / Other")
    p.add_argument("week")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--learnings-top", type=int, metavar="N",
                   help="strongest N learnings by grade; the rest are named, not dropped")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("check-summary", parents=[common],
                       help="every citation in the week's prose is carried by an entity")
    p.add_argument("week")
    p.set_defaults(fn=cmd_check_summary)

    p = sub.add_parser("stat-line", parents=[common],
                       help="print the derived stat line for a week")
    p.add_argument("week")
    p.set_defaults(fn=cmd_stat_line)

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
