# Alaska election results 2026

An embeddable results page for Grove: race tabs, a district/precinct map, a ranked choice
round viewer and a balance-of-power chart. Static files only; host `site/` on GitHub Pages.

Published with GitHub Pages from the `main` branch (repo root), so the page is at
https://eriwinsto.github.io/ak-results-2026/site/ and redeploys on every push.

## Folder

```
site/                 everything that gets published
  index.html          the page (all reader-facing text is in the COPY block near the top of the script)
  data/results.json   built from the Division CSV       (scripts/build_data.py)
  data/geo.json       precinct + district shapes        (scripts/build_geo.py)
  data/base.json      basemap: places, roads, water     (scripts/build_base.py)
  data/rcv/gov.json   ranked choice rounds, once posted (scripts/build_rcv.py)
  data/test/          RCTab's own test fixture, used only with ?demo=1
  vendor/             d3 7.9.0, topojson-client 3.1.0, pym 1.3.2
  embed-test.html     a fake story page for testing the embed and full screen locally
config/               files you edit by hand; rerun build_data.py after changing them
  calls.json          AP race calls
  caucus.json         organizing caucuses, once they form
  names.json          display-name fixes
  senate_holdovers.json  senators not on the 2026 ballot (pulled from akleg.gov Nov. 4)
scripts/
grove-embed.html      the snippet to paste into Grove
```

## Automatic updates

`.github/workflows/update-results.yml` runs `scripts/fetch_enr.py` on GitHub's servers every 10 minutes.
It reads the Division's `results/statewide.js` (the data behind "Results last updated at ..." on the
results page). When that time changes, it downloads the precinct CSV, rebuilds `results.json` with the
time in AP style, checks the output (same contests, 402 precincts, no race losing more than 1% of its
ballots) and pushes it. A failed check stops the update and GitHub emails you; the site keeps the
previous results.

- Write-ins: the precinct CSV has none. The updater also downloads the Division's Election Summary
  Report PDF (`results/ElectionSummaryReportRPT.pdf`) and reads each race's write-in line
  (`scripts/summary_writeins.py`, needs pdftotext from poppler-utils). Percentages then use named
  candidates plus write-ins, as the PDF does. Every race in the PDF must add up to its Total Votes and
  match the CSV's candidate totals exactly; if not, the updater waits for the next run, and fails (with
  an email) if they still disagree 30 minutes after the update. By hand: `build_data.py ... --summary
  path/to/ElectionSummaryReportRPT.pdf`.
- Run it now, or force a rebuild: Actions tab > "Update results from the Division" > Run workflow.
- Pause it: Actions tab > that workflow > "..." > Disable workflow.
- Ranked choice stays manual. After each RCTab run on the U.S. House contest, also run
  `python3 scripts/cvr_counts.py path/to/..._rctab_cvr.csv --as-of "..."` and commit
  `config/cvr_counts.json`, so the CVR gap note is computed against the new CVR.
- The Division's server sends the wrong intermediate certificate. Browsers fix that themselves; the
  workflow fetches the right one from the address in the server's own certificate. Verification stays on.

## Election night loop (by hand)


1. Download the Division's precinct CSV (`GA_ENR_Precinct_State_of_Alaska.csv`).
2. `python3 scripts/build_data.py path/to/GA_ENR_Precinct_State_of_Alaska.csv --as-of "2:30 a.m. Nov. 4" --source-updated "11/04/2026 2:30 AM" --cvr config/cvr_counts.json`
   - `--as-of` is the Division's update time. It appears as "Updated ..." in the header. Leave it off and no time shows.
   - The script prints totals and warns about anything it can't place in a district.
3. Commit and push `site/data/results.json`. Open pages refresh every two minutes. GitHub Pages caches files for up to 10 minutes.

## Race calls

Edit `config/calls.json` and push; the push starts a rebuild with the call (or rerun step 2 by hand). Keys are contest ids: `gov`, `ussen`, `ushouse`, `bm2`, `bm3`,
`hd1`–`hd40`, `sdA`–`sdT`.

```json
{ "hd1": { "winner": "Jeremy Bynum", "by": "AP" },
  "gov": { "winner": "Kreiss-Tomkins / Johnson", "by": "AP" } }
```

`winner` can be the display name or the Division's spelling. Called seats fill the balance-of-power bars.
Uncalled seats stay gray no matter who leads.

