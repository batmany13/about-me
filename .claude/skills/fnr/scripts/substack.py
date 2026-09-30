#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Substack -- put a released weekly on the clipboard, ready to paste.

Substack has no API that writes posts: the Developer API looks up profiles and
the Publisher API reads posts and stats. Its editor does take rich text, so
this renders the weekly to HTML and puts that on the macOS clipboard; pasting
into a new Substack post keeps the headings, lists, links and emphasis.

    uv run .claude/skills/fnr/scripts/substack.py 2026-W38            # copy the body
    uv run .claude/skills/fnr/scripts/substack.py 2026-W38 --html out.html --no-copy

The weekly's H1 becomes the post's title and its opening paragraph the
subtitle -- both printed, for Substack's own fields -- and the rest is the body.
Owner-block markers are dropped and relative links become GitHub URLs, since a
post has no repo to be relative to.

It reads only `fnr/<W>.md`, and only once it is committed and clean: what
reaches Substack is exactly what is on the public record, never a draft.
Nothing is posted -- the paste, and Publish, stay his.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import subprocess
import sys
from pathlib import Path

WEEK = re.compile(r"^\d{4}-W\d{2}$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")
RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")

CODE = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
ITALIC = re.compile(r"(?<![\w*])[*_](?=\S)(.+?)(?<=\S)[*_](?![\w*])")

# Pastes as plain text from stdin, HTML alongside, so a rich editor takes the
# HTML and a plain one still gets readable text.
CLIPBOARD_JXA = """
ObjC.import('AppKit');
const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
const text = $.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding).js;
const [markup, plain] = text.split('\\u0000');
const pb = $.NSPasteboard.generalPasteboard;
pb.clearContents;
pb.setStringForType($(markup), 'public.html');
pb.setStringForType($(plain), 'public.utf8-plain-text');
"""


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def repo_blob_base(root: Path) -> str:
    """https://github.com/<owner>/<repo>/blob/main -- from the origin remote."""
    url = git(root, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"origin is not a GitHub remote ({url}); pass --base-url")
    return f"https://github.com/{m.group(1)}/blob/main"


def released_weekly(root: Path, week: str) -> Path:
    """The public file, committed and unmodified -- or refuse."""
    if not WEEK.match(week):
        sys.exit(f"not a week: {week} (want YYYY-WNN)")
    rel = f"fnr/{week}.md"
    path = root / rel
    if not path.is_file():
        sys.exit(f"{rel} does not exist -- has `state.py release` run for {week}?")
    try:
        git(root, "ls-files", "--error-unmatch", rel)
    except subprocess.CalledProcessError:
        sys.exit(f"{rel} is not committed -- commit the release first")
    if git(root, "status", "--porcelain", "--", rel):
        sys.exit(f"{rel} has uncommitted changes -- Substack gets the committed record only")
    return path


