#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Six defects one weekly run hit, each needing a manual workaround.

  1. The pull read the mainline only, so a thread whose week lived on an open
     PR read as "no commits". `open_prs_in_week` lists those PRs.
  2. `validate` failed a past week's `open_prs` once the PR merged later. It
     now judges the entry against the week's own end.
  3. `check-summary` ignored `open_prs`, and read any hex run as a commit.
  4. The render printed a citation twice, and a "chars trimmed" marker into
     the summary instead of failing the over-long child note.
  5. The DeepVista push sent an argument the server rejects, and pushed
     confidential entities.
  6. (Docs and config only -- the calendar block. Checked here for shape.)

Run: uv run tests/test_open_prs_and_citations.py
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pull = load("pull_week")
ent = load("entities")
dvc = load("deepvista_cards")
import week_zone  # noqa: E402

W = "2026-W41"
TZ = "America/Los_Angeles"


def quiet(fn, *a, **kw):
    """Run fn; return (stdout, exit code or None)."""
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(*a, **kw)
        except SystemExit as e:
            code = e.code
    return out.getvalue(), code


# ---------------------------------------------------------------- 1. the pull

class OpenPrsInWeek(unittest.TestCase):
    def setUp(self):
        self.win = week_zone.Week.from_label(W, TZ)   # Mon Oct 5 – Sun Oct 11, Pacific
        self.ign = pull.build_ignore(pull.load_config(tempfile.gettempdir()))

    def commit(self, when, subject="work", oid="abcdef1234567"):
        return {"authoredDate": when, "messageHeadline": subject, "oid": oid}

    def test_a_draft_with_in_week_commits_is_listed(self):
        prs = [{"number": 80, "title": "Outcome work", "isDraft": True,
                "updatedAt": "2026-10-11T20:00:00Z", "headRefName": "b", "baseRefName": "main"}]
        commits = {80: [self.commit("2026-10-06T10:00:00-07:00", oid="1111111aaaa"),
                         self.commit("2026-10-11T22:00:00-07:00", oid="2222222bbbb"),
                         self.commit("2026-09-30T10:00:00-07:00", oid="3333333cccc")]}
        out = pull.open_prs_in_week(prs, commits.get, self.win, self.ign)
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p["number"], 80)
        self.assertTrue(p["draft"])
        # Sunday 22:00 Pacific is Monday in UTC -- still this week.
        self.assertEqual(p["commits_in_week"], 2)
        self.assertEqual(p["commits_total"], 3)
        self.assertEqual((p["first_day"], p["last_day"]), ("2026-10-06", "2026-10-11"))
        self.assertEqual(p["shas"], ["1111111aa", "2222222bb"])

    def test_merge_from_base_is_bookkeeping(self):
        prs = [{"number": 5, "updatedAt": "2026-10-07T00:00:00Z"}]
        commits = {5: [self.commit("2026-10-07T10:00:00-07:00", "Merge branch 'main' into x")]}
        self.assertEqual(pull.open_prs_in_week(prs, commits.get, self.win, self.ign), [])

    def test_untouched_since_the_week_opened_is_not_fetched(self):
        prs = [{"number": 7, "updatedAt": "2026-09-01T00:00:00Z"}]

        def boom(n):
            raise AssertionError("fetched commits for a PR not updated this week")
        self.assertEqual(pull.open_prs_in_week(prs, boom, self.win, self.ign), [])

    def test_unreadable_gh_is_none_not_empty(self):
        for answer in ("", "0", "{}", "not json"):
            with mock.patch.object(pull, "run", return_value=answer):
                self.assertIsNone(pull.gh_open_prs_in_week(".", self.win, self.ign), answer)

    def test_largest_first(self):
        prs = [{"number": 1, "updatedAt": "2026-10-08T00:00:00Z"},
               {"number": 2, "updatedAt": "2026-10-08T00:00:00Z"}]
        commits = {1: [self.commit("2026-10-07T10:00:00-07:00")],
                   2: [self.commit("2026-10-07T10:00:00-07:00")] * 3}
        out = pull.open_prs_in_week(prs, commits.get, self.win, self.ign)
        self.assertEqual([p["number"] for p in out], [2, 1])


