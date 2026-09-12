#!/usr/bin/env python3
"""
Runs on GitHub's servers (not the TV). Fetches today's games from ESPN and the
drink list from a Google Sheet, then writes small, simple JSON files the TV's
old browser can read from the same site.

Only uses the Python standard library so nothing needs installing.
"""
import csv
import io
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("BOARD_TZ", "America/New_York"))
SHEET_ID = os.environ.get("SHEET_ID", "").strip()

# key, display name, ESPN path, extra query
LEAGUES = [
    ("nfl", "NFL",                 "football/nfl",                       ""),
    ("cfb", "College Football",    "football/college-football",          ""),
    ("mlb", "MLB",                 "baseball/mlb",                       ""),
    ("nba", "NBA",                 "basketball/nba",                     ""),
    ("nhl", "NHL",                 "hockey/nhl",                         ""),
    ("cbb", "College Basketball",  "basketball/mens-college-basketball", ""),
    ("epl", "Premier League",      "soccer/eng.1",                       ""),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
    "Connection": "keep-alive",
}


def _get_urllib(url, timeout):
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_curl(url, timeout):
    import subprocess
    cmd = ["curl", "-sS", "-L", "--max-time", str(timeout), "--compressed", "-f"]
    for k, v in BROWSER_HEADERS.items():
        cmd += ["-H", "%s: %s" % (k, v)]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError("curl exit %d %s" % (out.returncode, out.stderr.decode("utf-8", "ignore").strip()[:120]))
    return out.stdout


def http_get(url, timeout=20):
    """Try a couple of ways; some sites' bot filters dislike Python's default client."""
    errors = []
    for name, fn in (("urllib", _get_urllib), ("curl", _get_curl)):
        try:
            data = fn(url, timeout)
            if data:
                return data
            errors.append("%s: empty" % name)
        except Exception as e:
            errors.append("%s: %s" % (name, str(e)[:100]))
    raise RuntimeError(" | ".join(errors))


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    """Write only if something other than the timestamp changed, so the site
    isn't rebuilt every few minutes when nothing is happening."""
    prev = load_json(path, None)
    if prev is not None:
        a = dict(prev); a.pop("updated", None)
        b = dict(obj);  b.pop("updated", None)
        if a == b:
            print("  (no change)")
            return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=True, separators=(",", ":"))


def fmt_time(iso):
    """ESPN gives e.g. 2026-09-12T17:00Z -> '1:00 PM' in board timezone."""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%MZ").replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(TZ)
        return local.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""


def parse_event(ev):
    comp = (ev.get("competitions") or [{}])[0]
    status = (comp.get("status") or ev.get("status") or {})
    stype = status.get("type") or {}
    state = stype.get("state", "pre")  # pre | in | post
    home = away = None
    for c in comp.get("competitors", []):
        team = c.get("team") or {}
        rec = ""
        recs = c.get("records") or []
        if recs:
            rec = recs[0].get("summary", "")
        rank = c.get("curatedRank", {}).get("current")
        if rank is not None and rank > 25:
            rank = None
        side = {
            "name": team.get("shortDisplayName") or team.get("displayName") or "",
            "abbr": team.get("abbreviation") or "",
            "score": c.get("score", ""),
            "rec": rec,
            "rank": rank,
            "winner": bool(c.get("winner")),
        }
        if c.get("homeAway") == "home":
            home = side
        else:
            away = side
    if home is None or away is None:
        return None

    if state == "pre":
        detail = fmt_time(ev.get("date", ""))
        if stype.get("name") == "STATUS_POSTPONED":
            detail = "Postponed"
    elif state == "in":
        detail = stype.get("shortDetail") or stype.get("detail") or "Live"
        # For soccer ESPN puts the clock in displayClock
        clock = status.get("displayClock")
        period = status.get("period")
        if detail and detail.upper() == "LIVE" and clock:
            detail = clock
    else:
        detail = stype.get("shortDetail") or "Final"
        if "Final" in detail and detail != "Final":
            # e.g. "Final/OT" keep as is, but strip dates like "Final - 9/12"
            detail = detail.split(" - ")[0]

    broadcast = ""
    bc = comp.get("broadcasts") or []
    if bc and bc[0].get("names"):
        broadcast = bc[0]["names"][0]

    return {
        "state": state,
        "detail": detail,
        "tv": broadcast,
        "home": home,
        "away": away,
        "sort": ev.get("date", ""),
    }


