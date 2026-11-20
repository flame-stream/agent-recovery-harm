PY ?= python3

.PHONY: tables check unpack clean

## Print Tables I-IV and every number of the paper from data/ (no model, no AppWorld needed)
tables:
	$(PY) scripts/tables/paper_numbers.py

## Compare with paper/expected_values.json; non-zero exit on any difference
check:
	$(PY) scripts/tables/check.py

## Unpack data/protected/protected.bundle (needs `pip install appworld`)
unpack:
	$(PY) scripts/unpack_protected.py

clean:
	rm -rf build
