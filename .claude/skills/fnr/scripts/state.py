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
    ...machine version, or the owner's words...
    <!-- /fnr:blurb -->

`paste` writes every answered block back between its markers, byte for byte,
so a re-render can never overwrite what the owner wrote. The machine never
edits an answered block; the only way to change one is another `answer`.

BLIND WRITE, THEN COMPARE. Every block keeps its MACHINE version -- captured
from the candidate at `init` and never touched again -- but the question
packet does not show it. He writes from the unredacted memory aid; the machine
version is shown only on request (`reveal`, recorded as revealed-before-answer)
or after he has answered (`compare`). Seeing the machine's prose first does the
reflecting for him and anchors the answer.

Each answer carries a verdict (kept / rewritten / skipped). Machine sections
without a marker are snapshotted by heading at `init` and again at `release`.
`pairs` turns all of it into JSONL: the eval dataset for the day the drafts get
good enough to keep.

Usage:
    state.py init 2026-W36 [--without <key>] [--config fnr/.private/fnr.config.json]
    state.py next 2026-W36                     # the next pending question, or "done"
    state.py reveal 2026-W36 [blurb]           # the machine version BEFORE answering (recorded)
    state.py answer 2026-W36 blurb --file a.md # the owner's words, verbatim
    state.py answer 2026-W36 blurb --keep      # the machine version stands
    state.py answer 2026-W36 next --skip       # the block comes out of the page
    state.py compare 2026-W36 blurb            # after answering: his words beside the machine's
    state.py paste 2026-W36 drafts/2026-W36.public.md   # answered blocks into the PRIVATE candidate
    state.py check 2026-W36 drafts/2026-W36.public.md
    state.py show 2026-W36
    state.py publish 2026-W36 --decision hold
    state.py publish 2026-W36 --decision publish --quote "<his words, containing 'publish'>"
    state.py release 2026-W36 fnr/2026-W36.md   # the ONLY writer of the public path; refuses without the quote
    state.py pairs 2026-W36 [2026-W37 ...] [--out evals/fnr-pairs.jsonl]
    state.py pairs 2026-W39 --machine-from first:drafts/2026-W39.public.md   # backfill a pre-pairs state
"""

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

STATUSES = ("pending", "answered", "kept", "skipped")
VERDICT_OF = {"answered": "rewritten", "kept": "kept", "skipped": "skipped"}
ASKED = ("owner", "pick")          # the section kinds that are walked, one question each
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
    blocks = [s for s in (cfg.get("sections") or []) if s.get("owner") in ASKED and s.get("key")]
    if not blocks:
        die(f"{path}: no owner blocks declared under `sections`")
    return cfg, blocks


def soft_config(path):
    """The config when it is there; {} when it is not. For commands that only
    enrich their output with it and must still run on a machine without it."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, TypeError, ValueError):
        return {}


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12] if text is not None else None


def similarity(a, b):
    if a is None or b is None:
        return None
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def path_for(args, week=None):
    return os.path.join(args.state_dir, f"{week or args.week}.state.json")


def load(args, week=None):
    p = path_for(args, week)
    if not os.path.isfile(p):
        die(f"no state at {p} -- run `state.py init {week or args.week}` first")
    with open(p) as fh:
        return json.load(fh)


