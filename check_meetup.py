#!/usr/bin/env python3
"""
RSVP-opening reminders for a public Meetup group, pushed to your phone via ntfy.sh.

For every upcoming event whose RSVPs aren't open yet, this reads the event's RSVP
opening time from Meetup and schedules three pushes on ntfy's server:

    1 hour before   "RSVPs open in 1 hour"
    15 sec before   "RSVPs open in 15 seconds"
    at opening      "RSVPs are open now"

ntfy delivers them at those exact times, so it doesn't matter that GitHub Actions
only runs this script roughly hourly. Each run re-sends the schedule with the same
IDs, which replaces the previous one, so if the organizer moves the opening time
the reminders move with it. If an event is cancelled, its reminders are cancelled.

Standard library only. Environment variables:

  MEETUP_GROUP_URL  required  e.g. https://www.meetup.com/diamond-bar-hacienda-heights-pick-up-soccer-meetup-group/
  NTFY_TOPIC        required  Your private ntfy topic name
  TITLE_FILTER      optional  Only events whose title contains this text (case-insensitive)
  REMINDERS         optional  Seconds before opening to remind, default "3600,15"
  NTFY_SERVER       optional  Default https://ntfy.sh
  STATE_FILE        optional  Default .state/meetup.json
  TEST_NOTIFY       optional  "true" sends a status push showing what's scheduled

It only reads public pages (no Meetup login) and never RSVPs for you.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NTFY_MIN_DELAY = 12          # ntfy won't schedule closer than 10s out
NTFY_MAX_DELAY = 3 * 86400   # ...or further than 3 days out


def env(name, default=None, required=False):
    val = (os.environ.get(name) or "").strip()
    if not val:
        if required:
            sys.exit(f"Missing required environment variable {name}")
        return default
    return val


GROUP_URL = env("MEETUP_GROUP_URL", required=True)
NTFY_TOPIC = env("NTFY_TOPIC", required=True)
TITLE_FILTER = (env("TITLE_FILTER", "") or "").lower()
REMINDERS = sorted({int(x) for x in env("REMINDERS", "3600,15").split(",") if x.strip()}, reverse=True)
NTFY_SERVER = env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
STATE_FILE = env("STATE_FILE", ".state/meetup.json")
TEST = env("TEST_NOTIFY", "false").lower() in ("1", "true", "yes")


# ---------- Meetup ----------

def group_slug(url):
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if not parts:
        raise RuntimeError(f"Can't find a group name in {url}")
    return parts[0]


def apollo_state(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GET {url} -> HTTP {e.code}") from e
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f"Meetup page layout changed (no __NEXT_DATA__) at {url}")
    state = (json.loads(m.group(1)).get("props", {}).get("pageProps", {}) or {}).get("__APOLLO_STATE__")
    if not isinstance(state, dict):
        raise RuntimeError(f"Meetup page layout changed (no event data) at {url}")
    return state


def upcoming_events(slug):
    state = apollo_state(f"https://www.meetup.com/{slug}/events/")
    raw = [v for v in state.values() if isinstance(v, dict) and v.get("__typename") == "Event"]
    if not raw:
        raise RuntimeError("No events found on the group page; Meetup may have changed it")
    events = {}
    for v in raw:
        title = v.get("title") or "Event"
        if v.get("status") != "ACTIVE" or slug not in (v.get("eventUrl") or ""):
            continue
        if v.get("rsvpState") in ("PAST", "CLOSED"):
            continue
        if TITLE_FILTER and TITLE_FILTER not in title.lower():
            continue
        events[str(v["id"])] = {
            "title": title,
            "when": v.get("dateTime") or "",
            "url": v.get("eventUrl"),
            "state": v.get("rsvpState") or "",
        }
    return events


def rsvp_open_time(event_url):
    """Return the RSVP opening time (aware datetime) from the event's own page, or None."""
    state = apollo_state(event_url)
    for v in state.values():
        if isinstance(v, dict) and isinstance(v.get("rsvpSettings"), dict):
            t = v["rsvpSettings"].get("rsvpOpenTime")
            if t:
                return datetime.fromisoformat(t)
    for v in state.values():  # settings object stored separately in some layouts
        if isinstance(v, dict) and v.get("rsvpOpenTime"):
            return datetime.fromisoformat(v["rsvpOpenTime"])
    return None


# ---------- ntfy ----------

