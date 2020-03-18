covid19-aut.sqlite: covid19-aut.csv
	rm $@ && pipenv run csvs-to-sqlite $< $@
