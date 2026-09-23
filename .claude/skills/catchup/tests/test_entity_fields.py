#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Every field the store accepts must SURVIVE normalize() and merge().

This file exists because the same bug shipped three times: a field validated
carefully in normalize(), with a helpful error for bad input, and then never
written to the entity -- `urls`, `rank`, and nearly `channel`. The validation
is the tell that someone meant to store it, and nothing checked that they did.

A second class is here too: an edit that lands inside the wrong block. One
insert re-parented the succession check under `if etype == "concept"`, so the
rule only fired for the one type it was never meant for. Silent, because a
warning that never fires looks exactly like a store with nothing to warn about.

Run: uv run tests/test_entity_fields.py
"""
import contextlib
import importlib.util
import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("entities", os.path.join(HERE, "..", "scripts", "entities.py"))
ent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ent)
W = "2026-W39"


def theme(**kw):
    base = {"id": "tt", "type": "theme", "category": "technical", "title": "T", "note": "n",
            "moved": "m", "why_it_matters": "w", "consequence": "major",
            "weight": {"commits": 3, "share": 0.1}}
    base.update(kw)
    return base


def stored(raw):
    """The week entry exactly as it would be written, after normalize and merge."""
    return ent.merge(None, ent.normalize(raw, W))


class FieldsSurvive(unittest.TestCase):
    def test_rank(self):
        e = stored({"id": "cc", "type": "concept", "category": "technical", "title": "C", "note": "n",
                    "claim": "x", "grade": "measured", "subject": "S", "rank": 2})
        self.assertEqual(e["weeks"][W].get("rank"), 2)

    def test_urls(self):
        e = stored({"id": "oo", "type": "thread", "category": "technical", "title": "O", "note": "n",
                    "urls": [{"label": "site", "url": "https://example.com"}]})
        self.assertEqual(e.get("urls"), [{"label": "site", "url": "https://example.com"}])

    def test_channel_and_confidential(self):
        e = stored({"id": "aa", "type": "org", "category": "meeting", "title": "A", "note": "n",
                    "channel": "lp-communication", "confidential": True})
        self.assertEqual(e["weeks"][W].get("channel"), "lp-communication")
        self.assertIs(e["weeks"][W].get("confidential"), True)

    def test_lesson(self):
        e = stored(theme(lesson="Finishing is its own skill."))
        self.assertEqual(e["weeks"][W].get("lesson"), "Finishing is its own skill.")

    def test_succession_both_directions(self):
        closed = stored(theme(status="done", succeeded_by=["next"]))
        self.assertEqual(closed["weeks"][W].get("succeeded_by"), ["next"])
        child = stored(theme(id="next", succeeds=["tt"]))
        self.assertEqual(child["weeks"][W].get("succeeds"), ["tt"])

    def test_empty_succession_is_kept_and_distinct_from_absent(self):
        declared = stored(theme(status="done", succeeded_by=[]))
        self.assertEqual(declared["weeks"][W].get("succeeded_by"), [])
        absent = stored(theme(status="done"))
        self.assertNotIn("succeeded_by", absent["weeks"][W])


class RulesFireForTheRightTypes(unittest.TestCase):
    def test_succession_warning_fires_for_a_closed_theme(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ent.normalize(theme(status="done"), W)
        self.assertIn("does not say what inherits it", err.getvalue())

    def test_succession_warning_silent_when_declared(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ent.normalize(theme(status="done", succeeded_by=[]), W)
        self.assertNotIn("does not say what inherits it", err.getvalue())

    def test_bad_channel_rejected(self):
        with self.assertRaises(ValueError):
            ent.normalize({"id": "xx", "type": "org", "category": "meeting", "title": "X",
                           "note": "n", "channel": "email"}, W)

    def test_lesson_refused_on_a_concept(self):
        with self.assertRaises(ValueError):
            ent.normalize({"id": "cc", "type": "concept", "category": "technical", "title": "C",
                           "note": "n", "claim": "x", "grade": "measured", "subject": "S",
                           "lesson": "no"}, W)


if __name__ == "__main__":
    unittest.main(verbosity=1)
