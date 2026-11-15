"""Tabulate Alaska ranked choice contests from scripts/cvr_extract.py output, following RCTab 2.1.0
with the settings in the Alaska Division of Elections' RCTab guide for Liberty CVRs.

  python3 scripts/tabulate_rcv.py cvr_patterns.json                     # every ranked contest, summary
  python3 scripts/tabulate_rcv.py cvr_patterns.json --contests gov ussen ushouse --site
                                                       # also write site/data/rcv/<id>.json
  python3 scripts/tabulate_rcv.py cvr_patterns.json --report-dir DIR    # RCTab-style report per contest

Rules (the guide's settings plus RCTab's defaults, as recorded in the audit logs of RCTab runs):
  * write-in candidates are excluded (treated as eliminated before round 1)
  * single winner, majority: the threshold is floor(active ballots / 2) + 1, recomputed each round
    until a winner is elected and held from then on
  * keep eliminating, one candidate per round, until two candidates remain
  * tie for last place: stop and report (RCTab "stop counting and ask")
  * overvote (two or more candidates marked at one rank): ballot inactive when it reaches that rank
  * more than one consecutive skipped rank (maxSkippedRanksAllowed 1): ballot inactive at that point
  * a candidate ranked more than once: later rankings of them are simply passed over
    (exhaustOnDuplicateCandidate false), so "repeated rankings" stays 0
  * ambiguous marks (IsAmbiguous) are ignored, as RCTab's Dominion reader does
  * a ballot with no rankings in the contest is an undervote and is not in any round
"""
import argparse, json, os, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import build_rcv  # noqa: E402

STATEWIDE = {'Governor / Lieutenant Governor': 'gov', 'U.S. Senator': 'ussen', 'U.S. Representative': 'ushouse'}
MAX_SKIPPED = 1
CATS = ['overvotes', 'skippedRankings', 'exhaustedChoices', 'repeatedRankings']

def site_id(name):
    if name in STATEWIDE:
        return STATEWIDE[name]
    if name.startswith('House District '):
        return 'hd' + name.split()[-1]
    if name.startswith('Senate District '):
        return 'sd' + name.split()[-1]
    return None

def rankings(marks, use_isvote=False):
    """marks [[rank, cand, ambiguous, isVote], ...] -> [(rank, frozenset(cands))] in rank order."""
    by = defaultdict(set)
    for rank, cand, amb, isvote in marks:
        if amb or (use_isvote and not isvote):
            continue
        by[rank].add(str(cand))
    return [(r, frozenset(by[r])) for r in sorted(by)]

def choose(ranks, continuing):
    """RCTab's per-ballot walk. Returns (candidate, None) or (None, inactive category)."""
    last = 0
    for rank, cands in ranks:
        if rank - last > MAX_SKIPPED + 1:
            return None, 'skippedRankings'
        last = rank
        if len(cands) > 1:
            return None, 'overvotes'
        (c,) = cands
        if c in continuing:
            return c, None
    return None, 'exhaustedChoices'

