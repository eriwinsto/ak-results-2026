"""Boil a Dominion/Liberty CVR export folder down to the ranked-choice contests' ballot patterns.

The Division's CVR export is ~1,600 JSON files and over a gigabyte. Tabulation only needs, for each
ranked contest, how many ballots carry each distinct set of rankings. This reads the export the
way RCTab's Dominion reader does and writes a small JSON file that scripts/tabulate_rcv.py reads.

  python3 scripts/cvr_extract.py "path/to/CVR_Export folder" cvr_patterns.json
  python3 scripts/cvr_extract.py FOLDER out.json --shard 3/10   # one tenth of the files (merge with --merge)
  python3 scripts/cvr_extract.py --merge out.json part1.json part2.json ...

Reading rules (RCTab 2.1.0, Dominion provider):
  * each session uses its "Original" record when IsCurrent is true, otherwise its "Modified"
    (adjudicated) record; a session with neither is skipped and counted
  * a record's cards are under "Cards" (or the record itself is the card)
  * every mark is kept with its rank and its IsAmbiguous / IsVote flags, so the tabulator decides
    which marks count
  * a contest the scanner flagged InvalidContest (outstack condition) is skipped, as RCTab skips it:
    these are ballots that carried a race the voter could not vote in, which the Division doesn't count
Also counts, for the U.S. House contest (id 7), ballots by precinct portion: the counts the
CVR gap note uses (scripts/cvr_counts.py made them from RCTab's output before).
"""
import json, os, sys
from collections import Counter
from multiprocessing import Pool

HOUSE_CONTEST = 7

def read_file(args):
    path, rcv_ids, invalid = args
    invalid = set(invalid)
    skipped_invalid = Counter()
    pats = {cid: Counter() for cid in rcv_ids}
    portions, sessions, skipped = Counter(), 0, 0
    for s in json.load(open(path, encoding='utf-8-sig'))['Sessions']:
        sessions += 1
        rec = s.get('Original') or {}
        if not rec.get('IsCurrent', True):
            rec = s.get('Modified')
            if not rec:
                skipped += 1
                continue
        cards = rec['Cards'] if 'Cards' in rec else [rec]
        for card in cards:
            for c in card.get('Contests', []):
                cid = c['Id']
                if cid not in pats:
                    continue
                if invalid & set(c.get('OutstackConditionIds') or []):
                    skipped_invalid[cid] += 1  # contest flagged InvalidContest: not counted (as RCTab does)
                    continue
                key = tuple(sorted((m['Rank'], m['CandidateId'], int(bool(m.get('IsAmbiguous'))), int(bool(m.get('IsVote', True))))
                                   for m in c.get('Marks', [])))
                pats[cid][key] += 1
                if cid == HOUSE_CONTEST:
                    portions[rec.get('PrecinctPortionId')] += 1
    return pats, portions, sessions, skipped, skipped_invalid

def merge(out, parts):
    res = None
    for p in parts:
        d = json.load(open(p))
        if res is None:
            res = d
            for c in res['contests'].values():
                c['patterns'] = Counter({json.dumps(m): n for n, m in c['patterns']})
            res['housePortions'] = Counter(res['housePortions'])
            continue
        for k in ('files', 'sessions', 'sessionsSkipped'):
            res[k] += d[k]
        for cid, c in d['contests'].items():
            r = res['contests'][cid]
            r['ballots'] += c['ballots']
            r['patterns'].update({json.dumps(m): n for n, m in c['patterns']})
        res['housePortions'].update(d['housePortions'])
    for c in res['contests'].values():
        c['patterns'] = [[n, json.loads(m)] for m, n in c['patterns'].most_common()]
    res['housePortions'] = dict(sorted(res['housePortions'].items()))
    res.pop('shard', None)
    json.dump(res, open(out, 'w'), separators=(',', ':'))
    print(f"merged {len(parts)} parts: {res['files']} files, {res['sessions']:,} sessions -> {out}", file=sys.stderr)

def main():
    if sys.argv[1] == '--merge':
        return merge(sys.argv[2], sys.argv[3:])
    folder, out = sys.argv[1], sys.argv[2]
    shard = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == '--shard' else None
    man = lambda n: json.load(open(os.path.join(folder, n), encoding='utf-8-sig'))['List']
    contests = {c['Id']: c for c in man('ContestManifest.json') if c.get('NumOfRanks', 0) > 0}
    cands = man('CandidateManifest.json')
    pp = {p['Id']: p['Description'] for p in man('PrecinctPortionManifest.json')}
    invalid = [o['Id'] for o in man('OutstackConditionManifest.json') if o['Description'] == 'InvalidContest']
    files = sorted(f for f in os.listdir(folder) if f.startswith('CvrExport') and f.endswith('.json'))
    if shard:
        i, n = map(int, shard.split('/'))
        files = files[i - 1::n]
    pats = {cid: Counter() for cid in contests}
    portions, sessions, skipped = Counter(), 0, 0
    invalid_total = Counter()
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for i, (p, por, n, sk, inv) in enumerate(pool.imap_unordered(read_file, [(os.path.join(folder, f), list(contests), invalid) for f in files], chunksize=8)):
            invalid_total.update(inv)
            for cid, cnt in p.items():
                pats[cid].update(cnt)
            portions.update(por)
            sessions += n
            skipped += sk
            if (i + 1) % 200 == 0:
                print(f'{i + 1}/{len(files)} files', file=sys.stderr)
    res = {'folder': os.path.basename(os.path.normpath(folder)), 'files': len(files), 'sessions': sessions,
           'sessionsSkipped': skipped, 'shard': shard, 'contests': {}}
    for cid, c in contests.items():
        res['contests'][str(cid)] = {
            'name': c['Description'], 'ranks': c['NumOfRanks'],
            'candidates': {str(x['Id']): {'name': x['Description'], 'type': x.get('Type', 'Regular')}
                           for x in cands if x['ContestId'] == cid},
            'ballots': sum(pats[cid].values()), 'invalidContestSkipped': invalid_total.get(cid, 0),
            'patterns': [[n, [list(m) for m in k]] for k, n in pats[cid].most_common()]}
    named = Counter()  # several precinct-portion ids can share one name; add them up
    for k, n in portions.items():
        named[pp.get(k, str(k))] += n
    res['housePortions'] = dict(sorted(named.items()))
    json.dump(res, open(out, 'w'), separators=(',', ':'))
    print(f"{len(files)} files, {sessions:,} sessions ({skipped} skipped), {len(contests)} ranked contests -> {out} "
          f"({os.path.getsize(out) / 1e6:.1f} MB)", file=sys.stderr)

if __name__ == '__main__':
    main()
