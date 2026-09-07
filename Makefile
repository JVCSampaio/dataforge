PY ?= python
export PYTHONPATH := src

.PHONY: install test lint run-ingest quality metrics serve

install:
	uv pip install -r requirements.txt

test:
	$(PY) -m pytest -v

lint:
	$(PY) -m ruff check src tests

run-ingest:
	$(PY) -m dataforge ingest --source all

quality:
	$(PY) -m dataforge quality

metrics:
	$(PY) -m dataforge metrics

serve:
	$(PY) -m dataforge serve
