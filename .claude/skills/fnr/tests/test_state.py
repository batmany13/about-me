#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""state.py keeps the machine's version of every block beside what he wrote.

Blind write, then compare: the question packet shows his notes, never the
machine's prose; the machine version is captured at `init`, revealed only on
request (and that is recorded), and paired with the final text for evals.
Every section name here is invented -- the real ones live in the private config.

Run: uv run tests/test_state.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "state.py")
W = "2031-W05"
FOOTER = "_the standing footer._"

CONFIG = {
    "contract": "fnr-config/v1",
    "sections": [
        {"key": "opening", "title": None, "owner": "owner", "default": "the record's headline",
         "memory": "the week in one line", "question": "How did it feel?"},
        {"key": "lane_a", "title": "Lane A", "owner": "machine", "source": "the lane"},
        {"key": "lane_a_note", "title": "Note.", "under": "lane_a", "owner": "owner",
         "default": "the lesson", "question": "Is that the lesson?"},
        {"key": "the_one", "title": "The One", "owner": "owner", "required": True,
         "default": None, "question": "One thing?"},
        {"key": "finds", "title": "Finds", "owner": "pick",
         "candidates": "public things from the week", "question": "Which of these?"},
    ],
    "footer": FOOTER,
}

UNREDACTED = f"""# {W} · UNREDACTED

<!-- fnr:opening -->
NOTES-OPENING: every name and number, by outcome and step.
<!-- /fnr:opening -->

## Lane A

Private detail about lane a.

**Note.**  <!-- fnr:lane_a_note -->
NOTES-NOTE: what the lane taught.
<!-- /fnr:lane_a_note -->

## The One

<!-- fnr:the_one -->
_(his)_
<!-- /fnr:the_one -->

## Finds

<!-- fnr:finds -->
- Thing A -- does a.
- Thing B -- does b.
- Thing C -- does c.
<!-- /fnr:finds -->
"""

CANDIDATE = f"""# {W}

<!-- fnr:opening -->
MACHINE-OPENING: a week of three outcomes.
<!-- /fnr:opening -->

## Lane A

Machine prose about lane a.

**Note.**  <!-- fnr:lane_a_note -->
MACHINE-NOTE: the lesson, scrubbed.
<!-- /fnr:lane_a_note -->

## The One

<!-- fnr:the_one -->
_(his — asked below)_
<!-- /fnr:the_one -->

## Finds

<!-- fnr:finds -->
_(picked below)_
<!-- /fnr:finds -->

{FOOTER}
"""


