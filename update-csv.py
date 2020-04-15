import httpx
import argparse
import re
import pendulum
import csv
from pathlib import Path
import sys
import json
import bs4
import zipfile
import shutil
import os
import math

deaths_re = re.compile(r'Todesfälle\s*\(1\)\s*,\s*Stand \d\d.\d\d.\d\d\d\d, \d\d:\d\d Uhr\s*:\s*([0-9.]+),')
recoveries_re = re.compile(r'Genesen\s*,\s*Stand \d\d.\d\d.\d\d\d\d, \d\d:\d\d Uhr\s*:\s*([0-9.]+),')
tests_re = re.compile(r'Bisher durchgeführte Testungen in Österreich \([^)]+\): ([0-9.]+)')
simpledata_url = 'https://info.gesundheitsministerium.at/data/SimpleData.js'
state_url = 'https://info.gesundheitsministerium.at/data/Bundesland.js'
sozmin_url = 'https://www.sozialministerium.at/Informationen-zum-Coronavirus/Neuartiges-Coronavirus-(2019-nCov).html'
datazip_url = 'https://info.gesundheitsministerium.at/data/data.zip'

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
    'V': 8,
    'W': 9,
}

headers = ['date', 'tests', 'confirmed', 'deaths', 'recovered'] + [f'confirmed_state_{i}' for i in range(1,10)] + [f'hospitalized_state_{i}' for i in range(1, 10)] + [f'intensivecare_state_{i}' for i in range(1, 10)] + ['hospitalized_total', 'intensivecare_total']


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

    data_folder = download_and_extract_datazip(datazip_url)

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

    hospitalized, intensivecare, hospitalized_total, intensivecare_total = fetch_hospital_numbers(data_folder)

    rows.append([fed.date.isoformat(), fed.tested, fed.confirmed, fed.deaths, fed.recovered] + state_counts + hospitalized + intensivecare + [hospitalized_total, intensivecare_total])

    # normalize rows
    updated_rows = []
    for row in rows:
        updated_rows.append(row + [None] * (len(headers) - len(row)))

    latest = updated_rows[-1]
    previous = latest
    if len(updated_rows) > 1:
        previous = get_latest_yesterday(updated_rows, now=fed.date)

    previous_hospitalized = previous[32]
    previous_intensivecare = previous[33]
    if not previous_hospitalized:
        previous_hospitalized = sum_columns(previous[14:23])
    current_hospitalized = hospitalized_total

    if not previous_intensivecare:
        previous_intensivecare = sum_columns(previous[23:32])
    current_intensivecare = intensivecare_total

    current_infected = fed.confirmed - fed.deaths - fed.recovered
    previous_infected = int(previous[2]) - int(previous[3]) - int(previous[4])

    print(f'''New numbers for Austria available ({fed.date.isoformat()}):
Positive tests: {fed.confirmed} ({format_delta(latest[2], previous[2])})
Currently infected: {current_infected} ({format_delta(current_infected, previous_infected)})
Recovered: {fed.recovered} ({format_delta(latest[4], previous[4])})
Deaths: {fed.deaths} ({format_delta(latest[3], previous[3])})
Hospitalized: {current_hospitalized} ({format_delta(current_hospitalized, previous_hospitalized)})
Intensive care: {current_intensivecare} ({format_delta(current_intensivecare, previous_intensivecare)})

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


def sum_columns(values):
    result = 0
    for v in values:
        try:
            result += int(v)
        except:
            pass
    return result


def fetch_hospital_numbers(data_folder):
    """
    Loads number of people in hospitals and those with intensive care.
    """
    # Fill old state-based numbers with empty values for now
    state_counts_hosp = [''] * 9
    state_counts_int = [''] * 9
    hospitalized_total = 0
    intensivecare_total = 0

    for idx, row in enumerate(csv.reader((data_folder / 'AllgemeinDaten.csv').open(), delimiter=';')):
        if idx == 0:
            continue
        hospitalized_cap, intensivecare_cap, hospitalized_total, intensivecare_total = int(row[6]), int(row[7]), int(row[8]), int(row[9])

    return state_counts_hosp, state_counts_int, hospitalized_total, intensivecare_total


def download_and_extract_datazip(url):
    resp = httpx.get(url)
    output = Path('data.zip')
    output_folder = Path('_datazip')
    if output_folder.exists():
        shutil.rmtree(output_folder)
    output_folder.mkdir(parents=True)
    with output.open('wb+') as fp:
        for chunk in resp.iter_bytes():
            fp.write(chunk)

    zf = zipfile.ZipFile(output)
    os.chdir(output_folder)
    try:
        zf.extractall()
    finally:
        os.chdir('..')
    return output_folder


if __name__ == '__main__':
    main()
