PY ?= .venv/bin/python

.PHONY: help install up down db-up logs dev test lint fmt prepare-data eval

help:          ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install:       ## create venv and install with dev extras
	python3.12 -m venv .venv && $(PY) -m pip install -e ".[dev]"

up:            ## start db + api in Docker
	docker compose up -d --build

down:          ## stop containers (data volume is kept)
	docker compose down

db-up:         ## start only Postgres (for local uvicorn / tests)
	docker compose up -d --wait db

logs:          ## follow api logs
	docker compose logs -f api

dev: db-up     ## run the API locally with reload
	$(PY) -m uvicorn api:app --reload --port 8000 --no-access-log

test: db-up    ## run the test suite (needs Postgres)
	$(PY) -m pytest

lint:          ## ruff + mypy
	$(PY) -m ruff check .
	$(PY) -m mypy

fmt:           ## auto-fix lint issues
	$(PY) -m ruff check --fix .

prepare-data:  ## CSV -> data/cloudtrail.duckdb without Docker (P2)
	$(PY) scripts/prepare_data.py

eval:          ## run the evaluation against the running API (see python main.py --help)
	$(PY) main.py
