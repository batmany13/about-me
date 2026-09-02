#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
DeepVista bridge -- render catchup entities as context cards. PROTOTYPE.

DeepVista's own model is the reason this shape works: "Context card captures
entities. Every team member, customer, meeting note, file, and session is stored
within a context card." So the mapping is one entity to one card -- not one card
per week and not one per bullet. A thread running four weeks stays ONE card that
accumulates, which is the same thing the entity store does locally.

Transport is the hosted MCP server at https://api.deepvista.ai/mcp. MCP tools are
called by the model, not by a shell script, so this script does the half a script
can do deterministically: decide create vs update vs skip, render the card body,
and record the returned card id. The model makes the actual tool calls in between.

    plan  ->  [model calls the deepvista MCP tools]  ->  record

Reading back is the exception: once the mcp-remote proxy has cached a sign-in,
`fetch` spawns it and reads the week's cards headlessly, into a file the
aggregator's control (and `compare`) can run on. Reads are free and change
nothing, which is why that half is scripted and the push half is not.

    fetch --week W --out cards.json  ->  [a summary written from the cards]  ->  compare

Skipping matters. The free tier is 100 credits a month, so an entity whose
content has not changed since its last push must cost nothing: `plan` compares a
content hash and emits `skip` for anything unchanged.

Usage:
    deepvista_cards.py plan --week 2026-W35
    deepvista_cards.py plan --all --category meeting
    deepvista_cards.py plan --week 2026-W35 --show-body    # eyeball the markdown
    deepvista_cards.py record --id ray-summit --card-id abc-123
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entities import (  # noqa: E402
    CATEGORY_ORDER, category_titles, content_hash, die, entity_path,
    load_all, load_config, store_dir, utc_now, write_entity,
)

# The server this bridge needs, declared ONCE and travelling with the skill.
# Registration used to be per-repo prose in the runbook, which meant every repo
# adopting the sync re-derived the same three values by hand and could get any of
# them wrong. `install-mcp` writes this into a target repo's .mcp.json, so the
# requirement lives with the code that has the requirement.
#
# There are two ways to register it, and it matters which one you pick:
#
#   type:http    -- the HOST APP's MCP client runs the OAuth. Needs nothing
#                   installed, but the app must expose a connect flow you can
#                   reach; a dead end where it does not.
#   mcp-remote   -- a local stdio proxy runs the OAuth ITSELF and caches the
#                   token under ~/.mcp-auth. One browser sign-in on first launch,
#                   headless from then on, INCLUDING from agent sessions. Costs a
#                   hard Node 18+ dependency, because `npx` runs the proxy.
#
# The proxy is preferred WHEN IT CAN RUN, because it makes the push reachable
# without a human in the loop after the first time. It was previously the only
# form this script would write, unconditionally -- and that is the bug fixed on
# 2026-09-01: `install-mcp` wrote an `npx` entry onto a machine with no Node at
# all, cheerfully reported success, and the failure surfaced one session later as
# `deepvista (ENOENT): Executable not found in $PATH: npx` at start-up, far from
# the command that caused it. A precondition a tool never checks is a precondition
# its user discovers at the worst moment.
#
# So: the entry is chosen against the runtime that is actually present. The http
# form is the fallback rather than a downgrade -- DeepVista serves the RFC 9728
# protected-resource metadata and RFC 8414 authorization-server metadata (with
# dynamic client registration) that a native MCP client needs, verified against
# the live endpoint 2026-09-01. What it costs is the headless property: the host
# app owns the token, so re-auth happens on the app's terms, not `~/.mcp-auth`'s.
MCP_SERVER_NAME = "deepvista"
MCP_ENDPOINT = "https://api.deepvista.ai/mcp"
MCP_ENTRY_PROXY = {"command": "npx", "args": ["-y", "mcp-remote", MCP_ENDPOINT]}
# npm 6's npx cannot run the proxy entry: it does not understand `-y`.
MCP_MIN_NPX = 7
MCP_ENTRY_HTTP = {"type": "http", "url": MCP_ENDPOINT}
MCP_ENTRIES = {"mcp-remote": MCP_ENTRY_PROXY, "http": MCP_ENTRY_HTTP}
MCP_RELPATH = ".mcp.json"
MCP_MIN_NODE = 18


