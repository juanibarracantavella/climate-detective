PYTHON := .venv/bin/python
PIP := .venv/bin/pip
UVICORN := .venv/bin/uvicorn
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

.PHONY: help setup run backend test lint format check

help:
	@echo "Available commands:"
	@echo "  make setup    Create the virtual environment and install dependencies"
	@echo "  make run      Run the backend with reload and variables from .env"
	@echo "  make test     Run the test suite"
	@echo "  make lint     Run Ruff checks"
	@echo "  make format   Format Python files"
	@echo "  make check    Run lint, formatting check, and tests"

setup:
	python -m venv .venv
	$(PIP) install -e '.[dev]'

run:
	@test -f .env || (echo "Missing .env; copy .env.example to .env first" && exit 1)
	$(UVICORN) app.main:app --reload --host 127.0.0.1 --port 8000 --env-file .env

backend: run

test:
	$(PYTEST) -q

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

check:
	$(RUFF) check .
	$(RUFF) format --check .
	$(PYTEST) -q
