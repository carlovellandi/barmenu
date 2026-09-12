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

## Changing things

* **Drinks** – edit the sheet from your phone. The board picks it up within
  ~10 minutes (GitHub job + the page's own 3-minute refresh).
* **Room name, seconds per screen, how often drinks show** – top of the
  `<script>` in `index.html` (the `settings` block). Edit on github.com and
  commit; the TV reloads the page nightly at 4 AM, or turn it off and on.
* **Leagues** – the `LEAGUES` list in `scripts/update_data.py`. Delete a line
  to drop a league; order there is the rotation order.

## If scores stop updating

* Actions tab → look at the latest run. Red = open it and read the error.
* GitHub pauses scheduled jobs on repos with no human activity for 60 days.
  If it stops, go to Actions and press **Enable** / **Run workflow** once.
* GitHub's scheduler can lag 5–15 minutes when it's busy; that's normal.