def node_runtime():
    """What Node is actually on PATH, as (npx_path, major, label).

    `npx` is what the entry names, so `npx` is what gets probed -- not `node`.
    A Node install missing npx, or an npx too old to run the proxy, is exactly
    the case a `node --version` check would wave through.
    """
    npx = shutil.which("npx")
    if not npx:
        return None, None, "no `npx` on PATH"
    node = shutil.which("node")
    if not node:
        return npx, None, "`npx` found but no `node` on PATH"
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return npx, None, f"`node --version` failed ({exc})"
    m = re.match(r"v(\d+)\.", (out.stdout or "").strip())
    if not m:
        return npx, None, f"could not parse `node --version` ({(out.stdout or '').strip()!r})"
    major = int(m.group(1))
    if major < MCP_MIN_NODE:
        return npx, major, f"Node {major} is older than the required {MCP_MIN_NODE}+"

    # And the npx version, which is a SEPARATE question from Node's. A machine
    # can carry a current node beside an npm 6 npx -- npm 6's npx does not
    # understand `-y`, so it reads the rest of the line as packages and tries to
    # npm-install the server URL. npm fetches it, gets the OAuth challenge every
    # MCP server answers with, and reports `E401 Unable to authenticate`: an auth
    # error, on a connector whose auth you are setting up, pointing at the wrong
    # layer entirely. Probing npx by PRESENCE and node by VERSION waves exactly
    # this through, which is the case this function set out to catch.
    try:
        nv = subprocess.run([npx, "--version"], capture_output=True, text=True,
                            timeout=20)
        nver = (nv.stdout or "").strip()
        nmaj = int(nver.split(".")[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return npx, major, f"Node v{major} at {node} (could not read `npx --version`)"
    if nmaj < MCP_MIN_NPX:
        alt = ""
        for cand in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx"):
            if cand == npx or not os.path.isfile(cand):
                continue
            try:
                av = subprocess.run([cand, "--version"], capture_output=True,
                                    text=True, timeout=20).stdout.strip()
                if int(av.split(".")[0]) >= MCP_MIN_NPX:
                    alt = f"; npx {av} at {cand} would work but loses on PATH"
                    break
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                continue
        return npx, None, (f"npx {nver} is older than the required {MCP_MIN_NPX}+ "
                           f"and cannot run this entry{alt}")
    return npx, major, f"Node v{major} at {node}, npx {nver}"


def resolve_npx(explicit=None):
    """An npx that can run the proxy, or None -- looking past PATH's first hit.

    `node_runtime()` answers "will the entry in .mcp.json start", which is a
    PATH question because the host app resolves the bare `npx` it names. This
    answers a different one: "can THIS script start the proxy itself" -- and for
    that the well-known install locations are fair game, because the path is
    used here and never written into a repo file. A Homebrew npx 11 sitting
    behind an npm-6 npx on PATH is exactly the machine this was written on.
    """
    cands = [explicit] if explicit else []
    cands += [shutil.which("npx"), "/opt/homebrew/bin/npx", "/usr/local/bin/npx"]
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        try:
            v = subprocess.run([c, "--version"], capture_output=True, text=True,
                               timeout=20).stdout.strip()
            if int(v.split(".")[0]) >= MCP_MIN_NPX:
                return c
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            continue
    return None


class McpClient:
    """The smallest MCP client that can read cards: JSON-RPC over the proxy's stdio.

    This exists because "MCP tools are called by the model, not by a script" was
    true only until the proxy cached a token. Once `mcp-remote` has signed in
    once, it will start headless for anyone who spawns it -- an agent session or
    a shell script alike -- and a READ of the week's cards is then a deterministic
    thing a script can own, the same way `plan` and `record` already are. Writes
    stay with the model on purpose: they spend credits and change the product,
    and a script that pushes on its own is a script that pushes twice.

    If the proxy needs a sign-in it prints the authorization URL to stderr and
    waits. That is surfaced rather than hidden, because the fix is a human in a
    browser and no amount of retrying substitutes for one.
    """

    # A session opened right after another proxy shut down can come back
    # `Session not found` on its first call, or the handshake can stall -- seen
    # repeatedly on 2026-09-02 whenever two reads ran back to back, and never
    # when they were minutes apart. The previous proxy's teardown is the likely
    # racer. Whatever the cause, the recovery is the same: a fresh proxy after a
    # short pause. So the handshake is attempted a few times, each on a new
    # process, and the count is reported so a run that needed it stands out.
    ATTEMPTS = 4
    BACKOFF = 2.5
    TOLERATED = ("Session not found",)

    def __init__(self, npx, endpoint=MCP_ENDPOINT, timeout=90):
        import time
        self.npx, self.endpoint, self.timeout = npx, endpoint, timeout
        self.reinits = 0
        self.attempts = 0
        self.proc = None
        last = None
        for i in range(self.ATTEMPTS):
            self.attempts += 1
            if i:
                self.close()
                time.sleep(self.BACKOFF * i)
            self._spawn()
            ok, last = self._handshake()
            if ok:
                return
        url = self._auth_url()
        if url:
            die("DeepVista needs a browser sign-in before this can run headless.\n"
                f"  Open once, then re-run:\n  {url}\n"
                "  (mcp-remote caches the token under ~/.mcp-auth after that.)")
        die(f"could not open a session after {self.ATTEMPTS} attempts; last: {last}")

    def _spawn(self):
        import threading
        # Its own process group, so close() can take the proxy down WITH the
        # node child npx spawns. Terminating npx alone left the proxy running
        # after the first probes.
        self.proc = subprocess.Popen(
            [self.npx, "-y", "mcp-remote", self.endpoint],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True)
        self._lines = []          # stdout, JSON-RPC
        self._stderr = []         # proxy chatter, kept for diagnosis
        self._lock = threading.Lock()
        self._next = 1
        threading.Thread(target=self._pump, args=(self.proc.stdout, self._lines),
                         daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self._stderr),
                         daemon=True).start()

    def _handshake(self):
        """initialize + initialized on the current proxy. (ok, error-text)."""
        r = self._rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "catchup-deepvista-cards", "version": "1"}},
            tolerate=self.TOLERATED, fatal=False)
        if r is None or r.get("error"):
            return False, (json.dumps(r["error"])[:200] if r else "no reply")
        self.server = (r.get("result") or {}).get("serverInfo") or {}
        self._notify("notifications/initialized")
        return True, None

    def _pump(self, stream, sink):
        for line in stream:
            with self._lock:
                sink.append(line)

    def _auth_url(self):
        for i, line in enumerate(self._stderr):
            if "Please authorize this client" in line:
                for nxt in self._stderr[i + 1:i + 4]:
                    if nxt.strip().startswith("http"):
                        return nxt.strip()
        return None

    def _send(self, msg):
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            die(f"proxy went away while sending {msg.get('method')}: {e}")

    def _notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _rpc(self, method, params, tolerate=(), fatal=True):
        """One request, one reply. An error reply dies unless its text contains
        one of `tolerate`, in which case the raw reply is returned for the
        caller to recover from. With fatal=False a timeout returns None
        instead of dying, so a handshake can be retried on a fresh proxy."""
        import time
        rid = self._next
        self._next += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        # A handshake that has not answered in 30s is not going to; the full
        # timeout is for calls that do real work.
        end = time.time() + (min(self.timeout, 30) if method == "initialize" else self.timeout)
        seen = 0
        while time.time() < end:
            with self._lock:
                chunk, seen = self._lines[seen:], len(self._lines)
            for line in chunk:
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if m.get("id") == rid:
                    if "error" in m:
                        txt = json.dumps(m["error"])
                        if any(t in txt for t in tolerate):
                            return m
                        die(f"{method}: {txt[:400]}")
                    return m
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        if not fatal:
            return None
        url = self._auth_url()
        tail = "".join(self._stderr[-6:]).strip()
        if url:
            die("DeepVista needs a browser sign-in before this can run headless.\n"
                f"  Open once, then re-run:\n  {url}\n"
                "  (mcp-remote caches the token under ~/.mcp-auth after that.)")
        die(f"no reply to {method} within {self.timeout}s"
            + (f"; proxy said:\n{tail}" if tail else ""))

    def _reinit(self):
        """The session went away mid-run: a fresh proxy, same retry ladder."""
        import time
        self.reinits += 1
        for i in range(self.ATTEMPTS):
            self.close()
            time.sleep(self.BACKOFF * (i + 1))
            self._spawn()
            ok, last = self._handshake()
            if ok:
                return
        die(f"session lost mid-run and could not be reopened; last: {last}")

    def call(self, tool, **args):
        """Call a tool; return its structured result (or its text parsed as JSON)."""
        r = self._rpc("tools/call", {"name": tool, "arguments": args},
                      tolerate=self.TOLERATED)
        if r.get("error"):
            self._reinit()
            r = self._rpc("tools/call", {"name": tool, "arguments": args})
        res = r.get("result") or {}
        if res.get("isError"):
            txt = " ".join(c.get("text", "") for c in res.get("content") or [])
            return {"_error": txt.strip()[:400] or "tool reported an error"}
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        for c in res.get("content") or []:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except json.JSONDecodeError:
                    return {"_text": c["text"]}
        return res

    def close(self):
        import signal
        if not self.proc:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass
        self.proc = None