class ProposeShowsOpenPrs(unittest.TestCase):
    def pull_file(self, commits, open_prs):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"weeks": [{"week": W, "commits": commits, "pr_details": [],
                              "open_prs_in_week": open_prs}]}, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def args(self, path):
        return argparse.Namespace(week=W, pull=path)

    OPEN = [{"number": 80, "title": "Outcome work", "draft": True, "commits_in_week": 12,
             "first_day": "2026-10-06", "last_day": "2026-10-11"}]

    def test_no_mainline_commits_is_not_an_empty_week(self):
        out, code = quiet(ent.cmd_propose, self.args(self.pull_file([], self.OPEN)), ".", {}, ".")
        self.assertIsNone(code)
        self.assertIn("#80", out)
        self.assertIn("12 commits", out)
        self.assertIn("open_prs", out)

    def test_listed_beside_the_mainline_clusters(self):
        commits = [{"sha": "a1b2c3d4e", "date": "2026-10-06", "subject": "x",
                    "paths": ["src/a.py"], "insertions": 3, "deletions": 1}]
        out, code = quiet(ent.cmd_propose, self.args(self.pull_file(commits, self.OPEN)), ".", {}, ".")
        self.assertIsNone(code)
        self.assertIn("Open PRs with commits authored this week", out)
        self.assertIn("#80", out)

    def test_unchecked_is_not_none(self):
        commits = [{"sha": "a1b2c3d4e", "date": "2026-10-06", "subject": "x", "paths": []}]
        out, _ = quiet(ent.cmd_propose, self.args(self.pull_file(commits, None)), ".", {}, ".")
        self.assertIn("NOT CHECKED", out)

    def test_nothing_anywhere_still_stops(self):
        _, code = quiet(ent.cmd_propose, self.args(self.pull_file([], [])), ".", {}, ".")
        self.assertEqual(code, 1)


# ------------------------------------------------------------- a store fixture

class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        self.cfg = {"week": {"timezone": TZ}}
        self.sdir = ent.store_dir(self.repo, self.cfg)
        self.wdir = ent.weeks_dir(self.repo, self.cfg)
        os.makedirs(self.wdir, exist_ok=True)

    def put(self, week=W, **raw):
        e = ent.merge(None, ent.normalize(raw, week))
        ent.write_entity(self.sdir, e)
        return e

    def record(self, week=W, **extra):
        win = week_zone.Week.from_label(week, TZ)
        rec = {"week": week, **win.stamp(), "stats": {"pr_numbers": []}}
        rec.update(extra)
        with open(os.path.join(self.wdir, f"{week}.json"), "w") as fh:
            json.dump(rec, fh)

    def summary(self, text, week=W):
        path = os.path.join(self.repo, "catchup", f"{week}.md")
        with open(path, "w") as fh:
            fh.write(text)

    def check(self, week=W):
        return quiet(ent.cmd_check_summary, argparse.Namespace(week=week),
                     self.repo, self.cfg, self.sdir)


# ------------------------------------------------------------ 2. validate

class OpenPrsJudgedAtTheirWeek(Store):
    def test_merged_after_the_week_closed_is_fine(self):
        end = week_zone.Week.from_label("2026-W40", TZ).end
        self.assertIsNone(ent.open_pr_problem("x", "2026-W40", 70, "2026-10-06T18:00:00Z", end))

    def test_merged_before_the_week_closed_fails(self):
        end = week_zone.Week.from_label("2026-W40", TZ).end
        self.assertIn("before the week closed",
                      ent.open_pr_problem("x", "2026-W40", 70, "2026-10-02T18:00:00Z", end))

    def test_still_open_is_fine(self):
        self.assertIsNone(ent.open_pr_problem("x", W, 1, None,
                                              week_zone.Week.from_label(W, TZ).end))

    def test_the_record_stamp_decides(self):
        # A legacy record cut in UTC ends at Monday 00:00 UTC, which is Sunday
        # 17:00 Pacific. The record's own cut is the authority, not the config.
        with open(os.path.join(self.wdir, "2026-W40.json"), "w") as fh:
            json.dump({"week": "2026-W40", "stats": {}}, fh)
        end = ent.week_end(self.repo, self.cfg, "2026-W40")
        self.assertEqual(end, week_zone.Week.from_label("2026-W40", "UTC").end)
        self.record("2026-W40")
        self.assertEqual(ent.week_end(self.repo, self.cfg, "2026-W40"),
                         week_zone.Week.from_label("2026-W40", TZ).end)

    def test_validate_end_to_end(self):
        self.put(week="2026-W40", id="draft-thread", type="thread", category="technical",
                 title="Draft", note="n", open_prs=[70])
        self.record("2026-W40")
        later = {70: "2026-10-07T18:00:00Z"}            # merged in W41
        with mock.patch.object(ent, "merged_pr_times", return_value=later), \
             mock.patch.object(ent, "mainline_shas", return_value=(None, None)):
            out, code = quiet(ent.cmd_validate, argparse.Namespace(no_gh=False),
                              self.repo, self.cfg, self.sdir)
        self.assertIsNone(code, out)
        earlier = {70: "2026-10-01T18:00:00Z"}          # merged inside W40
        with mock.patch.object(ent, "merged_pr_times", return_value=earlier), \
             mock.patch.object(ent, "mainline_shas", return_value=(None, None)):
            out, code = quiet(ent.cmd_validate, argparse.Namespace(no_gh=False),
                              self.repo, self.cfg, self.sdir)
        self.assertEqual(code, 1)
        self.assertIn("PR #70 is listed as open", out)


