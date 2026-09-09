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


class DeepVistaRowsTest(unittest.TestCase):
    """Rows are a typed edge with REPLACE semantics, so the dangerous case is
    not a failed write -- it is a successful one that silently deletes rows
    this repo never knew about."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.store = self.repo / "catchup" / "entities"
        self.store.mkdir(parents=True)
        self.write("acme", type="org", tags=["portfolio"], card_id="card-acme")
        self.write("beta", type="org", tags=["watchlist"], card_id="card-beta")
        self.write("gamma", type="org", tags=["portfolio"], card_id=None)
        self.cfg = {
            "repo": {"label": "fixture"},
            "deepvista": {
                "enabled": True,
                "databases": [{"card_id": "db-1", "types": ["org"],
                               "tags_any": ["portfolio"]}],
            },
        }

    def write(self, eid, type, tags, card_id):
        (self.store / f"{eid}.json").write_text(json.dumps({
            "id": eid, "type": type, "title": eid.title(), "summary": "s",
            "category": "orgs", "status": "active", "tags": tags, "links": [],
            "weeks": {"2026-W35": {"claim": "c"}},
            "deepvista": {"card_id": card_id, "synced_at": None, "content_hash": None},
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, **kw):
        base = dict(week="2026-W35", database=None, apply=False, prune=False,
                    force=False, limit=500, npx=None, timeout=1)
        base.update(kw)
        return argparse.Namespace(**base)

    def run_cmd(self, args, client=None):
        out = io.StringIO()
        ctx = mock.patch.object(deepvista_cards, "McpClient",
                                client or mock.Mock(side_effect=AssertionError("opened MCP")))
        with mock.patch.object(deepvista_cards, "resolve_npx", return_value="/npx"), ctx:
            with contextlib.redirect_stdout(out):
                deepvista_cards.cmd_rows(args, str(self.repo), self.cfg, str(self.store))
        return json.loads(out.getvalue())

    def test_preview_is_local_and_reports_unpushed(self):
        result = self.run_cmd(self.args())
        self.assertFalse(result["applied"])
        entry = result["databases"][0]
        self.assertEqual([r["card_id"] for r in entry["ours"]], ["card-acme"])
        # Selected by tag but never pushed, so it cannot be a row -- and an
        # empty-looking grid caused by an unfinished push is worth naming.
        self.assertEqual(entry["unpushed"], ["gamma"])

    def test_apply_writes_the_union_and_never_drops_a_foreign_row(self):
        seen = []

        class FakeClient:
            attempts, reinits = 1, 0

            def __init__(self, npx, timeout):
                pass

            def call(self, tool, **kw):
                seen.append((tool, kw))
                if tool == "list_related_context_cards":
                    # A row a human added in the product, and one of ours.
                    return {"cards": [{"card_id": "human-row"}, {"card_id": "card-acme"}]}
                if tool == "read_context_card":
                    return {"id": "db-1", "type": "database", "title": "DB",
                            "description": "body", "status": "active"}
                return {"id": "db-1"}

            def close(self):
                pass

        result = self.run_cmd(self.args(apply=True), client=FakeClient)
        self.assertTrue(result["applied"])
        # card-acme was already a row and nothing else selects, so there is
        # nothing to add and no credit to spend.
        self.assertFalse(result["databases"][0]["written"])
        self.assertEqual(result["databases"][0]["reason"], "already current")
        self.assertNotIn("upsert_context_card", [t for t, _ in seen])

    def test_apply_sends_properties_with_the_relations(self):
        seen = []

        class FakeClient:
            attempts, reinits = 1, 0

            def __init__(self, npx, timeout):
                pass

            def call(self, tool, **kw):
                seen.append((tool, kw))
                if tool == "list_related_context_cards":
                    return {"cards": [{"card_id": "human-row"}]}
                if tool == "read_context_card":
                    return {"id": "db-1", "type": "database", "title": "DB",
                            "description": "body", "status": "active"}
                return {"id": "db-1"}

            def close(self):
                pass

        result = self.run_cmd(self.args(apply=True), client=FakeClient)
        upsert = [kw for t, kw in seen if t == "upsert_context_card"][0]
        rows = [r["card_id"] for r in upsert["relations"]]
        # The human's row survives, ours joins it, and every edge is typed.
        self.assertEqual(rows, ["human-row", "card-acme"])
        self.assertTrue(all(r["rel_type"] == "row_of" for r in upsert["relations"]))
        # Properties travel WITH the relations: a links-only upsert re-saved 41
        # card bodies through an HTML-escaping pass on 2026-09-02.
        self.assertEqual(upsert["properties"]["description"], "body")
        self.assertTrue(result["databases"][0]["written"])

    def test_prune_removes_only_our_own_deselected_rows(self):
        class FakeClient:
            attempts, reinits = 1, 0

            def __init__(self, npx, timeout):
                pass

            def call(self, tool, **kw):
                if tool == "list_related_context_cards":
                    # card-beta is ours (watchlist, so no longer selected);
                    # human-row is nobody's.
                    return {"cards": [{"card_id": "human-row"},
                                      {"card_id": "card-beta"}]}
                if tool == "read_context_card":
                    return {"id": "db-1", "type": "database", "title": "DB",
                            "description": "body", "status": "active"}
                return {"id": "db-1"}

            def close(self):
                pass

        result = self.run_cmd(self.args(apply=True, prune=True), client=FakeClient)
        entry = result["databases"][0]
        self.assertEqual([d["entity_id"] for d in entry["dropped"]], ["beta"])
        self.assertEqual(entry["added"], ["card-acme"])

    def test_a_truncated_row_read_refuses_to_write(self):
        class FakeClient:
            attempts, reinits = 1, 0

            def __init__(self, npx, timeout):
                pass

            def call(self, tool, **kw):
                if tool == "list_related_context_cards":
                    return {"cards": [{"card_id": f"r{i}"} for i in range(3)]}
                return {"id": "db-1"}

            def close(self):
                pass

        # Writing back a truncated row list would delete the remainder, so the
        # read hitting its cap has to be fatal rather than merely noted.
        with self.assertRaises(SystemExit):
            self.run_cmd(self.args(apply=True, limit=3), client=FakeClient)

    def test_unknown_selector_key_fails_locally(self):
        self.cfg["deepvista"]["databases"] = [{"card_id": "db-1", "tags": ["oops"]}]
        with self.assertRaises(SystemExit):
            deepvista_cards.row_databases(self.cfg)


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
