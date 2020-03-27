import httpx
import argparse
import re
import pendulum
import csv
from pathlib import Path
import sys
import json
import bs4

deaths_re = re.compile(r'Todesfälle , Stand \d\d.\d\d.\d\d\d\d, \d\d:\d\d Uhr: (\d+),')
tests_re = re.compile(r'Bisher durchgeführte Testungen in Österreich \([^)]+\): ([0-9.]+)')
simpledata_url = 'https://info.gesundheitsministerium.at/data/SimpleData.js'
state_url = 'https://info.gesundheitsministerium.at/data/Bundesland.js'
sozmin_url = 'https://www.sozialministerium.at/Informationen-zum-Coronavirus/Neuartiges-Coronavirus-(2019-nCov).html'

state_mapping = {
    'Bgld': 1,
    'Ktn': 2,
    'NÖ': 3,
    'OÖ': 4,
    'Sbg': 5,
    'Stmk': 6,
    'T': 7,
    'Vbg': 8,
    'W': 9,
}

headers = ['date', 'tests', 'confirmed', 'deaths', 'recovered'] + [f'confirmed_state_{i}' for i in range(1,10)]

def atoi(s):
    return int(s.replace('.', ''))

def strip(elem):
    return ' '.join([s.strip() for s in elem.strings]).replace('  ', ' ')

class FederalData:
    date = None
    deaths = 0
    confirmed = 0
    tested = 0
    recovered = 0

    def __str__(self):
        return f'<FederatedData date={self.date} deaths={self.deaths} confirmed={self.confirmed} tested={self.tested}>'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-file')
    args = parser.parse_args()
    doc = None


    rows = []

    # read csv file if it already exists
    if args.output_file:
        output_file = Path(args.output_file)
        if output_file.exists():
            with open(output_file) as fp:
                for i, row in enumerate(csv.reader(fp)):
                    if i == 0:
                        continue
                    rows.append(row)

    # Load federal data:
    fed = FederalData()
    resp = httpx.get(simpledata_url)
    for line in resp.text.split('\n'):
        if 'Erkrankungen' in line:
            fed.confirmed = int(line.split(' = ')[1].rstrip(';'))
        if 'LetzteAktualisierung' in line:
            fed.date = pendulum.from_format(line.split(' = ')[1].rstrip(';')[1:-1], 'DD.MM.YYYY HH:mm.ss', tz='Europe/Vienna')

    resp = httpx.get(sozmin_url)
    doc = bs4.BeautifulSoup(resp.text, features='html.parser')
    for paragraph in [strip(p) for p in doc.find_all('p')]:
        mo = deaths_re.search(paragraph)
        if mo:
            fed.deaths = atoi(mo.group(1))
        mo = tests_re.search(paragraph)
        if mo:
            fed.tested = atoi(mo.group(1))


    resp = httpx.get(state_url)
    data = resp.text.lstrip('var dpBundesland = ').rstrip().rstrip(';')
    data = json.loads(data)
    # Load data for every state:
    state_counts = [''] * 9
    for state in data:
        state_name = state['label']
        state_code = state_mapping[state_name]
        state_count = state['y']
        state_counts[state_code-1] = state_count

    formatted_date = fed.date.isoformat()
    for row in rows:
        if row[0] == formatted_date:
            sys.exit(0)

    rows.append([fed.date.isoformat(), fed.tested, fed.confirmed, fed.deaths, fed.recovered] + state_counts)

    if args.output_file:
        with open(args.output_file, 'w+') as fp:
            csv.writer(fp).writerows([headers] + rows)
    else:
        csv.writer(sys.stdout).writerows([headers] + rows)


if __name__ == '__main__':
    main()
