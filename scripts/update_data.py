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
DAY_ROLLOVER_HOUR = 5   # the "day" on the board runs until 5 AM, so late games stay up


def board_now():
    """Current time, shifted so that 12:00-4:59 AM still counts as the previous date."""
    return datetime.now(TZ) - timedelta(hours=DAY_ROLLOVER_HOUR)


def board_today():
    return board_now().date()
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

COLLEGE_MAX_GAMES = 21  # 3 screens of 7

# Harvard on ESPN: school id 108. (sport/league path, label)
HARVARD_ID = "108"
HARVARD_SPORTS = [
    ("football/college-football",            "Football"),
    ("basketball/mens-college-basketball",   "Men's Basketball"),
    ("basketball/womens-college-basketball", "Women's Basketball"),
    ("hockey/mens-college-hockey",           "Men's Hockey"),
    ("hockey/womens-college-hockey",         "Women's Hockey"),
    ("baseball/college-baseball",            "Baseball"),
    ("lacrosse/mens-college-lacrosse",       "Men's Lacrosse"),
    ("soccer/usa.ncaa.m.1",                  "Men's Soccer"),
    ("soccer/usa.ncaa.w.1",                  "Women's Soccer"),
]
HARVARD_DAYS_AHEAD = 7
HARVARD_MAX = 16   # up to two screens of 8
HARVARD_RSS = "https://gocrimson.com/calendar.ashx/calendar.rss"

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


def http_get(url, timeout=8):
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