def choose_transport(pref):
    """Resolve --transport into (key, entry, why). `auto` follows the runtime."""
    if pref in MCP_ENTRIES:
        return pref, MCP_ENTRIES[pref], f"--transport {pref}"
    npx, major, label = node_runtime()
    if npx and major and major >= MCP_MIN_NODE:
        return "mcp-remote", MCP_ENTRY_PROXY, label
    return "http", MCP_ENTRY_HTTP, label

# Entity type -> DeepVista card_type. The right-hand side is DeepVista's fixed
# vocabulary (from the CLI's CARD_TYPES), not ours, so the mapping is lossy on
# purpose: `meeting` has no card type of its own and lands on `note`, which is
# what the docs' own "meeting note" example does.
CARD_TYPE = {
    "meeting": "note",
    "person": "person",
    "org": "organization",
    "thread": "topic",
    "decision": "keypoint",
    "correction": "keypoint",
    # A theme is an ongoing subject that accumulates weekly notes, which is what
    # `topic` is for. A concept is a point of knowledge with a claim and a grade,
    # which is `keypoint`. Both were missing here and fell through to the generic
    # `note` default -- so the two types the format is actually built around were
    # the two arriving in DeepVista untyped.
    "theme": "topic",
    "concept": "keypoint",
    "other": "note",
}

# `upsert_context_card`'s `status` enum, verbatim from the served tool schema
# (2026-09-01). Kept as a set so a config typo fails HERE, with the vocabulary
# printed, instead of at the 21st push -- an out-of-vocabulary value is the kind
# of thing an "unknown keys are ignored" server accepts and quietly discards.
CARD_STATUS = {"pending", "not_started", "in_progress", "completed",
               "for_review", "active", "archived"}
CARD_STATUS_DEFAULT = "active"


def card_status(dv_cfg):
    """The card `status` to send, validated against the served enum.

    Config carried `confirmed` -- a REST-era search-visibility flag, not a member
    of this enum. `active` is its intent here: live, not archived.
    """
    want = dv_cfg.get("card_status") or CARD_STATUS_DEFAULT
    if want == "confirmed":
        return CARD_STATUS_DEFAULT
    if want not in CARD_STATUS:
        die(f"card_status {want!r} is not one of the served values: "
            f"{', '.join(sorted(CARD_STATUS))}")
    return want


def render_body(e, titles, repo_label):
    """The card's markdown body.

    Carries the full week-by-week timeline, not just the current summary. That is
    deliberate: the point of pushing entities rather than a finished writeup is
    that the cards should hold enough for DeepVista to compose a catchup itself.
    A card that only said "here is the latest" could not.
    """
    weeks = sorted(e.get("weeks") or {})
    lines = [e.get("summary", "").strip(), ""]

    latest = (e.get("weeks") or {}).get(sorted(e.get("weeks") or {})[-1], {}) if e.get("weeks") else {}
    meta = [
        f"**Category:** {titles.get(e.get('category'), e.get('category'))}",
        f"**Type:** {e.get('type')}",]
    if latest.get("subject"):
        meta.append(f"**Subject:** {latest['subject']}")
    meta += [
        f"**Status:** {e.get('status')}",
        f"**Source:** {repo_label}",
    ]
    if weeks:
        span = weeks[0] if len(weeks) == 1 else f"{weeks[0]} → {weeks[-1]}"
        meta.append(f"**Active:** {span} ({len(weeks)} week{'s' if len(weeks) != 1 else ''})")
    lines += [" · ".join(meta), ""]

    lines.append("## Timeline")
    lines.append("")
    for w in weeks:
        blk = e["weeks"][w]
        head = f"### {w}"
        if blk.get("date"):
            head += f" — {blk['date']}"
        lines.append(head)

        # The structured fields FIRST, because they are the entity. This renderer
        # predates them and emitted only `note`, so a theme's weight, what moved
        # and why it matters -- and a learning's whole claim/grade/so_what/open --
        # never reached the card at all. What arrived was the footnote.
        if blk.get("moved"):
            lines.append(blk["moved"].strip())
        if blk.get("why_it_matters"):
            lines.append("")
            lines.append(f"**Why it matters:** {blk['why_it_matters'].strip()}")
        wt = blk.get("weight") or {}
        if wt.get("share") is not None:
            bits = [f"{wt['share']:.0%} of the week's commits"]
            if wt.get("line_share") is not None:
                bits.append(f"{wt['line_share']:.0%} of its churn")
            if wt.get("commits"):
                bits.append(f"{wt['commits']} commits")
            lines.append("")
            lines.append("**Weight:** " + " · ".join(bits))
        if blk.get("evidence"):
            lines.append("")
            lines.append("**Evidence:**")
            lines += [f"- {x}" for x in blk["evidence"]]

        if blk.get("claim"):
            grade = blk.get("grade")
            lines.append(f"**Claim:** {blk['claim'].strip()}"
                         + (f"  *[{grade}]*" if grade else ""))
        if blk.get("so_what"):
            lines.append("")
            lines.append(blk["so_what"].strip())
        if blk.get("open"):
            lines.append("")
            lines.append(f"**Open:** {blk['open'].strip()}")

        if blk.get("note"):
            lines.append("")
            lines.append(blk["note"].strip())
        ev = []
        if blk.get("people"):
            ev.append("People: " + ", ".join(blk["people"]))
        if blk.get("prs"):
            ev.append("PRs: " + ", ".join(f"#{p}" for p in blk["prs"]))
        if blk.get("commits"):
            ev.append("Commits: " + ", ".join(blk["commits"][:8])
                      + (f" (+{len(blk['commits']) - 8} more)" if len(blk["commits"]) > 8 else ""))
        if blk.get("paths"):
            ev.append("Paths: " + ", ".join(f"`{p}`" for p in blk["paths"][:6]))
        if ev:
            lines.append("")
            lines += [f"- {x}" for x in ev]
        lines.append("")

    if e.get("links"):
        lines.append("## Related")
        lines.append("")
        lines += [f"- `{l}`" for l in e["links"]]
        lines.append("")

    lines.append(f"<!-- catchup-entity: {e['id']} -->")
    return "\n".join(lines).strip() + "\n"


