"""Read write-in totals from the Division's Election Summary Report PDF.

The precinct CSV has no write-in votes; the summary PDF does, and its percentages (named
candidates plus write-ins) are the ones the Division treats as official. This reads the PDF
with pdftotext (poppler-utils) and returns {contest title: write-in votes}.

Every contest is checked before anything is returned:
  * its rows add up to the PDF's "Total Votes" line, and
  * its named candidates' votes are exactly the CSV's (passed in as expected), so the PDF
    and CSV are from the same update.
A failed check raises Mismatch, and nothing is used.

  python3 scripts/summary_writeins.py ElectionSummaryReportRPT.pdf   # prints what it finds
"""
import re, subprocess, sys

ROW = re.compile(r'^(?P<name>\S.*?)?\s+(?:[A-Z]{2,3}(?:/[A-Z]{2,3})?\s+)?(?P<votes>[\d,]+)\s+[\d.]+%$')

class Mismatch(Exception):
    pass

def parse(pdf_path):
    """{title: {'rows': [(name or '', votes)], 'total': n}} for every contest in the report."""
    txt = subprocess.run(['pdftotext', '-layout', pdf_path, '-'], check=True, capture_output=True, text=True).stdout
    lines = [l.rstrip() for l in txt.split('\n')]
    out, i = {}, 0
    while i < len(lines):
        if i + 1 < len(lines) and lines[i + 1].startswith('Precincts Reported:') and lines[i].strip() and not lines[i].startswith(' '):
            title = lines[i].strip()
            j = i + 2
            while j < len(lines) and not lines[j].startswith('Candidate'):
                j += 1
            rows, total = [], None
            for l in lines[j + 1:]:
                s = l.strip()
                m = re.match(r'^Total Votes\s+([\d,]+)$', s)
                if m:
                    total = int(m.group(1).replace(',', ''))
                    break
                if s.startswith('Page:') or s.startswith('Precincts Reported:'):
                    break
                m = ROW.match(l) if s else None
                if m:
                    rows.append(((m.group('name') or '').strip(), int(m.group('votes').replace(',', ''))))
            if total is not None:
                out[title] = {'rows': rows, 'total': total}
            i = j
        i += 1
    return out

def writeins(pdf_path, expected):
    """expected: {title: [named candidates' votes]} from the CSV. Returns {title: write-in votes}."""
    report = parse(pdf_path)
    found, problems = {}, []
    for title, votes in expected.items():
        c = report.get(title)
        if c is None:
            problems.append(f'{title}: not in the summary report'); continue
        if sum(v for _, v in c['rows']) != c['total']:
            problems.append(f'{title}: rows add to {sum(v for _, v in c["rows"]):,}, Total Votes says {c["total"]:,}'); continue
        wi = [v for n, v in c['rows'] if n == 'Write-in']
        named = sorted(v for n, v in c['rows'] if n != 'Write-in')
        if len(wi) > 1:
            problems.append(f'{title}: more than one write-in line'); continue
        if named != sorted(votes):
            problems.append(f'{title}: candidate votes {named} differ from the CSV {sorted(votes)}'); continue
        if wi:
            found[title] = wi[0]
    if problems:
        raise Mismatch('; '.join(problems[:6]) + (f' (and {len(problems) - 6} more)' if len(problems) > 6 else ''))
    return found

if __name__ == '__main__':
    for t, c in parse(sys.argv[1]).items():
        wi = [v for n, v in c['rows'] if n == 'Write-in']
        print(f"{t}: total {c['total']:,}, write-in {wi[0] if wi else '-'}, rows add up: {sum(v for _, v in c['rows']) == c['total']}")
