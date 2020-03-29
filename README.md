# COVID-19 numbers (Austria)

## What's in here?

- A simple script to scrape the latest numbers from sozialministerium.at.

## How to use?

```
pipenv sync
pipenv run python3 update-csv.py --output-file covid19-aut.csv
pipenv run csvs-to-sqlite covid19-aut.csv covid19-aut.sqlite
pipenv run datasette covid19-aut.sqlite
```

## Sources:

This repository contains data scraped from ORF.at and the website of the
Austrian "Bundesministerium Soziales, Gesundheit, Pflege und Konsumentenschutz.

- <https://orf.at/corona/daten>
- <https://www.sozialministerium.at/Informationen-zum-Coronavirus/Neuartiges-Coronavirus-(2019-nCov).html>
- <https://info.gesundheitsministerium.at/>
- <https://www.sozialministerium.at/Informationen-zum-Coronavirus/Dashboard/Zahlen-zur-Hospitalisierung>