# Free-text contact words a person entity may carry. They are stripped and
# replaced by the DERIVED `contact:` tag below, because a hand-typed one goes
# stale the moment a meeting is recorded and nothing reconciles it: one person
# shipped tagged `contacted`, `meeting-upcoming` AND `not-met` at the same time.
_CONTACT_WORDS = {"met", "not-met", "notmet", "contacted", "meeting-upcoming", "prep"}


def contact_state(e, all_entities):
    """met / contacted / prepped / none -- DERIVED from the meeting entities.

    The summary already derives this and the card must not be allowed to
    disagree with it: "have I met this person" is the single most useful field
    on a person card, and a card that answers it from a hand-typed tag answers
    it wrong. Same rule as the renderer -- to mark someone met, record the
    meeting.
    """
    if e.get("type") != "person":
        return None, None
    met = prep = None
    for m in all_entities:
        if m.get("type") != "meeting":
            continue
        is_prep = "prep" in (m.get("tags") or [])
        for wk in (m.get("weeks") or {}).values():
            if e["id"] not in (wk.get("attendees") or []):
                continue
            d = wk.get("date") or ""
            if is_prep:
                prep = max(prep or "", d)
            else:
                met = max(met or "", d)
    if met is not None:
        return "met", met or None
    if prep is not None:
        return "prepped", prep or None
    tags = set(e.get("tags") or [])
    if "meeting-upcoming" in tags:
        return "meeting-upcoming", None
    if "contacted" in tags:
        return "contacted", None
    return "not-met", None


def build_tags(e, cfg, repo_label, all_entities=()):
    dv = (cfg.get("deepvista") or {})
    tags = set(dv.get("tags") or ["catchup"])
    tags.add(f"repo:{repo_label}")
    tags.add(f"category:{e.get('category')}")
    tags.add(f"entity:{e['id']}")
    own = set(e.get("tags") or [])
    state, when = contact_state(e, all_entities)
    if state:
        own -= _CONTACT_WORDS
        tags.add(f"contact:{state}")
        if when:
            tags.add(f"met:{when}")
    tags.update(own)
    return sorted(t for t in tags if t)


def cmd_install_mcp(args, repo, cfg, sdir):
    """Register the DeepVista server in a repo's .mcp.json, idempotently.

    NO CREDENTIALS ARE WRITTEN and none belong here: the server does OAuth 2.1
    with dynamic client registration, so the entry is a name, a transport and a
    URL, and the browser sign-in happens once per machine through `/mcp`. A repo
    file is never the place for a bearer token even where a server accepts one.

    Project scope by default because that is what makes the skill portable -- the
    repo that runs the sync carries its own declaration. `--scope user` prints
    the one-line command instead, for someone who would rather authenticate once
    for every repo; a user-scope registration is a machine setting and not
    something a repo-level tool should write on anyone's behalf.

    The transport is CHOSEN, not assumed -- see the MCP_ENTRIES comment. `auto`
    writes the proxy form where Node 18+ can run it and the http form where it
    cannot, so the entry that lands is one this machine can actually start.
    """
    key, entry, why = choose_transport(args.transport)

    if args.scope == "user":
        cmd = (f"claude mcp add {MCP_SERVER_NAME} -- npx -y mcp-remote {MCP_ENDPOINT}"
               if key == "mcp-remote" else
               f"claude mcp add --transport http {MCP_SERVER_NAME} {MCP_ENDPOINT}")
        print(f"Transport: {key} ({why})\n")
        print("Run this once, in an interactive terminal:\n")
        print(f"  {cmd}\n")
        print("User scope covers every repo on this machine; project scope (the")
        print("default here) keeps the declaration with the repo that uses it.")
        print("Either way the first launch opens a browser once.")
        return

    path = os.path.join(repo, MCP_RELPATH)
    blob = {}
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                blob = json.load(fh)
        except json.JSONDecodeError as e:
            die(f"{MCP_RELPATH} is not valid JSON ({e}) -- refusing to overwrite it")
    servers = blob.setdefault("mcpServers", {})
    existing = servers.get(MCP_SERVER_NAME)

    # flush: `die` writes to stderr, and block-buffered stdout would otherwise
    # report the transport AFTER the error explaining it.
    print(f"Transport: {key} ({why})", flush=True)

    if existing == entry:
        print(f"already registered: {MCP_SERVER_NAME} -> {MCP_ENDPOINT}")
    elif existing and not args.force:
        # Naming the OTHER known form explicitly, because the overwhelmingly
        # common case for this branch is a repo carrying the entry for a
        # transport this machine cannot run -- which is a one-flag fix, not a
        # mystery worth reading the source over.
        other = next((k for k, v in MCP_ENTRIES.items() if v == existing), None)
        hint = (f"\nThat is the {other} form and this machine resolved to {key}."
                f"\nRe-run with --force to switch it, or --transport {other} to keep it."
                if other and other != key else
                "\nLeaving it alone -- pass --force to replace it.")
        die(f"{MCP_SERVER_NAME} is already in {MCP_RELPATH} with different settings:\n"
            f"  {json.dumps(existing)}\n"
            f"expected:\n  {json.dumps(entry)}" + hint)
    else:
        servers[MCP_SERVER_NAME] = dict(entry)
        if args.dry_run:
            print(f"would write to {os.path.relpath(path, repo)}:")
            print(json.dumps({MCP_SERVER_NAME: entry}, indent=2))
            return
        with open(path, "w") as fh:
            json.dump(blob, fh, indent=2)
            fh.write("\n")
        print(f"registered {MCP_SERVER_NAME} in {os.path.relpath(path, repo)}")

    if key == "mcp-remote":
        print("\nNeeds Node 18+ on the PATH the MCP CLIENT sees -- `npx` runs the proxy.")
        print("The first launch opens a browser once; the proxy caches the token under")
        print("~/.mcp-auth and every session after that is headless, agent runs included.")
    else:
        print("\nNo Node needed: the host app's own MCP client runs the OAuth. In Claude")
        print("Code that is `/mcp` -> authenticate, which needs an INTERACTIVE session.")
        print("Install Node 18+ and re-run with --force for the headless-after-first-run")
        print("proxy form instead.")

    print("\nStart a FRESH session either way: MCP servers connect at start-up, so one")
    print("added mid-session is invisible to it. Verify with `doctor` before pushing.")
    print("\nThen dump the tool list before pushing anything: the vendor publishes the")
    print("setup and the auth model but not the tool names, parameters, card_type")
    print("values or status field, so every field this bridge sends is inferred.")