def tabulate(contest, use_isvote=False):
    cands = contest['candidates']
    names = {k: v['name'] for k, v in cands.items()}
    excluded = {k for k, v in cands.items() if v['type'] == 'WriteIn'}
    groups, undervotes, total = [], 0, 0
    for n, marks in contest['patterns']:
        total += n
        r = rankings(marks, use_isvote)
        if not r:
            undervotes += n
            continue
        groups.append([n, r])
    continuing = [k for k in cands if k not in excluded]
    rounds, winner, problems, prev_assign = [], None, [], None
    inactive_cum = Counter()
    while True:
        tally = Counter({c: 0 for c in continuing})
        assign = []
        inactive_cum = Counter()
        cont = set(continuing)
        for n, r in groups:
            c, why = choose(r, cont)
            if c:
                tally[c] += n
            else:
                inactive_cum[why] += n
            assign.append(c or why)
        active = sum(tally.values())
        # RCTab stops updating the threshold once a winner is elected
        threshold = active // 2 + 1 if winner is None else threshold
        rnd = {'round': len(rounds) + 1, 'tally': {names[c]: str(tally[c]) for c in continuing},
               'threshold': str(threshold), 'tallyResults': [],
               'inactiveBallots': {k: str(inactive_cum.get(k, 0)) for k in CATS}}
        # transfers into this round are recorded on the previous round's elimination
        if prev_assign is not None and rounds and rounds[-1]['tallyResults']:
            moved = Counter()
            gone = rounds[-1]['_elim']
            for (n, _), a, b in zip(groups, prev_assign, assign):
                if a in gone and a != b:
                    moved['exhausted' if b in CATS else names[b]] += n
            rounds[-1]['tallyResults'][0]['transfers'] = {k: str(v) for k, v in moved.items()}
        top = max(continuing, key=lambda c: tally[c])
        if winner is None and tally[top] >= threshold:
            winner = top
            rnd['tallyResults'].append({'elected': names[top], 'transfers': {}})
            rnd['_elim'] = set()
            rounds.append(rnd)
            prev_assign = assign
            if len(continuing) <= 2:
                break
            continue  # RCTab declares the winner in its own round, then keeps eliminating
        if len(continuing) <= 2:
            rnd['_elim'] = set()
            rounds.append(rnd)
            if winner is None:
                problems.append('two candidates left and nobody reached the threshold')
            break
        low = min(tally[c] for c in continuing if c != winner)
        lows = [c for c in continuing if tally[c] == low and c != winner]
        if len(lows) > 1:
            if low == 0:
                problems.append('several zero-vote candidates eliminated together: ' + ', '.join(names[c] for c in lows))
            else:
                problems.append(f'tie for last at {low:,}: ' + ', '.join(names[c] for c in lows) + ' (RCTab would stop and ask)')
                rnd['_elim'] = set()
                rounds.append(rnd)
                break
        rnd['tallyResults'] = [{'eliminated': names[c], 'transfers': {}} for c in lows]
        rnd['_elim'] = set(lows)
        rounds.append(rnd)
        prev_assign = assign
        continuing = [c for c in continuing if c not in lows]
    for r in rounds:
        r.pop('_elim', None)
    # whom the winner's final-round ballots ranked No. 1 (the literal rank-1 mark, not the round-1 count:
    # a ballot with rank 1 left blank or given to a write-in is counted under those, not its next choice)
    if winner and rounds:
        fc = Counter()
        for (n, r), a in zip(groups, assign):
            if a != winner:
                continue
            rank, cs = r[0]
            if rank != 1:
                fc['_blank'] += n
            elif len(cs) > 1:
                fc['_overvote'] += n
            else:
                (c,) = cs
                fc['_writein' if c in excluded else names[c]] += n
        rounds[-1]['firstRanks'] = {'candidate': names[winner], 'ballots': dict(fc.most_common())}
    rep = {'config': {'contest': contest['name'], 'generatedBy': 'tabulate_rcv.py (RCTab 2.1.0 rules)'},
           'results': rounds,
           'summary': {'totalNumBallots': str(total), 'undervotes': str(undervotes)},
           'winner': names[winner] if winner else None, 'problems': problems}
    return rep

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('patterns')
    ap.add_argument('--contests', nargs='*', help='site ids (gov, ussen, hd24, sdM ...); default all')
    ap.add_argument('--site', action='store_true', help='write site/data/rcv/<id>.json for gov, ussen, ushouse')
    ap.add_argument('--legislature', action='store_true',
                    help='write House and Senate contests that went past round 1 to site/data/rcv/legislature.json')
    ap.add_argument('--label', default='', help='label for the site files (default: the page says it is not official)')
    ap.add_argument('--report-dir', help='write <id>.json (RCTab-style report) and <id>.site.json per contest here')
    ap.add_argument('--use-isvote', action='store_true', help='also drop marks with IsVote false (test only)')
    a = ap.parse_args()
    data = json.load(open(a.patterns))
    out, leg = {}, {}
    for cid, c in data['contests'].items():
        sid = site_id(c['name'])
        if not sid or (a.contests and sid not in a.contests):
            continue
        rep = tabulate(c, a.use_isvote)
        conv, unmatched = build_rcv.convert(rep, sid, a.label)
        # legislative races only go in when nobody won a majority of first choices
        if sid.startswith(('hd', 'sd')) and not conv['rounds'][0]['elected']:
            leg[sid] = conv
        out[sid] = (rep, conv, unmatched)
        if a.report_dir:
            os.makedirs(a.report_dir, exist_ok=True)
            json.dump(rep, open(os.path.join(a.report_dir, f'{sid}.json'), 'w'), indent=1, ensure_ascii=False)
            json.dump(conv, open(os.path.join(a.report_dir, f'{sid}.site.json'), 'w'), indent=1, ensure_ascii=False)
        if a.site and sid in STATEWIDE.values():
            json.dump(conv, open(os.path.join(ROOT, 'site', 'data', 'rcv', f'{sid}.json'), 'w'), indent=1, ensure_ascii=False)
        flag = (' PROBLEM: ' + '; '.join(rep['problems'])) if rep['problems'] else ''
        if unmatched:
            flag += f' (names not matched to results.json: {sorted(unmatched)})'
        print(f"{sid:8} {conv['totalBallots']:>9,.0f} ballots  winner {rep['winner'] or '-':28} {build_rcv.describe(conv)}{flag}")
    if a.legislature and leg:
        dest = os.path.join(ROOT, 'site', 'data', 'rcv', 'legislature.json')
        json.dump(leg, open(dest, 'w'), separators=(',', ':'), ensure_ascii=False)
        print(f'wrote {dest}: {len(leg)} contests')
    return out

if __name__ == '__main__':
    main()
