#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""One declared zone decides every week -- for commits and PRs alike.

The history this guards: slicing `%aI` read each author's zone while GitHub's
`mergedAt` is UTC, so the two halves of one pull disagreed; cutting in UTC
fixed that and put Sunday evening Pacific in the next week. 2026-W39 in the
tech repo counted a PR merged Sun Sep 20 20:47 PT (a W38 PR) and missed four
merged on the evening of Sun Sep 27 PT. Bruce, 2026-09-29: one declared zone,
stamped on every record.

Run: uv run tests/test_week_zone.py
"""
import argparse
import contextlib
import datetime as dt
import filecmp
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(f"catchup_{name}", os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wz = load("week_zone")
pull = load("pull_week")
ent = load("entities")

PT = "America/Los_Angeles"
W39 = wz.Week(2026, 39, PT)

# The four real shapes, as the two clocks write them.
COMMIT_SUN_2100_PT = "2026-09-27T21:00:00-07:00"      # git %aI, author in Pacific
MERGE_SUN_2235_PT = "2026-09-28T05:35:00Z"            # GitHub mergedAt: Sun 22:35 PT
MERGE_SUN_2047_PT_W38 = "2026-09-21T03:47:00Z"        # Sun Sep 20 20:47 PT -- a W38 PR
COMMIT_SUN_2100_PT_IN_UTC = "2026-09-28T04:00:00+00:00"  # same instant, rendered in UTC


class Boundaries(unittest.TestCase):
    def test_sunday_evening_commit_is_in_the_pacific_week(self):
        self.assertTrue(W39.contains(COMMIT_SUN_2100_PT))
        self.assertEqual(wz.week_of(COMMIT_SUN_2100_PT, W39.tz), "2026-W39")
        self.assertEqual(wz.local_date(COMMIT_SUN_2100_PT, W39.tz), dt.date(2026, 9, 27))

    def test_the_same_instant_in_another_offset_decides_the_same(self):
        # The old bug: the answer depended on which zone the timestamp was
        # RENDERED in. An instant is an instant.
        self.assertTrue(W39.contains(COMMIT_SUN_2100_PT_IN_UTC))
        self.assertEqual(wz.week_of(COMMIT_SUN_2100_PT_IN_UTC, W39.tz), "2026-W39")

    def test_sunday_late_merge_is_in_the_pacific_week(self):
        self.assertTrue(W39.contains(MERGE_SUN_2235_PT))
        self.assertEqual(wz.week_of(MERGE_SUN_2235_PT, W39.tz), "2026-W39")

    def test_previous_sunday_merge_is_not_in_the_next_week(self):
        self.assertFalse(W39.contains(MERGE_SUN_2047_PT_W38))
        self.assertEqual(wz.week_of(MERGE_SUN_2047_PT_W38, W39.tz), "2026-W38")

    def test_utc_cut_disagrees_exactly_as_w39_did(self):
        utc = wz.Week(2026, 39, "UTC")
        self.assertTrue(utc.contains(MERGE_SUN_2047_PT_W38))
        self.assertFalse(utc.contains(MERGE_SUN_2235_PT))

    def test_bounds_are_local_midnight_with_offsets(self):
        self.assertEqual(W39.start.isoformat(), "2026-09-21T00:00:00-07:00")
        self.assertEqual(W39.end.isoformat(), "2026-09-28T00:00:00-07:00")
        self.assertEqual(W39.footer(), "Week: Mon Sep 21 – Sun Sep 27, America/Los_Angeles")

    def test_dst_week_bounds(self):
        # 2026-W45: Mon Nov 2 .. Sun Nov 8. Clocks fell back Sun Nov 1, so the
        # week starts in PST; W44 straddles the change and is 169 hours long.
        w45 = wz.Week(2026, 45, PT)
        self.assertEqual(w45.start.isoformat(), "2026-11-02T00:00:00-08:00")
        self.assertEqual(w45.end.isoformat(), "2026-11-09T00:00:00-08:00")
        w44 = wz.Week(2026, 44, PT)
        self.assertEqual(w44.start.isoformat(), "2026-10-26T00:00:00-07:00")
        self.assertEqual(w44.end.isoformat(), "2026-11-02T00:00:00-08:00")
        self.assertEqual(w44.hours(), 169)
        self.assertEqual(w44.end, w45.start)
        # Sun Nov 1, 23:30 PST is still W44; Mon Nov 2 00:00 PST is W45.
        self.assertTrue(w44.contains("2026-11-02T07:30:00Z"))
        self.assertTrue(w45.contains("2026-11-02T08:00:00Z"))

    def test_spring_forward_week_is_167_hours(self):
        w = wz.Week(2026, 11, PT)   # Mar 9 .. Mar 15; DST began Sun Mar 8
        prev = wz.Week(2026, 10, PT)
        self.assertEqual(prev.hours(), 167)
        self.assertEqual(w.start.utcoffset(), dt.timedelta(hours=-7))

    def test_naive_and_garbage_timestamps_are_unplaceable(self):
        self.assertIsNone(wz.parse("2026-09-27T21:00:00"))
        self.assertIsNone(wz.parse("not a date"))
        self.assertFalse(W39.contains("2026-09-27"))

    def test_git_window_is_explicit_offset(self):
        since, until = W39.git_window(dt.timedelta(days=1))
        self.assertEqual(since, "2026-09-20T00:00:00-07:00")
        self.assertEqual(until, "2026-09-29T00:00:00-07:00")

    def test_bad_zone_is_a_readable_error(self):
        with self.assertRaises(ValueError) as cm:
            wz.zone("Pacific/Nowhere")
        self.assertIn("IANA", str(cm.exception))


class Choosing(unittest.TestCase):
    def test_utc_default_with_notice(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            name, source = wz.choose(None, None, where="x.json", prog="t")
        self.assertEqual((name, source), ("UTC", "default"))
        self.assertIn("no timezone declared in x.json", err.getvalue())
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)

    def test_declared_is_silent_and_cli_wins(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(wz.choose(None, PT), (PT, "declared"))
            self.assertEqual(wz.choose("UTC", PT), ("UTC", "cli"))
        self.assertEqual(err.getvalue(), "")


def git(repo, *args, env=None):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


class PullCutsInTheDeclaredZone(unittest.TestCase):
    """The pull, end to end on a scratch repo, with gh answered by a fake."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        for when, name in ((COMMIT_SUN_2100_PT, "late-sunday"),
                           ("2026-09-20T20:30:00-07:00", "previous-sunday")):
            with open(os.path.join(self.repo, name + ".py"), "w") as fh:
                fh.write("x = 1\n")
            git(self.repo, "add", "-A")
            env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
            git(self.repo, "commit", "-q", "-m", f"fix: {name}", env=env)
        self.gh_merged = json.dumps([
            {"number": 2, "mergedAt": MERGE_SUN_2235_PT},
            {"number": 1, "mergedAt": MERGE_SUN_2047_PT_W38},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, args, cwd=None, timeout=60):
        if args[:3] == ["gh", "pr", "list"]:
            if "open" in args:
                return "0"
            if "number,mergedAt" in args:
                return self.gh_merged
            return "[]"
        if args[:3] == ["gh", "pr", "view"]:
            return "[]"
        return self.real_run(args, cwd=cwd, timeout=timeout)

    def collect(self, tz_name):
        self.real_run = pull.run
        cfg = pull.load_config(self.repo)
        with mock.patch.object(pull, "run", side_effect=self.fake_run):
            return pull.collect(self.repo, 2026, 39, cfg, pull.build_matchers(cfg),
                                fetch=False, tz_name=tz_name, today=dt.date(2026, 9, 29))

    def test_pacific(self):
        w = self.collect(PT)
        self.assertEqual(w["timezone"], PT)
        self.assertEqual(w["start"], "2026-09-21T00:00:00-07:00")
        self.assertEqual(w["end"], "2026-09-28T00:00:00-07:00")
        self.assertEqual([c["subject"] for c in w["commits"]], ["fix: late-sunday"])
        self.assertEqual(w["commits"][0]["date"], "2026-09-27")
        self.assertEqual(w["prs_merged"], 1)

    def test_utc_cuts_differently(self):
        w = self.collect("UTC")
        self.assertEqual([c["subject"] for c in w["commits"]], ["fix: previous-sunday"])
        self.assertEqual(w["prs_merged"], 1)   # the previous Sunday's PR

    def test_machine_zone_does_not_move_the_week(self):
        # Same pull under a far-away machine zone: explicit offsets, same answer.
        script = os.path.join(SCRIPTS, "pull_week.py")
        cfgp = os.path.join(self.tmp.name, "cfg.json")
        with open(cfgp, "w") as fh:
            json.dump({"week": {"timezone": PT}}, fh)
        out = {}
        for tz in ("Asia/Tokyo", "Pacific/Honolulu", "UTC"):
            env = dict(os.environ, TZ=tz, PATH="/usr/bin:/bin")   # no gh on PATH
            r = subprocess.run([sys.executable, script, "2026-W39", "--repo", self.repo,
                                "--config", cfgp, "--no-fetch", "--no-prs"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            blob = json.loads(r.stdout)
            self.assertEqual(blob["timezone"], PT)
            out[tz] = [c["sha"] for c in blob["weeks"][0]["commits"]]
            self.assertNotIn("no timezone declared", r.stderr)
        self.assertEqual(len({tuple(v) for v in out.values()}), 1)
        self.assertEqual(len(out["UTC"]), 1)

    def test_no_config_means_utc_and_a_notice(self):
        script = os.path.join(SCRIPTS, "pull_week.py")
        env = dict(os.environ, PATH="/usr/bin:/bin")
        r = subprocess.run([sys.executable, script, "2026-W39", "--repo", self.repo,
                            "--no-fetch", "--no-prs"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no timezone declared", r.stderr)
        blob = json.loads(r.stdout)
        self.assertEqual((blob["timezone"], blob["timezone_source"]), ("UTC", "default"))
        self.assertEqual(blob["weeks"][0]["start"], "2026-09-21T00:00:00+00:00")


class RecordsCarryTheZone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        os.makedirs(os.path.join(self.repo, ".claude"))
        self.cfg = {"week": {"timezone": PT}}
        with open(os.path.join(self.repo, ".claude", "catchup.config.json"), "w") as fh:
            json.dump(self.cfg, fh)
        self.sdir = ent.store_dir(self.repo, self.cfg)
        os.makedirs(self.sdir)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, tz):
        pullp = os.path.join(self.repo, "pull.json")
        with open(pullp, "w") as fh:
            json.dump({"timezone": tz, "weeks": [dict(
                week="2026-W39", **wz.Week(2026, 39, tz).stamp(), partial=False,
                commit_count=3, commit_count_primary=3, prs_merged=2)]}, fh)
        args = argparse.Namespace(week="2026-W39", pull=pullp)
        with contextlib.redirect_stdout(io.StringIO()):
            ent.cmd_record_week(args, self.repo, self.cfg, self.sdir)
        with open(os.path.join(ent.weeks_dir(self.repo, self.cfg), "2026-W39.json")) as fh:
            return json.load(fh)

    def test_record_is_stamped(self):
        rec = self.record(PT)
        self.assertEqual(rec["timezone"], PT)
        self.assertEqual(rec["start"], "2026-09-21T00:00:00-07:00")
        self.assertEqual(rec["end"], "2026-09-28T00:00:00-07:00")
        self.assertEqual(rec["first_day"], "2026-09-21")

    def test_record_refuses_a_pull_from_another_zone(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.record("UTC")

    def test_stat_line_says_the_zone(self):
        rec = self.record(PT)
        line = ent.stat_line(self.cfg, rec, [], "2026-W39")
        self.assertTrue(line.endswith("*Week: Mon Sep 21 – Sun Sep 27, America/Los_Angeles.*"), line)
        # A legacy record says nothing rather than guessing.
        legacy = {k: v for k, v in rec.items() if k != "timezone"}
        self.assertNotIn("Week:", ent.stat_line(self.cfg, legacy, [], "2026-W39"))

    def check_summary(self):
        with open(os.path.join(self.repo, "catchup", "2026-W39.md"), "w") as fh:
            fh.write("# 2026-W39\n\nNothing cited.\n")
        out = io.StringIO()
        args = argparse.Namespace(week="2026-W39")
        try:
            with contextlib.redirect_stdout(out):
                ent.cmd_check_summary(args, self.repo, self.cfg, self.sdir)
            return 0, out.getvalue()
        except SystemExit as e:
            return e.code, out.getvalue()

    def test_check_summary_passes_on_matching_zone(self):
        self.record(PT)
        code, out = self.check_summary()
        self.assertEqual(code, 0, out)

    def test_check_summary_fails_on_a_record_from_another_zone(self):
        self.record(PT)
        rpath = os.path.join(ent.weeks_dir(self.repo, self.cfg), "2026-W39.json")
        with open(rpath) as fh:
            rec = json.load(fh)
        rec.pop("timezone")        # a legacy record: cut in UTC
        with open(rpath, "w") as fh:
            json.dump(rec, fh)
        code, out = self.check_summary()
        self.assertEqual(code, 1)
        self.assertIn("cut in UTC (legacy", out)


class CopiesStayIdentical(unittest.TestCase):
    """week_zone.py is duplicated into each skill that decides weeks. Keep them one file."""

    def test_sibling_copies(self):
        skills = os.path.abspath(os.path.join(HERE, "..", ".."))
        mine = os.path.join(SCRIPTS, "week_zone.py")
        found = 0
        for sib in ("rollup", "fnr"):
            other = os.path.join(skills, sib, "scripts", "week_zone.py")
            if os.path.isfile(other):
                found += 1
                self.assertTrue(filecmp.cmp(mine, other, shallow=False),
                                f"{sib}/scripts/week_zone.py differs from catchup's copy")
        if not found:
            self.skipTest("no sibling skill deployed beside this one")


if __name__ == "__main__":
    unittest.main(verbosity=1)
