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

# Teams that always appear even when unranked (ESPN team ids, per league key).
FAVORITE_TEAMS = {
    "cbb": ["300"],      # UC Irvine Anteaters
}

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
HARVARD_MAX = 14   # two screens of 7
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
            "id": str(team.get("id") or ""),
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
        favs = FAVORITE_TEAMS.get(key) or []

        def is_fav(g):
            return g["home"].get("id") in favs or g["away"].get("id") in favs

        def keep(g):
            return g["state"] == "in" or g["home"]["rank"] or g["away"]["rank"] or is_fav(g)

        ranked = [g for g in games if keep(g)]
        if ranked:
            games = ranked
        if len(games) > COLLEGE_MAX_GAMES:
            # never let the cap drop a favorite
            fav_games = [g for g in games if is_fav(g)]
            rest = [g for g in games if not is_fav(g)]
            games = fav_games + rest[:max(0, COLLEGE_MAX_GAMES - len(fav_games))]
        for g in games:
            if is_fav(g):
                g["fav"] = True

    # Live first, then upcoming, then finals; within each by start time
    order = {"in": 0, "pre": 1, "post": 2}
    games.sort(key=lambda g: (order.get(g["state"], 3), g["sort"]))
    for g in games:
        g.pop("sort", None)
    print("  %s: %d games" % (name, len(games)))
    return {"key": key, "name": name, "games": games}


def short_sport(name):
    """'[W] Harvard University Men's Water Polo' -> 'M Water Polo'.
    Coed programs (sailing, rowing) carry no M/W."""
    import re
    n = " " + (name or "").strip() + " "
    n = re.sub(r"\[[^\]]*\]", " ", n)                      # drop [W]/[L] markers
    for _ in range(3):                                      # school words, anywhere
        n = re.sub(r"\s(harvard|crimson|university|univ\.?|athletics|varsity)\s", " ", n, flags=re.I)
    gender = ""
    if re.search(r"\bwom[ae]n'?s?\b", n, flags=re.I):
        gender = "W "
    elif re.search(r"\bm[ae]n'?s?\b", n, flags=re.I):
        gender = "M "
    n = re.sub(r"\b(wom[ae]n'?s?|m[ae]n'?s?)\b", " ", n, flags=re.I)
    n = re.sub(r"\b(coed|co-ed|mixed)\b", " ", n, flags=re.I)
    if re.search(r"\b(sailing|rowing|crew|equestrian|cheer)\b", n, flags=re.I):
        gender = ""
    n = re.sub(r"\bice hockey\b", "Hockey", n, flags=re.I)
    n = re.sub(r"\bswimming (and|&) diving\b", "Swim & Dive", n, flags=re.I)
    n = re.sub(r"\bswimming\b", "Swim", n, flags=re.I)
    n = re.sub(r"\bvolleyball\b", "Volleyball", n, flags=re.I)
    n = re.sub(r"\bbasketball\b", "Basketball", n, flags=re.I)
    n = re.sub(r"\bcross country\b", "XC", n, flags=re.I)
    n = re.sub(r"\b(indoor |outdoor )?track (and|&) field\b", "Track", n, flags=re.I)
    n = re.sub(r"\b(heavyweight|lightweight)\b", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" -\u2013")
    return (gender + n).strip() or "Harvard"


