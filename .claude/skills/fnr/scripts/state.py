#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
FNR state -- the one-question-at-a-time weekly, resumable across sessions.

The weekly is a short state machine: the machine writes a complete draft, then
asks the owner one question per turn, and each answer is written straight
into the public file. This file is the memory of that conversation, so a
session that ends after question two picks up at question three tomorrow,
under Claude or Codex alike.

    fnr/.private/drafts/<W>.state.json

The sections, which blocks are the owner's, which are required, and the
question asked for each are declared in the PRIVATE config
(`fnr/.private/fnr.config.json`) -- nothing here names a section. Blocks the
owner may write are marked in the public file:

    <!-- fnr:blurb -->
    ...machine default, or the owner's words...
    <!-- /fnr:blurb -->

`paste` writes every answered block back between its markers, byte for byte,
so a re-render can never overwrite what the owner wrote. The machine never
edits an answered block; the only way to change one is another `answer`.

Usage:
    state.py init 2026-W36 [--without <key>] [--config fnr/.private/fnr.config.json]
    state.py next 2026-W36                     # the next pending question, or "done"
    state.py answer 2026-W36 blurb --file a.md # the owner's words, verbatim
    state.py answer 2026-W36 blurb --keep      # the machine text stands
    state.py answer 2026-W36 next --skip       # not answered; machine text stands
    state.py paste 2026-W36 fnr/2026-W36.md    # write answered blocks into the file
    state.py check 2026-W36 fnr/2026-W36.md    # every answered block is in the file, unchanged
    state.py show 2026-W36
    state.py publish 2026-W36 --decision publish|hold
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

STATUSES = ("pending", "answered", "kept", "skipped")
DEFAULT_STATE_DIR = os.path.join("fnr", ".private", "drafts")
DEFAULT_CONFIG = os.path.join("fnr", ".private", "fnr.config.json")

# Which blocks exist, their order, and which are required come from the
# PRIVATE config, never from this file: the section titles and the questions
# are the owner's, and this script is committed to a public repo.


def read_config(path):
    if not os.path.isfile(path):
        die(f"no fnr config at {path} -- the blocks and questions live in the private repo")
    with open(path) as fh:
        cfg = json.load(fh)
    blocks = [s for s in (cfg.get("sections") or []) if s.get("owner") == "owner" and s.get("key")]
    if not blocks:
        die(f"{path}: no owner blocks declared under `sections`")
    return cfg, blocks


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def path_for(args):
    return os.path.join(args.state_dir, f"{args.week}.state.json")


def load(args):
    p = path_for(args)
    if not os.path.isfile(p):
        die(f"no state at {p} -- run `state.py init {args.week}` first")
    with open(p) as fh:
        return json.load(fh)


def save(args, st):
    st["updated"] = now()
    p = path_for(args)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def cmd_init(args):
    p = path_for(args)
    if os.path.isfile(p):
        print(f"exists: {p}")
        return
    _, blocks = read_config(args.config)
    without = set(args.without or [])
    order = [b["key"] for b in blocks if b["key"] not in without]
    required = sorted(b["key"] for b in blocks if b.get("required") and b["key"] in order)
    st = {
        "week": args.week,
        "started": now(),
        "config": args.config,
        "order": order,
        "required": required,
        "questions": {k: {"status": "pending", "text": None, "at": None} for k in order},
        "publish": "pending",
    }
    save(args, st)
    print(f"wrote {p} -- {len(order)} questions, required: {', '.join(required) or 'none'}")


def cmd_next(args):
    st = load(args)
    for k in st["order"]:
        if st["questions"][k]["status"] == "pending":
            print(k)
            return
    # Every question has a status. The required ones must be ANSWERED, not
    # skipped -- skip is refused for them in `answer`, so this is a belt.
    for k in st.get("required") or []:
        if k in st["questions"] and st["questions"][k]["status"] != "answered":
            print(k)
            return
    print("done" if st["publish"] != "pending" else "publish")


