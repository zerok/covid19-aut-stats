import httpx
import argparse
from bs4 import BeautifulSoup
import re
import pendulum
import csv
from pathlib import Path
import sys

time_re = re.compile(r'Stand, (\d\d.\d\d.\d\d\d\d, \d\d:\d\d)')
tests_re = re.compile(r'Testungen: ([^ ]+)')
confirmed_re = re.compile(r'Bestätigte Fälle: ([^ ]+)')
deaths_re = re.compile(r'Todesfälle: ([^ ]+)')
recovered_re = re.compile(r'Genesene Personen: ([^ ]+)')
state_count_re = re.compile(r'(\S+)\s\(([^)]+)\)')

bms_url = 'https://www.sozialministerium.at/Informationen-zum-Coronavirus/Neuartiges-Coronavirus-(2019-nCov).html'

state_mapping = {
    'Burgenland': 1,
    'Kärnten': 2,
    'Niederösterreich': 3,
    'Oberösterreich': 4,
    'Salzburg': 5,
    'Steiermark': 6,
    'Tirol': 7,
    'Vorarlberg': 8,
    'Wien': 9,
}

headers = ['date', 'tests', 'confirmed', 'deaths', 'recovered'] + [f'state_{i}' for i in range(1,10)]

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
    parser.add_argument('--input-file')
    parser.add_argument('--output-file')
    args = parser.parse_args()
    doc = None
    if args.input_file:
        with open(args.input_file, encoding='utf-8') as fp:
            doc = BeautifulSoup(fp.read(), features='html.parser')
    else:
        resp = httpx.get(bms_url)
        doc = BeautifulSoup(resp.text, features='html.parser')

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
    abstract = doc.find(attrs={
        'class': 'abstract'
    })
    raw = strip(abstract)

    fed = FederalData()
    mo = time_re.search(raw)
    if mo:
        fed.date = pendulum.from_format(mo.group(1), 'DD.MM.YYYY, HH:mm', tz='Europe/Vienna')
    mo = tests_re.search(raw)
    if mo:
        fed.tested = atoi(mo.group(1))
    mo = confirmed_re.search(raw)
    if mo:
        fed.confirmed = atoi(mo.group(1))
    mo = deaths_re.search(raw)
    if mo:
        fed.deaths = atoi(mo.group(1))
    mo = recovered_re.search(raw)
    if mo:
        fed.recovered = atoi(mo.group(1))

    # Load data for every state:
    infoboxes = [strip(e) for e in doc.find(class_='infobox').find_all('p')]
    state_counts = [''] * 9
    for box in infoboxes:
        if box.startswith('Bestätigte Fälle'):
            for state in state_count_re.finditer(box):
                state_name = state.group(1)
                state_code = state_mapping[state_name]
                state_count = atoi(state.group(2))
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
