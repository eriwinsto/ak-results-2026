"""Build the site's ranked choice files from the Division of Elections' RCV Detailed Report PDFs.

  python3 scripts/division_rcv.py "RCV Detail reports" --label "As tabulated by ..."

Reads every RCV-*.pdf (HD23, SenM, USRep ...), turns each into the same structure build_rcv.py
writes, and writes site/data/rcv/ushouse.json (and gov / ussen if present) plus
site/data/rcv/legislature.json holding only the Division's legislative races.
Inactive ballots = the report's Exhausted + Overvotes (Blanks are ballots with no rankings, like
RCTab's undervotes). The dashed majority line is half the continuing ballots plus one, as before.
"""
import argparse, glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import build_rcv
from division_rcv_parse import parse

def site_id(key):
    if key == 'USRep': return 'ushouse'
    if key == 'USSen': return 'ussen'
    if key in ('Gov', 'Governor'): return 'gov'
    if key.startswith('HD'): return 'hd' + key[2:]
    if key.startswith('Sen'): return 'sd' + key[3:]
    raise ValueError(key)

def to_rep(d):
    results, gone = [], set()
    n = len(d['rounds'])
    for i, r in enumerate(d['rounds']):
        tally = {k: str(v) for k, v in r['tally'].items() if k not in gone}
        cont = r['Continuing Ballots Total']
        tr = []
        for name in r['elected']:
            tr.append({'elected': name, 'transfers': {}})
        last = i == n - 1
        for name in r['eliminated']:
            if last:
                continue  # "eliminated because the candidate was not elected in the last round": not an elimination
            t = {}
            for dest, v in r['transfers'].get(name, {}).items():
                k = 'exhausted' if dest in ('Exhausted', 'Overvotes') else dest
                t[k] = str(int(t.get(k, 0)) + v)
            tr.append({'eliminated': name, 'transfers': t})
            gone.add(name)
        results.append({'round': r['round'], 'tally': tally, 'tallyResults': tr, 'threshold': str(cont // 2 + 1),
                        'inactiveBallots': {'exhausted': str(r['Exhausted']), 'overvotes': str(r['Overvotes'])}})
    r1 = d['rounds'][0]
    return {'config': {'contest': d['title'], 'generatedBy': f"Division of Elections RCV Detailed Report, tabulated {d.get('tabulationTime', '')}"},
            'results': results,
            'summary': {'totalNumBallots': str(r1['Continuing Ballots Total'] + r1['Non Transferable Total']), 'undervotes': str(r1['Blanks'])}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder'); ap.add_argument('--label', required=True)
    a = ap.parse_args()
    leg = {}
    for pdf in sorted(glob.glob(os.path.join(a.folder, 'RCV-*.pdf'))):
        key = os.path.basename(pdf)[4:-4]; sid = site_id(key)
        d = parse(pdf)
        out, unmatched = build_rcv.convert(to_rep(d), sid, a.label)
        out['source'] = 'division'
        if unmatched:
            sys.exit(f'{key}: names not matched to results.json: {sorted(unmatched)}')
        # sanity: every round's tally adds up to the report's continuing total
        for r, src in zip(out['rounds'], d['rounds']):
            assert round(sum(r['tally'].values())) == src['Continuing Ballots Total'], (key, r['round'])
        if sid.startswith(('hd', 'sd')):
            leg[sid] = out
        else:
            json.dump(out, open(os.path.join(ROOT, 'site', 'data', 'rcv', f'{sid}.json'), 'w'), indent=1, ensure_ascii=False)
        print(f'{key:6} -> {sid:8} {build_rcv.describe(out)}')
    json.dump(leg, open(os.path.join(ROOT, 'site', 'data', 'rcv', 'legislature.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    print(f'legislature.json: {len(leg)} races')

if __name__ == '__main__':
    main()