def put(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def get(path):
    with open(path) as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "drafts")
        os.makedirs(self.dir)
        self.cfg = os.path.join(self.tmp.name, "fnr.config.json")
        put(self.cfg, json.dumps(CONFIG))
        self.write("unredacted", UNREDACTED)
        self.write("public", CANDIDATE)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, suffix, body, week=W):
        put(os.path.join(self.dir, f"{week}.{suffix}.md"), body)

    def run_state(self, *argv, ok=True):
        r = subprocess.run([sys.executable, SCRIPT, "--state-dir", self.dir, "--config", self.cfg, *argv],
                           capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        else:
            self.assertNotEqual(r.returncode, 0, r.stdout)
        return r

    def state(self, week=W):
        return json.loads(get(os.path.join(self.dir, f"{week}.state.json")))

    def answer_file(self, text):
        p = os.path.join(self.tmp.name, "a.md")
        put(p, text)
        return p

    def pairs(self, *extra):
        out = self.run_state("pairs", *extra).stdout
        return {r["key"]: r for r in map(json.loads, out.splitlines())}


class Init(Base):
    def test_machine_versions_captured(self):
        self.run_state("init", W)
        q = self.state()["questions"]
        self.assertEqual(q["opening"]["machine"], "MACHINE-OPENING: a week of three outcomes.")
        self.assertEqual(len(q["opening"]["machine_sha"]), 12)
        self.assertEqual(q["lane_a_note"]["machine"], "MACHINE-NOTE: the lesson, scrubbed.")
        # default null -> no machine version; the placeholder is a prompt, not a draft
        self.assertIsNone(q["the_one"]["machine"])
        # a pick block's machine version is the candidate list, from the private side
        self.assertIn("Thing B", q["finds"]["machine"])
        self.assertEqual(self.state()["pick"], ["finds"])

    def test_machine_section_snapshot_excludes_nested_owner_block(self):
        self.run_state("init", W)
        sec = self.state()["machine_sections"]
        self.assertEqual(list(sec), ["lane_a"])
        self.assertEqual(sec["lane_a"]["machine"], "Machine prose about lane a.")


class Blind(Base):
    def test_packet_hides_machine_version(self):
        out = self.run_state("init", W).stdout
        self.assertIn("NOTES-OPENING", out)          # his notes are the packet
        self.assertNotIn("MACHINE-OPENING", out)     # the machine's prose is not
        out = self.run_state("next", W).stdout
        self.assertNotIn("MACHINE-OPENING", out)
        self.assertIn("reveal", out)

    def test_reveal_is_recorded_and_flags_the_answer(self):
        self.run_state("init", W)
        out = self.run_state("next", W, "--reveal").stdout
        self.assertIn("MACHINE-OPENING", out)
        self.assertTrue(self.state()["questions"]["opening"]["revealed_at"])
        self.run_state("answer", W, "opening", "--keep")
        q = self.state()["questions"]["opening"]
        self.assertTrue(q["revealed_before_answer"])
        self.assertEqual(q["verdict"], "kept")

    def test_blind_answer_is_not_flagged(self):
        self.run_state("init", W)
        self.run_state("answer", W, "opening", "--file", self.answer_file("In my words.\n"))
        q = self.state()["questions"]["opening"]
        self.assertFalse(q["revealed_before_answer"])
        self.assertEqual(q["machine"], "MACHINE-OPENING: a week of three outcomes.")  # untouched

    def test_compare_only_after_answer(self):
        self.run_state("init", W)
        r = self.run_state("compare", W, "opening", ok=False)
        self.assertIn("not answered yet", r.stderr)
        self.run_state("answer", W, "opening", "--file", self.answer_file("MACHINE-OPENING: a week, mine."))
        out = self.run_state("compare", W, "opening").stdout
        self.assertIn("rewritten", out)
        self.assertIn("revealed before answer: no", out)
        self.assertIn("similarity 0.", out)
        self.assertIn("a week, mine.", out)
        self.assertIn("MACHINE-OPENING: a week of three outcomes.", out)

    def test_keep_refused_where_nothing_to_keep(self):
        self.run_state("init", W)
        self.assertIn("nothing to keep", self.run_state("answer", W, "finds", "--keep", ok=False).stderr)
        self.assertIn("nothing to keep", self.run_state("answer", W, "the_one", "--keep", ok=False).stderr)
        self.run_state("reveal", W, "the_one", ok=False)   # no machine version to reveal


class Verdicts(Base):
    def walk(self):
        self.run_state("init", W)
        self.run_state("answer", W, "opening", "--keep")
        self.run_state("answer", W, "lane_a_note", "--file", self.answer_file("What I actually learned."))
        self.run_state("answer", W, "the_one", "--file", self.answer_file("The one thing."))
        self.run_state("answer", W, "finds", "--skip")

    def test_verdicts(self):
        self.walk()
        q = self.state()["questions"]
        self.assertEqual({k: v["verdict"] for k, v in q.items()},
                         {"opening": "kept", "lane_a_note": "rewritten", "the_one": "rewritten", "finds": "skipped"})

    def test_pairs_rows(self):
        self.walk()
        rows = self.pairs(W)
        self.assertEqual(set(rows), {"opening", "lane_a_note", "the_one", "finds", "lane_a"})
        o = rows["opening"]
        self.assertEqual(o["final"], o["machine"])
        self.assertEqual(o["similarity"], 1.0)
        self.assertEqual(o["chars_machine"], len(o["machine"]))
        self.assertEqual(o["owner"], "owner")
        self.assertIs(o["revealed_before_answer"], False)
        self.assertEqual(o["machine_from"], "state")
        self.assertLess(rows["lane_a_note"]["similarity"], 0.6)
        self.assertIsNone(rows["the_one"]["machine"])
        self.assertIsNone(rows["the_one"]["similarity"])
        self.assertEqual(rows["finds"]["owner"], "pick")
        self.assertEqual(rows["finds"]["final"], "")
        self.assertEqual(rows["lane_a"]["owner"], "machine")
        self.assertEqual(rows["lane_a"]["verdict"], "kept")   # candidate unchanged so far
        for r in rows.values():
            self.assertEqual(set(r), {"week", "key", "owner", "machine", "final", "verdict",
                                      "revealed_before_answer", "chars_machine", "chars_final",
                                      "similarity", "machine_from"})

    def test_pending_blocks_are_not_pairs(self):
        self.run_state("init", W)
        self.run_state("answer", W, "opening", "--keep")
        self.assertEqual(set(self.pairs(W)), {"opening", "lane_a"})

    def test_release_snapshots_a_rewritten_machine_section(self):
        self.walk()
        self.run_state("paste", W, os.path.join(self.dir, f"{W}.public.md"))
        body = get(os.path.join(self.dir, f"{W}.public.md"))
        self.write("public", body.replace("Machine prose about lane a.", "He dictated this instead."))
        self.run_state("publish", W, "--decision", "publish", "--quote", "publish it")
        self.run_state("release", W, os.path.join(self.tmp.name, "out", f"{W}.md"))
        s = self.state()["machine_sections"]["lane_a"]
        self.assertEqual(s["final"], "He dictated this instead.")
        self.assertEqual(s["verdict"], "rewritten")
        self.assertEqual(self.pairs(W)["lane_a"]["verdict"], "rewritten")

    def test_release_refuses_an_unwalked_pick(self):
        self.run_state("init", W)
        for k in ("opening", "lane_a_note"):
            self.run_state("answer", W, k, "--keep")
        self.run_state("answer", W, "the_one", "--file", self.answer_file("x"))
        self.run_state("paste", W, os.path.join(self.dir, f"{W}.public.md"))
        self.run_state("publish", W, "--decision", "publish", "--quote", "publish")
        r = self.run_state("release", W, os.path.join(self.tmp.name, "o.md"), ok=False)
        self.assertIn("nothing picked", r.stderr)


LEGACY = {
    "week": W, "started": "2031-02-03T00:00:00+00:00", "config": "x", "order": ["opening", "lane_a_note", "the_one"],
    "required": ["the_one"],
    "questions": {
        "opening": {"status": "kept", "text": None, "at": "t"},
        "lane_a_note": {"status": "answered", "text": "His note.", "at": "t"},
        "the_one": {"status": "answered", "text": "His one.", "at": "t"},
    },
    "publish": "pending",
}


class Legacy(Base):
    def setUp(self):
        super().setUp()
        put(os.path.join(self.dir, f"{W}.state.json"), json.dumps(LEGACY))

    def test_legacy_state_still_works(self):
        self.run_state("show", W)
        self.assertEqual(self.run_state("next", W, "--bare").stdout.strip(), "publish")
        self.run_state("paste", W, os.path.join(self.dir, f"{W}.public.md"))
        self.run_state("check", W, os.path.join(self.dir, f"{W}.public.md"))
        rows = self.pairs(W)
        self.assertIsNone(rows["lane_a_note"]["machine"])
        self.assertEqual(rows["lane_a_note"]["verdict"], "rewritten")
        self.assertIsNone(rows["lane_a_note"]["revealed_before_answer"])
        self.assertNotIn("lane_a", rows)      # no snapshot, no backfill: no machine-section pair

    def test_backfill_from_a_file(self):
        first = os.path.join(self.tmp.name, "first.md")
        put(first, CANDIDATE)
        self.run_state("paste", W, os.path.join(self.dir, f"{W}.public.md"))
        rows = self.pairs(W, "--machine-from", first)
        self.assertEqual(rows["lane_a_note"]["machine"], "MACHINE-NOTE: the lesson, scrubbed.")
        self.assertEqual(rows["lane_a_note"]["final"], "His note.")
        self.assertEqual(rows["lane_a_note"]["machine_from"], first)
        self.assertEqual(rows["opening"]["final"], rows["opening"]["machine"])
        self.assertIsNone(rows["the_one"]["machine"])     # default null: its placeholder is no baseline
        self.assertEqual(rows["lane_a"]["machine"], "Machine prose about lane a.")
        self.assertEqual(rows["lane_a"]["verdict"], "kept")

    def test_backfill_from_first_git_revision(self):
        def git(*a):
            subprocess.run(["git", "-C", self.tmp.name, *a], check=True, capture_output=True)
        git("init", "-q"); git("config", "user.email", "t@example.com"); git("config", "user.name", "T")
        git("add", "drafts"); git("commit", "-qm", "machine drafts")
        self.run_state("paste", W, os.path.join(self.dir, f"{W}.public.md"))
        git("commit", "-qam", "his answers")
        rows = self.pairs(W, "--machine-from", "first:drafts/{week}.public.md")
        self.assertEqual(rows["lane_a_note"]["machine"], "MACHINE-NOTE: the lesson, scrubbed.")
        self.assertTrue(rows["lane_a_note"]["machine_from"].endswith(f":drafts/{W}.public.md"))


if __name__ == "__main__":
    unittest.main()
