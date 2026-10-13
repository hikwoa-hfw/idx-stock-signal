.PHONY: test lint format clean install-dev ingest validate features labels train backtest signals telegram send-daily positions outcomes evaluate retrain deploy

VENV_PYTHON = .venv/Scripts/python
VENV_PYTEST = .venv/Scripts/pytest
VENV_RUFF = .venv/Scripts/ruff

test:
	$(VENV_PYTEST)

lint:
	$(VENV_RUFF) check .

format:
	$(VENV_RUFF) format .

ingest:
	$(VENV_PYTHON) -m scripts.ingest_daily

validate:
	$(VENV_PYTHON) -m scripts.validate_data

features:
	$(VENV_PYTHON) -m scripts.build_features

labels:
	$(VENV_PYTHON) -m scripts.build_labels

train:
	$(VENV_PYTHON) -m scripts.train_model --model-type lightgbm --save-registry

backtest:
	$(VENV_PYTHON) -m scripts.run_backtest --format table

signals:
	$(VENV_PYTHON) -m scripts.generate_signals --use-champion --format table

telegram:
	$(VENV_PYTHON) -m scripts.send_daily_telegram --dry-run

send-daily:
	$(VENV_PYTHON) -m scripts.send_daily_telegram

positions:
	$(VENV_PYTHON) -m scripts.manage_positions list --status OPEN --format table

outcomes:
	$(VENV_PYTHON) -m scripts.resolve_outcomes --save-db

evaluate:
	$(VENV_PYTHON) -m scripts.evaluate_models --from-outcomes --output-format table

retrain:
	$(VENV_PYTHON) -m scripts.retrain_model --auto-promote

deploy:
	$(VENV_PYTHON) -m scripts.deploy_aws

clean:
	$(VENV_PYTHON) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('.pytest_cache')]"