class Renderer:
    def __init__(self, source_dir: str, base_url: str):
        self.source_dir = source_dir  # the weekly's directory, repo-relative
        self.base_url = base_url

    def href(self, target: str) -> str:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            return target
        path, _, anchor = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(self.source_dir, path))
        return f"{self.base_url}/{resolved}" + (f"#{anchor}" if anchor else "")

    def inline(self, text: str) -> str:
        # Code spans and links go to placeholders first, so an underscore in a
        # URL or a star in code is never read as emphasis.
        held: list[str] = []

        def hold(fragment: str) -> str:
            held.append(fragment)
            return f"\x00{len(held) - 1}\x00"

        text = CODE.sub(lambda m: hold(f"<code>{html.escape(m.group(1))}</code>"), text)
        text = LINK.sub(
            lambda m: hold(
                f'<a href="{html.escape(self.href(m.group(2)))}">'
                f"{self.emphasis(html.escape(m.group(1)))}</a>"
            ),
            text,
        )
        text = self.emphasis(html.escape(text))
        return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)

    @staticmethod
    def emphasis(text: str) -> str:
        text = BOLD.sub(r"<strong>\1</strong>", text)
        return ITALIC.sub(r"<em>\1</em>", text)

    def blocks(self, markdown: str) -> list[str]:
        out: list[str] = []
        for block in re.split(r"\n\s*\n", COMMENT.sub("", markdown)):
            lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
            if not lines:
                continue
            if block.lstrip().startswith("```"):
                body = "\n".join(block.strip().splitlines()[1:]).rstrip("`").rstrip()
                out.append(f"<pre><code>{html.escape(body)}</code></pre>")
            elif (m := HEADING.match(lines[0])) and len(lines) == 1:
                level = len(m.group(1))
                out.append(f"<h{level}>{self.inline(m.group(2))}</h{level}>")
            elif len(lines) == 1 and RULE.match(lines[0]):
                out.append("<hr>")
            elif BULLET.match(lines[0]) or NUMBERED.match(lines[0]):
                out.append(self.list_block(lines))
            elif all(l.startswith(">") for l in lines):
                quoted = " ".join(l.lstrip("> ").strip() for l in lines)
                out.append(f"<blockquote><p>{self.inline(quoted)}</p></blockquote>")
            else:
                out.append(f"<p>{self.inline(' '.join(lines))}</p>")
        return out

    def list_block(self, lines: list[str]) -> str:
        tag = "ol" if NUMBERED.match(lines[0]) else "ul"
        items: list[str] = []
        for line in lines:
            m = BULLET.match(line) or NUMBERED.match(line)
            if m:
                items.append(m.group(1))
            elif items:  # a wrapped continuation of the item above
                items[-1] += " " + line
        body = "".join(f"<li>{self.inline(item)}</li>" for item in items)
        return f"<{tag}>{body}</{tag}>"


def split_post(blocks: list[str]) -> tuple[str, str, list[str]]:
    """(title, subtitle, body): the H1, the paragraph before the first H2, the rest."""
    title = subtitle = ""
    if blocks and blocks[0].startswith("<h1>"):
        title, blocks = blocks[0], blocks[1:]
    if blocks and blocks[0].startswith("<p>"):
        subtitle, blocks = blocks[0], blocks[1:]
    return plain(title), plain(subtitle), blocks


def plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def copy_to_clipboard(markup: str, text: str) -> None:
    if sys.platform != "darwin":
        sys.exit("--copy needs macOS; use --html and paste from a browser instead")
    subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", CLIPBOARD_JXA],
        input=f"{markup}\x00{text}".encode(),
        check=True,
        capture_output=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("week", help="the released week, e.g. 2026-W38")
    ap.add_argument("--repo", default=".", help="the about-me checkout (default: .)")
    ap.add_argument("--base-url", help="where relative links point (default: origin on GitHub, main)")
    ap.add_argument("--html", metavar="PATH", help="also write a standalone preview page")
    ap.add_argument("--no-copy", dest="copy", action="store_false", help="skip the clipboard")
    ap.add_argument("--whole", action="store_true", help="keep the title and subtitle in the body")
    args = ap.parse_args()

    root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel"))
    path = released_weekly(root, args.week)
    renderer = Renderer("fnr", args.base_url or repo_blob_base(root))
    blocks = renderer.blocks(path.read_text())

    title, subtitle, body = split_post(blocks)
    if args.whole:
        body = blocks
    markup = "\n".join(body)

    if args.html:
        page = (
            f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<body style='max-width:40rem;margin:2rem auto;font:17px/1.6 Georgia,serif'>"
            f"<h1>{html.escape(title)}</h1><p><em>{html.escape(subtitle)}</em></p><hr>"
            f"<article>{markup}</article>"
        )
        Path(args.html).write_text(page)
        print(f"wrote {args.html}")
    if args.copy:
        copy_to_clipboard(markup, "\n\n".join(plain(b) for b in body))
        print("body copied -- paste into a new Substack post")

    print(f"title:    {title}")
    print(f"subtitle: {subtitle}")


if __name__ == "__main__":
    main()
