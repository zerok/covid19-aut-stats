covid19-aut.sqlite: covid19-aut.csv
	rm -f $@ && poetry run csvs-to-sqlite $< $@
