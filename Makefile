\
SHELL := /bin/bash

PY := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTHON := $(VENV)/bin/python

.DEFAULT_GOAL := help

help:
	@echo "Targets:"
	@echo "  make venv              Create venv in .venv/"
	@echo "  make install           Install python deps"
	@echo "  make fmt               (noop) placeholder"
	@echo "  make api               Run FastAPI webhook server"
	@echo "  make runner            Run job runner"
	@echo "  make scheduler         Run cron-like scheduler"
	@echo "  make dev               Run api + runner + scheduler (foreground; Ctrl+C to stop)"
	@echo "  make submit-example    Submit example job via CLI"
	@echo "  make webhook-example   Submit example job via webhook"

venv:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip

install:
	$(PIP) install -r requirements.txt

api:
	@set -a; [ -f .env ] && source .env; set +a; \
	$(PYTHON) -m gateway.webhook_server

runner:
	@set -a; [ -f .env ] && source .env; set +a; \
	$(PYTHON) -m orchestrator.runner

scheduler:
	@set -a; [ -f .env ] && source .env; set +a; \
	$(PYTHON) -m orchestrator.scheduler

dev:
	@./scripts/dev.sh

submit-example:
	@set -a; [ -f .env ] && source .env; set +a; \
	$(PYTHON) -m cli submit examples/jobs/simple_job.json

webhook-example:
	@./scripts/webhook_example.sh
