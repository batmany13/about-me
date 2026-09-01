#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
DeepVista bridge -- render catchup entities as context cards. PROTOTYPE.

DeepVista's own model is the reason this shape works: "Context card captures
entities. Every team member, customer, meeting note, file, and session is stored
within a context card." So the mapping is one entity to one card -- not one card
per week and not one per bullet. A thread running four weeks stays ONE card that
accumulates, which is the same thing the entity store does locally.

Transport is the hosted MCP server at https://api.deepvista.ai/mcp. MCP tools are
called by the model, not by a shell script, so this script does the half a script
can do deterministically: decide create vs update vs skip, render the card body,
and record the returned card id. The model makes the actual tool calls in between.

    plan  ->  [model calls the deepvista MCP tools]  ->  record

Skipping matters. The free tier is 100 credits a month, so an entity whose
content has not changed since its last push must cost nothing: `plan` compares a
content hash and emits `skip` for anything unchanged.

Usage:
    deepvista_cards.py plan --week 2026-W35
    deepvista_cards.py plan --all --category meeting
    deepvista_cards.py plan --week 2026-W35 --show-body    # eyeball the markdown
    deepvista_cards.py record --id ray-summit --card-id abc-123
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entities import (  # noqa: E402
    CATEGORY_ORDER, category_titles, content_hash, die, entity_path,
    load_all, load_config, store_dir, write_entity,
)

MCP_ENDPOINT = "https://api.deepvista.ai/mcp"

# Entity type -> DeepVista card_type. The right-hand side is DeepVista's fixed
# vocabulary (from the CLI's CARD_TYPES), not ours, so the mapping is lossy on
# purpose: `meeting` has no card type of its own and lands on `note`, which is
# what the docs' own "meeting note" example does.
CARD_TYPE = {
    "meeting": "note",
    "person": "person",
    "org": "organization",
    "thread": "topic",
    "decision": "keypoint",
    "correction": "keypoint",
    # A theme is an ongoing subject that accumulates weekly notes, which is what
    # `topic` is for. A concept is a point of knowledge with a claim and a grade,
    # which is `keypoint`. Both were missing here and fell through to the generic
    # `note` default -- so the two types the format is actually built around were
    # the two arriving in DeepVista untyped.
    "theme": "topic",
    "concept": "keypoint",
    "other": "note",
}


def render_body(e, titles, repo_label):
    """The card's markdown body.

    Carries the full week-by-week timeline, not just the current summary. That is
    deliberate: the point of pushing entities rather than a finished writeup is
    that the cards should hold enough for DeepVista to compose a catchup itself.
    A card that only said "here is the latest" could not.
    """
    weeks = sorted(e.get("weeks") or {})
    lines = [e.get("summary", "").strip(), ""]

    latest = (e.get("weeks") or {}).get(sorted(e.get("weeks") or {})[-1], {}) if e.get("weeks") else {}
    meta = [
        f"**Category:** {titles.get(e.get('category'), e.get('category'))}",
        f"**Type:** {e.get('type')}",]
    if latest.get("subject"):
        meta.append(f"**Subject:** {latest['subject']}")
    meta += [
        f"**Status:** {e.get('status')}",
        f"**Source:** {repo_label}",
    ]
    if weeks:
        span = weeks[0] if len(weeks) == 1 else f"{weeks[0]} → {weeks[-1]}"
        meta.append(f"**Active:** {span} ({len(weeks)} week{'s' if len(weeks) != 1 else ''})")
    lines += [" · ".join(meta), ""]

    lines.append("## Timeline")
    lines.append("")
    for w in weeks:
        blk = e["weeks"][w]
        head = f"### {w}"
        if blk.get("date"):
            head += f" — {blk['date']}"
        lines.append(head)

        # The structured fields FIRST, because they are the entity. This renderer
        # predates them and emitted only `note`, so a theme's weight, what moved
        # and why it matters -- and a learning's whole claim/grade/so_what/open --
        # never reached the card at all. What arrived was the footnote.
        if blk.get("moved"):
            lines.append(blk["moved"].strip())
        if blk.get("why_it_matters"):
            lines.append("")
            lines.append(f"**Why it matters:** {blk['why_it_matters'].strip()}")
        wt = blk.get("weight") or {}
        if wt.get("share") is not None:
            bits = [f"{wt['share']:.0%} of the week's commits"]
            if wt.get("line_share") is not None:
                bits.append(f"{wt['line_share']:.0%} of its churn")
            if wt.get("commits"):
                bits.append(f"{wt['commits']} commits")
            lines.append("")
            lines.append("**Weight:** " + " · ".join(bits))
        if blk.get("evidence"):
            lines.append("")
            lines.append("**Evidence:**")
            lines += [f"- {x}" for x in blk["evidence"]]

        if blk.get("claim"):
            grade = blk.get("grade")
            lines.append(f"**Claim:** {blk['claim'].strip()}"
                         + (f"  *[{grade}]*" if grade else ""))
        if blk.get("so_what"):
            lines.append("")
            lines.append(blk["so_what"].strip())
        if blk.get("open"):
            lines.append("")
            lines.append(f"**Open:** {blk['open'].strip()}")

        if blk.get("note"):
            lines.append("")
            lines.append(blk["note"].strip())
        ev = []
        if blk.get("people"):
            ev.append("People: " + ", ".join(blk["people"]))
        if blk.get("prs"):
            ev.append("PRs: " + ", ".join(f"#{p}" for p in blk["prs"]))
        if blk.get("commits"):
            ev.append("Commits: " + ", ".join(blk["commits"][:8])
                      + (f" (+{len(blk['commits']) - 8} more)" if len(blk["commits"]) > 8 else ""))
        if blk.get("paths"):
            ev.append("Paths: " + ", ".join(f"`{p}`" for p in blk["paths"][:6]))
        if ev:
            lines.append("")
            lines += [f"- {x}" for x in ev]
        lines.append("")

    if e.get("links"):
        lines.append("## Related")
        lines.append("")
        lines += [f"- `{l}`" for l in e["links"]]
        lines.append("")

    lines.append(f"<!-- catchup-entity: {e['id']} -->")
    return "\n".join(lines).strip() + "\n"


def build_tags(e, cfg, repo_label):
    dv = (cfg.get("deepvista") or {})
    tags = set(dv.get("tags") or ["catchup"])
    tags.add(f"repo:{repo_label}")
    tags.add(f"category:{e.get('category')}")
    tags.add(f"entity:{e['id']}")
    tags.update(e.get("tags") or [])
    return sorted(t for t in tags if t)


