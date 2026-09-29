"""Application settings loaded from defaults and the root .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """Configuration values loaded from environment variables and the root .env file."""

    # Project Paths
    BASE_DIR: Path = BASE_DIR
    
    # Scraper Config
    BASE_LOCATION_LAT: float = 50.0647
    BASE_LOCATION_LON: float = 19.9450
    SEARCH_RADIUS_KM: int = 50
    # Lowered threshold so single relevant keywords can match short titles
    MIN_MATCH_SCORE: int = 5
    SELENIUM_HEADLESS: bool = True
    CHROME_BINARY_PATH: str = os.getenv("CHROME_BINARY_PATH", "")
    
    # Database
    DB_PATH: str = str(BASE_DIR / "data" / "apjobs.db")
    
    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
