"""Configurazione centralizzata (letta da .env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    db_path: str = "/data/portfolio.db"
    replica_path: str = "/replica/portfolio_replica.db"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Backup (Fase 4)
    backup_on_startup: bool = False
    google_sa_key_path: str = "/secrets/service_account.json"
    gdrive_backup_folder_id: str = ""
    backup_retention: int = 12

    # AI (Fase 6)
    ai_api_key: str = ""
    ai_provider: str = ""

    # Import
    import_min_year: int = 2026

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()
