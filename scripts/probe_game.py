#!/usr/bin/env python3
"""One-off: what does ESPN expose for Harvard-Yale (event 401867844)?"""
import json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "application/json, */*", "Referer": "https://www.espn.com/"}
def get(u, t=20):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t).read())
B = "https://site.web.api.espn.com/apis"
EV = "401867844"

try:
    s = get(B + "/site/v2/sports/football/college-football/summary?event=" + EV)
    print("SUMMARY keys:", sorted(s.keys()))
    comp = s["header"]["competitions"][0]
    print("date:", comp.get("date"), "| status:", comp["status"]["type"].get("state"), comp["status"]["type"].get("shortDetail"))
    print("broadcasts:", [b.get("media", {}).get("shortName") for b in comp.get("broadcasts", [])])
    for c in comp["competitors"]:
        t = c["team"]
        print("  %s id=%s %s rank=%s score=%s winner=%s records=%s" % (
            c.get("homeAway"), t.get("id"), t.get("displayName"), c.get("rank"), c.get("score"), c.get("winner"),
            [(r.get("type"), r.get("summary")) for r in c.get("record", [])]))
    gi = s.get("gameInfo") or {}
    print("venue:", (gi.get("venue") or {}).get("fullName"), "| weather:", gi.get("weather"))
    print("LEADERS:")
    for tl in s.get("leaders", []):
        print("  team:", tl["team"].get("displayName"))
        for cat in tl.get("leaders", []):
            for l in cat.get("leaders", [])[:1]:
                a = l.get("athlete", {})
                print("     %-16s %-24s #%s %s | %s" % (cat.get("displayName"), a.get("displayName"),
                      a.get("jersey"), (a.get("position") or {}).get("abbreviation"), l.get("displayValue")))
    bx = s.get("boxscore") or {}
    print("boxscore keys:", sorted(bx.keys()), "| players blocks:", len(bx.get("players", [])))
    for tm in bx.get("teams", []):
        st = {x.get("name"): x.get("displayValue") for x in tm.get("statistics", [])}
        print("  team stats", tm["team"].get("abbreviation"), list(st.items())[:8])
    print("predictor:", s.get("predictor"))
    pc = s.get("pickcenter") or []
    print("pickcenter:", [(p.get("provider", {}).get("name"), p.get("details"), p.get("overUnder")) for p in pc][:2])
    print("scoringPlays:", len(s.get("scoringPlays", [])), "| drives:", "current" in (s.get("drives") or {}))
    print("standings groups:", [g.get("header") for g in (s.get("standings") or {}).get("groups", [])])
    for g in (s.get("standings") or {}).get("groups", []):
        for e in (g.get("standings") or {}).get("entries", []):
            st = {x.get("name") or x.get("type"): x.get("displayValue") for x in e.get("stats", [])}
            print("     %-14s %s" % (e.get("team"), st))
except Exception as e:
    print("SUMMARY FAIL", repr(e)[:200])

for name, url in [
    ("athlete",   B + "/common/v3/sports/football/college-football/athletes/5226865"),
    ("ath-stats", B + "/common/v3/sports/football/college-football/athletes/5226865/stats"),
    ("ath-log",   B + "/common/v3/sports/football/college-football/athletes/5226865/gamelog"),
    ("team-stat", B + "/site/v2/sports/football/college-football/teams/108/statistics"),
    ("yale-team", B + "/site/v2/sports/football/college-football/teams/43"),
]:
    try:
        j = get(url)
        print("\n%s OK keys=%s" % (name, sorted(j.keys())[:12]))
        if name == "athlete":
            a = j.get("athlete", j)
            print("   ", a.get("displayName"), "#%s" % a.get("jersey"), (a.get("position") or {}).get("abbreviation"),
                  a.get("displayHeight"), a.get("displayWeight"), (a.get("experience") or {}).get("displayValue"),
                  a.get("displayBirthPlace"), "| statsSummary:", json.dumps(a.get("statsSummary"))[:300])
        if name == "ath-stats":
            for c in j.get("categories", [])[:4]:
                print("    cat:", c.get("name"), c.get("labels"))
                for st in c.get("statistics", []):
                    print("       ", (st.get("season") or {}).get("year"), st.get("stats"))
        if name == "ath-log":
            print("    labels:", j.get("labels"), "| seasonTypes:", len(j.get("seasonTypes", [])))
        if name == "team-stat":
            print("   ", json.dumps(j)[:500])
        if name == "yale-team":
            t = j.get("team", {})
            print("    ", t.get("displayName"), t.get("standingSummary"), [r.get("summary") for r in (t.get("record") or {}).get("items", [])])
    except Exception as e:
        print("\n%s FAIL %s" % (name, repr(e)[:140]))
