from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATABASE = (ROOT / "data" / "demo.db").resolve()


class Settings(BaseSettings):
    app_name: str = "Job Compass · Public Demo"
    database_url: str = f"sqlite:///{DEMO_DATABASE.as_posix()}"
    ai_analyzer_enabled: bool = False
    demo_mode: bool = True
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    @model_validator(mode="after")
    def enforce_public_demo_isolation(self) -> "Settings":
        """Fail closed if this public build is pointed at any other database."""
        if not self.demo_mode:
            raise ValueError("The public build requires DEMO_MODE=true")
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("The public build only supports its isolated SQLite demo database")
        configured = Path(self.database_url.removeprefix(prefix)).resolve()
        if configured != DEMO_DATABASE:
            raise ValueError(f"DATABASE_URL must point to {DEMO_DATABASE}")
        return self


settings = Settings()