def cmd_doctor(args, repo, cfg, sdir):
    """Diagnose the registration BEFORE a session start-up failure does.

    This exists because the original failure mode was silent at the only moment
    anyone could have acted on it. `install-mcp` wrote an `npx` entry, printed
    success, and the machine had no Node; the first evidence was a start-up line
    in the NEXT session -- `ENOENT: Executable not found in $PATH: npx` -- which
    names neither the file that asked for npx nor the command that put it there.

    So `doctor` checks the three things that are separately capable of breaking
    it, and reports each one on its own: the runtime, the registered entry, and
    the endpoint. It is read-only and exits non-zero when the registration
    cannot work as written, which makes it usable as a preflight.
    """
    ok = True

    print("== runtime ==")
    npx, major, label = node_runtime()
    proxy_ok = bool(npx and major and major >= MCP_MIN_NODE)
    print(f"  {'OK  ' if proxy_ok else 'note'}  {label}")
    if npx:
        print(f"        npx: {npx}")
    if not proxy_ok:
        print(f"        -> the mcp-remote proxy form CANNOT run here (needs Node {MCP_MIN_NODE}+).")
        print("        -> `brew install node`, or use --transport http.")

    print("\n== registration ==")
    path = os.path.join(repo, MCP_RELPATH)
    if not os.path.isfile(path):
        print(f"  FAIL  no {MCP_RELPATH} in {repo}")
        print(f"        -> run: install-mcp --repo {repo}")
        ok = False
    else:
        try:
            blob = json.load(open(path))
        except json.JSONDecodeError as e:
            print(f"  FAIL  {MCP_RELPATH} is not valid JSON ({e})")
            return 1
        entry = (blob.get("mcpServers") or {}).get(MCP_SERVER_NAME)
        if not entry:
            print(f"  FAIL  {MCP_SERVER_NAME} is not registered in {MCP_RELPATH}")
            print(f"        -> run: install-mcp --repo {repo}")
            ok = False
        else:
            key = next((k for k, v in MCP_ENTRIES.items() if v == entry), None)
            print(f"  OK    {MCP_SERVER_NAME} -> {json.dumps(entry)}")
            if key is None:
                print("  note  that is neither known form; it may still be valid, but this")
                print("        script cannot vouch for it.")
            elif key == "mcp-remote" and not proxy_ok:
                # Say it in the words the failure will actually use, so the two
                # are recognisably the same problem -- which means predicting the
                # RIGHT one. A missing npx and an npx too old fail at different
                # moments with different messages, and naming the wrong symptom
                # sends the reader to the wrong layer just as surely as no
                # diagnosis at all.
                if shutil.which("npx"):
                    print("  FAIL  this entry runs `npx -y`, which the `npx` on this PATH")
                    print("        is too old to understand. It will read the URL as a")
                    print("        package and try to install it, failing with:")
                    print("          npm ERR! code E401")
                    print("          npm ERR! Unable to authenticate, need: Bearer resource_metadata=...")
                    print("        That is npm's auth error, not the connector's — the proxy")
                    print("        never starts.")
                else:
                    print("  FAIL  this entry runs `npx`, which this machine cannot resolve.")
                    print("        Every session will fail at start-up with:")
                    print("          deepvista (ENOENT): Executable not found in $PATH: npx")
                print(f"        -> `brew install node` (then restart the session), or")
                print(f"        -> install-mcp --repo {repo} --transport http --force")
                ok = False

    print("\n== endpoint ==")
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        MCP_ENDPOINT, method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "catchup-doctor", "version": "0"}}}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"  OK    {MCP_ENDPOINT} answered {r.status} (already authorized)")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # 401 is the HEALTHY answer for an unauthenticated probe. The header
            # is the interesting part: it is what tells a native MCP client where
            # to run the OAuth, and its presence is why --transport http is a
            # real option here rather than a hopeful one.
            www = e.headers.get("www-authenticate", "")
            print(f"  OK    {MCP_ENDPOINT} -> 401 + OAuth discovery (expected when signed out)")
            if www:
                print(f"        {www[:160]}")
        else:
            print(f"  FAIL  {MCP_ENDPOINT} -> HTTP {e.code}")
            ok = False
    except (urllib.error.URLError, OSError) as e:
        print(f"  FAIL  {MCP_ENDPOINT} unreachable ({e})")
        ok = False

    print("\n" + ("all checks passed" if ok else "PROBLEMS FOUND -- see -> lines above"))
    return 0 if ok else 1


def cmd_plan(args, repo, cfg, sdir):
    ents = load_all(sdir)
    # Contact state is derived from the meeting entities, so derivation must see
    # ALL of them -- a --week or --category filter would otherwise hide the very
    # meeting that proves someone was met, and the card would ship "not-met".
    all_ents = list(ents)
    if args.week:
        ents = [e for e in ents if args.week in (e.get("weeks") or {})]
    elif not args.all:
        die("pass --week YYYY-WNN or --all")
    if args.category:
        ents = [e for e in ents if e.get("category") == args.category]
    if args.status:
        ents = [e for e in ents if e.get("status") == args.status]

    titles = category_titles(cfg)
    dv_cfg = cfg.get("deepvista") or {}
    repo_label = (cfg.get("repo") or {}).get("label") or os.path.basename(repo)
    type_map = dict(CARD_TYPE, **(dv_cfg.get("card_types") or {}))

    # Entity id -> card id, for every entity already pushed. Graph edges are
    # resolved from this so `related_card_ids` only ever names cards that exist.
    card_of = {x["id"]: (x.get("deepvista") or {}).get("card_id")
               for x in all_ents if (x.get("deepvista") or {}).get("card_id")}

    plan, counts = [], {"create": 0, "update": 0, "skip": 0}
    for e in sorted(ents, key=lambda x: (CATEGORY_ORDER.index(x.get("category", "other"))
                                         if x.get("category") in CATEGORY_ORDER else 9, x["id"])):
        dv = e.get("deepvista") or {}
        h = content_hash(e)
        if dv.get("card_id") and dv.get("content_hash") == h and not args.force:
            action = "skip"
        elif dv.get("card_id"):
            action = "update"
        else:
            action = "create"
        counts[action] += 1
        if action == "skip" and not args.include_skipped:
            continue

        item = {
            "action": action,
            "entity_id": e["id"],
            "card_id": dv.get("card_id"),
            "content_hash": h,
            # Keyed to match `upsert_context_card`'s `properties` object, which is
            # the served contract -- reconciled against the connected server on
            # 2026-09-01, the step the runbook insists on before a first push.
            # Two of the three inferred fields were wrong, and the interesting
            # part is that they were wrong in OPPOSITE ways:
            #
            #   card_type -> type   The tool takes `type` and says so: "Use the
            #                       key 'type', NOT 'card_type'." Unknown keys
            #                       are IGNORED rather than rejected, and `type`
            #                       is required on create -- so the old payload
            #                       would have been dropped on the floor and then
            #                       failed for a missing field it was in fact
            #                       sending, under another name.
            #   status              Exists, but with a vocabulary that has no
            #                       `confirmed` in it at all. The old value came
            #                       from the REST-era confirmed/unconfirmed
            #                       search filter, which is not this enum.
            #
            # The card_type VALUES were right: note, topic, keypoint, person and
            # organization are all in the served type list. It was the key and
            # the status vocabulary that were inferred wrong, which is exactly
            # why the runbook says to dump the tool list rather than trust this.
            "card": {
                "type": type_map.get(e.get("type"), "note"),
                "title": e["title"],
                "description": render_body(e, titles, repo_label),
                "tags": build_tags(e, cfg, repo_label, all_ents),
                "status": card_status(dv_cfg),
            },
            # Graph edges, passed as the tool's `related_context_card_ids` IN THE
            # SAME CALL as `properties`. Never as a second, links-only call: on
            # the 2026-09-02 first live push a links-only upsert re-saved the
            # existing description through an HTML-escaping pass -- `&` became
            # `&amp;` and the `<!-- catchup-entity -->` tracer became literal
            # `&lt;!-- ... --&gt;` text -- on all 41 cards it touched. Sending
            # description and links together left the body untouched. Only
            # links whose target already has a card are emitted, so a first
            # push of a linked pair lands the edge on whichever side is pushed
            # second (or on the next run, when both have ids and the hash of
            # the earlier one is unchanged -- use --force to re-send it).
            "related_card_ids": sorted({
                card_of[l] for l in list(e.get("links") or []) + [e.get("theme")]
                if l and l in card_of and card_of[l] != dv.get("card_id")
            }),
        }
        if not args.show_body:
            # A preview, and named as one. This used to overwrite `description`
            # in place with 280 characters plus a "[truncated]" marker, while the
            # `next` line said to call the tool with `card` -- so following the
            # instruction as written pushed a truncated body, with the marker
            # text in it, into the product. The full body only ever lives under
            # --show-body, so the preview now sits in its own key and `card` is
            # never a payload the plan has quietly altered.
            body = item["card"].pop("description")
            item["card_body_preview"] = body[:280].rstrip() + " …"
            item["card_body_lines"] = body.count("\n") + 1
        plan.append(item)
        if args.limit and len(plan) >= args.limit:
            break

    ready = args.show_body
    print(json.dumps({
        "endpoint": MCP_ENDPOINT,
        "limited_to": args.limit or None,
        "repo": repo_label,
        "week": args.week,
        "project_id": dv_cfg.get("project_id"),
        "enabled": dv_cfg.get("enabled", False),
        "counts": counts,
        "pushable": ready,
        "plan": plan,
        "next": (
            "For each item call the DeepVista MCP create/update card tool with `card`, "
            "then run: deepvista_cards.py record --id <entity_id> --card-id <returned id>"
            if ready else
            "PREVIEW ONLY — `card` here has no `description`, so it is not a payload. "
            "Re-run with --show-body to get the full card bodies before pushing anything."),
    }, indent=2))


def _mentions(text, entity):
    """Whether a summary actually refers to this entity.

    Title first, then the distinctive half of the id -- a summary that says
    "the Daytona event" has covered `daytona-ai-builders-sf` without quoting it.
    Deliberately loose: the question is coverage, and a strict match would report
    a summary as having missed what it plainly discusses.
    """
    low = text.lower()
    if (entity.get("title") or "").lower() in low:
        return True
    # A learning renders as its CLAIM, not its title -- the local summary leads
    # every "What we learned" bullet with the claim sentence and carries the
    # title nowhere. Title-only matching scored all four concept rows of the
    # first control run as "only the DeepVista summary" when the local one had
    # every one of them, one line each. Match the claim's opening too.
    for wk in (entity.get("weeks") or {}).values():
        claim = (wk.get("claim") or "").strip().rstrip(".").lower()
        if len(claim) > 24 and claim[:60] in low:
            return True
    parts = [p for p in entity["id"].split("-") if len(p) > 3]
    return bool(parts) and all(p in low for p in parts[:2])


