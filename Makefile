.PHONY: test lint format clean install-dev

VENV_PYTHON = .venv/Scripts/python
VENV_PYTEST = .venv/Scripts/pytest
VENV_RUFF = .venv/Scripts/ruff

test:
	$(VENV_PYTEST)

lint:
	$(VENV_RUFF) check .

format:
	$(VENV_RUFF) format .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
