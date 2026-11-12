"""Turn the Division of Elections precinct results CSV into site/data/results.json.

Usage:
  python3 scripts/build_data.py GA_ENR_Precinct_State_of_Alaska.csv --as-of "Nov. 4, 2026, 2:30 a.m."

--as-of is the Division's "last updated" time, shown to readers as "Updated ...".
Leave it off and no time is shown.

Editable inputs in config/:
  names.json   display-name overrides, keyed by the Division's candidate_name
  calls.json   AP race calls, keyed by contest id (see README)
  colors.json  optional per-candidate color overrides
"""
import argparse, csv, json, os, re, sys
from collections import defaultdict, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, 'config')

# Contests included, in picker order. Keys are the Division's Contest_title.
FIXED = OrderedDict([
    ('Governor / Lieutenant Governor', ('gov', 'statewide')),
    ('U.S. Senator', ('ussen', 'statewide')),
    ('U.S. Representative', ('ushouse', 'statewide')),
    ('BM#2 24ESEG', ('bm2', 'measure')),
    ('BM#3 25USCV', ('bm3', 'measure')),
])

PARTY = {'REP': 'R', 'DEM': 'D', 'NON': 'N', 'UND': 'U', 'LIB': 'L', 'DEM/NON': 'D',
         'AIP': 'A', 'GRE': 'G', '': ''}

def load(name, default):
    p = os.path.join(CFG, name)
    return json.load(open(p)) if os.path.exists(p) else default

def display_name(raw, overrides):
    if raw in overrides:
        return overrides[raw]
    if raw in ('YES', 'NO'):
        return raw.capitalize()
    if '/' in raw and ',' not in raw:          # governor tickets: "Last/Last"
        return raw.replace('/', ' / ')
    if ',' not in raw:
        return raw
    last, rest = [s.strip() for s in raw.split(',', 1)]
    suffix = ''
    m = re.search(r'\s+(Jr\.?|Sr\.?|II|III|IV)$', rest)
    if m:
        suffix, rest = ' ' + m.group(1), rest[:m.start()]
    nick = re.search(r'"([^"]+)"', rest)
    if nick:
        first = nick.group(1)
    else:
        parts = [p for p in rest.split() if not re.fullmatch(r'[A-Z]\.', p)]
        first = ' '.join(parts)
    return f'{first} {last}{suffix}'.strip()

def area_of(name, pct):
    """Return ('p', precinct_id, hd) for a precinct row, ('d', None, hd) for a
    district-level absentee/early/question row, ('x', None, None) otherwise."""
    if re.fullmatch(r'\d\d-\d\d\d', pct or '') and pct != '99-999':
        return 'p', pct, int(pct[:2])
    m = re.match(r'District (\d+)\s+-\s+(Absentee|Early Voting|Question|Remote)', name)
    if m:
        return 'd', m.group(2), int(m.group(1))
    return 'x', None, None

RCV_DIR = os.path.join(ROOT, 'site', 'data', 'rcv')

def cvr_gap(cvr_path, enr_path):
    """Compare RCTab's normalized CVR with the results CSV for the same contest.

    Returns precincts that have Election Day ballots in the results but no ballots in
    the CVR. In House districts split across judicial districts, the CVR labels early
    votes "House District N - Judicial District J" instead of "District N - Early Voting";
    those are counted back to their district before comparing.
    """
    portions = defaultdict(int)
    contest = None
    if cvr_path.lower().endswith('.json'):
        # ballot counts by precinct portion, made from the RCTab CVR by scripts/cvr_counts.py
        c = json.load(open(cvr_path))
        contest = str(c['contest'])
        portions.update(c['portions'])
    else:
        with open(cvr_path, newline='', encoding='utf-8-sig') as f:
            rd = csv.DictReader(f)
            for r in rd:
                contest = contest or r.get('Contest Id')
                portions[re.sub(r'\s+', ' ', r['Precinct Portion'].strip())] += 1
    cvr_total = sum(portions.values())
    cvr_p = defaultdict(int); cvr_d = defaultdict(int); unplaced = 0
    for k, n in portions.items():
        m = re.match(r'(\d\d-\d\d\d)\b', k)
        if m:
            cvr_p[m.group(1)] += n; continue
        m = re.match(r'District (\d+) - (.+)$', k)
        if m:
            cvr_d[(int(m.group(1)), m.group(2))] += n; continue
        m = re.match(r'House District (\d+) - Judicial District \d+$', k)
        if m:
            cvr_d[(int(m.group(1)), 'Early Voting')] += n; continue
        if k.startswith('HD99'):
            cvr_d[(99, 'Overseas')] += n; continue
        unplaced += n
    # results ballots for the same contest (CVR contest 7 = U.S. Representative)
    title = {'7': 'U.S. Representative', '6': 'U.S. Senator', '5': 'Governor / Lieutenant Governor'}.get(contest, 'U.S. Representative')
    enr_p, enr_d, enr_total = {}, defaultdict(int), 0
    with open(enr_path, newline='', encoding='utf-8-sig') as f:
        seen = set()
        for r in csv.DictReader(f):
            if r['Contest_title'] != title:
                continue
            name = r['Precinct_name'].strip()
            if name in seen:
                continue
            seen.add(name)
            b = int(r['total_ballots'] or 0); enr_total += b
            kind, x, hd = area_of(name, r['Pct_Id'].strip())
            if kind == 'p':
                enr_p[x] = (name[7:].strip(), hd, b)
            elif kind == 'd':
                enr_d[(hd, x)] += b
            elif name.startswith('HD99'):
                enr_d[(99, 'Overseas')] += b
    missing = [[pid, nm, hd, b] for pid, (nm, hd, b) in sorted(enr_p.items()) if b > 0 and cvr_p.get(pid, 0) == 0]
    miss_total = sum(m[3] for m in missing)
    other = (enr_total - cvr_total) - miss_total
    if other:
        print(f'WARNING: {other:+,} ballots of the CVR gap are not explained by missing precincts', file=sys.stderr)
    if unplaced:
        print(f'WARNING: {unplaced:,} CVR ballots have a precinct portion this script does not recognize', file=sys.stderr)
    print(f'CVR gap ({title}): results {enr_total:,}, CVR {cvr_total:,}; '
          f'{len(missing)} precincts with {miss_total:,} Election Day ballots have no CVR ballots')
    return {'contest': title, 'enr': enr_total, 'cvr': cvr_total, 'missingBallots': miss_total,
            'unexplained': other, 'missing': missing}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--as-of', default='')
    ap.add_argument('--cvr', default='', help="RCTab's normalized CVR (..._rctab_cvr.csv) or config/cvr_counts.json; lists precincts it is missing")
    ap.add_argument('--source-updated', default='', help="the Division's own timestamp, e.g. '11/10/2026 7:13 PM'")
    ap.add_argument('--summary', default='', help="the Division's Election Summary Report PDF; adds each race's write-in votes")
    ap.add_argument('--out', default=os.path.join(ROOT, 'site', 'data', 'results.json'))
    a = ap.parse_args()

    names = load('names.json', {})
    calls = load('calls.json', {})
    colors = load('colors.json', {})
    holdovers = load('senate_holdovers.json', {})

    contests = OrderedDict()
    for t, (cid, kind) in FIXED.items():
        contests[t] = {'id': cid, 'kind': kind}
    for i in range(1, 41):
        contests[f'House District {i}'] = {'id': f'hd{i}', 'kind': 'house', 'district': i}
    for L in 'ABCDEFGHIJKLMNOPQRST':
        contests[f'Senate District {L}'] = {'id': f'sd{L}', 'kind': 'senate', 'district': L}

    cand = defaultdict(OrderedDict)                       # title -> raw name -> info
    votes = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # title -> area -> raw -> votes
    ballots = defaultdict(lambda: defaultdict(int))       # title -> area -> ballots
    seen_ballots = set()
    precincts = {}
    unknown_rows = set()

    with open(a.csv, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            t = r['Contest_title']
            name, pct = r['Precinct_name'].strip(), r['Pct_Id'].strip()
            kind, pid, hd = area_of(name, pct)
            if kind == 'p':
                tb = int(r['total_ballots'] or 0) if t == 'Governor / Lieutenant Governor' else None
                p = precincts.setdefault(pid, {'name': name[7:].strip(), 'hd': hd,
                                               'reg': int(r['Reg_voters'] or 0), 'ballots': 0})
                if tb is not None:
                    p['ballots'] = tb
            elif kind == 'x' and not name.startswith('HD99'):
                unknown_rows.add(name)
            if t not in contests:
                continue
            raw = r['candidate_name'].strip()
            if raw not in cand[t]:
                cand[t][raw] = {'party': PARTY.get(r['Party_Code'].strip(), r['Party_Code'].strip()),
                                'code': r['Party_Code'].strip(), 'seq': int(r['cand_seq_nbr'] or 0)}
            v = int(r['total_votes'] or 0)
            areas = ['all']
            if hd:
                areas.append(f'h{hd}')
            if kind == 'p':
                areas.append(pid)
            for ar in areas:
                votes[t][ar][raw] += v
            key = (t, name)
            if key not in seen_ballots:
                seen_ballots.add(key)
                b = int(r['total_ballots'] or 0)
                for ar in areas:
                    ballots[t][ar] += b

    if unknown_rows:
        print('WARNING: rows not assigned to a district:', sorted(unknown_rows), file=sys.stderr)

    out_contests = []
    for t, c in contests.items():
        if t not in cand:
            continue                              # not on the ballot this year
        raws = list(cand[t].keys())
        tot = votes[t]['all']
        order = sorted(raws, key=lambda x: (-tot[x], cand[t][x]['seq']))
        cands = []
        for raw in order:
            cands.append({'name': display_name(raw, names), 'raw': raw,
                          'party': cand[t][raw]['party'], 'code': cand[t][raw]['code'],
                          'votes': tot[raw]})
        if c['kind'] == 'measure':
            cands.sort(key=lambda x: 0 if x['raw'] == 'YES' else 1)
        idx = {x['raw']: i for i, x in enumerate(cands)}
        areas = {}
        for ar, vv in votes[t].items():
            if ar == 'all':
                continue
            row = [0] * len(cands)
            for raw, n in vv.items():
                row[idx[raw]] = n
            areas[ar] = [ballots[t][ar]] + row
        call = calls.get(c['id'])
        if call and call.get('winner') and call['winner'] not in (x['name'] for x in cands) \
                and call['winner'] not in idx:
            print(f"WARNING: calls.json winner {call['winner']!r} not a candidate in {c['id']}", file=sys.stderr)
        oc = dict(c, title=t, ballots=ballots[t]['all'], candidates=cands, areas=areas)
        if call and call.get('winner'):
            w = call['winner']
            oc['call'] = {'winner': next((x['name'] for x in cands if w in (x['name'], x['raw'])), w),
                          'by': call.get('by', 'AP'), 'time': call.get('time', '')}
        for x in cands:
            if x['raw'] in colors:
                x['color'] = colors[x['raw']]
        out_contests.append(oc)

    # Senate seats not on the ballot this year
    on_ballot = {c['district'] for c in out_contests if c['kind'] == 'senate'}
    hold = {k: v for k, v in holdovers.items() if not k.startswith('_') and k not in on_ballot}

    hds = defaultdict(lambda: {'reg': 0})
    for p in precincts.values():
        hds[p['hd']]['reg'] += p['reg']

    if a.summary:
        # write-ins are only in the summary PDF; it must agree with this CSV race by race
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import summary_writeins
        expected = {c['title']: [x['votes'] for x in c['candidates']] for c in out_contests if c['kind'] != 'measure'}
        try:
            wi = summary_writeins.writeins(a.summary, expected)
        except summary_writeins.Mismatch as e:
            print(f'SUMMARY MISMATCH: {e}', file=sys.stderr)
            sys.exit(4)
        for c in out_contests:
            if c['title'] in wi:
                c['writeIn'] = wi[c['title']]
        print(f'write-ins from the summary report: {len(wi)} races, governor {wi.get("Governor / Lieutenant Governor", 0):,}')

    data = {
        'asOf': a.as_of,
        'sourceUpdated': a.source_updated,
        'source': os.path.basename(a.csv),
        'precincts': {k: [v['name'], v['hd'], v['reg'], v['ballots']] for k, v in sorted(precincts.items())},
        'contests': out_contests,
        'senateHoldovers': hold,
        'caucus': load('caucus.json', {}),
        # always list the site's published RCV files, even when --out writes somewhere else
        'rcv': sorted(f[:-5] for f in os.listdir(RCV_DIR) if f.endswith('.json')) if os.path.isdir(RCV_DIR) else [],
    }
    if a.cvr:
        data['cvrGap'] = cvr_gap(a.cvr, a.csv)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as f:
        json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
    gov = next(c for c in out_contests if c['id'] == 'gov')
    print(f"wrote {a.out} ({os.path.getsize(a.out):,} bytes): {len(out_contests)} contests, "
          f"{len(precincts)} precincts, {sum(1 for p in precincts.values() if p['ballots'])} with ballots; "
          f"governor ballots {gov['ballots']:,}")

if __name__ == '__main__':
    main()
