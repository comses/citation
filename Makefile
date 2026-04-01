SHELL := /bin/bash

COMPOSE ?= docker compose
PYPI_ORG ?= comses
PYPI_REPOSITORY ?= pypi

.PHONY: build clean format lock publish up test

build:
	$(COMPOSE) build

up: build
	$(COMPOSE) up -d

clean:
	$(COMPOSE) down --volumes --remove-orphans

format: build
	$(COMPOSE) run --rm test uv run ruff format .

lock:
	$(COMPOSE) run --rm test uv lock

publish: build
	@test -n "$(PYPI_TOKEN)" || (echo "PYPI_TOKEN is required" && exit 1)
	$(COMPOSE) run --rm -e PYPI_TOKEN="$(PYPI_TOKEN)" test bash -lc \
		'echo "Publishing citation to $(PYPI_REPOSITORY) under org $(PYPI_ORG)" && uv build && uv publish --token "$$PYPI_TOKEN" --index "$(PYPI_REPOSITORY)" dist/*'

test: build
	$(COMPOSE) up -d db
	$(COMPOSE) run --rm test ./run_tests.py
