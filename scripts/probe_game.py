#!/usr/bin/env python3
"""One-off: run fetch_thegame against the real game and a finished one."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_data as u

pre = u.fetch_thegame()
print("@@PRE@@" + json.dumps(pre) + "@@END@@")

sched = json.loads(u.http_get("https://site.web.api.espn.com/apis/site/v2/sports/football/college-football/teams/108/schedule").decode())
done = [e for e in sched.get("events", []) if (((e.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}).get("state") == "post"]
last = done[-1]
print("last finished:", last.get("name"), last.get("id"))
post = u.fetch_thegame(last.get("id"))
print("@@POST@@" + json.dumps(post) + "@@END@@")
# is anyone from the roster findable in a finished box score? (shape check)
s = json.loads(u.http_get(u.SUMMARY_API % last.get("id")).decode())
pl = (s.get("boxscore") or {}).get("players") or []
print("box players blocks:", len(pl))
for blk in pl[:1]:
    for cat in (blk.get("statistics") or [])[:3]:
        a0 = (cat.get("athletes") or [{}])[0]
        print("   cat=%s labels=%s first=%s %s" % (cat.get("name"), cat.get("labels"), (a0.get("athlete") or {}).get("displayName"), a0.get("stats")))
sp = (s.get("scoringPlays") or [{}])[0]
print("scoringPlay keys:", sorted(sp.keys()))
