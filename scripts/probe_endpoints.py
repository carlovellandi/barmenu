#!/usr/bin/env python3
"""Probe round 2: NFL standings nesting, article type distribution, recap text."""
import json, urllib.request, collections

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Referer": "https://www.espn.com/"}
def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t).read()
B = "https://site.web.api.espn.com/apis"

print("########## NFL STANDINGS NESTING (level=3)")
j = json.loads(get(B + "/v2/sports/football/nfl/standings?level=3"))
def walk(node, d=0):
    nm = node.get("name") or node.get("abbreviation")
    ent = (node.get("standings") or {}).get("entries") or []
    print("  " * d + "- %r  entries=%d  children=%d" % (nm, len(ent), len(node.get("children") or [])))
    for e in ent[:2]:
        t = e.get("team") or {}
        st = {s.get("name"): s.get("displayValue") for s in (e.get("stats") or [])}
        print("  " * d + "    %-24s W=%s L=%s T=%s pct=%s str=%s" % (
            t.get("displayName"), st.get("wins"), st.get("losses"), st.get("ties"),
            st.get("winPercent"), st.get("streak")))
    for c in (node.get("children") or []):
        walk(c, d + 1)
walk(j)

print("\n########## ARTICLE TYPES PER LEAGUE")
for nm, path in [("NFL","football/nfl"), ("NBA","basketball/nba"), ("NHL","hockey/nhl"),
                 ("CFB","football/college-football"), ("CBB","basketball/mens-college-basketball"),
                 ("EPL","soccer/eng.1")]:
    try:
        a = json.loads(get(B + "/site/v2/sports/%s/news?limit=50" % path)).get("articles", [])
        c = collections.Counter(x.get("type") for x in a)
        print("  %-5s n=%-3d %s" % (nm, len(a), dict(c)))
        for x in a:
            if x.get("type") == "Story":
                print("        STORY  %r" % (x.get("headline") or "")[:88])
                print("               desc(%d): %r" % (len(x.get("description") or ""), (x.get("description") or "")[:170]))
                break
    except Exception as e:
        print("  %-5s FAIL %s" % (nm, str(e)[:70]))

print("\n########## RECAP-TYPE CONTENT? (nfl, all fields on one Story)")
a = json.loads(get(B + "/site/v2/sports/football/nfl/news?limit=30")).get("articles", [])
for x in a:
    if x.get("type") == "Story":
        print("  fields:", sorted(x.keys()))
        print("  byline:", repr(x.get("byline")))
        print("  published:", x.get("published"))
        print("  categories:", [(c.get("type"), c.get("description")) for c in (x.get("categories") or [])][:6])
        break