def cmd_compare(args, repo, cfg, sdir):
    """Compare our rendered summary against one built from the DeepVista cards.

    The cards carry the same entities, so the interesting question is not which
    prose reads better -- it is what each version COVERS and what each one
    leaves out. That is checkable; style is not.

    Neither side is assumed correct. A card-derived summary is written from what
    survived the push, so anything it covers that ours does not is either a fact
    the local summary dropped or evidence the push carried something the summary
    was right to leave out. Both are worth knowing, and only a coverage diff
    tells them apart.
    """
    ours_path = args.ours or os.path.join(
        repo, (cfg.get("output") or {}).get("dir", "catchup"), f"{args.week}.md")
    if not os.path.isfile(ours_path):
        die(f"no local summary at {ours_path}")
    if not os.path.isfile(args.against):
        die(f"no DeepVista-derived summary at {args.against} -- "
            "fetch the week's cards through the MCP tools and save it first")
    ours = open(ours_path).read()
    theirs = open(args.against).read()

    ents = [e for e in load_all(sdir) if args.week in (e.get("weeks") or {})]
    if not ents:
        die(f"no entities recorded for {args.week}")

    rows = []
    for e in sorted(ents, key=lambda x: (x.get("type", ""), x["id"])):
        rows.append((e, _mentions(ours, e), _mentions(theirs, e)))

    both = [r for r in rows if r[1] and r[2]]
    only_ours = [r for r in rows if r[1] and not r[2]]
    only_theirs = [r for r in rows if r[2] and not r[1]]
    neither = [r for r in rows if not r[1] and not r[2]]

    if args.json:
        print(json.dumps({
            "week": args.week,
            "ours": os.path.relpath(ours_path, repo), "theirs": args.against,
            "words": {"ours": len(ours.split()), "theirs": len(theirs.split())},
            "covered_by_both": [e["id"] for e, _, _ in both],
            "only_ours": [e["id"] for e, _, _ in only_ours],
            "only_deepvista": [e["id"] for e, _, _ in only_theirs],
            "covered_by_neither": [e["id"] for e, _, _ in neither],
        }, indent=2))
        return

    print(f"# {args.week} — local summary vs DeepVista cards\n")
    print(f"  words: {len(ours.split()):,} local · {len(theirs.split()):,} DeepVista")
    print(f"  entities this week: {len(ents)}\n")
    print(f"  covered by both          {len(both):>3}")
    print(f"  only the local summary   {len(only_ours):>3}")
    print(f"  only the DeepVista one   {len(only_theirs):>3}")
    print(f"  covered by NEITHER       {len(neither):>3}")

    def show(label, sel, why):
        if not sel:
            return
        print(f"\n## {label}\n  {why}\n")
        for e, _, _ in sel:
            print(f"  - {e['id']:<34} {e.get('type','')}  {e.get('title','')[:56]}")

    show("Only the local summary", only_ours,
         "Either the push did not carry these, or the card-derived summary dropped them.")
    show("Only the DeepVista summary", only_theirs,
         "The local summary left these out. Check whether that was judgment or an omission.")
    show("Covered by neither", neither,
         "In the store, in neither summary. The strongest signal here — both writers "
         "independently passed over them, which is either agreement that they do not "
         "matter or a shared blind spot.")


TRACER = "<!-- catchup-entity: {id} -->"


def _tracer_state(body, eid):
    """intact / escaped / missing -- whether the card still points at its entity.

    `escaped` is a real state, not a parse failure: a links-only upsert on the
    first live push re-saved bodies through an HTML-escaping pass, so the tracer
    on those cards reads `&lt;!-- ... --&gt;` and their `&` became `&amp;`. The
    card is still the right card; its body is no longer byte-for-byte what was
    sent, and a control that did not distinguish the two would score the
    escaping damage as a content difference.
    """
    if TRACER.format(id=eid) in body:
        return "intact"
    if TRACER.format(id=eid).replace("<", "&lt;").replace(">", "&gt;") in body:
        return "escaped"
    return "missing"


def _unescape(body):
    return (body.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))


def _body_state(card_body, rendered, tracer):
    """matches / cosmetic / differs -- how far the card body is from the render.

    The product does not hand a body back byte-for-byte: on the first live push
    it backslash-escaped `[grade]` markers, inserted blank lines, and (on the
    links-only pass) HTML-escaped the whole thing. None of that is a content
    difference, and a control that reported it as one would drown the signal it
    exists to carry -- an entity whose text moved on after it was pushed. So
    the comparison is made on a normalised form, and the raw inequality is
    reported as `cosmetic` rather than hidden.
    """
    got = _unescape(card_body) if tracer == "escaped" else card_body
    if got.strip() == rendered.strip():
        return "matches"
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"\\([\[\]*_`#>~|])", r"\1", s)).strip()
    return "cosmetic" if norm(got) == norm(rendered) else "differs"


def cmd_fetch(args, repo, cfg, sdir):
    """Read a week's cards BACK from DeepVista, as a file a control can be run on.

    The push is one direction; this is the other. It fetches every card the
    store says it pushed for the week, browses the repo's tag for cards the store
    does NOT know about, and writes one JSON file carrying the card bodies plus a
    fidelity read per card -- whether the tracer survived, and whether the body
    is what the entity would render today.

    That file is what the aggregator's control is built on: a second summary of
    the same week, written from the cards alone and diffed against the local one
    with `compare`. A read costs no credits and changes nothing, which is why
    this half is scripted and the push half is not.
    """
    ents = load_all(sdir)
    all_ents = list(ents)
    if args.week:
        ents = [e for e in ents if args.week in (e.get("weeks") or {})]
    elif not args.all:
        die("pass --week YYYY-WNN or --all")
    if not ents:
        die(f"no entities recorded for {args.week or 'any week'}")

    dv_cfg = cfg.get("deepvista") or {}
    if not dv_cfg.get("enabled") and not args.force:
        die("deepvista.enabled is not true in this repo's config; pass --force to read anyway")
    titles = category_titles(cfg)
    repo_label = (cfg.get("repo") or {}).get("label") or os.path.basename(repo)

    npx = resolve_npx(args.npx)
    if not npx:
        die(f"no npx {MCP_MIN_NPX}+ found to run the mcp-remote proxy -- `brew install node`, "
            "or pass --npx /path/to/npx")
    client = McpClient(npx, timeout=args.timeout)
    try:
        # The complete listing under this repo's tag, which is the only way to
        # see cards the store has forgotten -- a `record` that never ran leaves a
        # live card behind with no entity pointing at it, and the next push
        # creates its twin. Empty query = exact listing, per the tool's own docs.
        listing = client.call("search_context_cards", query="",
                              tag=f"repo:{repo_label}", limit=100)
        hits = listing.get("hits") or [] if isinstance(listing, dict) else []
        listed = {h.get("card_id"): h for h in hits if h.get("card_id")}
        listing_complete = len(hits) < 100

        known = {(x.get("deepvista") or {}).get("card_id"): x["id"]
                 for x in all_ents if (x.get("deepvista") or {}).get("card_id")}

        cards, not_found, unpushed = [], [], []
        for e in sorted(ents, key=lambda x: (x.get("category", ""), x["id"])):
            dv = e.get("deepvista") or {}
            cid = dv.get("card_id")
            if not cid:
                unpushed.append(e["id"])
                continue
            card = client.call("read_context_card", card_id=cid)
            if not isinstance(card, dict) or card.get("_error") or not card.get("id"):
                not_found.append({"entity_id": e["id"], "card_id": cid,
                                  "error": (card or {}).get("_error", "no card returned")})
                continue
            body = card.get("description") or ""
            tracer = _tracer_state(body, e["id"])
            state = _body_state(body, render_body(e, titles, repo_label), tracer)
            cards.append({
                "entity_id": e["id"],
                "entity_type": e.get("type"),
                "category": e.get("category"),
                "card_id": cid,
                "card_type": card.get("type"),
                "title": card.get("title"),
                "status": card.get("status"),
                "tags": card.get("tags") or [],
                "created_at": card.get("created_at"),
                "updated_at": card.get("updated_at"),
                "synced_at": dv.get("synced_at"),
                "tracer": tracer,
                # Two separate questions. `store_current`: has the entity changed
                # since it was pushed (plan would say `update`)? `body`: is the
                # card what the entity renders to NOW -- matches, cosmetic, or
                # differs? `differs` with store_current false is the ordinary
                # "entity moved on" case; `differs` with store_current TRUE means
                # the product changed the content, which is the one to look at.
                "store_current": dv.get("content_hash") == content_hash(e),
                "body": state,
                "description": body,
            })

        orphans = [{"card_id": cid, "card_type": h.get("card_type"), "title": h.get("title")}
                   for cid, h in listed.items() if cid not in known]
    finally:
        client.close()

    out = {
        "week": args.week,
        "repo": repo_label,
        "endpoint": MCP_ENDPOINT,
        "server": client.server,
        "session": {"handshake_attempts": client.attempts, "reinits": client.reinits},
        "fetched_at": utc_now(),
        "listing": {"tag": f"repo:{repo_label}", "cards": len(listed),
                    "complete": listing_complete},
        "counts": {
            "entities": len(ents),
            "fetched": len(cards),
            "unpushed": len(unpushed),
            "not_found": len(not_found),
            "orphans": len(orphans),
            "tracer": dict(sorted(
                {t: sum(1 for c in cards if c["tracer"] == t) for t in
                 ("intact", "escaped", "missing")}.items())),
            "body": dict(sorted(
                {s: sum(1 for c in cards if c["body"] == s) for s in
                 ("matches", "cosmetic", "differs")}.items())),
            "store_current": sum(1 for c in cards if c["store_current"]),
        },
        "cards": cards,
        "unpushed": unpushed,
        "not_found": not_found,
        "orphans": orphans,
    }
    blob = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(blob)
        c = out["counts"]
        print(f"fetched {c['fetched']}/{c['entities']} cards for {repo_label} {args.week or ''} "
              f"-> {args.out}\n  tracer {c['tracer']} · body vs render "
              f"{c['body']} · unpushed {c['unpushed']} · not found "
              f"{c['not_found']} · orphans under tag {c['orphans']}"
              + ("" if listing_complete else "  (listing hit the 100-card cap; orphans may be undercounted)"),
              file=sys.stderr)
    else:
        sys.stdout.write(blob)


def cmd_record(args, repo, cfg, sdir):
    p = entity_path(sdir, args.id)
    if not os.path.isfile(p):
        die(f"no such entity: {args.id}")
    with open(p) as fh:
        e = json.load(fh)
    e.setdefault("deepvista", {})
    e["deepvista"]["card_id"] = args.card_id
    e["deepvista"]["synced_at"] = utc_now()
    # Hash the entity WITHOUT the deepvista block, matching plan's comparison.
    e["deepvista"]["content_hash"] = content_hash(e)
    write_entity(sdir, e)
    print(json.dumps({"id": args.id, "card_id": args.card_id,
                      "content_hash": e["deepvista"]["content_hash"],
                      "synced_at": e["deepvista"]["synced_at"]}, indent=2))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", dest="repo_sub", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", parents=[common], help="decide create/update/skip and render card bodies")
    p.add_argument("--week")
    p.add_argument("--all", action="store_true")
    p.add_argument("--category", choices=CATEGORY_ORDER)
    p.add_argument("--status")
    p.add_argument("--force", action="store_true", help="re-push even if unchanged")
    p.add_argument("--show-body", action="store_true", help="full markdown, not truncated")
    p.add_argument("--include-skipped", action="store_true")
    p.add_argument("--limit", type=int, default=0,
                   help="plan at most N items — use --limit 1 for a first live push")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("install-mcp", parents=[common],
                       help="register the DeepVista MCP server in this repo's .mcp.json")
    p.add_argument("--scope", choices=["project", "user"], default="project",
                   help="project writes .mcp.json; user prints the one-line command")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="replace a conflicting entry")
    p.add_argument("--transport", choices=["auto", "mcp-remote", "http"], default="auto",
                   help="auto (default) picks mcp-remote where Node 18+ can run it, "
                        "else the http form the host app authenticates itself")
    p.set_defaults(fn=cmd_install_mcp)

    p = sub.add_parser("doctor", parents=[common],
                       help="check the runtime, the registered entry and the endpoint")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("compare", parents=[common],
                       help="coverage diff: local summary vs one built from the cards")
    p.add_argument("week")
    p.add_argument("--against", required=True,
                   help="a summary built from the DeepVista cards, saved to a file")
    p.add_argument("--ours", default=None, help="local summary (default: the week's file)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("fetch", parents=[common],
                       help="read a week's cards back from DeepVista into a JSON file (headless)")
    p.add_argument("--week")
    p.add_argument("--all", action="store_true")
    p.add_argument("--out", default=None, help="write here instead of stdout")
    p.add_argument("--npx", default=None, help="npx to run the mcp-remote proxy with")
    p.add_argument("--timeout", type=int, default=90, help="seconds to wait per call")
    p.add_argument("--force", action="store_true", help="read even if deepvista.enabled is false")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("record", parents=[common], help="write back the card id after an MCP call")
    p.add_argument("--id", required=True)
    p.add_argument("--card-id", required=True)
    p.set_defaults(fn=cmd_record)

    args = ap.parse_args()
    repo = os.path.abspath(os.path.expanduser(args.repo_sub or args.repo))
    cfg = load_config(repo)
    # Propagated so `doctor` can be a preflight: a check that always exits 0 is
    # not a gate anything can be chained behind.
    raise SystemExit(args.fn(args, repo, cfg, store_dir(repo, cfg)) or 0)


if __name__ == "__main__":
    main()
