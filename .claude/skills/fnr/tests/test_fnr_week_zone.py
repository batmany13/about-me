#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The fnr pull cuts the week in the registry's zone -- the catchup's zone.

It used to pass naive `--since/--until` dates to git, which git reads in the
MACHINE's zone, and slice `%aI[:10]` in each author's zone -- so it disagreed
with the catchup it is meant to agree with.

Run: uv run tests/test_fnr_week_zone.py
"""
import filecmp
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "pull_week.py")
PT = "America/Los_Angeles"


def git(repo, *args, env=None):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


class FnrPull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "src")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        for when, name in (("2026-09-27T21:00:00-07:00", "late-sunday"),
                           ("2026-09-20T20:47:00-07:00", "previous-sunday")):
            with open(os.path.join(self.repo, name), "w") as fh:
                fh.write(name)
            git(self.repo, "add", "-A")
            env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
            git(self.repo, "commit", "-q", "-m", name, env=env)

    def tearDown(self):
        self.tmp.cleanup()

    def pull(self, registry, machine_tz="UTC", extra=()):
        path = os.path.join(self.tmp.name, "repos.json")
        with open(path, "w") as fh:
            json.dump(registry, fh)
        env = dict(os.environ, TZ=machine_tz, PATH="/usr/bin:/bin")   # no gh
        r = subprocess.run([sys.executable, SCRIPT, "2026-W39", "--repos-json", path, *extra],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), r.stderr

    def registry(self, **top):
        return dict(top, repos=[{"name": "src", "path": self.repo, "lane": "work",
                                 "disclosure": "named", "public_stats": True}])

    def test_registry_zone_cuts_the_week(self):
        for machine in ("UTC", "Asia/Tokyo", "America/New_York"):
            blob, err = self.pull(self.registry(timezone=PT), machine)
            self.assertEqual(blob["timezone"], PT)
            self.assertEqual(blob["start"], "2026-09-21T00:00:00-07:00")
            self.assertEqual(blob["end"], "2026-09-28T00:00:00-07:00")
            subjects = [c["subject"] for c in blob["repos"][0]["commits"]]
            self.assertEqual(subjects, ["late-sunday"], machine)
            self.assertEqual(blob["repos"][0]["commits"][0]["date"], "2026-09-27")
            self.assertNotIn("no timezone declared", err)

    def test_undeclared_is_utc_with_notice(self):
        blob, err = self.pull(self.registry())
        self.assertEqual((blob["timezone"], blob["timezone_source"]), ("UTC", "default"))
        self.assertIn("no timezone declared", err)
        self.assertEqual([c["subject"] for c in blob["repos"][0]["commits"]], ["previous-sunday"])

    def test_cli_overrides_registry(self):
        blob, _ = self.pull(self.registry(timezone=PT), extra=("--timezone", "UTC"))
        self.assertEqual(blob["timezone"], "UTC")

    def test_repo_declaring_another_zone_is_warned(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        with open(os.path.join(self.repo, ".claude", "catchup.config.json"), "w") as fh:
            json.dump({"week": {"timezone": "UTC"}}, fh)
        blob, err = self.pull(self.registry(timezone=PT))
        self.assertEqual(blob["repos"][0]["declared_timezone"], "UTC")
        self.assertIn("the rollup will refuse", err)

    def test_week_zone_copy_matches_catchup(self):
        mine = os.path.join(HERE, "..", "scripts", "week_zone.py")
        other = os.path.join(HERE, "..", "..", "catchup", "scripts", "week_zone.py")
        if not os.path.isfile(other):
            self.skipTest("catchup skill not beside this one")
        self.assertTrue(filecmp.cmp(mine, other, shallow=False))


if __name__ == "__main__":
    unittest.main(verbosity=1)