## Ranked choice rounds

After you tabulate the CVR in RCTab, point the script at either report it writes in the config's
`outputDirectory`: the `..._detailed_report.json` or the `..._detailed_report.csv`.

```
python3 scripts/build_rcv.py "path/to/2026-11-04_03-18_detailed_report.csv" gov
python3 scripts/build_rcv.py "path/to/2026-11-04_03-26_detailed_report.csv" ussen
python3 scripts/build_rcv.py "path/to/2026-11-04_03-37_detailed_report.json" ushouse
python3 scripts/build_data.py path/to/latest.csv --as-of "..." --cvr "path/to/..._rctab_cvr.csv"
```

`--cvr` takes the normalized CVR that RCTab writes (`..._rctab_cvr.csv`) and lists the precincts that
have Election Day ballots in the results but none in the CVR. That list goes under each ranked choice
chart. The script warns if missing precincts don't account for the whole gap. In House districts 30, 36,
37 and 39, the CVR labels early votes by judicial district ("House District 36 - Judicial District 4").
The script counts those back to the district's early vote.

With `continueUntilTwoCandidatesRemain` on, RCTab spends one round declaring a winner and then repeats
the same tallies before the next elimination. The script merges that repeated round.

`build_rcv.py` drops RCTab's "Undeclared Write-ins" round so round numbers match the Division's reports.
It also counts transfers to "exhausted" as inactive ballots and maps RCTab names to the Division's names.
The page labels the section with `--label` or, by default, COPY.rcvLabelDefault, which says it is an
Alaska Public Media tabulation and not official.
Add other contests to `RCV_CONTESTS` in index.html (e.g. `'ushouse'`).

## Embedding in Grove

Paste `grove-embed.html` into a Responsive Embed and set the URL. Optional URL parameters:

| Parameter | Effect |
|---|---|
| `?race=gov` / `ussen` / `ushouse` / `bm2` / `bm3` / `house` / `senate` | which tab opens first |
| `?view=map` | map only, no table or other sections |
| `?view=rcv` | ranked choice section only |
| `?view=bop` | balance of power only |
| `?view=results` | race results and map; leaves out the ranked choice and balance of power sections (and the RCV note in the footer) |
| `?demo=1` | **test mode**: fake race calls plus RCTab's synthetic fixture, with a yellow TEST banner. Never embed this. |

The "Full screen" button tells the Grove page to pin the iframe over the whole viewport. This works on
iPhone, where browsers can't make an iframe go full screen on their own. Opened directly (not through
Pym), the page fills the window itself.

Map gestures: inline in a story, one finger scrolls the story and two fingers pinch or pan the map. The
+/− buttons, region buttons, tapping a district and search all work too. In full screen, one finger pans.
On desktop, ctrl/⌘ + scroll or a trackpad pinch zooms, so scrolling the story doesn't get trapped by the map.

## Boundaries

`build_geo.py` reads the Division's `AK_Election_Precincts_2023Final/Precincts.shp`. All 402 precincts
match the results CSV by ID. Eight polygons in that file have reversed ring winding (Glacier Valley Area,
Moose Creek, Tyonek, JBER No. 1 and No. 2, Snowshoe, Fairview No. 1, St. Michael), and the script fixes
them. House and Senate districts are dissolved from the precincts, so the layers always agree. The precinct
shapes extend across open water, so the script clips them to the shoreline using the Census Bureau's
cartographic boundary file for Alaska (`cb_2024_us_state_500k`, public domain). That lets the coast, inlets
and the Inside Passage show through. Clipping changes only what's drawn; results are keyed by precinct ID.

## Basemap

`site/data/base.json` holds the reference layers: Canada and Russia, lakes and rivers (Natural Earth),
primary and secondary roads (Census TIGER/Line 2024), and place labels. The labels are every Alaska city
and census-designated place in TIGER, ranked by 2020 census population, with regional hubs placed first.
Labels keep the same size at every zoom, and smaller places appear as you zoom in. Anchorage neighborhood
labels (Downtown, Midtown, Eagle River, ...) sit on the Division precincts that carry those names. All
sources are public domain. To rebuild:

```
python3 scripts/build_base.py     # downloads sources into build/base/ the first time
```

Readers can turn places and roads off with the switch in the map legend.

## Testing locally

```
cd site && python3 -m http.server 8000
open http://localhost:8000/embed-test.html
```