def save(args, st):
    st["updated"] = now()
    p = path_for(args, st.get("week"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _draft(args, suffix, week=None):
    """A sibling draft file, by convention: <state-dir>/<week>.<suffix>.md."""
    p = os.path.join(args.state_dir, f"{week or args.week}.{suffix}.md")
    try:
        with open(p) as fh:
            return p, fh.read()
    except OSError:
        return p, None


def _block(body, key):
    if not body:
        return None
    m = re.search(rf"<!-- fnr:{key} -->\n?(.*?)\n?<!-- /fnr:{key} -->", body, re.S)
    return m.group(1).strip() if m else None


def _section(body, title, footer=None):
    """A machine section's text: its `## title` up to the next heading, with any
    marked owner block (and the line introducing it) and the footer removed --
    so the pair is the machine's prose only, never an answer nested inside it."""
    if not body or not title:
        return None
    m = re.search(rf"(?m)^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.S)
    if not m:
        return None
    text = re.sub(r"(?m)^[^\n]*<!-- fnr:(\w+) -->.*?<!-- /fnr:\1 -->[^\n]*\n?", "", m.group(1), flags=re.S)
    if footer:
        text = text.replace(footer, "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _machine_version(cfg, unred, pub):
    """The machine's own version of an asked block, before any answer.

    A `pick` block's machine version is its candidate list, which lives on the
    private side -- the public candidate holds only a placeholder, because
    nothing is listed that he did not pick. A block whose config `default` is
    null (the required one) has no machine version at all: its placeholder is
    a prompt, not a draft, and pairing it would score him against nothing.
    """
    if "default" in cfg and cfg["default"] is None:
        return None
    return _block(unred if cfg.get("owner") == "pick" else pub, cfg["key"])


def _machine_sections(full):
    return [s for s in (full.get("sections") or []) if s.get("owner") == "machine" and s.get("key")]


def cmd_init(args):
    p = path_for(args)
    if os.path.isfile(p):
        print(f"exists: {p}")
        return
    full, blocks = read_config(args.config)
    without = set(args.without or [])
    order = [b["key"] for b in blocks if b["key"] not in without]
    required = sorted(b["key"] for b in blocks if b.get("required") and b["key"] in order)
    _, unred = _draft(args, "unredacted")
    pub_path, pub = _draft(args, "public")
    if pub is None:
        print(f"warning: no candidate at {pub_path} -- machine versions not captured; "
              "write the drafts before init", file=sys.stderr)
    cfgs = {b["key"]: b for b in blocks}
    questions = {}
    for k in order:
        m = _machine_version(cfgs[k], unred, pub)
        questions[k] = {"status": "pending", "text": None, "at": None,
                        "machine": m, "machine_sha": sha(m)}
    # Machine sections are never asked, but he can still rewrite one by telling
    # you -- snapshot them now and again at release, so that is a pair too.
    sections = {}
    for s in _machine_sections(full):
        m = _section(pub, s.get("title"), full.get("footer")) if s["key"] not in without else None
        if m is not None:
            sections[s["key"]] = {"title": s["title"], "machine": m, "machine_sha": sha(m)}
    st = {
        "week": args.week,
        "started": now(),
        "config": args.config,
        "order": order,
        "required": required,
        "pick": [k for k in order if cfgs[k].get("owner") == "pick"],
        "questions": questions,
        "machine_sections": sections,
        "publish": "pending",
    }
    save(args, st)
    n = sum(1 for q in questions.values() if q["machine"] is not None)
    print(f"wrote {p} -- {len(order)} questions, required: {', '.join(required) or 'none'}; "
          f"machine versions held for {n} block(s) and {len(sections)} machine section(s)")
    # Hand straight over to question 1. The draft is finished at this point and
    # the next move is always the same move; printing a count and stopping is
    # what turns a walk into something someone has to remember to start.
    print()
    packet(args, order[0])


def _learning_counts(args):
    """`{sources}` / `{promoted}` in a question, filled from the reading lane."""
    p = os.path.join(os.path.dirname(os.path.abspath(args.state_dir)),
                     "learning", f"{args.week}.md")
    try:
        body = open(p).read()
    except OSError:
        return {"sources": "no sources captured", "promoted": "0"}
    # A separator row is one whose characters are ALL pipes, dashes and spaces.
    # This was a strict-superset test, which silently required an ASCII hyphen
    # somewhere in every data row -- so a row whose title used an em dash and
    # whose link carried no hyphen was counted as a separator and dropped.
    rows = [l for l in body.splitlines()
            if l.startswith("|") and not l.startswith("| Source |")
            and not set(l) <= set("|-: ")]
    yes = sum(1 for l in rows if l.rstrip("|").rsplit("|", 1)[-1].strip() == "yes")
    n = len(rows)
    return {"sources": f"{n} source{'' if n == 1 else 's'}", "promoted": str(yes)}


def _fmt_examples(cfg, key, indent="    "):
    """Past cases for one block, from the private config's `examples`.

    The public skill describes the shapes; the real material they were learned
    on lives in the private config, so no real week ever has to be quoted here
    to teach one. Kept first, then rewritten, then cut.
    """
    cases = (cfg.get("examples") or {}).get(key) or []
    order = {"kept": 0, "rewritten": 1, "cut": 2}
    out = []
    for e in sorted(cases, key=lambda e: order.get(e.get("verdict"), 3)):
        v = e.get("verdict", "?")
        tag = f"[{e.get('week', '?')} · {v}{' · summary' if e.get('summary') else ''}]"
        label = "drafted" if v == "rewritten" else v
        out.append(f"{indent}{tag}")
        out.append(f"{indent}  {label}: {e.get('text', '')}")
        if e.get("became"):
            out.append(f"{indent}  became:  {e['became']}")
        for f in ("why", "rule"):
            if e.get(f):
                out.append(f"{indent}  {f}: {e[f]}")
    return out


def _can_keep(st, cfg, key):
    """Keep needs something to keep: never on the required block, never on a
    pick block (nothing is listed he did not pick), never where the config
    declares no machine version."""
    return not (key in (st.get("required") or []) or key in (st.get("pick") or [])
                or cfg.get("owner") == "pick" or ("default" in cfg and cfg["default"] is None))


def packet(args, key):
    """Everything needed to ASK one question, so asking takes no judgment.

    The weekly is a walk, not a set of prompts someone remembers to run. This
    prints the whole turn -- position, the memory aid, the question and the
    allowed answers -- so `init`, `next` and `answer` each hand the caller the
    next step instead of a bare key. A draft that ends with a report instead of
    question 1 is the failure this removes.

    The machine version is NOT in the packet. He writes from his notes; the
    machine's prose is behind `reveal` (recorded) or `compare` (after).
    """
    st = load(args)
    full, blocks = read_config(args.config)
    cfg = {b["key"]: b for b in blocks}.get(key, {})
    order = st["order"]
    n, total = (order.index(key) + 1, len(order)) if key in order else (0, len(order))
    title = cfg.get("title") or "the opening line"
    req = key in (st.get("required") or [])
    pick = key in (st.get("pick") or []) or cfg.get("owner") == "pick"

    _, unred = _draft(args, "unredacted")
    pub_path, _ = _draft(args, "public")

    out = [f"=== {args.week} — question {n} of {total} — `{key}`  [{title}]"
           + ("   REQUIRED" if req else "") + ("   PICK" if pick else "")]

    u = _block(unred, key)
    label = ("the candidates (private) -- he picks; nothing he doesn't pick is listed" if pick
             else "his notes (unredacted, private) -- the memory aid he writes from")
    missing = "    (no marked block -- open the unredacted draft and show this section by hand"
    missing += f"; the config's `memory` for it: {cfg['memory']})" if cfg.get("memory") else ")"
    out += ["", f"--- {label}:", u if u else missing]

    q = (cfg.get("question") or "").strip()
    if "{sources}" in q or "{promoted}" in q:
        try:
            q = q.format(**_learning_counts(args))
        except (KeyError, IndexError):
            pass
    out += ["", "--- ask exactly this:", q or "(no question declared in the config)"]
    if cfg.get("nudge"):
        out += ["", f"--- nudge (from the unredacted draft, never published by name): {cfg['nudge']}"]
    ex = _fmt_examples(full, key)
    if ex:
        out += ["", "--- past cases for this block (private config, never quoted in the weekly):"] + ex

    w = args.week
    lines = [f"  {'picks' if pick else 'words'}  -> answer {w} {key} --file "
             + ("<the items he picked, as listed>" if pick else "<his words verbatim>")]
    if _can_keep(st, cfg, key):
        lines.append(f"  keep   -> answer {w} {key} --keep")
        lines.append(f"  reveal -> reveal {w} {key}   (only if he asks to see the machine version first; recorded)")
    lines.append("  skip   -> REFUSED, this block is required" if req
                 else f"  skip   -> answer {w} {key} --skip   (the block comes out of the page)")
    lines.append(f"  then:     paste {w} {pub_path}")
    out += ["", "--- record his reply with ONE of:"] + lines
    out += ["", "(his words go in verbatim -- grammar and spelling only.  The machine version is "
                "hidden on purpose: he writes first, `compare` shows it after.)"]
    print("\n".join(out))


def _pending(st):
    for k in st["order"]:
        if st["questions"][k]["status"] == "pending":
            return k
    # Every question has a status. The required ones must be ANSWERED, not
    # skipped -- skip is refused for them in `answer`, so this is a belt.
    for k in st.get("required") or []:
        if k in st["questions"] and st["questions"][k]["status"] != "answered":
            return k
    return None


def cmd_next(args):
    st = load(args)
    k = _pending(st)
    if k and args.reveal:
        args.key = k
        return cmd_reveal(args)
    if k:
        print(k) if args.bare else packet(args, k)
        return
    print("done" if st["publish"] != "pending" else "publish")


def _machine_of(args, st, key):
    """The machine version from the state, or -- for a state written before
    machine versions were captured -- from the candidate's marker."""
    q = st["questions"][key]
    if "machine" in q:
        return q["machine"]
    return _block(_draft(args, "public")[1], key)


def cmd_reveal(args):
    st = load(args)
    k = args.key or _pending(st)
    if not k or k not in st["questions"]:
        die(f"nothing to reveal; this week's blocks are {', '.join(st['order'])}")
    q = st["questions"][k]
    if q["status"] != "pending":
        args.key = k
        return cmd_compare(args)
    m = _machine_of(args, st, k)
    if m is None:
        die(f"{k} has no machine version -- the config declares none; this one is his to write, or skip")
    # A kept answer after a reveal is a different signal from a blind one, so
    # the reveal is recorded, not just printed.
    q["revealed_at"] = q.get("revealed_at") or now()
    save(args, st)
    print(f"=== {args.week} — `{k}` — the machine version (revealed before his answer; recorded)\n")
    print(m)
    print(f"\n--- keep -> answer {args.week} {k} --keep   ·   or his words -> --file   ·   or --skip")


def cmd_answer(args):
    st = load(args)
    k = args.key
    if k not in st["questions"]:
        die(f"unknown question {k!r}; this week's are {', '.join(st['order'])}")
    q = st["questions"][k]
    cfg = {s.get("key"): s for s in (soft_config(args.config).get("sections") or [])}.get(k, {})
    if args.keep:
        if not _can_keep(st, cfg, k):
            die(f"{k} has nothing to keep -- it is required, a pick, or has no machine version. "
                "Answer it with his words, or --skip.")
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
    # `machine` is never touched here: it is the baseline the answer is scored
    # against, and an answer that rewrote its own baseline would score 1.0.
    q["verdict"] = VERDICT_OF[q["status"]]
    q["revealed_before_answer"] = bool(q.get("revealed_at"))
    save(args, st)
    print(f"{k}: {q['status']} ({q['verdict']}"
          + (", after reveal" if q["revealed_before_answer"] else "") + ")")
    if q["status"] == "answered" and _machine_of(args, st, k) is not None:
        print(f"    optional: `compare {args.week} {k}` shows the machine version beside his")
    # ... and immediately the next question, so the loop advances on its own.
    # `paste` still has to run to put an answer into the candidate; the
    # reminder is in every packet's footer.
    print()
    args.bare = False
    args.reveal = False
    cmd_next(args)


def cmd_compare(args):
    st = load(args)
    k = args.key
    if k in st["questions"]:
        q = st["questions"][k]
        if q["status"] == "pending":
            die(f"{k} is not answered yet -- compare comes after he writes. "
                f"`reveal {args.week} {k}` shows the machine version first, and records that it did.")
        machine = _machine_of(args, st, k)
        final = _final(q, machine)
        verdict, revealed = q.get("verdict") or VERDICT_OF[q["status"]], q.get("revealed_before_answer")
    elif k in (st.get("machine_sections") or {}):
        s = st["machine_sections"][k]
        machine = s["machine"]
        final = s["final"] if "final" in s else _section(
            _draft(args, "public")[1], s["title"], soft_config(args.config).get("footer"))
        verdict, revealed = _section_verdict(machine, final), None
    else:
        die(f"unknown block {k!r}")
    sim = similarity(machine, final)
    print(f"=== {args.week} — `{k}` — {verdict}"
          + ("" if revealed is None else f" · revealed before answer: {'yes' if revealed else 'no'}")
          + ("" if sim is None else f" · similarity {sim:.2f}"))
    print("\n--- his (final):")
    print(final if final else "(nothing -- the block came out)")
    print("\n--- the machine's:")
    print(machine if machine is not None else "(no machine version)")


_MARK = re.compile(r"<!-- fnr:(\w+) -->\n(.*?)\n<!-- /fnr:\1 -->", re.S)


def cmd_paste(args):
    st = load(args)
    src = open(args.file).read()
    found = {m.group(1) for m in _MARK.finditer(src)}
    # A skipped block has already been removed by an earlier paste; requiring
    # its markers makes the second paste of a week fail on a decision that was
    # correctly honoured. Same bug `check` had.
    missing = [k for k in st["order"] if k not in found
               and st["questions"][k]["status"] != "skipped"]
    if missing:
        die(f"{args.file} has no markers for: {', '.join(missing)} -- the public file must carry every block")

    def sub(m):
        k = m.group(1)
        q = st["questions"].get(k)
        if q and q["status"] == "answered":
            return f"<!-- fnr:{k} -->\n{q['text']}\n<!-- /fnr:{k} -->"
        # SKIPPED means the block comes OUT -- it does not mean the machine
        # default stands. Leaving it was the worst failure this file could
        # have: the owner says "don't say this" and the candidate keeps
        # saying it, in his weekly, under his name, with the state file
        # recording that he declined it.
        if q and q["status"] == "skipped":
            return "\x00SKIP\x00"
        return m.group(0)

    out = _MARK.sub(sub, src)
    # Remove the skipped block along with the title line that introduces it
    # (`**Learning.**  <!-- fnr:key -->`) and any heading left standing alone.
    out = re.sub(r"\n*(?:^|\n)[^\n]*\x00SKIP\x00", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # A section heading whose only content was the skipped block goes too.
    out = re.sub(r"\n## [^\n]+\n+(?=## )", "\n", out)
    if out != src:
        with open(args.file, "w") as fh:
            fh.write(out)
    n = sum(1 for k in st["order"] if st["questions"][k]["status"] == "answered")
    sk = [k for k in st["order"] if st["questions"][k]["status"] == "skipped"]
    print(f"pasted {n} answered block(s) into {args.file}"
          + (f"; removed {len(sk)} skipped ({', '.join(sk)})" if sk else ""))


def cmd_check(args):
    st = load(args)
    src = open(args.file).read()
    blocks = {m.group(1): m.group(2) for m in _MARK.finditer(src)}
    problems = []
    for k in st["order"]:
        q = st["questions"][k]
        # A skipped block is SUPPOSED to be gone -- `paste` removes it. Absence
        # is the correct state, and flagging it as a missing marker turned a
        # decision into an error message. Its presence is the real problem:
        # that would mean a block he declined is still in the candidate.
        if q["status"] == "skipped":
            if k in blocks:
                problems.append(f"{k}: skipped, but still in the file -- run `paste` to remove it")
            continue
        if k not in blocks:
            problems.append(f"{k}: no markers in the file")
            continue
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
        rev = " (revealed)" if q.get("revealed_at") else ""
        preview = (q["text"] or "").replace("\n", " ")[:70]
        print(f"  {k:<18} {q['status']:<9}{req}{rev}  {preview}")


def cmd_publish(args):
    st = load(args)
    for k in st.get("required") or []:
        if k in st["questions"] and st["questions"][k]["status"] != "answered":
            die(f"{k} is required and not answered -- nothing publishes")
    if args.decision == "publish":
        # PUBLISH IS A WORD THE OWNER SAYS. Not a decision on the flagged
        # list, not silence, not "looks fine" -- the literal word, quoted here
        # from his message. A weekly once reached the public repo because his
        # answers on four flagged items were read as consent to publish.
        quote = (args.quote or "").strip()
        if "publish" not in quote.lower():
            die("publish needs --quote with the owner's own words containing the word 'publish'. "
                "Decisions on flagged items are not a publish decision. Record hold instead.")
        st["publish_quote"] = quote
    st["publish"] = args.decision
    save(args, st)
    print(f"{st['week']}: {args.decision}")


def _section_verdict(machine, final):
    if final is None or not final.strip():
        return "skipped"
    return "kept" if final.strip() == (machine or "").strip() else "rewritten"


def cmd_release(args):
    """Copy the private candidate into the public repo -- the ONLY writer of that path."""
    st = load(args)
    if st.get("publish") != "publish" or "publish" not in (st.get("publish_quote") or "").lower():
        die("not published: the state does not carry the owner's explicit 'publish'. Nothing is copied.")
    src = os.path.join(args.state_dir, f"{args.week}.public.md")
    if not os.path.isfile(src):
        die(f"no candidate at {src}")
    body = open(src).read()
    blocks = {m.group(1): m.group(2) for m in _MARK.finditer(body)}
    for k in st["order"]:
        q = st["questions"][k]
        if q["status"] == "answered" and blocks.get(k) != q["text"]:
            die(f"{k}: the candidate differs from the owner's answer -- run `paste` first")
        # A pick block's candidate holds a placeholder, never the list: only
        # what he picked is published, so an unwalked pick cannot ship.
        if k in (st.get("pick") or []) and q["status"] == "pending":
            die(f"{k}: a pick block with nothing picked -- ask it, or --skip to drop the section")
    os.makedirs(os.path.dirname(args.public_path) or ".", exist_ok=True)
    with open(args.public_path, "w") as fh:
        fh.write(body)
    # The machine sections' second snapshot: what shipped, beside what was drafted.
    footer = soft_config(args.config).get("footer")
    for k, s in (st.get("machine_sections") or {}).items():
        s["final"] = _section(body, s["title"], footer)
        s["verdict"] = _section_verdict(s["machine"], s["final"])
    save(args, st)
    print(f"released {src} -> {args.public_path} (owner said: {st['publish_quote'][:60]!r})")


def _final(q, machine):
    if q["status"] == "answered":
        return q["text"]
    if q["status"] == "kept":
        return machine
    if q["status"] == "skipped":
        return ""
    return None


def _read_spec(args, spec, week):
    """`path`, or `<git-rev>:<repo-path>` read from the repo holding the state
    dir. `{week}` is substituted; the rev `first` is the earliest commit that
    touched the path -- the machine's draft, before any answer was pasted in."""
    spec = spec.replace("{week}", week)
    if os.path.isfile(spec):
        return open(spec).read(), spec
    rev, sep, path = spec.partition(":")
    if not sep:
        die(f"--machine-from {spec!r}: no such file, and not <rev>:<path>")
    # <rev>:<path> is repo-root relative, and so is the log pathspec once run from the top.
    top = subprocess.run(["git", "-C", args.state_dir if os.path.isdir(args.state_dir) else ".",
                          "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode:
        die(f"--machine-from {spec!r}: {args.state_dir} is not in a git repo")
    repo = top.stdout.strip()
    if rev == "first":
        log = subprocess.run(["git", "-C", repo, "log", "--format=%H", "--", path],
                             capture_output=True, text=True)
        revs = log.stdout.split()
        if log.returncode or not revs:
            die(f"--machine-from {spec!r}: no commit touches {path} in {repo}")
        rev = revs[-1]
    show = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True)
    if show.returncode:
        die(f"--machine-from {spec!r}: {show.stderr.strip()}")
    return show.stdout, f"{rev[:12]}:{path}"


def _pairs_for(args, week):
    st = load(args, week)
    cfg = soft_config(args.config) or soft_config(st.get("config"))
    kinds = {s.get("key"): s.get("owner") for s in (cfg.get("sections") or [])}
    backfill, origin = (None, None)
    if args.machine_from:
        backfill, origin = _read_spec(args, args.machine_from, week)
    rows = []

    def row(key, owner, machine, final, verdict, revealed, source):
        return {"week": week, "key": key, "owner": owner, "machine": machine, "final": final,
                "verdict": verdict, "revealed_before_answer": revealed,
                "chars_machine": None if machine is None else len(machine),
                "chars_final": None if final is None else len(final),
                "similarity": similarity(machine, final), "machine_from": source}

    for k in st["order"]:
        q = st["questions"][k]
        if q["status"] == "pending":
            continue                       # not a pair until he has replied
        if "machine" in q:
            machine, source = q["machine"], "state"
        elif backfill is not None:
            sec = next((s for s in (cfg.get("sections") or []) if s.get("key") == k), {"key": k})
            machine, source = _machine_version(sec, backfill, backfill), origin
        else:
            machine, source = None, None
        rows.append(row(k, kinds.get(k, "owner"), machine, _final(q, machine),
                        q.get("verdict") or VERDICT_OF[q["status"]],
                        q.get("revealed_before_answer"), source))

    # Machine sections: from the state when init captured them; otherwise
    # backfilled by heading. `final` is what release snapshotted, or -- before
    # release -- the candidate as it stands now.
    secs = st.get("machine_sections")
    if secs is None and backfill is not None:
        secs = {s["key"]: {"title": s.get("title"), "_from": origin,
                           "machine": _section(backfill, s.get("title"), cfg.get("footer"))}
                for s in _machine_sections(cfg)}
    current = None
    for k, s in (secs or {}).items():
        if s.get("machine") is None:
            continue
        if "final" in s:
            final = s["final"]
        else:
            if current is None:
                current = _draft(args, "public", week)[1] or ""
            final = _section(current, s["title"], cfg.get("footer"))
        rows.append(row(k, "machine", s["machine"], final or "",
                        s.get("verdict") or _section_verdict(s["machine"], final),
                        None, s.get("_from", "state")))
    return rows


def cmd_pairs(args):
    """One JSONL row per walked block: the machine version beside what shipped.

    This is the eval dataset. The number to watch over the weeks is how often
    `kept` beats `rewritten` -- and, within `rewritten`, whether similarity
    climbs. A kept block after `revealed_before_answer` is a weaker signal
    than a blind one, which is why the flag rides along.
    """
    rows = [r for w in args.weeks for r in _pairs_for(args, w)]
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {len(rows)} pair(s) to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def cmd_examples(args):
    """Every section's past cases, machine sections included -- read before drafting.

    Most cuts happen in the machine sections, and those are never asked about,
    so the packet alone would show the examples only where they matter least.
    """
    cfg, _ = read_config(args.config)
    keys = [s["key"] for s in (cfg.get("sections") or []) if s.get("key")]
    if args.key:
        keys = [k for k in keys if k == args.key] or [args.key]
    shown = 0
    for k in keys:
        ex = _fmt_examples(cfg, k)
        if ex:
            print(f"=== {k}"); print("\n".join(ex)); print(); shown += 1
    if not shown:
        print("(no examples in the config" + (f" for {args.key}" if args.key else "") + ")")


WEEK = re.compile(r"^\d{4}-W\d{2}$")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="the private fnr config declaring the sections, owner blocks and questions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("week")
    p.add_argument("--without", action="append", metavar="KEY", help="drop a conditional block this week (repeatable)")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("next"); p.add_argument("week")
    p.add_argument("--bare", action="store_true",
                   help="print just the key, not the whole question packet")
    p.add_argument("--reveal", action="store_true",
                   help="show the pending block's machine version before he answers (recorded)")
    p.set_defaults(fn=cmd_next, key=None)
    p = sub.add_parser("reveal", help="the machine version of a block BEFORE he answers -- recorded in the state")
    p.add_argument("week"); p.add_argument("key", nargs="?"); p.set_defaults(fn=cmd_reveal)
    p = sub.add_parser("answer"); p.add_argument("week"); p.add_argument("key")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file"); g.add_argument("--text"); g.add_argument("--keep", action="store_true"); g.add_argument("--skip", action="store_true")
    p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("compare", help="after he answers: his block beside the machine's, with similarity")
    p.add_argument("week"); p.add_argument("key"); p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("paste"); p.add_argument("week"); p.add_argument("file"); p.set_defaults(fn=cmd_paste)
    p = sub.add_parser("check"); p.add_argument("week"); p.add_argument("file"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("show"); p.add_argument("week"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("examples", help="past kept/cut/rewritten cases per section, from the private config -- read before drafting")
    p.add_argument("--key", help="one section only"); p.set_defaults(fn=cmd_examples)
    p = sub.add_parser("publish"); p.add_argument("week"); p.add_argument("--decision", choices=["publish", "hold"], required=True)
    p.add_argument("--quote", help="the owner's own words; must contain 'publish' for --decision publish")
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("release", help="copy drafts/<W>.public.md into the public repo -- refuses without an explicit publish")
    p.add_argument("week"); p.add_argument("public_path"); p.set_defaults(fn=cmd_release)
    p = sub.add_parser("pairs", help="machine version vs final, one JSONL row per block -- the eval dataset")
    p.add_argument("weeks", nargs="+")
    p.add_argument("--out", help="write here instead of stdout (e.g. evals/fnr-pairs.jsonl in the private repo)")
    p.add_argument("--machine-from", metavar="SPEC",
                   help="backfill a state with no captured machine versions: a file, or <git-rev>:<path> "
                        "in the private repo; `first` as the rev = the earliest commit of that path; {week} is substituted")
    p.set_defaults(fn=cmd_pairs)
    args = ap.parse_args()
    for w in ([args.week] if hasattr(args, "week") else []) + (getattr(args, "weeks", None) or []):
        if not WEEK.match(w):
            die(f"week must look like 2026-W36, got {w!r}")
    args.fn(args)


if __name__ == "__main__":
    main()
