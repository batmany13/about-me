import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "catchup_deepvista_cards", SCRIPT_DIR / "deepvista_cards.py")
deepvista_cards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deepvista_cards)


class DeepVistaPushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.store = self.repo / "catchup" / "entities"
        self.store.mkdir(parents=True)
        self.entity = {
            "id": "command-scope",
            "type": "concept",
            "title": "Command-scoped connection",
            "summary": "DeepVista connects only for an explicit applied command.",
            "category": "technical",
            "status": "active",
            "tags": [],
            "links": [],
            "weeks": {"2026-W35": {"claim": "The preview is local.", "grade": "measured"}},
            "deepvista": {"card_id": None, "synced_at": None, "content_hash": None},
        }
        (self.store / "command-scope.json").write_text(json.dumps(self.entity))
        self.cfg = {"repo": {"label": "fixture"}, "deepvista": {"enabled": True}}

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, apply=False):
        return argparse.Namespace(
            week="2026-W35", all=False, category=None, status=None, limit=0,
            force=False, apply=apply, npx=None, timeout=1)

    def test_preview_makes_no_mcp_connection(self):
        with mock.patch.object(deepvista_cards, "McpClient",
                               side_effect=AssertionError("preview opened MCP")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                deepvista_cards.cmd_push(
                    self.args(), str(self.repo), self.cfg, str(self.store))
        result = json.loads(out.getvalue())
        self.assertFalse(result["applied"])
        self.assertIn("No DeepVista call was made", result["next"])

    def test_apply_uses_one_short_lived_client_and_records_card(self):
        calls = []

        class FakeClient:
            attempts = 1
            reinits = 0

            def __init__(self, npx, timeout):
                calls.append(("open", npx, timeout))

            def call(self, tool, **kwargs):
                calls.append((tool, kwargs))
                return {"id": "card-1"}

            def close(self):
                calls.append(("close",))

        with mock.patch.object(deepvista_cards, "resolve_npx", return_value="/npx"), \
             mock.patch.object(deepvista_cards, "McpClient", FakeClient):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                deepvista_cards.cmd_push(
                    self.args(apply=True), str(self.repo), self.cfg, str(self.store))

        result = json.loads(out.getvalue())
        saved = json.loads((self.store / "command-scope.json").read_text())
        self.assertTrue(result["applied"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(saved["deepvista"]["card_id"], "card-1")
        self.assertEqual(calls[0][0], "open")
        self.assertEqual(calls[1][0], "upsert_context_card")
        self.assertEqual(calls[-1], ("close",))


class DeepVistaCardBodyTest(unittest.TestCase):
    def test_meeting_card_carries_what_is_owed_and_still_to_ask(self):
        """The half of a conversation that expires.

        The local summary has rendered these as sub-bullets since the meetings
        format was rewritten; the card renderer never emitted them, so the W35
        control's card-only summary could say what every conversation was about
        and not one thing it left outstanding.
        """
        entity = {
            "id": "meeting-acme",
            "type": "meeting",
            "title": "Acme — Dana",
            "summary": "First call.",
            "category": "meetings",
            "status": "active",
            "weeks": {"2026-W35": {
                "date": "2026-08-27",
                "note": "They walked through the pipeline.",
                "owed": ["Intro to the   infra lead", "Send the memo"],
                "asks": ["Their churn number"],
                "people": ["dana"],
            }},
        }
        body = deepvista_cards.render_body(entity, {"meetings": "Meetings"}, "fixture")
        self.assertIn("**Owed:**", body)
        self.assertIn("- Intro to the infra lead", body)   # whitespace collapsed
        self.assertIn("- Send the memo", body)
        self.assertIn("**Ask:**", body)
        self.assertIn("- Their churn number", body)
        # The note is the synthesis and still leads; the actions follow it.
        self.assertLess(body.index("They walked through"), body.index("**Owed:**"))
        self.assertLess(body.index("**Owed:**"), body.index("**Ask:**"))

    def test_an_entity_with_neither_gains_no_empty_headings(self):
        entity = {
            "id": "concept-x", "type": "concept", "title": "X", "summary": "s",
            "category": "technical", "status": "active",
            "weeks": {"2026-W35": {"claim": "c", "owed": [], "asks": None}},
        }
        body = deepvista_cards.render_body(entity, {}, "fixture")
        self.assertNotIn("**Owed:**", body)
        self.assertNotIn("**Ask:**", body)


class DeepVistaTechFieldsTest(unittest.TestCase):
    """The tech lane had the same defect as meetings, and more of it.

    A theme card carried what MOVED and never whether it stuck; a concept card
    carried a claim and never its rank; and PRs still open, where an entity is
    published, and who was in the room reached no card at all.
    """

    def test_theme_carries_disposition_and_consequence(self):
        e = {"id": "t", "type": "theme", "title": "T", "summary": "s",
             "category": "technical", "status": "active",
             "weeks": {"2026-W36": {"moved": "Rebuilt the ladder.",
                                    "disposition": "dropped",
                                    "consequence": "Cost a week and bought nothing."}}}
        body = deepvista_cards.render_body(e, {}, "fixture")
        self.assertIn("**Disposition:** dropped", body)
        self.assertIn("**Consequence:** Cost a week and bought nothing.", body)

    def test_concept_claim_carries_its_rank_beside_its_grade(self):
        e = {"id": "c", "type": "concept", "title": "C", "summary": "s",
             "category": "technical", "status": "active",
             "weeks": {"2026-W36": {"claim": "A cache hit is a validated computation.",
                                    "grade": "measured", "rank": 2}}}
        body = deepvista_cards.render_body(e, {}, "fixture")
        self.assertIn("*[measured]*", body)
        self.assertIn("*[rank 2]*", body)

    def test_attendees_render_as_names_and_open_prs_as_still_open(self):
        e = {"id": "m", "type": "meeting", "title": "M", "summary": "s",
             "category": "meeting", "status": "active",
             "links": ["dana-lee"],
             "weeks": {"2026-W36": {"attendees": ["dana-lee", "unknown-id"],
                                    "prs": ["12"], "open_prs": ["13"]}}}
        body = deepvista_cards.render_body(e, {}, "fixture", {"dana-lee": "Dana Lee"})
        self.assertIn("In the room: Dana Lee, unknown-id", body)   # id is the fallback
        self.assertIn("Still open: #13", body)
        # Related resolves the same way, so a card reads as names not slugs.
        self.assertIn("- Dana Lee (`dana-lee`)", body)

    def test_published_urls_reach_the_card(self):
        e = {"id": "p", "type": "thread", "title": "P", "summary": "s",
             "category": "technical", "status": "active",
             "urls": [{"label": "index", "url": "https://example.com/x/"}],
             "weeks": {"2026-W36": {"note": "n"}}}
        body = deepvista_cards.render_body(e, {}, "fixture")
        self.assertIn("## Published", body)
        self.assertIn("- [index](https://example.com/x/)", body)


class DeepVistaTypeFilterTest(unittest.TestCase):
    """`category` is the summary bucket, not the entity type.

    On a relationship repo `category: meeting` holds the people, companies,
    decisions and corrections as well -- 111 entities where `type: meeting` is
    15. A renderer fix that only changes meeting bodies needs the type, or the
    --force re-push spends a credit each on a hundred unchanged cards.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.store = self.repo / "catchup" / "entities"
        self.store.mkdir(parents=True)
        for eid, etype in (("m1", "meeting"), ("p1", "person"), ("o1", "org")):
            (self.store / f"{eid}.json").write_text(json.dumps({
                "id": eid, "type": etype, "title": eid, "summary": "s",
                "category": "meeting", "status": "active", "tags": [], "links": [],
                "weeks": {"2026-W35": {"note": "n"}},
                "deepvista": {"card_id": f"card-{eid}", "content_hash": None},
            }))
        self.cfg = {"repo": {"label": "fixture"}, "deepvista": {"enabled": True}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_type_narrows_within_a_category(self):
        args = argparse.Namespace(week=None, all=True, category="meeting", type=["meeting"],
                                  status=None, limit=0, force=True, show_body=True,
                                  include_skipped=False)
        result = deepvista_cards.build_plan(args, str(self.repo), self.cfg, str(self.store))
        self.assertEqual([i["entity_id"] for i in result["plan"]], ["m1"])

    def test_several_types_at_once(self):
        args = argparse.Namespace(week=None, all=True, category=None, type=["meeting", "org"],
                                  status=None, limit=0, force=True, show_body=True,
                                  include_skipped=False)
        result = deepvista_cards.build_plan(args, str(self.repo), self.cfg, str(self.store))
        self.assertEqual(sorted(i["entity_id"] for i in result["plan"]), ["m1", "o1"])

    def test_category_alone_still_takes_the_whole_bucket(self):
        args = argparse.Namespace(week=None, all=True, category="meeting", type=None,
                                  status=None, limit=0, force=True, show_body=True,
                                  include_skipped=False)
        result = deepvista_cards.build_plan(args, str(self.repo), self.cfg, str(self.store))
        self.assertEqual(len(result["plan"]), 3)


class DeepVistaRegistrationTest(unittest.TestCase):
    def test_repository_mcp_config_does_not_register_deepvista(self):
        root = Path(__file__).resolve().parents[4]
        config = root / ".mcp.json"
        if not config.is_file():
            return
        servers = json.loads(config.read_text()).get("mcpServers", {})
        self.assertNotIn(
            "api.deepvista.ai/mcp", json.dumps(servers).lower(),
            "DeepVista must be command-scoped; do not register it in .mcp.json")


if __name__ == "__main__":
    unittest.main()
