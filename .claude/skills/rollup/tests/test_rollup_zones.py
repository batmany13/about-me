#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The rollup adds up only week records cut in one zone.

A week cut in Pacific and a week cut in UTC are different weeks; their sum is
not a number about either. Records name the zone that cut them, the registry
names the zone the weekly is cut in, and the rollup refuses a disagreement.
A record with no `timezone` predates the stamp and was cut in UTC.

Run: uv run tests/test_rollup_zones.py
"""
import argparse
import contextlib
import filecmp
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
spec = importlib.util.spec_from_file_location("rollup_main", os.path.join(SCRIPTS, "rollup.py"))
rollup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollup)
wz = rollup.week_zone

PT = "America/Los_Angeles"
W = "2026-W39"


class Zones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def repo(self, name, tz):
        """A source repo holding one week record, cut in `tz` (None = legacy)."""
        path = os.path.join(self.root, name)
        os.makedirs(os.path.join(path, "catchup", "weeks"))
        rec = {"week": W, "stats": {"commits_primary": 10, "prs_merged": 2},
               "entities": {}, "entity_count": 0}
        if tz:
            rec.update(wz.Week.from_label(W, tz).stamp())
        else:
            rec.update({"start": "2026-09-21", "end": "2026-09-27"})
        with open(os.path.join(path, "catchup", "weeks", f"{W}.json"), "w") as fh:
            json.dump(rec, fh)
        return {"name": name, "path": path, "lane": "work", "disclosure": "hidden"}

    def run_rollup(self, repos, zone):
        registry = {"repos": repos}
        args = argparse.Namespace(registry=os.path.join(self.root, "repos.json"), zone_name=zone)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                return rollup.collect(W, registry, args), err.getvalue()
            except SystemExit:
                return None, err.getvalue()

    def test_matching_zones_merge(self):
        d, _ = self.run_rollup([self.repo("a", PT), self.repo("b", PT)], PT)
        self.assertEqual(d["timezone"], PT)
        self.assertEqual(d["legacy_utc"], [])
        self.assertEqual(d["totals"]["commits_primary"], 20)

    def test_records_in_different_zones_are_refused(self):
        d, err = self.run_rollup([self.repo("a", PT), self.repo("b", "UTC")], PT)
        self.assertIsNone(d)
        self.assertIn("refusing to merge", err)
        self.assertIn("b: record cut in UTC, expected America/Los_Angeles", err)

    def test_records_disagreeing_with_the_registry_are_refused(self):
        d, err = self.run_rollup([self.repo("a", "UTC"), self.repo("b", "UTC")], PT)
        self.assertIsNone(d)
        self.assertIn("expected America/Los_Angeles", err)

    def test_legacy_beside_stamped_is_refused(self):
        d, err = self.run_rollup([self.repo("a", PT), self.repo("b", None)], PT)
        self.assertIsNone(d)
        self.assertIn("legacy records", err)

    def test_all_legacy_is_flagged_not_refused(self):
        d, err = self.run_rollup([self.repo("a", None), self.repo("b", None)], PT)
        self.assertIsNotNone(d)
        self.assertEqual(d["legacy_utc"], ["a", "b"])
        self.assertEqual(d["timezone"], "UTC")
        self.assertIn("legacy week records", err)

    def test_tampered_bounds_are_refused(self):
        r = self.repo("a", PT)
        p = os.path.join(r["path"], "catchup", "weeks", f"{W}.json")
        with open(p) as fh:
            rec = json.load(fh)
        rec["end"] = "2026-09-28T07:00:00-07:00"
        with open(p, "w") as fh:
            json.dump(rec, fh)
        d, err = self.run_rollup([r], PT)
        self.assertIsNone(d)
        self.assertIn("record bounds", err)

    def test_week_zone_copy_matches_catchup(self):
        other = os.path.join(HERE, "..", "..", "catchup", "scripts", "week_zone.py")
        if not os.path.isfile(other):
            self.skipTest("catchup skill not deployed beside this one")
        self.assertTrue(filecmp.cmp(os.path.join(SCRIPTS, "week_zone.py"), other, shallow=False))


if __name__ == "__main__":
    unittest.main(verbosity=1)
