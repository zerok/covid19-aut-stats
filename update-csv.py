import httpx
import argparse
import re
import pendulum
import csv
from pathlib import Path
import sys
import json
import bs4

deaths_re = re.compile(r'Todesfälle\s*\(1\)\s*, Stand \d\d.\d\d.\d\d\d\d, \d\d:\d\d Uhr: ([0-9.]+),')
recoveries_re = re.compile(r'Genesen\s*, Stand \d\d.\d\d.\d\d\d\d, \d\d:\d\d Uhr: ([0-9.]+),')
tests_re = re.compile(r'Bisher durchgeführte Testungen in Österreich \([^)]+\): ([0-9.]+)')
simpledata_url = 'https://info.gesundheitsministerium.at/data/SimpleData.js'
state_url = 'https://info.gesundheitsministerium.at/data/Bundesland.js'
sozmin_url = 'https://www.sozialministerium.at/Informationen-zum-Coronavirus/Neuartiges-Coronavirus-(2019-nCov).html'

statename_mapping = {
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

headers = ['date', 'tests', 'confirmed', 'deaths', 'recovered'] + [f'confirmed_state_{i}' for i in range(1,10)] + [f'hospitalized_state_{i}' for i in range(1, 10)] + [f'intensivecare_state_{i}' for i in range(1, 10)]


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
        return f'<FederatedData date={self.date} deaths={self.deaths} recovered={self.recovered} confirmed={self.confirmed} tested={self.tested}>'


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
            fed.confirmed = int(line.split(' = ')[1].rstrip(';').strip('"\''))
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
        mo = recoveries_re.search(paragraph)
        if mo:
            fed.recovered = atoi(mo.group(1))

    resp = httpx.get(state_url)
    data = resp.text.split('\n')[0].lstrip('var dpBundesland = ').rstrip().rstrip(';')
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

    hospitalized, intensivecare = fetch_hospital_numbers()

    rows.append([fed.date.isoformat(), fed.tested, fed.confirmed, fed.deaths, fed.recovered] + state_counts + hospitalized + intensivecare)

    # normalize rows
    updated_rows = []
    for row in rows:
        updated_rows.append(row + [None] * (len(headers) - len(row)))

    latest = rows[-1]
    previous = latest
    if len(rows) > 1:
        previous = get_latest_yesterday(rows, now=fed.date)

    previous_hospitalized = sum([int(i) for i in previous[14:23]])
    current_hospitalized = sum([int(i) for i in latest[14:23]])
    previous_intensivecare = sum([int(i) for i in previous[23:32]])
    current_intensivecare = sum([int(i) for i in latest[23:32]])
    assert current_hospitalized == sum(hospitalized)
    assert current_intensivecare == sum(intensivecare)

    print(f'''New numbers for Austria available ({fed.date.isoformat()}):
Positive tests: {fed.confirmed} ({format_delta(latest[2], previous[2])})
Recovered: {fed.recovered} ({format_delta(latest[4], previous[4])})
Deaths: {fed.deaths} ({format_delta(latest[3], previous[3])})
Hospitalized: {sum(hospitalized)} ({format_delta(current_hospitalized, previous_hospitalized)})
Intensive care: {sum(intensivecare)} ({format_delta(current_intensivecare, previous_intensivecare)})

(Compared to {previous[0]})''')

    if args.output_file:
        with open(args.output_file, 'w+') as fp:
            csv.writer(fp).writerows([headers] + updated_rows)
    else:
        csv.writer(sys.stdout).writerows([headers] + updated_rows)


def get_latest_yesterday(rows, now=None):
    if now is None:
        now = pendulum.now()
    yesterday = now.subtract(days=1)
    candidate = None
    for row in reversed(rows):
        d = pendulum.parse(row[0])
        if d.day == yesterday.day and d.month == yesterday.month and d.year == yesterday.year:
            candidate = row
            break
    if candidate is None and len(rows) > 1:
        candidate = rows[-2]
    return candidate


def format_delta(current, previous):
    curr = int(current)
    prev = int(previous)
    if curr >= prev:
        return f'+{curr-prev}'
    return f'{curr-prev}'


def fetch_hospital_numbers():
    """
    Loads number of people in hospitals and those with intensive care.
    """
    hospital_url = 'https://www.sozialministerium.at/Informationen-zum-Coronavirus/Dashboard/Zahlen-zur-Hospitalisierung'
    resp = httpx.get(hospital_url)
    doc = bs4.BeautifulSoup(resp.text, features='html.parser')
    tables = list(doc.find_all('tbody'))
    if len(tables) != 1:
        raise 'unexpected number of tables found'
    state_counts_hosp = [''] * 9
    state_counts_int = [''] * 9
    for row in tables[0].find_all('tr'):
        rowtext = strip(row).strip()
        fields = rowtext.split(' ')
        if len(fields) > 3:
            continue
        state_name = fields[0]
        state_code = statename_mapping[state_name]
        state_count_hosp = int(fields[1])
        state_count_intensive = int(fields[2])
        state_counts_hosp[state_code-1] = state_count_hosp
        state_counts_int[state_code-1] = state_count_intensive
    return state_counts_hosp, state_counts_int


if __name__ == '__main__':
    main()
