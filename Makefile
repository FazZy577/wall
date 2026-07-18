# Makefile-style commands for development

.PHONY: help install test lint format type-check check clean

help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linter"
	@echo "  make format       - Format code"
	@echo "  make type-check   - Run type checker"
	@echo "  make check        - Run all checks (lint + type-check + test)"
	@echo "  make clean        - Clean temporary files"

install:
	uv sync --extra dev

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

test-cov:
	uv run pytest --cov=src --cov-report=html --cov-report=term

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

format-check:
	uv run ruff format --check src tests

type-check:
	uv run mypy src

check: lint type-check test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