def ntfy(path, message=None, headers=None, method="POST"):
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{path}",
        data=message.encode("utf-8") if message is not None else None,
        method=method,
        headers=headers or {},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def schedule(seq_id, at_unix, title, body, click, priority, tags):
    ntfy(f"{urllib.parse.quote(NTFY_TOPIC)}/{seq_id}", body, {
        "At": str(int(at_unix)),
        "Title": title, "Priority": priority, "Tags": tags, "Click": click,
    })


def cancel(seq_id):
    try:
        ntfy(f"{urllib.parse.quote(NTFY_TOPIC)}/{seq_id}", method="DELETE")
    except urllib.error.HTTPError:
        pass  # already delivered or gone


def send_now(title, body, click, priority="default", tags="soccer"):
    ntfy(urllib.parse.quote(NTFY_TOPIC), body,
         {"Title": title, "Priority": priority, "Tags": tags, "Click": click})


# ---------- helpers ----------

def fmt_time(dt):
    return dt.strftime("%a %b %-d, %-I:%M %p")


def fmt_lead(secs):
    if secs % 3600 == 0:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''}"
    if secs % 60 == 0:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''}"
    return f"{secs} seconds"


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


# ---------- main ----------

def main():
    now = time.time()
    slug = group_slug(GROUP_URL)
    events = upcoming_events(slug)
    old = load_state()          # event_id -> {"open": unix, "ids": [seq ids]}
    new = {}
    summary = []

    for eid, e in sorted(events.items(), key=lambda kv: kv[1]["when"]):
        game = fmt_time(datetime.fromisoformat(e["when"])) if e["when"] else e["title"]
        if e["state"] != "NOT_OPEN_YET":
            print(f"  {game}: RSVP state {e['state']}, nothing to schedule")
            continue
        opens = rsvp_open_time(e["url"])
        if not opens:
            print(f"  {game}: RSVPs not open yet, but no opening time published")
            summary.append(f"{game}: opening time not published")
            continue

        open_unix = opens.timestamp()
        print(f"  {game}: RSVPs open {opens.isoformat()}")
        summary.append(f"Game {game}: RSVPs open {fmt_time(opens)}")

        pushes = [(f"m{eid}-{lead}", open_unix - lead, lead) for lead in REMINDERS] + \
                 [(f"m{eid}-open", open_unix, 0)]
        ids = []
        for seq_id, at, lead in pushes:
            delay = at - now
            if delay < NTFY_MIN_DELAY:
                continue        # moment passed (or already delivered)
            if delay > NTFY_MAX_DELAY:
                continue        # too far out for ntfy; a later run will schedule it
            if lead:
                title = f"Soccer RSVPs open in {fmt_lead(lead)}"
                body = f"{e['title']}, {game}\nOpens {fmt_time(opens)}. Get the page ready."
                prio, tags = ("urgent", "rotating_light,soccer") if lead <= 60 else ("high", "alarm_clock,soccer")
            else:
                title = "Soccer RSVPs are OPEN"
                body = f"{e['title']}, {game}\nTap to RSVP now."
                prio, tags = "urgent", "rotating_light,soccer"
            schedule(seq_id, at, title, body, e["url"], prio, tags)
            ids.append(seq_id)
            print(f"    scheduled '{title}' for {datetime.fromtimestamp(at, opens.tzinfo).isoformat()}")

        prev = old.get(eid, {})
        # keep remembering already-scheduled IDs so a cancellation can still remove them
        keep = [i for i in prev.get("ids", []) if prev.get("open", 0) > now]
        new[eid] = {"open": open_unix, "ids": sorted(set(ids) | set(keep))}

    # Events that vanished, got cancelled, or opened early: cancel their pending reminders.
    for eid, prev in old.items():
        if eid not in new and prev.get("open", 0) > now:
            for seq_id in prev.get("ids", []):
                cancel(seq_id)
            print(f"  cancelled pending reminders for event {eid}")
            e = events.get(eid)
            if e and e["state"] == "JOIN_OPEN":   # organizer opened RSVPs early
                send_now("Soccer RSVPs are OPEN (early)",
                         f"{e['title']}\nRSVPs opened earlier than scheduled. Tap to RSVP now.",
                         e["url"], priority="urgent", tags="rotating_light,soccer")
                print(f"  RSVPs opened early for event {eid}; sent alert")

    if TEST:
        send_now("Meetup checker is working",
                 "\n".join(summary) or "No upcoming games with a published RSVP opening time yet.",
                 GROUP_URL, tags="white_check_mark")
        print("Sent test notification")

    save_state(new)


if __name__ == "__main__":
    main()
