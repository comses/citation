SHELL := /bin/bash

COMPOSE ?= docker compose

.PHONY: build clean lock up test

build:
	$(COMPOSE) build

up: build
	$(COMPOSE) up -d

clean:
	$(COMPOSE) down --volumes --remove-orphans

lock:
	$(COMPOSE) run --rm test uv lock

test: build
	$(COMPOSE) up -d db
	$(COMPOSE) run --rm test ./run_tests.py
