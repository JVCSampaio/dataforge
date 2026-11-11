PY ?= python
export PYTHONPATH := src

.PHONY: install test lint run-ingest quality metrics serve

install:
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

run-ingest:
	$(PY) -m dataforge ingest --source all

quality:
	$(PY) -m dataforge quality --output-dir reports

metrics:
	$(PY) -m dataforge metrics

serve:
	$(PY) -m dataforge serve