def fetch_league(key, name, path, extra, day=None):
    today = day or board_today()
    datestr = today.strftime("%Y%m%d")
    urls = [
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
            if dt.date() != today:
                continue
        except Exception:
            pass
        g = parse_event(ev)
        if g:
            games.append(g)
    # College: hundreds of games a day is too many for a board. Keep games with a
    # ranked (top-25) team, plus anything live, then cap the total.
    if key in ("cfb", "cbb"):
        def keep(g):
            return g["state"] == "in" or g["home"]["rank"] or g["away"]["rank"]
        ranked = [g for g in games if keep(g)]
        if ranked:
            games = ranked
        games = games[:COLLEGE_MAX_GAMES]

    # Live first, then upcoming, then finals; within each by start time
    order = {"in": 0, "pre": 1, "post": 2}
    games.sort(key=lambda g: (order.get(g["state"], 3), g["sort"]))
    for g in games:
        g.pop("sort", None)
    print("  %s: %d games" % (name, len(games)))
    return {"key": key, "name": name, "games": games}


def short_sport(name):
    """Men's Soccer -> M Soccer, Women's Ice Hockey -> W Hockey, Sailing -> Sailing."""
    import re
    n = (name or "").strip()
    n = re.sub(r"^(harvard|crimson)\s+", "", n, flags=re.I)
    n = re.sub(r"\bice hockey\b", "Hockey", n, flags=re.I)
    n = re.sub(r"\b(cross country)\b", "XC", n, flags=re.I)
    n = re.sub(r"\b(track (and|&) field)\b", "Track", n, flags=re.I)
    n = re.sub(r"^(men'?s|mens|men)\b\s*", "M ", n, flags=re.I)
    n = re.sub(r"^(women'?s|womens|women)\b\s*", "W ", n, flags=re.I)
    n = re.sub(r"^(coed|co-ed)\s+", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip()


def short_opp(name):
    import re
    n = (name or "").strip()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = re.sub(r"^boston university$", "BU", n.strip(), flags=re.I)
    n = re.sub(r"^(the\s+)?university of\s+", "", n, flags=re.I)
    n = re.sub(r"\s+(university|univ\.?)\b", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -\u2013")
    return n


def _score_val(c):
    sc = c.get("score")
    if isinstance(sc, dict):
        return sc.get("displayValue") or str(sc.get("value", "")).rstrip("0").rstrip(".") or ""
    return "" if sc is None else str(sc)


def fetch_harvard_espn():
    now = datetime.now(TZ)
    today = board_today()
    horizon = today + timedelta(days=HARVARD_DAYS_AHEAD)
    games = []
    for path, label in HARVARD_SPORTS:
        urls = [
            "https://site.web.api.espn.com/apis/site/v2/sports/%s/teams/%s/schedule" % (path, HARVARD_ID),
        ]
        data = None
        for url in urls:
            try:
                data = json.loads(http_get(url).decode("utf-8"))
                break
            except Exception as e:
                last = e
        if data is None:
            print("  ! Harvard %s: %s" % (label, str(last)[:80]), file=sys.stderr)
            continue
        for ev in data.get("events", []):
            try:
                dt = datetime.strptime(ev.get("date", ""), "%Y-%m-%dT%H:%MZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
            except Exception:
                continue
            if dt.date() < today or dt.date() > horizon:
                continue
            comp = (ev.get("competitions") or [{}])[0]
            status = comp.get("status") or ev.get("status") or {}
            stype = status.get("type") or {}
            state = stype.get("state", "pre")
            us = them = None
            for c in comp.get("competitors", []):
                if str((c.get("team") or {}).get("id")) == HARVARD_ID or (c.get("team") or {}).get("displayName", "").startswith("Harvard"):
                    us = c
                else:
                    them = c
            if us is None or them is None:
                continue
            if state == "pre":
                detail = (dt.strftime("%a %I:%M %p").replace(" 0", " ")) if dt.date() != today else ("Today " + dt.strftime("%I:%M %p").lstrip("0"))
            elif state == "in":
                detail = stype.get("shortDetail") or "Live"
            else:
                detail = stype.get("shortDetail") or "Final"
                detail = detail.split(" - ")[0]
            games.append({
                "sport": short_sport(label),
                "opp": short_opp((them.get("team") or {}).get("shortDisplayName") or (them.get("team") or {}).get("displayName") or ""),
                "home": us.get("homeAway") == "home",
                "state": state,
                "detail": detail,
                "us": _score_val(us),
                "them": _score_val(them),
                "won": bool(us.get("winner")),
                "sort": ev.get("date", ""),
            })
    order = {"in": 0, "post": 1, "pre": 2}
    # today's games first (live, then finals, then later today), then upcoming by date
    games.sort(key=lambda g: (0 if g["sort"][:10] == now.strftime("%Y-%m-%d") else 1, order.get(g["state"], 3), g["sort"]))
    print("  Harvard (ESPN): %d games" % len(games))
    return games


def _norm_sport(name):
    n = name.lower().replace("ice hockey", "hockey").replace("'", "").strip()
    return n


def fetch_harvard_rss():
    """All-sports schedule from Harvard's athletics site (Sidearm RSS)."""
    import re
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    try:
        raw = http_get(HARVARD_RSS)
        root = ET.fromstring(raw)
    except Exception as e:
        print("  ! Harvard schedule feed: %s" % str(e)[:100], file=sys.stderr)
        return None
    now = datetime.now(TZ)
    today = board_today()
    horizon = today + timedelta(days=HARVARD_DAYS_AHEAD)
    items = root.findall(".//item")
    games, shown = [], 0
    for it in items:
        fields = {}
        for ch in it:
            tag = ch.tag.split("}")[-1].lower()
            fields[tag] = (ch.text or "").strip()
        title = fields.get("title", "")
        desc = re.sub(r"<[^>]+>", " ", fields.get("description", ""))
        # date: prefer sidearm's startdate, fall back to pubDate
        dt = None
        for key in ("startdate", "pubdate"):
            v = fields.get(key)
            if not v:
                continue
            try:
                dt = parsedate_to_datetime(v)
            except Exception:
                try:
                    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if dt:
                break
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        dt = dt.astimezone(TZ)
        if dt.date() < today or dt.date() > horizon:
            continue
        if shown < 3:
            print("    sample: %s | %s" % (title[:90], desc[:90].replace("\n", " ")))
            shown += 1
        # title looks like "9/12 1:00 PM Football vs Brown" or "Men's Soccer at UMass"
        t = re.sub(r"^\s*\d{1,2}/\d{1,2}(/\d{2,4})?\s+(\d{1,2}:\d{2}\s*[AP]M\s+)?", "", title, flags=re.I).strip()
        m = re.match(r"(.+?)\s+(vs\.?|at|@)\s+(.+)$", t, flags=re.I)
        if m:
            sport, va, opp = m.group(1), m.group(2).lower(), m.group(3)
        else:
            sport, va, opp = fields.get("sport") or t, "vs", fields.get("opponent", "")
        # Sidearm feeds sometimes name the sport in its own tag; prefer that when present
        if fields.get("sport"):
            sport = fields["sport"]
        if fields.get("opponent") and not m:
            opp = fields["opponent"]
        if fields.get("location", "").lower().find("away") >= 0:
            va = "at"
        sport = re.sub(r"^(harvard|crimson)\s+", "", sport, flags=re.I)
        opp = re.sub(r"\s*[-–]\s*(W|L|T)\b.*$", "", opp).strip()
        opp = re.sub(r"\s*\(.*?\)\s*$", "", opp).strip()
        home = not va.startswith("at") and va != "@"
        res = re.search(r"\b([WLT])[,\s]+(\d+)\s*-\s*(\d+)", title + " " + desc)
        if res:
            state, us, them = "post", res.group(2), res.group(3)
            detail = "Final"
            won = res.group(1).upper() == "W"
        else:
            us = them = ""
            won = False
            if dt < now and dt.date() == today and (now - dt) < timedelta(hours=4):
                state, detail = "in", "In progress"
            elif dt.date() == today:
                state, detail = "pre", "Today " + dt.strftime("%I:%M %p").lstrip("0")
            else:
                state, detail = "pre", dt.strftime("%a %I:%M %p").replace(" 0", " ")
        if state == "pre" and dt.hour == 0 and dt.minute == 0:
            detail = "Today" if dt.date() == today else dt.strftime("%a")   # time not announced
        games.append({
            "sport": short_sport(sport), "opp": short_opp(opp), "home": home, "state": state, "detail": detail,
            "us": us, "them": them, "won": won, "sort": dt.strftime("%Y-%m-%dT%H:%MZ"),
        })
    print("  Harvard (gocrimson): %d games in window" % len(games))
    return games


def fetch_harvard(prev):
    now = board_now()
    rss = fetch_harvard_rss()
    espn = fetch_harvard_espn()
    if rss is None:
        games = espn
    else:
        games = rss
        # overlay ESPN live/final scores onto the same sport + day
        for e in espn:
            if e["state"] == "pre":
                continue
            key = (_norm_sport(e["sport"]), e["sort"][:10])
            for i, g in enumerate(games):
                if (_norm_sport(g["sport"]), g["sort"][:10]) == key:
                    games[i] = e
                    break
            else:
                games.append(e)
    order = {"in": 0, "post": 1, "pre": 2}
    games.sort(key=lambda g: (0 if g["sort"][:10] == now.strftime("%Y-%m-%d") else 1, order.get(g["state"], 3), g["sort"]))
    games = games[:HARVARD_MAX]
    for g in games:
        g.pop("sort", None)
    print("  Harvard: %d games" % len(games))
    return {"name": "Harvard", "games": games}


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
    harvard = fetch_harvard(prev)
    out = {
        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "date_label": board_today().strftime("%A, %B %d").replace(" 0", " "),
        "leagues": leagues,
        "harvard": harvard,
    }
    # Morning extras: only bother between 4 AM and 1 PM so night runs stay quick
    hr = datetime.now(TZ).hour
    if 4 <= hr <= 13:
        out["yesterday"] = fetch_yesterday(prev)
        out["news"] = fetch_news(prev)
    else:
        if prev.get("yesterday"): out["yesterday"] = prev["yesterday"]
        if prev.get("news"): out["news"] = prev["news"]
    return out


def fetch_yesterday(prev):
    day = board_today() - timedelta(days=1)
    print("Yesterday's finals:")
    leagues = []
    for key, name, path, extra in LEAGUES:
        got = fetch_league(key, name, path, extra, day=day)
        if not got:
            continue
        finals = [g for g in got["games"] if g["state"] == "post"]
        if finals:
            leagues.append({"key": key, "name": name, "games": finals[:12]})
    return {"date_label": day.strftime("%A, %B %d").replace(" 0", " "), "leagues": leagues}


NEWS_PER_LEAGUE = 4
NEWS_MAX = 24


def fetch_news(prev):
    print("Headlines:")
    stories, seen = [], {}
    for key, name, path, extra in LEAGUES:
        url = "https://site.web.api.espn.com/apis/site/v2/sports/%s/news?limit=%d" % (path, NEWS_PER_LEAGUE * 2)
        try:
            data = json.loads(http_get(url).decode("utf-8"))
        except Exception as e:
            print("  ! %s news: %s" % (name, str(e)[:80]), file=sys.stderr)
            continue
        n = 0
        for a in data.get("articles", []):
            if a.get("type") in ("Media", "Video", "Podcast"):
                continue
            h = (a.get("headline") or "").strip()
            if not h or h.lower() in seen:
                continue
            seen[h.lower()] = 1
            d = (a.get("description") or "").strip()
            if len(d) > 180:
                d = d[:177].rsplit(" ", 1)[0] + "..."
            stories.append({"league": name, "headline": h, "desc": d, "published": a.get("published", "")})
            n += 1
            if n >= NEWS_PER_LEAGUE:
                break
        print("  %s: %d stories" % (name, n))
    stories.sort(key=lambda x: x["published"], reverse=True)
    stories = stories[:NEWS_MAX]
    for st in stories:
        st.pop("published", None)
    return stories


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

    items, notices = [], []
    for r in rows[1:]:
        if i_name >= len(r) or not r[i_name].strip():
            continue

        def get(i):
            return r[i].strip() if (i is not None and i < len(r)) else ""

        stock = get(i_stock).lower()
        if stock in ("no", "n", "0", "false", "out", "x"):
            continue  # hidden from the board
        if get(i_cat).strip().lower() in ("notice", "notices", "house notice"):
            notices.append(get(i_name))
            continue
        price = get(i_price)
        if price and price[0].isdigit():
            price = "$" + price
        items.append({
            "name": get(i_name),
            "cat": get(i_cat) or "Drinks",
            "price": price,
            "note": get(i_note),
        })
    print("  drinks: %d items, %d notices" % (len(items), len(notices)))
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "items": items, "notices": notices}


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