def short_opp(name):
    """'Dartmouth College' stays; 'Boston University' -> 'BU'; drops result tails."""
    import re
    n = (name or "").strip()
    n = re.sub(r"\[[^\]]*\]", " ", n)
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = re.sub(r"\s*[-\u2013,]\s*[WLT][,\s]+\d+\s*-\s*\d+.*$", "", n)
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
        if shown < 4:
            print("    raw: %s || %s" % (title[:110], desc[:110].replace("\n", " ")))
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
        opp = re.sub(r"\s*[-–]\s*(W|L|T)\b.*$", "", opp).strip()
        opp = re.sub(r"\s*\(.*?\)\s*$", "", opp).strip()
        home = not va.startswith("at") and va != "@"
        # Harvard's feed marks finished games with a [W]/[L]/[T] tag in the title.
        blob = title + " " + desc
        mark = re.search(r"\[\s*([WLT])\s*\]", blob)
        score = (re.search(r"\b[WLT][,\s]+(\d+)\s*[-\u2013]\s*(\d+)", blob)
                 or re.search(r"\b(\d+)\s*[-\u2013]\s*(\d+)\s*\(\s*[WLT]\s*\)", blob)
                 or (re.search(r"\b(\d+)\s*[-\u2013]\s*(\d+)\b", blob) if mark else None))
        if mark:
            state, detail = "post", "Final"
            won = mark.group(1).upper() == "W"
            us, them = (score.group(1), score.group(2)) if score else ("", "")
        elif False:
            pass
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
    # A tri-meet shows up as one row per opponent; show it as a single line.
    merged, byslot = [], {}
    for g in games:
        slot = (g["sport"], g["sort"][:16], g["state"])
        if slot in byslot:
            prev_g = byslot[slot]
            if g["opp"] and g["opp"] not in prev_g["opp"]:
                prev_g["opp"] = prev_g["opp"] + ", " + g["opp"] if prev_g["opp"] else g["opp"]
            continue
        byslot[slot] = g
        merged.append(g)
    games = merged

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
    # Morning-paper material. Only fetched in the small hours and through the
    # morning so evening runs stay quick; otherwise the last good copy is kept.
    hr = datetime.now(TZ).hour
    carry = ("yesterday", "news", "rankings", "standings")
    if (3 <= hr <= 13) or os.environ.get("FORCE_MORNING"):
        out["yesterday"] = fetch_yesterday(prev)
        out["news"] = fetch_news(prev)
        out["rankings"] = fetch_rankings(prev)
        out["standings"] = fetch_standings(out)
        # a fetch that came back empty shouldn't wipe yesterday's good copy
        for k in carry:
            if not out.get(k) and prev.get(k):
                out[k] = prev[k]
    else:
        for k in carry:
            if prev.get(k):
                out[k] = prev[k]
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


# ---------------------------------------------------------------- morning paper
#
# The old version pulled whatever ESPN's news feed returned, which is mostly
# transactional churn ("sources say X is questionable"). ESPN tags each article
# with a type: Recap (what happened), Story (features and analysis), Preview,
# HeadlineNews (wire churn) and Media (video). We keep the first two.

NEWS_GOOD_TYPES = ("Recap", "Story")
NEWS_PER_LEAGUE = 5
NEWS_MAX = 18
FEATURE_MAX = 6

# Headlines that are nearly always noise on a bar board.
NEWS_REJECT = ("fantasy", "best bets", "bets to make", "odds", "parlay", "survivor pool",
               "start 'em", "start em", "waiver", "power rankings: updated poll",
               "where to watch", "how to watch", "what to know", "live updates",
               "transfer rumors", "transfer talk", "mock draft", "takeaways from")

# A story about a named person tends to be the human-interest kind.
def _is_feature(a):
    cats = a.get("categories") or []
    has_athlete = any(c.get("type") == "athlete" for c in cats)
    return a.get("type") == "Story" and has_athlete


