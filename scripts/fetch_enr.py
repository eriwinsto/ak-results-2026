"""Check the Division of Elections for new results and rebuild site/data/results.json.

Run by .github/workflows/update-results.yml every 10 minutes; also works by hand:

  python3 scripts/fetch_enr.py            # rebuild only if the Division's timestamp changed
  python3 scripts/fetch_enr.py --force    # rebuild regardless

How it works:
  1. Reads the Division's results/statewide.js (the JSON its results page loads) for the
     "Results last updated at" time, e.g. "11/10/2026 7:13 PM".
  2. If that matches sourceUpdated in the current results.json, stops: nothing new.
  3. Otherwise downloads the precinct CSV, checks it was written in the same update, runs
     build_data.py with that time (in AP style) and config/cvr_counts.json, and sanity-checks
     the output before replacing results.json.

Exit codes: 0 updated or nothing new, 3 Division mid-update (try next run), 1 problem
(the job fails, and GitHub emails the repo owner).

The Division's server sends the wrong intermediate certificate. Browsers repair that on
their own; scripts don't. The workflow fetches the right one from the address in the
server's certificate and points SSL_CERT_FILE at the completed bundle. Verification stays on.
"""
import argparse, email.utils, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'https://www.elections.alaska.gov/enr/26GENR/'
STATEWIDE = BASE + 'results/statewide.js'
CSV = BASE + 'results/GA_ENR_Precinct_State_of_Alaska.csv'
OUT = os.path.join(ROOT, 'site', 'data', 'results.json')
COUNTS = os.path.join(ROOT, 'config', 'cvr_counts.json')
UA = 'AlaskaPublicMedia-results-map/1.0 (newsroom results graphic; checks every 10 minutes)'

AP_MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']

def ap_time(stamp):
    """'11/10/2026 7:13 PM' -> '7:13 p.m. Nov. 10' (AP style; noon and midnight spelled out)."""
    t = datetime.strptime(stamp.strip(), '%m/%d/%Y %I:%M %p')
    if t.hour == 12 and t.minute == 0:
        clock = 'noon'
    elif t.hour == 0 and t.minute == 0:
        clock = 'midnight'
    else:
        h = t.hour % 12 or 12
        clock = (f'{h}' if t.minute == 0 else f'{h}:{t.minute:02d}') + (' a.m.' if t.hour < 12 else ' p.m.')
    return f'{clock} {AP_MONTHS[t.month - 1]} {t.day}'

def get(url):
    req = urllib.request.Request(f'{url}?t={int(time.time())}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers

def modified(headers):
    v = headers.get('Last-Modified')
    return email.utils.parsedate_to_datetime(v).timestamp() if v else None

def summary(d):
    c = {x['id']: x for x in d['contests']}
    return {k: c[k]['ballots'] for k in ('gov', 'ussen', 'ushouse') if k in c}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()

    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    body, sw_h = get(STATEWIDE)
    sw = json.loads(body)
    stamp = sw.get('updated', '').strip()
    if not stamp:
        sys.exit('statewide.js has no "updated" time; the Division may have changed its format')
    print(f'Division: "Results last updated at {stamp}" (certified: {sw.get("certified")})')
    if stamp == old.get('sourceUpdated') and not a.force:
        print('No new results.')
        return

    csv_body, csv_h = get(CSV)
    # the CSV and statewide.js are written together; if the CSV is older, the Division is mid-update
    sw_t, csv_t = modified(sw_h), modified(csv_h)
    if sw_t and csv_t and csv_t < sw_t - 120:
        print(f'CSV ({csv_h.get("Last-Modified")}) is older than statewide.js ({sw_h.get("Last-Modified")}); '
              'waiting for the next run.')
        sys.exit(3)

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'GA_ENR_Precinct_State_of_Alaska.csv')
        open(src, 'wb').write(csv_body)
        new_path = os.path.join(tmp, 'results.json')
        cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'build_data.py'), src,
               '--as-of', ap_time(stamp), '--source-updated', stamp, '--out', new_path]
        if os.path.exists(COUNTS):
            cmd += ['--cvr', COUNTS]
        subprocess.run(cmd, check=True)
        new = json.load(open(new_path))

        # sanity checks before publishing
        problems = []
        if old.get('contests') and len(new['contests']) != len(old['contests']):
            problems.append(f"contest count changed: {len(old['contests'])} -> {len(new['contests'])}")
        if len(new['precincts']) != 402:
            problems.append(f"{len(new['precincts'])} precincts (expected 402)")
        before, after = summary(old) if old.get('contests') else {}, summary(new)
        for k, n in after.items():
            if k in before and n < before[k] * 0.99:
                problems.append(f'{k} ballots fell from {before[k]:,} to {n:,}')
        if problems:
            sys.exit('Not publishing: ' + '; '.join(problems))

        shutil.move(new_path, OUT)
    print('Updated:', ap_time(stamp), {k: f'{before.get(k, 0):,} -> {n:,}' for k, n in after.items()})

if __name__ == '__main__':
    main()
