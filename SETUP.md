# Bar board – setup

Everything runs on GitHub. The TV only ever loads one plain-HTTP web page.

## 1. Put the files in your repo

Upload these, keeping the folder structure exactly:

```
index.html
data/scores.json
data/drinks.json
scripts/update_data.py
.github/workflows/update.yml
```

On github.com: open the repo → **Add file → Upload files** → drag the whole
`barboard` folder contents in → **Commit changes**. (Folders upload fine from a
computer; on a phone, use "Create new file" and type the path
`.github/workflows/update.yml` in the filename box to create folders.)

The repo must be **public** (free scheduled jobs need that).

## 2. Turn on the website

Repo → **Settings → Pages** → under *Build and deployment* choose
**Deploy from a branch**, branch **main**, folder **/ (root)** → Save.

Leave **Enforce HTTPS** unchecked. Your address will be
`http://YOURNAME.github.io/REPONAME/` (note `http`, not `https`).
It takes a minute or two to appear the first time.

## 3. Make the drinks sheet

1. Create a Google Sheet. Row 1 must be headers. Use these column names
   (order doesn't matter, capitalisation doesn't matter):

   | Name | Category | Price | In Stock | Note |
   |------|----------|-------|----------|------|
   | Harpoon IPA | Beer | 7 | yes | 16 oz can |
   | Old Fashioned | Cocktails | 12 | yes | rye, bitters |
   | Guinness | Beer | 7 | no | |

   * **In Stock** = anything other than `no` / `n` / `0` / `out` / `x` shows.
     Blank counts as in stock.
   * **Price** – type just the number; a `$` is added. Leave blank to hide it.
   * **Note** is optional (shows small under the name).
   * Categories appear in the order they first occur in the sheet.
2. **Share → General access → Anyone with the link → Viewer**.
3. Copy the ID from the sheet's URL – it's the long string between
   `/d/` and `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`1AbCdEf...xyz`**`/edit`

## 4. Give GitHub the sheet ID

Repo → **Settings → Secrets and variables → Actions → Variables tab →
New repository variable**. Name: `SHEET_ID`. Value: the ID you copied. Save.

## 5. Run it once by hand

Repo → **Actions** → *Update board data* → **Run workflow → Run workflow**.
Wait ~1 minute, open the run, and check both steps are green. After that it
runs itself every ~6 minutes, forever, and only commits when something changed.

If Actions shows a "workflows are disabled" banner, press **Enable**.

## 6. On the TV

Open **Web Browser** → go to `http://YOURNAME.github.io/REPONAME/`.
In the browser settings, set that as the **home page** and hide the toolbar.
From then on: turn on TV → Smart Hub → Web Browser, and it's up.

## The sheet

Row 1 is headers. Recognised columns: **Name**, **Category**, **Price**,
**In Stock**, **Note**, **Tags**. Anything else is ignored.

* **In Stock** – `no` / `n` / `0` / `out` / `x` hides the row. Blank = in stock.
* **Price** – type the number; a `$` is added. Leave the whole column blank and
  the menu drops the prices and dotted leaders entirely.
* **Category** drives the section bands, and three names are special:
  * `Notice` – the row becomes a rotating house notice in the footer.
  * `Mixer` – stock that is not a drink (Coke, tonic, limes, bitters, simple
    syrup). Counted by the cocktail engine, never printed on the menu.
  * `Cocktails` – ignored. This section is generated, not typed (below).
* **Tags** – optional override when a bottle's name gives nothing away. Comma
  separated, e.g. `bourbon` or `triple_sec`.

## Cocktails build themselves

List the bottles and mixers you actually have and the board works out what can
be made from them. Add tonic to the sheet and Gin & Tonic and Vodka Tonic show
up on their own; run out and they disappear.

The Actions log for each run prints three useful lines:

```
stock tags: aperol, bourbon, campari, gin, ...
makeable: 5 -> Negroni, Negroni Sbagliato, Boulevardier, Martini, Manhattan
one ingredient away: Gin & Tonic (needs tonic); Jack & Coke (needs coke); ...
```

That last line is the shopping list: each of those is one purchase away from
appearing on the menu. **Mixers are what unlock most of the book** – with
spirits alone only a handful of drinks are possible.

The recipe book lives in `COCKTAIL_BOOK` in `scripts/update_data.py`; add a
line to it to teach the board a new drink.

## The morning paper (5 AM – noon)

Between those hours most of the rotation becomes:

* **The morning paper** – overnight recaps and features. ESPN tags its articles,
  and only `Recap` and `Story` are used; injury-wire churn, previews, video and
  anything matching `NEWS_REJECT` (fantasy, odds, "where to watch"…) is dropped.
* **The feature** – one human-interest story a slide, with byline and room to
  read it.
* **CFP Rankings / AP Top 25** – full top 25 with weekly movement.
* **Standings** – NFL by division, NBA and NHL by conference. Leagues out of
  season are skipped automatically.
* **Last night** – the previous day's finals.

At noon it returns to the normal rotation on its own.

## How often each screen comes up

Slides are weighted rather than shown in a fixed order, so a league with a live
game comes up far more than one that finished hours ago, and the mix shifts
through the day (drinks in the evening, the paper in the morning). The weights
are in `weightFor()` near the top of the `<script>` in `index.html`.

## Favourite teams

College scoreboards normally only show ranked teams. `FAVORITE_TEAMS` in
`scripts/update_data.py` lists teams that always get through anyway and are
marked with a star. UC Irvine men's basketball (ESPN team id `300`) is in there;
add ids to that list for any others.

## Changing things

* **Drinks** – edit the sheet from your phone. The board picks it up within a
  few minutes (the update loop, plus the page's own 90-second refresh).
* **Bar name, seconds per screen, rows per slide, morning hours** – the settings
  block at the top of the `<script>` in `index.html`.
* **Leagues** – the `LEAGUES` list in `scripts/update_data.py`. Delete a line to
  drop a league.

## If scores stop updating

* Actions tab → the **Update board data** run should be green and *in progress*.
  It is meant to stay running for hours: each run refreshes every two minutes
  and the hourly schedule only restarts it.
* GitHub pauses scheduled jobs on repos with no human activity for 60 days. If
  it stops, go to Actions and press **Enable** / **Run workflow** once.
* The "Scores as of" time only moves when something actually changed, so a
  static time on a quiet night is normal.
