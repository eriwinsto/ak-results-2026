"""Parse the Division's Liberty 'RCV Detailed Report' PDFs into rounds."""
import re, subprocess, json, sys, glob, os
def parse(pdf):
    t = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout
    lines = [l.rstrip() for l in t.split('\n')]
    head = {}
    for l in lines[:40]:
        m = re.match(r'^\s*Tabulation time:\s+(.*)$', l)
        if m: head['tabulationTime'] = m.group(1).strip()
        m = re.match(r'^Page: \d+ / \d+\s+(\S+ \S+)$', l)
        if m and 'printed' not in head: head['printed'] = m.group(1)
    title = next(l.strip() for l in lines if re.match(r'^(House District|Senate District|U\.S\.|Governor|United States)', l.strip()))
    rounds, cur, mode, tr = [], None, None, None
    for l in lines:
        s = l.strip()
        if not s or s.startswith('Page:') or s == 'State of Alaska': continue
        m = re.match(r'^Round (\d+)$', s)
        if m:
            cur = {'round': int(m.group(1)), 'tally': {}, 'transfers': {}, 'eliminated': [], 'elected': []}; rounds.append(cur); mode = 'tally'; continue
        if cur is None: continue
        if s.startswith('Candidate') and 'Votes' in s: continue
        m = re.match(r'^(Continuing Ballots Total|Blanks|Exhausted|Overvotes|Non Transferable Total)\s+([\d,]+)$', s)
        if m: cur[m.group(1)] = int(m.group(2).replace(',', '')); continue
        m = re.match(r'^(.+?) is eliminated because (.*)$', s)
        if m: cur['eliminated'].append(m.group(1)); cur.setdefault('why', []).append(m.group(2)); continue
        m = re.match(r'^(.+?) is elected because', s)
        if m: cur['elected'].append(m.group(1)); continue
        if s.startswith('Elimination transfer') or re.match(r'^\d+ ballots have been transferred', s) or s.startswith('Transferred from'):
            mode = 'transfer'; continue
        if mode == 'transfer':
            m = re.match(r'^(.+?)\s{2,}(.+?)\s{2,}(\d+)\s+1\s+[\d,]+$', s)
            if m: cur['transfers'].setdefault(m.group(1), {})[m.group(2)] = int(m.group(3)); continue
        if mode == 'tally':
            m = re.match(r'^(.+?)\s{2,}([\d,]+)\s+([\d.]+)%$', s)
            if m: cur['tally'][m.group(1)] = int(m.group(2).replace(',', '')); continue
    return {'title': title, **head, 'rounds': rounds}
if __name__ == '__main__':
    out = {os.path.basename(p)[4:-4]: parse(p) for p in sorted(glob.glob(sys.argv[1] + '/*.pdf'))}
    json.dump(out, open(sys.argv[2], 'w'), indent=1)
    for k, v in out.items(): print(k, v['title'], v.get('tabulationTime'), len(v['rounds']), 'rounds', 'elected', [r['elected'] for r in v['rounds'] if r['elected']])
