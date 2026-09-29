"""Application configuration. Secrets are loaded from environment only."""

from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. AWS credentials are never exposed to clients."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: str | None = Field(default=None, alias="AWS_SESSION_TOKEN")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )
    default_model_id: str = Field(
        default="anthropic.claude-haiku-4-5-20251001-v1:0",
        alias="DEFAULT_MODEL_ID",
    )
    default_provider: Literal["bedrock", "local"] = Field(
        default="bedrock",
        alias="DEFAULT_PROVIDER",
    )
    local_llm_base_url: str | None = Field(default=None, alias="LOCAL_LLM_BASE_URL")
    local_llm_api_token: str | None = Field(default=None, alias="LOCAL_LLM_API_TOKEN")
    local_llm_model: str | None = Field(default=None, alias="LOCAL_LLM_MODEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | List[str]) -> str:
        if isinstance(value, list):
            return ",".join(value)
        return value

    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def has_explicit_credentials(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
