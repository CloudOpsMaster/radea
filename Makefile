.PHONY: setup test lint clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	@echo "✓ Setup complete. Activate with: source .venv/bin/activate"

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check src/ tests/

clean:
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache dist build
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +
