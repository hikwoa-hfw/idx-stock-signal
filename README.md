# Indonesian Stock Daily Signal Generator — BEI

Production-minded daily stock swing signal generator, tracking journal, and model evaluation system for Indonesian Stock Exchange (IDX/BEI) tickers.

Designed for local development with seamless cloud migration (AWS serverless / Lambda / EventBridge / RDS PostgreSQL) for remote access.

## Architecture & Directory Structure

```text
indonesian-stock-ai/
│
├── apps/
│   ├── api/          # API layer (Node.js / Express or FastAPI)
│   └── web/          # Future web dashboard (Next.js)
│
├── services/
│   └── telegram/     # Daily signals Telegram dispatch service
│
├── python/           # Core ML, feature engineering, and signal pipelines
│   ├── data/         # Ingestion, validation, market data adapters
│   ├── features/     # Feature calculators (Momentum, Trend, RSI, Volatility, Regime)
│   ├── labels/       # TP/SL outcome labelling
│   ├── models/       # Model definitions and inference
│   ├── signals/      # Daily signal generator and ranking
│   ├── risk/         # Position sizing and risk management
│   ├── outcomes/     # Price-path tracking and trade outcome evaluation
│   ├── backtest/     # Walk-forward backtester
│   ├── evaluation/   # Champion vs Challenger metrics
│   ├── retraining/   # Retraining orchestrators
│   ├── config/       # Environment and global configuration
│   └── common/       # Typed domain models and shared utilities
│
├── datasets/         # Local data store (raw, processed, features)
├── models/           # Model registry (champion, challengers)
├── tests/            # Test suite (unit, integration, backtest)
├── scripts/          # Helper CLI scripts
├── infra/aws/        # Cloud deployment templates (Terraform / SAM / CDK)
├── docs/             # Technical specs and architecture guide
├── PROJECT_RULES.md  # Local agent rules (summary.md append-only, walkthrough.md)
├── summary.md        # Append-only cumulative changelog
└── walkthrough.md    # Session-by-session detailed task log
```

## Quick Start (Local Setup)

### 1. Requirements
- Python 3.12+ (or 3.13)
- Node.js 24 LTS (for web/api apps)
- Git

### 2. Python Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv

# Windows Powershell:
.\.venv\Scripts\Activate.ps1

# Install baseline dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. Environment Variables
```bash
cp .env.example .env
```
Adjust parameters in `.env` as needed.

### 4. Run Tests
```bash
pytest
```

## Rules and Guidelines
- See [`PROJECT_RULES.md`](PROJECT_RULES.md) for documentation protocol (`summary.md` append-only, `walkthrough.md` per session, antislop, and Karpathy guidelines).
- Full development guide is located in [`docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md`](docs/04_ai_agent_coding_development_guide_BEI_stock_signal.md).