def _clean_desc(d, limit=170):
    """Trim on a sentence or word boundary, never mid-word."""
    import re
    d = " ".join((d or "").split())
    d = re.sub(r"^[\u2014\u2013-]+\s*", "", d)          # AP dateline dash
    d = d.replace(" -- ", " \u2014 ").replace("--", "\u2014")
    if len(d) <= limit:
        return d
    cut = d[:limit]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if dot > limit * 0.55:
        return cut[:dot + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "\u2026"


def fetch_news(prev):
    """Returns {'briefs': [...], 'features': [...]} for the morning paper."""
    print("Morning paper:")
    briefs, features, seen = [], [], {}
    for key, name, path, extra in LEAGUES:
        url = "https://site.web.api.espn.com/apis/site/v2/sports/%s/news?limit=50" % path
        try:
            arts = json.loads(http_get(url, timeout=12).decode("utf-8")).get("articles", [])
        except Exception as e:
            print("  ! %s news: %s" % (name, str(e)[:80]), file=sys.stderr)
            continue
        kept = 0
        for a in arts:
            if a.get("type") not in NEWS_GOOD_TYPES:
                continue
            h = " ".join((a.get("headline") or "").split())
            h = h.replace(" -- ", " \u2014 ").replace("--", "\u2014")
            if not h or h.lower() in seen:
                continue
            low = h.lower()
            if any(bad in low for bad in NEWS_REJECT):
                continue
            desc = _clean_desc(a.get("description"))        # briefs: two lines
            if len(desc) < 40:        # no context = no value on a wall screen
                continue
            seen[low] = 1
            item = {
                "league": name,
                "kind": "recap" if a.get("type") == "Recap" else "story",
                "headline": h,
                "desc": desc,
                "by": " ".join((a.get("byline") or "").split()),
                "published": a.get("published", ""),
            }
            if _is_feature(a):
                item["desc"] = _clean_desc(a.get("description"), 320)   # the feature gets room
                item["who"] = next((c.get("description") for c in (a.get("categories") or [])
                                    if c.get("type") == "athlete"), "")
                features.append(item)
            else:
                briefs.append(item)
            kept += 1
            if kept >= NEWS_PER_LEAGUE:
                break
        print("  %s: %d kept" % (name, kept))

    briefs.sort(key=lambda x: (x["kind"] != "recap", x["published"]), reverse=False)
    briefs.sort(key=lambda x: x["published"], reverse=True)
    briefs.sort(key=lambda x: 0 if x["kind"] == "recap" else 1)
    features.sort(key=lambda x: x["published"], reverse=True)
    briefs, features = briefs[:NEWS_MAX], features[:FEATURE_MAX]
    for lst in (briefs, features):
        for x in lst:
            x.pop("published", None)
    print("  -> %d briefs, %d features" % (len(briefs), len(features)))
    return {"briefs": briefs, "features": features}


# ---------------------------------------------------------------- rankings
RANK_SOURCES = [
    ("cfb", "College Football",   "football/college-football"),
    ("cbb", "College Basketball", "basketball/mens-college-basketball"),
]
# Which polls to show, best first. CFP only exists late in the CFB season.
POLL_PREF = [("cfp", "CFP Rankings"), ("ap", "AP Top 25")]


def fetch_rankings(prev):
    print("Rankings:")
    out = []
    for key, label, path in RANK_SOURCES:
        url = "https://site.web.api.espn.com/apis/site/v2/sports/%s/rankings" % path
        try:
            data = json.loads(http_get(url, timeout=12).decode("utf-8"))
        except Exception as e:
            print("  ! %s: %s" % (label, str(e)[:80]), file=sys.stderr)
            continue
        polls = {}
        for r in data.get("rankings") or []:
            t = (r.get("type") or "").lower()
            if t in polls:
                continue
            rows = []
            for e in (r.get("ranks") or [])[:25]:
                team = e.get("team") or {}
                trend = (e.get("trend") or "").strip()
                if trend in ("-", "0", ""):
                    move = ""
                elif trend.startswith("+"):
                    move = trend
                else:
                    move = "-" + trend.lstrip("-")
                rows.append({
                    "n": e.get("current"),
                    "team": team.get("nickname") or team.get("shortDisplayName") or team.get("name") or "",
                    "abbr": team.get("abbreviation") or "",
                    "rec": e.get("recordSummary") or "",
                    "move": move,
                })
            if rows:
                polls[t] = {"name": r.get("name") or t.upper(), "rows": rows}
        for t, nice in POLL_PREF:
            if t in polls:
                out.append({"league": label, "poll": nice, "rows": polls[t]["rows"]})
                print("  %s / %s (%s): %d" % (label, nice, polls[t]["name"], len(polls[t]["rows"])))
                break
    return out


# ---------------------------------------------------------------- standings
# level=3 gives league > conference > division for the NFL; level=2 stops at
# conference, which is what we want for the NBA and NHL.
STANDING_SOURCES = [
    ("nfl", "NFL", "football/nfl",      3),
    ("nba", "NBA", "basketball/nba",    2),
    ("nhl", "NHL", "hockey/nhl",        2),
    ("mlb", "MLB", "baseball/mlb",      3),
]
STANDINGS_PER_GROUP = 5     # teams shown per conference block (divisions show all 4)


def _stat(entry, *names):
    st = {s.get("name"): s for s in (entry.get("stats") or [])}
    for n in names:
        if n in st:
            return st[n].get("displayValue") or ""
    return ""


def _groups(node, depth=0, out=None):
    """Collect the deepest named groups that actually hold teams."""
    if out is None:
        out = []
    entries = (node.get("standings") or {}).get("entries") or []
    kids = node.get("children") or []
    if entries and not kids:
        out.append((node.get("name") or node.get("abbreviation") or "", entries))
    for c in kids:
        _groups(c, depth + 1, out)
    return out


def fetch_standings(prev):
    """`prev` here is the run being built: it already has today's games, and
    yesterday's, which together are a good test of what is actually in season."""
    print("Standings:")
    out = []
    active = set()
    for l in (prev.get("leagues") or []):
        if l.get("games"):
            active.add(l.get("key"))
    for l in ((prev.get("yesterday") or {}).get("leagues") or []):
        if l.get("games"):
            active.add(l.get("key"))
    print("  in season: %s" % (", ".join(sorted(active)) or "(none)"))
    for key, label, path, level in STANDING_SOURCES:
        url = "https://site.web.api.espn.com/apis/v2/sports/%s/standings?level=%d" % (path, level)
        try:
            data = json.loads(http_get(url, timeout=12).decode("utf-8"))
        except Exception as e:
            print("  ! %s: %s" % (label, str(e)[:80]), file=sys.stderr)
            continue
        groups = []
        for gname, entries in _groups(data):
            rows = []
            for e in entries:
                t = e.get("team") or {}
                w, l_, ties = _stat(e, "wins"), _stat(e, "losses"), _stat(e, "ties")
                rec = "%s-%s" % (w, l_)
                if ties and ties not in ("0", ""):
                    rec += "-" + ties
                rows.append({
                    "team": t.get("shortDisplayName") or t.get("displayName") or t.get("name") or "",
                    "rec": rec,
                    "extra": _stat(e, "streak", "gamesBehind", "winPercent"),
                })
            if rows:
                groups.append({"name": gname, "rows": rows[:STANDINGS_PER_GROUP]})
        if groups:
            if key not in active:
                print("  %s: skipped (out of season)" % label)
                continue
            out.append({"league": label, "groups": groups})
            print("  %s: %d groups" % (label, len(groups)))
    return out


# ---------------------------------------------------------------- cocktails
#
# The sheet lists what is physically in the room (bottles, cans, mixers, fruit).
# Everything below works out which drinks can actually be made from that, so the
# Cocktails section of the menu is never hand-maintained. Add a bottle or a
# bottle of tonic to the sheet and the drinks that use it appear on their own.
#
# Give a row Category = Mixer for things nobody orders on their own (tonic,
# Coke, limes, bitters): they count as stock but stay off the printed menu.

# (regex, tags). First match wins per phrase, so specific entries come first.
INGREDIENT_HINTS = [
    (r"ginger beer",                      ["ginger_beer"]),
    (r"ginger ale",                       ["ginger_ale"]),
    (r"diet coke|coke zero",              ["coke"]),
    (r"\bcoca[- ]?cola\b|\bcoke\b|\bcola\b", ["coke"]),
    (r"sprite|7[- ]?up|lemon[- ]lime soda", ["sprite"]),
    (r"tonic",                            ["tonic"]),
    (r"club soda|soda water|seltzer water|sparkling water", ["soda"]),
    (r"orange juice|\boj\b",              ["oj"]),
    (r"cranberry",                        ["cranberry"]),
    (r"pineapple",                        ["pineapple"]),
    (r"grapefruit|paloma mix",            ["grapefruit"]),
    (r"lemonade",                         ["lemonade"]),
    (r"sour mix|sweet.?(and|&).?sour",    ["sour"]),
    (r"tomato|clamato|bloody mary mix",   ["tomato"]),
    (r"\blimes?\b|lime juice",            ["lime"]),
    (r"\blemons?\b|lemon juice",          ["lemon"]),
    (r"\bmint\b",                         ["mint"]),
    (r"simple syrup|sugar|demerara",      ["sugar"]),
    (r"bitters",                          ["bitters"]),
    (r"grenadine",                        ["grenadine"]),
    (r"\bolives?\b",                      ["olive"]),
    (r"triple sec|cointreau|grand marnier|curacao|cura\u00e7ao", ["triple_sec"]),
    (r"campari",                          ["campari"]),
    (r"aperol",                           ["aperol"]),
    (r"dry vermouth|vermouth.*\bdry\b",   ["vermouth_dry"]),
    (r"sweet vermouth|rosso|vermouth.*sweet", ["vermouth_sweet"]),
    (r"vermouth",                         ["vermouth_sweet", "vermouth_dry"]),
    (r"prosecco|cava|champagne|sparkling wine", ["prosecco"]),
    (r"amaretto",                         ["amaretto"]),
    (r"kahlua|coffee liqueur",            ["kahlua"]),
    (r"baileys|irish cream",              ["cream_liqueur"]),
    (r"peach schnapps",                   ["peach"]),
    (r"elderflower|st[- ]?germain",       ["elderflower"]),
    (r"spiced rum|captain morgan",        ["rum", "spiced_rum"]),
    (r"dark rum|black rum|gosling",       ["rum", "dark_rum"]),
    (r"coconut rum|malibu",               ["rum", "coconut_rum"]),
    (r"\brum\b|bacardi",                  ["rum"]),
    (r"mezcal",                           ["tequila", "mezcal"]),
    (r"tequila|jose cuervo|espol|patr",   ["tequila"]),
    (r"\brye\b",                          ["whiskey", "rye"]),
    (r"bourbon|evan williams|bulleit|maker|jim beam|woodford|buffalo trace", ["whiskey", "bourbon"]),
    (r"scotch|johnnie walker|dewar|glenliv", ["whiskey", "scotch"]),
    (r"irish whisk|jameson|tullamore",    ["whiskey", "irish_whiskey"]),
    (r"whisk(e)?y|jack daniel|fireball",  ["whiskey"]),
    (r"\bgin\b|bombay|tanqueray|hendrick|beefeater", ["gin"]),
    (r"vodka|tito|smirnoff|absolut|new amsterdam|grey goose", ["vodka"]),
    (r"brandy|cognac|hennessy",           ["brandy"]),
    (r"\bsake\b",                         ["sake"]),
]

# name, hard requirements (each inner list = acceptable alternatives), note
COCKTAIL_BOOK = [
    ("Negroni",          [["gin"], ["campari"], ["vermouth_sweet"]],              "gin, Campari, sweet vermouth"),
    ("Negroni Sbagliato",[["campari"], ["vermouth_sweet"], ["prosecco"]],         "Campari, vermouth, prosecco"),
    ("Boulevardier",     [["bourbon", "whiskey"], ["campari"], ["vermouth_sweet"]], "bourbon, Campari, sweet vermouth"),
    ("Americano",        [["campari"], ["vermouth_sweet"], ["soda"]],             "Campari, vermouth, soda"),
    ("Aperol Spritz",    [["aperol"], ["prosecco"], ["soda"]],                    "Aperol, prosecco, splash of soda"),
    ("Campari Spritz",   [["campari"], ["prosecco"], ["soda"]],                   "Campari, prosecco, soda"),
    ("Garibaldi",        [["campari"], ["oj"]],                                   "Campari, orange juice"),
    ("Martini",          [["gin", "vodka"], ["vermouth_dry"]],                    "gin or vodka, dry vermouth"),
    ("Manhattan",        [["whiskey", "bourbon", "rye"], ["vermouth_sweet"]],     "whiskey, sweet vermouth, bitters"),
    ("Old Fashioned",    [["bourbon", "whiskey", "rye"], ["sugar"], ["bitters"]], "whiskey, sugar, bitters"),
    ("Whiskey Ginger",   [["whiskey", "bourbon"], ["ginger_ale"]],                "whiskey, ginger ale"),
    ("Whiskey Sour",     [["whiskey", "bourbon"], ["lemon", "sour"], ["sugar"]],  "whiskey, lemon, sugar"),
    ("Jack & Coke",      [["whiskey", "bourbon"], ["coke"]],                      "whiskey and Coke"),
    ("Seven & Seven",    [["whiskey"], ["sprite"]],                               "whiskey, lemon-lime soda"),
    ("Gin & Tonic",      [["gin"], ["tonic"]],                                    "gin, tonic, lime if we have it"),
    ("Tom Collins",      [["gin"], ["lemon", "sour"], ["soda"], ["sugar"]],       "gin, lemon, soda, sugar"),
    ("French 75",        [["gin"], ["lemon"], ["prosecco"]],                      "gin, lemon, prosecco"),
    ("Gimlet",           [["gin", "vodka"], ["lime"], ["sugar"]],                 "gin or vodka, lime, sugar"),
    ("Vodka Tonic",      [["vodka"], ["tonic"]],                                  "vodka, tonic"),
    ("Vodka Soda",       [["vodka"], ["soda"]],                                   "vodka, soda, lime if we have it"),
    ("Vodka Cranberry",  [["vodka"], ["cranberry"]],                              "vodka, cranberry"),
    ("Screwdriver",      [["vodka"], ["oj"]],                                     "vodka, orange juice"),
    ("Greyhound",        [["vodka", "gin"], ["grapefruit"]],                      "vodka, grapefruit"),
    ("Moscow Mule",      [["vodka"], ["ginger_beer"], ["lime"]],                  "vodka, ginger beer, lime"),
    ("Kamikaze",         [["vodka"], ["triple_sec"], ["lime"]],                   "vodka, triple sec, lime"),
    ("Cosmopolitan",     [["vodka"], ["triple_sec"], ["cranberry"], ["lime"]],    "vodka, triple sec, cranberry, lime"),
    ("Lemon Drop",       [["vodka"], ["triple_sec"], ["lemon"], ["sugar"]],       "vodka, triple sec, lemon, sugar"),
    ("Bloody Mary",      [["vodka"], ["tomato"]],                                 "vodka, tomato, whatever's in the spice rack"),
    ("Margarita",        [["tequila"], ["triple_sec"], ["lime"]],                 "tequila, triple sec, lime"),
    ("Tequila Soda",     [["tequila"], ["soda"], ["lime"]],                       "tequila, soda, lime"),
    ("Paloma",           [["tequila"], ["grapefruit"]],                           "tequila, grapefruit, salt if we're fancy"),
    ("Rum & Coke",       [["rum"], ["coke"]],                                     "rum and Coke"),
    ("Cuba Libre",       [["rum"], ["coke"], ["lime"]],                           "rum, Coke, lime"),
    ("Daiquiri",         [["rum"], ["lime"], ["sugar"]],                          "rum, lime, sugar"),
    ("Mojito",           [["rum"], ["lime"], ["mint"], ["soda"]],                 "rum, lime, mint, soda"),
    ("Dark & Stormy",    [["dark_rum", "spiced_rum", "rum"], ["ginger_beer"], ["lime"]], "dark rum, ginger beer, lime"),
    ("Rum Punch",        [["rum"], ["pineapple"], ["oj"]],                        "rum, pineapple, orange"),
    ("Pi\u00f1a Colada",   [["coconut_rum", "rum"], ["pineapple"]],                 "rum, pineapple, coconut if we have it"),
    ("Sidecar",          [["brandy"], ["triple_sec"], ["lemon"]],                 "brandy, triple sec, lemon"),
    ("Amaretto Sour",    [["amaretto"], ["lemon", "sour"]],                       "amaretto, lemon"),
    ("White Russian",    [["vodka"], ["kahlua"], ["cream_liqueur"]],              "vodka, coffee liqueur, cream"),
    ("Mimosa",           [["prosecco"], ["oj"]],                                  "prosecco, orange juice"),
    ("Bellini",          [["prosecco"], ["peach"]],                               "prosecco, peach"),
    ("Shirley Temple",   [["sprite"], ["grenadine"]],                             "no booze: lemon-lime and grenadine"),
    ("Roy Rogers",       [["coke"], ["grenadine"]],                               "no booze: Coke and grenadine"),
]

MIXER_CATS = ("mixer", "mixers", "pantry", "supplies", "ingredient", "ingredients")
COCKTAIL_CATS = ("cocktail", "cocktails", "house cocktails", "drinks to make")
# A pre-made can lists its contents on the label; that is not loose stock.
SEALED_CATS = ("canned cocktails", "canned cocktail", "rtd", "seltzer", "beer", "wine", "cider")
COCKTAIL_MAX = 16


def tags_for(text):
    import re
    found, low = [], " %s " % (text or "").lower()
    for pat, tags in INGREDIENT_HINTS:
        if re.search(pat, low):
            for t in tags:
                if t not in found:
                    found.append(t)
    return found


def makeable_cocktails(items, extra_tags):
    """items: inventory rows. Returns menu rows for everything we can build."""
    have = set(extra_tags)
    for it in items:
        if (it.get("cat") or "").strip().lower() in SEALED_CATS:
            continue          # a sealed can's label is not a shelf of ingredients
        for t in tags_for(" ".join([it.get("name", ""), it.get("note", ""), it.get("cat", "")])):
            have.add(t)
    made, near = [], []
    for name, need, note in COCKTAIL_BOOK:
        missing = [grp for grp in need if not any(t in have for t in grp)]
        if not missing:
            made.append({"name": name, "note": note, "base": need[0][0]})
        elif len(missing) == 1:
            near.append((name, missing[0][0]))
    print("  stock tags: %s" % (", ".join(sorted(have)) or "(none)"))
    print("  makeable: %d -> %s" % (len(made), ", ".join(m["name"] for m in made) or "(none)"))
    if near:
        print("  one ingredient away: %s" % "; ".join("%s (needs %s)" % n for n in near[:14]))

    # Round-robin by base spirit so a long list doesn't come out as six Campari
    # drinks followed by six whiskey ones.
    bases, order = {}, []
    for m in made:
        b = m["base"]
        if b not in bases:
            bases[b] = []
            order.append(b)
        bases[b].append(m)
    picked = []
    while len(picked) < min(len(made), COCKTAIL_MAX):
        progressed = False
        for b in order:
            if bases[b]:
                picked.append(bases[b].pop(0))
                progressed = True
                if len(picked) >= COCKTAIL_MAX:
                    break
        if not progressed:
            break
    if len(picked) < len(made):
        print("  showing %d of %d (rotating by base spirit)" % (len(picked), len(made)))
    return [{"name": m["name"], "cat": "Cocktails", "price": "", "note": m["note"]} for m in picked]


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
    i_tags = col(["tags", "tag", "ingredients"])
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
            "tags": get(i_tags),
        })

    # Split the sheet into: things we pour (menu), things we only mix with
    # (stock), and the hand-written cocktail rows the engine now replaces.
    menu, stock_only, hand_cocktails = [], [], []
    for it in items:
        c = (it.get("cat") or "").strip().lower()
        if c in MIXER_CATS:
            stock_only.append(it)
        elif c in COCKTAIL_CATS:
            hand_cocktails.append(it)
        else:
            menu.append(it)

    extra = []
    for it in items:
        for t in (it.get("tags") or "").replace(";", ",").split(","):
            t = t.strip().lower().replace(" ", "_")
            if t:
                extra.append(t)
    print("  cocktail engine:")
    built = makeable_cocktails(menu + stock_only, extra)
    if not built and hand_cocktails:
        print("  (nothing computed; keeping the sheet's own cocktail rows)")
        built = [{"name": h["name"], "cat": "Cocktails", "price": h.get("price", ""),
                  "note": h.get("note", "")} for h in hand_cocktails]
    for it in menu:
        it.pop("tags", None)
    out_items = menu + built
    print("  drinks: %d on the menu (%d poured + %d mixed), %d stock-only, %d notices"
          % (len(out_items), len(menu), len(built), len(stock_only), len(notices)))
    return {"updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
            "items": out_items, "notices": notices}


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
