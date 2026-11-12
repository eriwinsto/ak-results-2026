"""Count ballots by precinct portion in RCTab's normalized CVR, for the CVR gap note.

The full CVR is too big to keep in the repo; the automatic results update only needs these
counts. Run this after each new RCTab run on the U.S. House contest:

  python3 scripts/cvr_counts.py path/to/..._rctab_cvr.csv --as-of "7:16 p.m. Nov. 10"

writes config/cvr_counts.json, which scripts/fetch_enr.py passes to build_data.py --cvr.
"""
import argparse, csv, json, os, re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rctab_cvr')
    ap.add_argument('--as-of', default='', help='when the Division released this CVR (for your reference)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'config', 'cvr_counts.json'))
    a = ap.parse_args()
    portions, contest = Counter(), None
    with open(a.rctab_cvr, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            contest = contest or r.get('Contest Id')
            portions[re.sub(r'\s+', ' ', r['Precinct Portion'].strip())] += 1
    out = {'contest': contest, 'cvrAsOf': a.as_of, 'source': os.path.basename(a.rctab_cvr),
           'ballots': sum(portions.values()), 'portions': dict(sorted(portions.items()))}
    json.dump(out, open(a.out, 'w'), indent=0, ensure_ascii=False)
    print(f"wrote {a.out}: contest {contest}, {out['ballots']:,} ballots in {len(portions)} precinct portions")

if __name__ == '__main__':
    main()
