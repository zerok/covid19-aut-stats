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
from httpx._config import DEFAULT_CIPHERS


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

def download_datasets():
    data_folder = Path('data')
    if data_folder.exists():
        shutil.rmtree(data_folder)
    data_folder.mkdir()
    data_sets = {
        'CovidFaelle_Timeline.csv': 'https://covid19-dashboard.ages.at/data/CovidFaelle_Timeline.csv',
        'CovidFallzahlen.csv': 'https://covid19-dashboard.ages.at/data/CovidFallzahlen.csv',
    }

    # Something about the DH key changed on 2021-03-16 15:00
    # UTC+1. Disabling that part of the check for now:
    context = httpx.create_ssl_context()
    ciphers = DEFAULT_CIPHERS + ':HIGH:!DH:!aNULL'
    context.set_ciphers(ciphers)

    for key, url in data_sets.items():
        (data_folder / key).write_text(httpx.get(url, verify=context).content.decode('utf-8').rstrip('\0'))


def get_case_numbers():
    data_folder = Path('data')
    max_date = None
    with (data_folder / 'CovidFaelle_Timeline.csv').open(encoding='utf-8-sig') as fp:
        for row in csv.DictReader(fp, delimiter=';'):
            max_date = parse_date(row['Time'])
    federal = None
    by_state = {}
    with (data_folder / 'CovidFaelle_Timeline.csv').open(encoding='utf-8-sig') as fp:
        for row in csv.DictReader(fp, delimiter=';'):
            if parse_date(row['Time']) != max_date:
                continue
            if row['BundeslandID'] == '10':
                d = FederalData()
                d.date = max_date
                d.deaths = atoi(row['AnzahlTotSum'])
                d.confirmed = atoi(row['AnzahlFaelleSum'])
                d.recovered = atoi(row['AnzahlGeheiltSum'])
                federal = d
            else:
                d = StateData()
                d.date = max_date
                d.deaths = atoi(row['AnzahlTotSum'])
                d.confirmed = atoi(row['AnzahlFaelleSum'])
                d.recovered = atoi(row['AnzahlGeheiltSum'])
                d.id = atoi(row['BundeslandID'])
                d.name = row['Bundesland']
                by_state[row['BundeslandID']] = d
    # We need to reset the max date as both datasets are not updated at the same time.
    with (data_folder / 'CovidFallzahlen.csv').open() as fp:
        for row in csv.DictReader(fp, delimiter=';'):
            max_date = parse_date(row['MeldeDatum'])
    with (data_folder / 'CovidFallzahlen.csv').open() as fp:
        for row in csv.DictReader(fp, delimiter=';'):
            if parse_date(row['MeldeDatum']) != max_date:
                continue
            if row['BundeslandID'] == '10':
                federal.tested = atoi(row['TestGesamt'])
                federal.hospitalized = atoi(row['FZHosp'])
                federal.intensivecare = atoi(row['FZICU'])
            else:
                by_state[row['BundeslandID']].tested = atoi(row['TestGesamt'])
                by_state[row['BundeslandID']].hospitalized = atoi(row['FZHosp'])
                by_state[row['BundeslandID']].intensivecare = atoi(row['FZICU'])
    # Use the date that is newer
    if max_date > federal.date:
        federal.date = max_date
    return (federal, by_state)
    

def atoi(s):
    return int(s.replace('.', ''))


class StateData:
    id = 0
    name = None
    date = None
    confirmed = 0
    hospitalized = 0
    intensivecare = 0
    tested = 0

    def __str__(self):
        return f'<StateData date={self.date} deaths={self.deaths} recovered={self.recovered} confirmed={self.confirmed} tested={self.tested} intensivecare={self.intensivecare} hospitalized={self.hospitalized}>'

    def __repr__(self):
        return str(self)


class FederalData:
    date = None
    deaths = 0
    confirmed = 0
    tested = 0
    recovered = 0
    hospitalized = 0
    intensivecare = 0

    def __str__(self):
        return f'<FederatedData date={self.date} deaths={self.deaths} recovered={self.recovered} confirmed={self.confirmed} tested={self.tested}>'

    def __repr__(self):
        return str(self)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-file')
    parser.add_argument('--skip-download', default=False, action='store_true')
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

    if not args.skip_download:
        download_datasets()
    fed, by_state = get_case_numbers()

    # Load data for every state:
    state_counts = [''] * 9
    hospitalized = [''] * 9
    intensivecare = [''] * 9
    for _, state in by_state.items():
        state_counts[state.id-1] = state.confirmed
        intensivecare[state.id-1] = state.intensivecare
        hospitalized[state.id-1] = state.hospitalized
    hospitalized_total = fed.hospitalized
    intensivecare_total = fed.intensivecare

    formatted_date = fed.date.isoformat()
    for row in rows:
        if row[0] == formatted_date:
            sys.exit(0)

    rows.append([fed.date.isoformat(), fed.tested, fed.confirmed, fed.deaths, fed.recovered] + state_counts + hospitalized + intensivecare + [hospitalized_total, intensivecare_total])

    # normalize rows
    updated_rows = []
    for row in rows:
        updated_rows.append(row + [None] * (len(headers) - len(row)))
        if not updated_rows[-1][32]:
            updated_rows[-1][32] = sum_columns(updated_rows[-1][14:23])
        if not updated_rows[-1][33]:
            updated_rows[-1][33] = sum_columns(updated_rows[-1][23:32])

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


def parse_date(s):
    return pendulum.from_format(s, 'DD.MM.YYYY HH:mm:ss', tz='Europe/Vienna')


if __name__ == '__main__':
    main()
