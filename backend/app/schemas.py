"""Pydantic schemas for API request/response bodies."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ProviderType = Literal["bedrock", "local"]

ALLOWED_ATTACHMENT_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/csv",
})

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5


class MessageAttachment(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    media_type: str = Field(..., min_length=1, max_length=100)
    data: str = Field(..., min_length=1, description="Base64-encoded file bytes")

    @model_validator(mode="after")
    def validate_attachment(self) -> "MessageAttachment":
        if self.media_type not in ALLOWED_ATTACHMENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_ATTACHMENT_TYPES))
            raise ValueError(f"Unsupported attachment type. Allowed: {allowed}")
        # Rough decoded size check without loading huge payloads twice.
        if len(self.data) > (MAX_ATTACHMENT_BYTES * 4) // 3 + 4:
            raise ValueError(
                f"Attachment too large (max {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
            )
        return self


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = "user"
    content: str = Field(default="", max_length=32000)
    attachments: list[MessageAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_or_attachments(self) -> "ChatMessage":
        if self.role == "assistant":
            return self
        if not self.content.strip() and not self.attachments:
            raise ValueError("Message must include text or at least one attachment.")
        if len(self.attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ValueError(
                f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message."
            )
        return self


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    model_id: str | None = None
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    system_prompt: str | None = Field(default=None, max_length=8000)


class ChatResponse(BaseModel):
    content: str
    model_id: str
    provider: ProviderType
    usage: dict | None = None


class ModelInfo(BaseModel):
    model_id: str
    provider: str
    display_name: str


class BedrockCatalog(BaseModel):
    regions: list[str]
    models: list[ModelInfo]


class ConfigUpdate(BaseModel):
    provider: ProviderType | None = None
    model_id: str | None = None
    aws_region: str | None = None
    local_endpoint_url: str | None = None
    local_model_id: str | None = None
    local_api_token: str | None = None
    clear_local_api_token: bool = False


class PublicConfig(BaseModel):
    """Client-safe configuration — no secrets."""

    provider: ProviderType
    model_id: str
    aws_region: str
    aws_configured: bool
    credential_source: str
    local_endpoint_url: str
    local_model_id: str
    local_configured: bool
    local_token_configured: bool
    chat_ready: bool
    bedrock_error: str | None = None


class HealthResponse(BaseModel):
    status: str
    provider: ProviderType
    aws_configured: bool
    local_configured: bool
    chat_ready: bool
    bedrock_error: str | None = None
