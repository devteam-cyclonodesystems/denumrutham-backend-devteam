import os
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "TMS API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "supersecretkey-change-in-prod")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/tms_postgres")
    SQLALCHEMY_DATABASE_URI: str = DATABASE_URL
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "development")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    PORT: int = int(os.getenv("PORT", "8000"))
    CORS_ALLOWED_ORIGINS: str = os.getenv("CORS_ALLOWED_ORIGINS", "")
    ENABLE_STAFF_SELF_REGISTRATION: bool = False

    @model_validator(mode="after")
    def validate_secrets(self) -> 'Settings':
        if self.ENVIRONMENT.lower() == "production":
            required_vars = ["DATABASE_URL", "SECRET_KEY"]
            for var in required_vars:
                if not os.getenv(var):
                    raise ValueError(f"Missing required production environment variable: {var}")
            if self.SECRET_KEY == "supersecretkey-change-in-prod":
                raise ValueError("SECRET_KEY must be changed from the default value in production.")
            if not self.JWT_SECRET:
                raise ValueError("JWT_SECRET must be set in production environment.")
            if self.JWT_SECRET == "supersecretkey-change-in-prod":
                raise ValueError("JWT_SECRET cannot be the default fallback value in production.")
        
        # Normalize database URL for SQLAlchemy asyncpg
        db_url = self.DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        self.DATABASE_URL = db_url
        self.SQLALCHEMY_DATABASE_URI = db_url
        return self

    @property
    def jwt_secret_key(self) -> str:
        return self.JWT_SECRET if self.JWT_SECRET else self.SECRET_KEY

    @property
    def cors_origins(self) -> List[str]:
        if not self.CORS_ALLOWED_ORIGINS:
            return ["http://localhost:3000", "http://localhost:5173"]
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()

# socket.gethostbyname check removed to prevent startup hangs in certain Docker environments.
