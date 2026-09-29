"""In-memory runtime state for provider, models, and local LLM settings."""

from threading import Lock
from typing import Literal

from app.config import get_settings

Provider = Literal["bedrock", "local"]


class RuntimeState:
    """Thread-safe mutable config. Secrets (local API token) never leave the server."""

    def __init__(self) -> None:
        settings = get_settings()
        self._lock = Lock()
        self._provider: Provider = settings.default_provider
        self._model_id = settings.default_model_id
        self._region = settings.aws_region
        self._local_endpoint_url = settings.local_llm_base_url or ""
        self._local_api_token = settings.local_llm_api_token or ""
        self._local_model_id = settings.local_llm_model or "llama3.2"

    def get_provider(self) -> Provider:
        with self._lock:
            return self._provider

    def set_provider(self, provider: Provider) -> None:
        with self._lock:
            self._provider = provider

    def get_model_id(self) -> str:
        with self._lock:
            return self._model_id

    def set_model_id(self, model_id: str) -> None:
        with self._lock:
            self._model_id = model_id

    def get_region(self) -> str:
        with self._lock:
            return self._region

    def set_region(self, region: str) -> None:
        with self._lock:
            self._region = region

    def get_local_endpoint_url(self) -> str:
        with self._lock:
            return self._local_endpoint_url

    def set_local_endpoint_url(self, url: str) -> None:
        with self._lock:
            self._local_endpoint_url = url.strip()

    def get_local_api_token(self) -> str:
        with self._lock:
            return self._local_api_token

    def set_local_api_token(self, token: str) -> None:
        with self._lock:
            self._local_api_token = token

    def clear_local_api_token(self) -> None:
        with self._lock:
            self._local_api_token = ""

    def get_local_model_id(self) -> str:
        with self._lock:
            return self._local_model_id

    def set_local_model_id(self, model_id: str) -> None:
        with self._lock:
            self._local_model_id = model_id.strip()

    def has_local_token(self) -> bool:
        with self._lock:
            return bool(self._local_api_token)

    def is_local_ready(self) -> bool:
        with self._lock:
            return bool(self._local_endpoint_url.strip() and self._local_model_id.strip())


runtime_state = RuntimeState()