# -------------------------------------------------------- 3. check-summary

class ShaContext(unittest.TestCase):
    def test_bare_and_code_span_shas_count(self):
        self.assertEqual(ent.cited_commit_shas("fixed in a1b2c3d and `9f8e7d6c`."),
                         {"a1b2c3d", "9f8e7d6c"})

    def test_a_word_is_not_a_sha(self):
        self.assertEqual(ent.cited_commit_shas("the defaced page"), set())

    def test_quoted_and_introduced_ids_do_not(self):
        for text in ('the research hash 3f9a1c2e', 'run id: 3f9a1c2e', '"3f9a1c2e"',
                     '`bundle-3f9a1c2e`', 'see run-3f9a1c2e', 'at reports/3f9a1c2e/',
                     'https://example.com/r/3f9a1c2e', 'sha256 3f9a1c2e4b'):
            self.assertEqual(ent.cited_commit_shas(text), set(), text)


class CheckSummary(Store):
    def base(self, **kw):
        self.put(id="outcome", type="theme", category="technical", title="Outcome",
                 note="n", moved="m", why_it_matters="w", consequence="major", weight={"commits": 1, "share": 0.5},
                 commits=["a1b2c3d4e"], **kw)

    def test_open_pr_citation_passes(self):
        self.base(open_prs=[90])
        self.record()
        self.summary("# W\n\nThe rework is in review (draft #90).\n")
        out, code = self.check()
        self.assertIsNone(code, out)
        self.assertIn("1 open PRs", out)

    def test_an_uncarried_pr_still_fails(self):
        self.base(open_prs=[90])
        self.record()
        self.summary("# W\n\nSomething (#91).\n")
        out, code = self.check()
        self.assertEqual(code, 1)
        self.assertIn("PR #91 is cited in the summary but carried by no entity", out)

    def test_an_open_pr_on_the_merged_line_fails(self):
        self.base(open_prs=[90])
        self.record()
        self.summary("# W\n\nPRs merged: #90\n")
        out, code = self.check()
        self.assertEqual(code, 1)
        self.assertIn("did not merge this week", out)

    def test_quoted_research_hash_passes_and_a_real_sha_is_held(self):
        self.base()
        self.record()
        self.summary("# W\n\nThe research hash 3f9a1c2e matched. Landed in a1b2c3d.\n")
        out, code = self.check()
        self.assertIsNone(code, out)
        self.summary("# W\n\nLanded in 7e6d5c4.\n")
        out, code = self.check()
        self.assertEqual(code, 1)
        self.assertIn("commit 7e6d5c4", out)

    def test_long_theme_child_fails_with_its_id(self):
        self.base()
        self.put(id="step-one", type="thread", category="technical", title="Step 1",
                 note="x" * 300, theme="outcome")
        self.record()
        self.summary("# W\n")
        out, code = self.check()
        self.assertEqual(code, 1)
        self.assertIn("`step-one`", out)
        self.assertIn("300-char note", out)

    def test_no_cap_where_the_layout_renders_no_themes(self):
        self.cfg["summary"] = {"layout": [{"section": "meetings"}, {"section": "other"}]}
        self.base()
        self.put(id="step-one", type="thread", category="technical", title="Step 1",
                 note="x" * 300, theme="outcome")
        self.record()
        self.summary("# W\n")
        out, code = self.check()
        self.assertIsNone(code, out)

    def test_uncarried_open_pr_with_week_commits_warns(self):
        self.base()
        self.record(stats={"pr_numbers": [], "open_prs_in_week": [
            {"number": 80, "commits": 12, "draft": True}]})
        self.summary("# W\n")
        out, code = self.check()
        self.assertIsNone(code, out)
        self.assertIn("#80 (12 commits)", out)


# ----------------------------------------------------------------- 4. render

class Render(Store):
    def render(self):
        args = argparse.Namespace(week=W, with_open=False, learnings_top=4)
        return quiet(ent.cmd_render, args, self.repo, self.cfg, self.sdir)

    def test_citation_tail(self):
        self.assertEqual(ent.citation_tail("landed (#12).", [12]), "")
        self.assertEqual(ent.citation_tail("landed (#12, #14)", [14, 12]), "")
        self.assertEqual(ent.citation_tail("landed (#12).", [12, 14]), " (#14)")
        self.assertEqual(ent.citation_tail("#12 landed.", [12]), " (#12)")
        self.assertEqual(ent.citation_tail("landed", []), "")

    def test_other_does_not_repeat_a_citation(self):
        self.put(id="loose", type="decision", category="other", title="Loose",
                 note="It shipped (#12).", prs=[12])
        out, code = self.render()
        self.assertIsNone(code, out)
        self.assertIn("It shipped (#12).", out)
        self.assertNotIn("(#12). (#12)", out)
        self.assertEqual(out.count("#12"), 1)

    def test_long_child_is_printed_whole(self):
        self.put(id="outcome", type="theme", category="technical", title="Outcome",
                 note="n", moved="m", why_it_matters="w", consequence="major", weight={"commits": 1, "share": 0.5})
        long = "First sentence. " + "word " * 80
        self.put(id="step-one", type="thread", category="technical", title="Step 1",
                 note=long, theme="outcome")
        out, code = self.render()
        self.assertIsNone(code, out)
        self.assertNotIn("chars trimmed", out)
        self.assertIn(" ".join(long.split()), out)


# -------------------------------------------------------------- 5. DeepVista

class DeepVistaPush(Store):
    def setUp(self):
        super().setUp()
        self.cfg = {"repo": {"label": "fixture"}, "deepvista": {"enabled": True}}
        self.sdir = ent.store_dir(self.repo, self.cfg)
        a = self.put(id="alpha", type="thread", category="technical", title="Alpha",
                     note="n", links=["beta"])
        b = self.put(id="beta", type="thread", category="technical", title="Beta", note="n")
        b["deepvista"] = {"card_id": "card-beta", "content_hash": ent.content_hash(b)}
        ent.write_entity(self.sdir, b)
        self.put(id="secret", type="org", category="meeting", title="Secret",
                 note="n", confidential=True)

    def push(self, **kw):
        base = dict(week=W, all=False, category=None, type=None, status=None, limit=0,
                    force=False, apply=True, npx=None, timeout=1)
        base.update(kw)
        calls = []

        class Fake:
            attempts, reinits = 1, 0

            def __init__(self, npx, timeout):
                pass

            def call(self, tool, **kwargs):
                calls.append((tool, kwargs))
                return {"id": f"card-{len(calls)}"}

            def close(self):
                pass

        with mock.patch.object(dvc, "resolve_npx", return_value="/npx"), \
             mock.patch.object(dvc, "McpClient", Fake):
            out, code = quiet(dvc.cmd_push, argparse.Namespace(**base),
                              self.repo, self.cfg, self.sdir)
        self.assertIsNone(code, out)
        return calls

    def test_edges_go_as_relations(self):
        calls = self.push()
        upserts = {kw["properties"]["title"]: kw for tool, kw in calls
                   if tool == "upsert_context_card"}
        alpha = upserts["Alpha"]
        self.assertNotIn("related_context_card_ids", alpha)
        self.assertEqual(alpha["relations"], [{"card_id": "card-beta", "rel_type": "related"}])
        for kw in upserts.values():
            self.assertNotIn("related_context_card_ids", kw)

    def test_rel_type_can_be_overridden(self):
        self.assertEqual(dvc.relations_for(["c"], {"related_rel_type": "relates_to"}),
                         [{"card_id": "c", "rel_type": "relates_to"}])

    def test_confidential_is_held_back(self):
        titles = [kw["properties"]["title"] for tool, kw in self.push()]
        self.assertNotIn("Secret", titles)
        plan = dvc.build_plan(argparse.Namespace(
            week=W, all=False, category=None, type=None, status=None, limit=0, force=False,
            show_body=False, include_skipped=False), self.repo, self.cfg, self.sdir)
        self.assertEqual(plan["counts"]["confidential"], 1)
        self.assertEqual(plan["confidential_held_back"], ["secret"])

    def test_include_confidential_pushes_it(self):
        titles = [kw["properties"]["title"] for tool, kw in self.push(include_confidential=True)]
        self.assertIn("Secret", titles)


# ----------------------------------------------------------- 6. calendar shape

class CalendarConfig(unittest.TestCase):
    def test_example_declares_the_block_generically(self):
        with open(os.path.join(HERE, "..", "assets", "catchup.config.example.json")) as fh:
            cal = json.load(fh)["calendar"]
        self.assertIs(cal["correlate"], False)
        for key in ("source", "notes", "match_open_prs", "drop_keywords", "gap_entity"):
            self.assertIn(key, cal)
        # A placeholder, never an address.
        self.assertNotIn("@", cal["source"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