def fetch_league(key, name, path, extra):
    today = datetime.now(TZ)
    datestr = today.strftime("%Y%m%d")
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/%s/scoreboard?dates=%s%s" % (path, datestr, extra),
        "https://site.web.api.espn.com/apis/site/v2/sports/%s/scoreboard?dates=%s%s" % (path, datestr, extra),
    ]
    data = None
    for url in urls:
        try:
            data = json.loads(http_get(url).decode("utf-8"))
            break
        except Exception as e:
            print("  ! %s via %s: %s" % (name, url.split("/")[2], e), file=sys.stderr)
    if data is None:
        return None
    games = []
    for ev in data.get("events", []):
        # ESPN's dates filter is loose; keep only games that start today (local)
        try:
            dt = datetime.strptime(ev.get("date", ""), "%Y-%m-%dT%H:%MZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
            if dt.date() != today.date():
                continue
        except Exception:
            pass
        g = parse_event(ev)
        if g:
            games.append(g)
    # Live first, then upcoming, then finals; within each by start time
    order = {"in": 0, "pre": 1, "post": 2}
    games.sort(key=lambda g: (order.get(g["state"], 3), g["sort"]))
    for g in games:
        g.pop("sort", None)
    print("  %s: %d games" % (name, len(games)))
    return {"key": key, "name": name, "games": games}


def fetch_scores(prev):
    prev_leagues = {l["key"]: l for l in (prev.get("leagues") or [])}
    leagues = []
    for key, name, path, extra in LEAGUES:
        got = fetch_league(key, name, path, extra)
        if got is None and key in prev_leagues:
            got = prev_leagues[key]  # keep last good copy on a fetch hiccup
        if got is None:
            got = {"key": key, "name": name, "games": []}
        leagues.append(got)
    return {
        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "date_label": datetime.now(TZ).strftime("%A, %B %d").replace(" 0", " "),
        "leagues": leagues,
    }


def fetch_drinks(prev):
    if not SHEET_ID:
        print("  SHEET_ID not set; leaving drinks.json alone")
        return prev
    url = "https://docs.google.com/spreadsheets/d/%s/export?format=csv" % SHEET_ID
    try:
        raw = http_get(url).decode("utf-8-sig")
    except Exception as e:
        print("  ! drinks sheet failed: %s" % e, file=sys.stderr)
        return prev
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return prev
    header = [h.strip().lower() for h in rows[0]]

    def col(names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_name = col(["name", "drink", "item"])
    i_cat = col(["category", "type", "section"])
    i_price = col(["price", "cost"])
    i_stock = col(["in stock", "instock", "stock", "available"])
    i_note = col(["note", "notes", "description"])
    if i_name is None:
        print("  ! sheet needs a 'Name' column", file=sys.stderr)
        return prev

    items = []
    for r in rows[1:]:
        if i_name >= len(r) or not r[i_name].strip():
            continue

        def get(i):
            return r[i].strip() if (i is not None and i < len(r)) else ""

        stock = get(i_stock).lower()
        if stock in ("no", "n", "0", "false", "out", "x"):
            continue  # hidden from the board
        price = get(i_price)
        if price and price[0].isdigit():
            price = "$" + price
        items.append({
            "name": get(i_name),
            "cat": get(i_cat) or "Drinks",
            "price": price,
            "note": get(i_note),
        })
    print("  drinks: %d items" % len(items))
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "items": items}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scores_path = os.path.join(root, "data", "scores.json")
    drinks_path = os.path.join(root, "data", "drinks.json")

    print("Scores:")
    scores = fetch_scores(load_json(scores_path, {}))
    save_json(scores_path, scores)

    print("Drinks:")
    drinks = fetch_drinks(load_json(drinks_path, {"items": []}))
    save_json(drinks_path, drinks)


if __name__ == "__main__":
    main()
