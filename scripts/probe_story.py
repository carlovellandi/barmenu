#!/usr/bin/env python3
"""Can we get the actual body text of a feature story, not just the teaser?"""
import json, re, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.espn.com/"}
def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=t).read()

feed = json.loads(get("https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=50"))
art = None
for a in feed.get("articles", []):
    if a.get("type") == "Story" and any(c.get("type") == "athlete" for c in (a.get("categories") or [])):
        art = a; break
if not art:
    art = [a for a in feed["articles"] if a.get("type") == "Story"][0]

print("HEADLINE:", art.get("headline"))
print("ID:", art.get("id"), "| nowId:", art.get("nowId"))
print("DESC:", (art.get("description") or "")[:150])
print("TOP-LEVEL KEYS:", sorted(art.keys()))
print("HAS 'story' FIELD:", "story" in art)
print("LINKS:")
def walk(d, pre=""):
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            if "href" in v: print("   %s%s -> %s" % (pre, k, v["href"]))
            else: walk(v, pre + k + ".")
walk(art.get("links"))

aid = str(art.get("id"))
tries = [
  ("now.core",   "https://now.core.api.espn.com/v1/sports/news/%s" % aid),
  ("api.espn",   "http://api.espn.com/v1/sports/news/%s" % aid),
  ("core.site",  "https://site.api.espn.com/apis/site/v2/sports/news/%s" % aid),
]
web = ((art.get("links") or {}).get("web") or {}).get("href")
if web: tries.append(("web-html", web.split("?")[0]))

for name, url in tries:
    try:
        raw = get(url)
        body = raw.decode("utf-8", "ignore")
        print("\n=== %s OK %d bytes  (%s)" % (name, len(raw), url[:92]))
        if body.lstrip().startswith("{"):
            j = json.loads(body)
            print("    json keys:", list(j.keys())[:10])
            hs = (j.get("headlines") or [None])[0] or j
            print("    inner keys:", sorted(hs.keys())[:24] if isinstance(hs, dict) else type(hs))
            story = (hs or {}).get("story") if isinstance(hs, dict) else None
            if story:
                txt = re.sub(r"<[^>]+>", " ", story)
                txt = re.sub(r"\s+", " ", txt).strip()
                print("    STORY chars=%d" % len(txt))
                print("    FIRST 600:", txt[:600])
        else:
            paras = re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)
            clean = []
            for p in paras:
                t = re.sub(r"<[^>]+>", " ", p); t = re.sub(r"\s+", " ", t).strip()
                if len(t) > 60: clean.append(t)
            print("    <p> blocks >60 chars: %d" % len(clean))
            for t in clean[:4]: print("      *", t[:190])
    except Exception as e:
        print("\n=== %s FAIL %s" % (name, str(e)[:120]))
