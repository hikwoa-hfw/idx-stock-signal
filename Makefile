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
	$(VENV_PYTHON) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('.pytest_cache')]"