def cmd_plan(args, repo, cfg, sdir):
    ents = load_all(sdir)
    if args.week:
        ents = [e for e in ents if args.week in (e.get("weeks") or {})]
    elif not args.all:
        die("pass --week YYYY-WNN or --all")
    if args.category:
        ents = [e for e in ents if e.get("category") == args.category]
    if args.status:
        ents = [e for e in ents if e.get("status") == args.status]

    titles = category_titles(cfg)
    dv_cfg = cfg.get("deepvista") or {}
    repo_label = (cfg.get("repo") or {}).get("label") or os.path.basename(repo)
    type_map = dict(CARD_TYPE, **(dv_cfg.get("card_types") or {}))

    plan, counts = [], {"create": 0, "update": 0, "skip": 0}
    for e in sorted(ents, key=lambda x: (CATEGORY_ORDER.index(x.get("category", "other"))
                                         if x.get("category") in CATEGORY_ORDER else 9, x["id"])):
        dv = e.get("deepvista") or {}
        h = content_hash(e)
        if dv.get("card_id") and dv.get("content_hash") == h and not args.force:
            action = "skip"
        elif dv.get("card_id"):
            action = "update"
        else:
            action = "create"
        counts[action] += 1
        if action == "skip" and not args.include_skipped:
            continue

        item = {
            "action": action,
            "entity_id": e["id"],
            "card_id": dv.get("card_id"),
            "content_hash": h,
            "card": {
                "card_type": type_map.get(e.get("type"), "note"),
                "title": e["title"],
                "description": render_body(e, titles, repo_label),
                "tags": build_tags(e, cfg, repo_label),
                # Agent-created cards default to `unconfirmed`, and unconfirmed
                # cards are filtered out of search -- so a card pushed without
                # this is invisible in the product it was pushed to.
                "status": dv_cfg.get("card_status", "confirmed"),
            },
        }
        if not args.show_body:
            # A preview, and named as one. This used to overwrite `description`
            # in place with 280 characters plus a "[truncated]" marker, while the
            # `next` line said to call the tool with `card` -- so following the
            # instruction as written pushed a truncated body, with the marker
            # text in it, into the product. The full body only ever lives under
            # --show-body, so the preview now sits in its own key and `card` is
            # never a payload the plan has quietly altered.
            body = item["card"].pop("description")
            item["card_body_preview"] = body[:280].rstrip() + " …"
            item["card_body_lines"] = body.count("\n") + 1
        plan.append(item)
        if args.limit and len(plan) >= args.limit:
            break

    ready = args.show_body
    print(json.dumps({
        "endpoint": MCP_ENDPOINT,
        "limited_to": args.limit or None,
        "repo": repo_label,
        "week": args.week,
        "project_id": dv_cfg.get("project_id"),
        "enabled": dv_cfg.get("enabled", False),
        "counts": counts,
        "pushable": ready,
        "plan": plan,
        "next": (
            "For each item call the DeepVista MCP create/update card tool with `card`, "
            "then run: deepvista_cards.py record --id <entity_id> --card-id <returned id>"
            if ready else
            "PREVIEW ONLY — `card` here has no `description`, so it is not a payload. "
            "Re-run with --show-body to get the full card bodies before pushing anything."),
    }, indent=2))


def cmd_record(args, repo, cfg, sdir):
    p = entity_path(sdir, args.id)
    if not os.path.isfile(p):
        die(f"no such entity: {args.id}")
    with open(p) as fh:
        e = json.load(fh)
    e.setdefault("deepvista", {})
    e["deepvista"]["card_id"] = args.card_id
    e["deepvista"]["synced_at"] = utc_now()
    # Hash the entity WITHOUT the deepvista block, matching plan's comparison.
    e["deepvista"]["content_hash"] = content_hash(e)
    write_entity(sdir, e)
    print(json.dumps({"id": args.id, "card_id": args.card_id,
                      "content_hash": e["deepvista"]["content_hash"],
                      "synced_at": e["deepvista"]["synced_at"]}, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", dest="repo_sub", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", parents=[common], help="decide create/update/skip and render card bodies")
    p.add_argument("--week")
    p.add_argument("--all", action="store_true")
    p.add_argument("--category", choices=CATEGORY_ORDER)
    p.add_argument("--status")
    p.add_argument("--force", action="store_true", help="re-push even if unchanged")
    p.add_argument("--show-body", action="store_true", help="full markdown, not truncated")
    p.add_argument("--include-skipped", action="store_true")
    p.add_argument("--limit", type=int, default=0,
                   help="plan at most N items — use --limit 1 for a first live push")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("record", parents=[common], help="write back the card id after an MCP call")
    p.add_argument("--id", required=True)
    p.add_argument("--card-id", required=True)
    p.set_defaults(fn=cmd_record)

    args = ap.parse_args()
    repo = os.path.abspath(os.path.expanduser(args.repo_sub or args.repo))
    cfg = load_config(repo)
    args.fn(args, repo, cfg, store_dir(repo, cfg))


if __name__ == "__main__":
    main()
