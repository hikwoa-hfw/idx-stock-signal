import os
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


class Settings(BaseModel):
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite:///{PROJECT_ROOT.as_posix()}/datasets/stock_signals.db"
        )
    )
    market_data_provider: str = Field(
        default_factory=lambda: os.getenv("MARKET_DATA_PROVIDER", "local_csv")
    )
    market_data_api_key: str = Field(default_factory=lambda: os.getenv("MARKET_DATA_API_KEY", ""))
    telegram_bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    aws_region: str = Field(default_factory=lambda: os.getenv("AWS_REGION", "ap-southeast-3"))
    s3_bucket: str = Field(default_factory=lambda: os.getenv("S3_BUCKET", ""))
    model_registry_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("MODEL_REGISTRY_PATH", str(PROJECT_ROOT / "models" / "registry"))
        )
    )
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


settings = Settings()
