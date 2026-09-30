#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Which ISO week does a moment belong to? One declared timezone decides.

THE RULE: a repo declares one zone; every week runs from Monday 00:00 to the
next Monday 00:00 IN THAT ZONE; and every timestamp -- a commit's git `%aI`, a
PR's GitHub `mergedAt` -- is converted into that zone before anything asks
which week, or which day, it belongs to. Two clocks, one conversion.

Why a declared zone, rather than the machine's zone or always-UTC:

  * Local slicing was the first bug. Git renders an author date in the
    AUTHOR's zone, so `%aI[:10]` gave a local day while `mergedAt` is UTC: the
    commit half and the PR half of one pull disagreed about where the week
    ended. Naive `--since/--until` dates are read in the MACHINE's zone, so the
    answer also moved with whoever ran the pull.
  * UTC fixed the disagreement and put the boundary in the wrong place. For
    work done in Pacific time, Sunday evening is still the week; in UTC it is
    already Monday. 2026-W39 in the tech repo: the UTC cut counted a PR merged
    Sun Sep 20, 20:47 PT -- a W38 PR -- and missed four merged on the Sunday
    evening of Sep 27 PT.
  * So, Bruce, 2026-09-29: "let's standardize on one timezone, and make it
    clear, otherwise, it'll mess with records in the future" -- Pacific,
    America/Los_Angeles, declared by every repo the weekly reads.

"Make it clear" is the other half of the rule: every week record names the zone
that cut it, with its exact start and end instants, and the cross-repo rollup
refuses to add up records cut in different zones.

When nothing is declared the zone is UTC -- the one choice that means the same
instant on every machine -- and a one-line notice on stderr says so, because an
undeclared zone is a decision nobody made.

This file is copied byte for byte into each skill that decides weeks (catchup,
rollup, fnr) instead of being imported across skills: a skill is deployed into
other repos on its own, and a cross-skill import breaks the first repo that
has one skill without the other. The copies are kept identical by hand, and
each skill's tests compare them whenever a sibling copy is present.

Store stamps (`updated_at`, `generated`) are a different thing. They record an
INSTANT, not a week decision, and stay UTC ISO with an explicit offset.
"""

import datetime as dt
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE = "UTC"


def zone(name):
    """A tzinfo for an IANA zone name. Raises ValueError with a readable message."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"timezone must be an IANA zone name such as "
                         f"'America/Los_Angeles', got {name!r}")
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown timezone {name!r} -- use an IANA zone name "
                         f"such as 'America/Los_Angeles' or 'UTC'") from None


def choose(cli=None, declared=None, where="config", prog="week"):
    """The zone to cut weeks in: `--timezone`, else the declared one, else UTC.

    Returns (name, source), source being "cli", "declared" or "default". The
    default is not an error -- a skill must work in a repo that has never
    heard of it -- but it is announced on stderr rather than left silent.
    """
    for val, source in ((cli, "cli"), (declared, "declared")):
        if val:
            zone(val)
            return val.strip(), source
    print(f"{prog}: no timezone declared in {where} -- cutting weeks in "
          f"{DEFAULT_ZONE}. Declare one so every record says which clock cut it.",
          file=sys.stderr)
    return DEFAULT_ZONE, "default"


def parse(ts):
    """An aware datetime from an ISO timestamp (git `%aI`, GitHub `mergedAt`).

    None for anything unparseable or NAIVE: a timestamp with no offset is an
    instant nobody can place, and guessing its zone is the bug this exists to
    prevent.
    """
    if isinstance(ts, dt.datetime):
        d = ts
    else:
        try:
            d = dt.datetime.fromisoformat(str(ts or "").strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.utcoffset() is not None else None


def local_date(ts, tz):
    """The calendar date of a timestamp in the declared zone, or None."""
    d = parse(ts)
    return d.astimezone(tz).date() if d else None


def week_label(year, week):
    return f"{year}-W{week:02d}"


def week_of(ts, tz):
    """'YYYY-Www' for a timestamp, decided in the declared zone; None if unplaceable."""
    d = local_date(ts, tz)
    if d is None:
        return None
    y, w, _ = d.isocalendar()
    return week_label(y, w)


class Week:
    """One ISO week in one zone: [Monday 00:00, next Monday 00:00), both aware.

    `start` and `end` are instants and `end` is EXCLUSIVE. `first_day` and
    `last_day` are the Monday and the Sunday, for display. Built by calendar
    arithmetic in the zone, so a DST week is 167 or 169 hours long and both
    ends are still local midnight.
    """

    def __init__(self, year, week, name):
        self.tz = zone(name)
        self.name = name.strip()
        monday = dt.date.fromisocalendar(year, week, 1)   # ValueError on a bad week
        self.year, self.week = year, week
        self.label = week_label(year, week)
        self.first_day = monday
        self.last_day = monday + dt.timedelta(days=6)
        self.start = dt.datetime.combine(monday, dt.time(0), tzinfo=self.tz)
        self.end = dt.datetime.combine(monday + dt.timedelta(days=7), dt.time(0),
                                       tzinfo=self.tz)
        # Compared in UTC. Python compares two datetimes sharing one tzinfo by
        # WALL CLOCK, which is wrong across a DST change; UTC has no such week.
        self._start_utc = self.start.astimezone(dt.timezone.utc)
        self._end_utc = self.end.astimezone(dt.timezone.utc)

    @classmethod
    def from_label(cls, label, name):
        y, _, w = str(label).upper().partition("-W")
        return cls(int(y), int(w), name)

    def contains(self, ts):
        """Whether a timestamp falls inside the week. Unplaceable -> False."""
        d = parse(ts)
        return d is not None and self._start_utc <= d.astimezone(dt.timezone.utc) < self._end_utc

    def hours(self):
        """Real elapsed hours: 168, or 167/169 in a week the clocks change."""
        return (self._end_utc - self._start_utc) / dt.timedelta(hours=1)

    def git_window(self, pad):
        """`--since`/`--until` values with an explicit offset, widened by `pad`.

        Never naive dates: git reads those in the machine's local zone, so the
        window moved with whoever ran the pull. An explicit offset is one
        instant everywhere. Filter the rows with `contains()` afterwards --
        git filters on committer date, the week is decided by author date.
        """
        return (self.start - pad).isoformat(), (self.end + pad).isoformat()

    def is_partial(self, today):
        """Whether the week is still running on `today`, a date in the declared zone."""
        return self.first_day <= today <= self.last_day

    def span(self):
        """'Mon Sep 21 – Sun Sep 27' -- the week as a reader names it."""
        return f"{self.first_day:%a %b} {self.first_day.day} – {self.last_day:%a %b} {self.last_day.day}"

    def footer(self):
        """The line a rendered summary carries, so its zone is never implicit."""
        return f"Week: {self.span()}, {self.name}"

    def stamp(self):
        """What a record carries so its cut can be checked later."""
        return {"timezone": self.name,
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
                "first_day": self.first_day.isoformat(),
                "last_day": self.last_day.isoformat()}


def today_in(tz, now=None):
    """Today's date in the declared zone -- what 'the last closed week' is judged by."""
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz).date()