def cmd_answer(args):
    st = load(args)
    k = args.key
    if k not in st["questions"]:
        die(f"unknown question {k!r}; this week's are {', '.join(st['order'])}")
    q = st["questions"][k]
    if args.keep:
        q.update(status="kept", text=None, at=now())
    elif args.skip:
        if k in (st.get("required") or []):
            die(f"{k} is required -- it cannot be skipped. Answer it, or stop here; the draft is saved.")
        q.update(status="skipped", text=None, at=now())
    else:
        text = open(args.file).read() if args.file else (args.text or "")
        text = text.strip("\n")
        if not text.strip():
            die("an answer needs text (--file or --text), or --keep / --skip")
        q.update(status="answered", text=text, at=now())
    save(args, st)
    print(f"{k}: {q['status']}")


_MARK = re.compile(r"<!-- fnr:(\w+) -->\n(.*?)\n<!-- /fnr:\1 -->", re.S)


def cmd_paste(args):
    st = load(args)
    src = open(args.file).read()
    found = {m.group(1) for m in _MARK.finditer(src)}
    missing = [k for k in st["order"] if k not in found]
    if missing:
        die(f"{args.file} has no markers for: {', '.join(missing)} -- the public file must carry every block")

    def sub(m):
        k = m.group(1)
        q = st["questions"].get(k)
        if q and q["status"] == "answered":
            return f"<!-- fnr:{k} -->\n{q['text']}\n<!-- /fnr:{k} -->"
        return m.group(0)

    out = _MARK.sub(sub, src)
    if out != src:
        with open(args.file, "w") as fh:
            fh.write(out)
    n = sum(1 for k in st["order"] if st["questions"][k]["status"] == "answered")
    print(f"pasted {n} answered block(s) into {args.file}")


def cmd_check(args):
    st = load(args)
    src = open(args.file).read()
    blocks = {m.group(1): m.group(2) for m in _MARK.finditer(src)}
    problems = []
    for k in st["order"]:
        if k not in blocks:
            problems.append(f"{k}: no markers in the file")
            continue
        q = st["questions"][k]
        if q["status"] == "answered" and blocks[k] != q["text"]:
            problems.append(f"{k}: the file differs from the owner's answer -- run `paste`, never edit the block")
        if k in (st.get("required") or []) and q["status"] != "answered":
            problems.append(f"{k}: required and not answered")
    if problems:
        print(f"{args.week}: {len(problems)} problem(s):")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print(f"ok — {args.week}: every answered block is in {args.file} unchanged; required blocks answered")


def cmd_show(args):
    st = load(args)
    print(f"{st['week']}  publish={st['publish']}")
    for k in st["order"]:
        q = st["questions"][k]
        req = " (required)" if k in (st.get("required") or []) else ""
        preview = (q["text"] or "").replace("\n", " ")[:70]
        print(f"  {k:<18} {q['status']:<9}{req}  {preview}")


def cmd_publish(args):
    st = load(args)
    for k in st.get("required") or []:
        if k in st["questions"] and st["questions"][k]["status"] != "answered":
            die(f"{k} is required and not answered -- nothing publishes")
    st["publish"] = args.decision
    save(args, st)
    print(f"{st['week']}: {args.decision}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="the private fnr config declaring the sections, owner blocks and questions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("week")
    p.add_argument("--without", action="append", metavar="KEY", help="drop a conditional block this week (repeatable)")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("next"); p.add_argument("week"); p.set_defaults(fn=cmd_next)
    p = sub.add_parser("answer"); p.add_argument("week"); p.add_argument("key")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file"); g.add_argument("--text"); g.add_argument("--keep", action="store_true"); g.add_argument("--skip", action="store_true")
    p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("paste"); p.add_argument("week"); p.add_argument("file"); p.set_defaults(fn=cmd_paste)
    p = sub.add_parser("check"); p.add_argument("week"); p.add_argument("file"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("show"); p.add_argument("week"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("publish"); p.add_argument("week"); p.add_argument("--decision", choices=["publish", "hold"], required=True); p.set_defaults(fn=cmd_publish)
    args = ap.parse_args()
    if not re.match(r"^\d{4}-W\d{2}$", args.week):
        die(f"week must look like 2026-W36, got {args.week!r}")
    args.fn(args)


if __name__ == "__main__":
    main()
