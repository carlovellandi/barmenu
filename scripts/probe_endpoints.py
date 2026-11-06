#!/usr/bin/env python3
"""One-off: check which ESPN endpoints are reachable from GitHub's runners
and print enough shape to build against. Safe to delete afterwards."""
import json, sys, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
     "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.espn.com/"}

def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t).read()

B = "https://site.web.api.espn.com/apis"
TESTS = [
    ("cfb_rankings",  B + "/site/v2/sports/football/college-football/rankings"),
    ("cbb_rankings",  B + "/site/v2/sports/basketball/mens-college-basketball/rankings"),
    ("nfl_standings", B + "/v2/sports/football/nfl/standings?level=3"),
    ("nba_standings", B + "/v2/sports/basketball/nba/standings?level=2"),
    ("nhl_standings", B + "/v2/sports/hockey/nhl/standings?level=2"),
    ("nfl_news",      B + "/site/v2/sports/football/nfl/news?limit=10"),
    ("cbb_uci",       B + "/site/v2/sports/basketball/mens-college-basketball/teams/300"),
    ("cbb_sb_groups", B + "/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=400"),
]

for name, url in TESTS:
    try:
        raw = get(url)
        j = json.loads(raw)
        print("\n=== %s  OK  %d bytes" % (name, len(raw)))
        print("    keys: %s" % list(j.keys())[:10])
        if "rankings" in j:
            for r in j["rankings"][:3]:
                print("    poll: %r  type=%r  n=%d" % (r.get("name"), r.get("type"), len(r.get("ranks", []))))
            r0 = (j["rankings"] or [{}])[0]
            for e in (r0.get("ranks") or [])[:3]:
                t = e.get("team") or {}
                print("      #%s %s (%s) rec=%s pts=%s trend=%r" % (
                    e.get("current"), t.get("nickname") or t.get("name"), t.get("abbreviation"),
                    e.get("recordSummary"), e.get("points"), e.get("trend")))
        if "children" in j:
            print("    children: %d" % len(j["children"]))
            for c in j["children"][:2]:
                st = (c.get("standings") or {}).get("entries") or []
                print("      %r entries=%d" % (c.get("name"), len(st)))
                for e in st[:2]:
                    t = e.get("team") or {}
                    stats = {s.get("name"): s.get("displayValue") for s in (e.get("stats") or [])}
                    print("        %s  W=%s L=%s pct=%s" % (
                        t.get("displayName") or t.get("name"), stats.get("wins"),
                        stats.get("losses"), stats.get("winPercent")))
        if "articles" in j:
            for a in j["articles"][:4]:
                print("    art type=%-12r cat=%s" % (a.get("type"),
                      [c.get("description") or c.get("type") for c in (a.get("categories") or [])][:3]))
                print("        %r" % (a.get("headline") or "")[:95])
                print("        desc len=%d  %r" % (len(a.get("description") or ""), (a.get("description") or "")[:150]))
        if "team" in j:
            t = j["team"]
            print("    team: %s %s  id=%s  rec=%r" % (t.get("location"), t.get("name"), t.get("id"),
                  [r.get("summary") for r in ((t.get("record") or {}).get("items") or [])][:2]))
        if "events" in j:
            print("    events: %d" % len(j["events"]))
    except Exception as e:
        print("\n=== %s  FAIL  %s" % (name, str(e)[:140]))
