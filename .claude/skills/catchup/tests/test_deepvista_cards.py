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
