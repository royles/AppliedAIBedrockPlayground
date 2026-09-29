"""AWS Bedrock integration. Credentials are never logged or returned to clients."""

import base64
import json
import logging
from collections.abc import Iterator
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models_catalog import resolve_bedrock_client_region, resolve_inference_model_id
from app.config import get_settings
from app.schemas import ChatMessage, MessageAttachment
from app.state import runtime_state

logger = logging.getLogger(__name__)


class BedrockError(Exception):
    """Raised when Bedrock invocation fails."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _credential_source() -> str:
    settings = get_settings()
    if settings.has_explicit_credentials():
        return "environment_variables"
    return "iam_role_or_default_chain"


def is_aws_configured() -> bool:
    """True if explicit env credentials exist or default credential chain is available."""
    settings = get_settings()
    if settings.has_explicit_credentials():
        return True
    try:
        client_region = resolve_bedrock_client_region(runtime_state.get_region())
        session = boto3.Session(region_name=client_region)
        credentials = session.get_credentials()
        return credentials is not None and credentials.access_key is not None
    except Exception:
        return False


def _build_session(client_region: str | None = None) -> boto3.Session:
    settings = get_settings()
    region = client_region or resolve_bedrock_client_region(runtime_state.get_region())
    kwargs: dict[str, Any] = {"region_name": region}
    if settings.has_explicit_credentials():
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.Session(**kwargs)


def _get_client() -> Any:
    client_region = resolve_bedrock_client_region(runtime_state.get_region())
    session = _build_session(client_region)
    return session.client("bedrock-runtime", region_name=client_region)


def _anthropic_text_blocks(text: str) -> list[dict[str, Any]]:
    """Claude on Bedrock: content blocks include type + text."""
    return [{"type": "text", "text": text}]


def _anthropic_attachment_block(attachment: MessageAttachment) -> dict[str, Any]:
    if attachment.media_type.startswith("image/"):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": attachment.media_type,
                "data": attachment.data,
            },
        }
    if attachment.media_type == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": attachment.media_type,
                "data": attachment.data,
            },
        }
    text = base64.b64decode(attachment.data).decode("utf-8", errors="replace")
    return {"type": "text", "text": f"[{attachment.filename}]\n{text}"}


def _anthropic_message_blocks(message: ChatMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if message.content.strip():
        blocks.append({"type": "text", "text": message.content})
    for attachment in message.attachments:
        blocks.append(_anthropic_attachment_block(attachment))
    return blocks or [{"type": "text", "text": "Please review the attached file(s)."}]


def _nova_text_blocks(text: str) -> list[dict[str, str]]:
    """Amazon Nova: content blocks use text only (no type key)."""
    return [{"text": text}]


def _is_amazon_nova(model_id: str) -> bool:
    lowered = model_id.lower()
    return "amazon" in lowered and "nova" in lowered


def _normalize_model_id(model_id: str) -> str:
    """Strip geo inference prefixes for capability checks."""
    for prefix in ("global.", "eu.", "us.", "au."):
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def _anthropic_disallows_sampling(model_id: str) -> bool:
    """Claude 5+ models reject explicit temperature/top_p/top_k on Bedrock."""
    lowered = _normalize_model_id(model_id).lower()
    return any(
        marker in lowered
        for marker in (
            "claude-sonnet-5",
            "claude-opus-5",
            "claude-opus-4-7",
            "claude-opus-4-8",
        )
    )


def _format_anthropic(
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
    system_prompt: str | None,
    model_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {"role": m.role, "content": _anthropic_message_blocks(m)} for m in messages
        ],
    }
    if not _anthropic_disallows_sampling(model_id):
        body["temperature"] = temperature
    if system_prompt:
        body["system"] = _anthropic_text_blocks(system_prompt)
    return body


def _format_amazon_nova(
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
    system_prompt: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemaVersion": "messages-v1",
        "messages": [
            {"role": m.role, "content": _nova_text_blocks(m.content)} for m in messages
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }
    if system_prompt:
        body["system"] = _nova_text_blocks(system_prompt)
    return body


def _format_amazon_titan(
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    # Titan expects a single prompt string.
    parts: list[str] = []
    for msg in messages:
        prefix = "User: " if msg.role == "user" else "Assistant: "
        parts.append(f"{prefix}{msg.content}")
    parts.append("Assistant: ")
    return {
        "inputText": "\n".join(parts),
        "textGenerationConfig": {
            "maxTokenCount": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }


def _format_meta_llama(
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    prompt_parts: list[str] = ["<s>"]
    for msg in messages:
        if msg.role == "user":
            prompt_parts.append(f"[INST] {msg.content} [/INST]")
        else:
            prompt_parts.append(msg.content)
    return {
        "prompt": "".join(prompt_parts),
        "max_gen_len": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }


def _format_mistral(
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    prompt_parts: list[str] = ["<s>"]
    for msg in messages:
        if msg.role == "user":
            prompt_parts.append(f"[INST] {msg.content} [/INST]")
        else:
            prompt_parts.append(msg.content)
    return {
        "prompt": "".join(prompt_parts),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }


def _build_request_body(
    model_id: str,
    messages: list[ChatMessage],
    max_tokens: int,
    temperature: float,
    system_prompt: str | None,
) -> dict[str, Any]:
    if _is_amazon_nova(model_id):
        return _format_amazon_nova(messages, max_tokens, temperature, system_prompt)
    if model_id.startswith("anthropic."):
        return _format_anthropic(
            messages, max_tokens, temperature, system_prompt, model_id
        )
    if model_id.startswith("amazon.titan"):
        return _format_amazon_titan(messages, max_tokens, temperature)
    if model_id.startswith("meta."):
        return _format_meta_llama(messages, max_tokens, temperature)
    if model_id.startswith("mistral."):
        return _format_mistral(messages, max_tokens, temperature)
    # Fallback: try Anthropic format for unknown models.
    return _format_anthropic(
        messages, max_tokens, temperature, system_prompt, model_id
    )


def _parse_nova_response(response_body: dict[str, Any]) -> tuple[str, dict | None]:
    usage = response_body.get("usage")
    output = response_body.get("output", {})
    message = output.get("message", {})
    content = message.get("content", [])
    if content:
        return content[0].get("text", ""), usage
    return json.dumps(response_body), usage


def _parse_response(model_id: str, response_body: dict[str, Any]) -> tuple[str, dict | None]:
    usage: dict | None = None

    if _is_amazon_nova(model_id):
        return _parse_nova_response(response_body)

    if model_id.startswith("anthropic."):
        content = response_body.get("content", [])
        text_parts = [
            block.get("text", "")
            for block in content
            if block.get("type") == "text" and block.get("text")
        ]
        text = "".join(text_parts)
        if "usage" in response_body:
            usage = response_body["usage"]
        return text, usage

    if model_id.startswith("amazon.titan"):
        results = response_body.get("results", [])
        text = results[0].get("outputText", "") if results else ""
        return text, usage

    if model_id.startswith("meta."):
        return response_body.get("generation", ""), usage

    if model_id.startswith("mistral."):
        outputs = response_body.get("outputs", [])
        text = outputs[0].get("text", "") if outputs else ""
        return text, usage

    # Generic fallback
    return json.dumps(response_body), usage


def invoke_chat(
    messages: list[ChatMessage],
    model_id: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    system_prompt: str | None = None,
) -> tuple[str, str, dict | None]:
    """
    Invoke Bedrock and return (content, model_id, usage).
    Raises BedrockError on failure.
    """
    catalog_model = model_id or runtime_state.get_model_id()
    ui_region = runtime_state.get_region()
    inference_model = resolve_inference_model_id(catalog_model, ui_region)
    body = _build_request_body(
        catalog_model, messages, max_tokens, temperature, system_prompt
    )

    try:
        client = _get_client()
        logger.info(
            "Bedrock invoke region=%s inference_model=%s catalog_model=%s",
            resolve_bedrock_client_region(ui_region),
            inference_model,
            catalog_model,
        )
        response = client.invoke_model(
            modelId=inference_model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        response_body = json.loads(response["body"].read())
        text, usage = _parse_response(catalog_model, response_body)
        return text, catalog_model, usage
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        error_msg = exc.response.get("Error", {}).get("Message", str(exc))
        logger.error("Bedrock ClientError [%s]: %s", error_code, error_msg)
        status = 403 if error_code in ("AccessDeniedException", "UnauthorizedException") else 502
        raise BedrockError(f"Bedrock error ({error_code}): {error_msg}", status_code=status) from exc
    except BotoCoreError as exc:
        logger.error("BotoCoreError: %s", exc)
        raise BedrockError(f"AWS connection error: {exc}", status_code=502) from exc
    except Exception as exc:
        logger.error("Unexpected Bedrock error: %s", exc)
        raise BedrockError(f"Unexpected error: {exc}", status_code=500) from exc


def _extract_stream_text(model_id: str, data: dict[str, Any]) -> str | None:
    if _is_amazon_nova(model_id):
        block = data.get("contentBlockDelta")
        if block:
            return block.get("delta", {}).get("text")
        return None

    if model_id.startswith("anthropic."):
        if data.get("type") == "content_block_delta":
            return data.get("delta", {}).get("text")
        return None

    if model_id.startswith("meta."):
        return data.get("generation")

    if model_id.startswith("mistral."):
        outputs = data.get("outputs", [])
        if outputs:
            return outputs[0].get("text")
        return None

    if model_id.startswith("amazon.titan"):
        return data.get("outputText")

    return None


def _supports_native_streaming(model_id: str) -> bool:
    return (
        _is_amazon_nova(model_id)
        or model_id.startswith("anthropic.")
        or model_id.startswith("meta.")
        or model_id.startswith("mistral.")
    )


def stream_chat(
    messages: list[ChatMessage],
    model_id: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    system_prompt: str | None = None,
) -> Iterator[str]:
    """Yield text deltas from Bedrock streaming API."""
    catalog_model = model_id or runtime_state.get_model_id()
    ui_region = runtime_state.get_region()
    inference_model = resolve_inference_model_id(catalog_model, ui_region)

    if not _supports_native_streaming(catalog_model):
        text, _, _ = invoke_chat(
            messages, catalog_model, max_tokens, temperature, system_prompt
        )
        if text:
            yield text
        return

    body = _build_request_body(
        catalog_model, messages, max_tokens, temperature, system_prompt
    )

    try:
        client = _get_client()
        logger.info(
            "Bedrock stream region=%s inference_model=%s catalog_model=%s",
            resolve_bedrock_client_region(ui_region),
            inference_model,
            catalog_model,
        )
        response = client.invoke_model_with_response_stream(
            modelId=inference_model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        for event in response.get("body", []):
            chunk = event.get("chunk")
            if not chunk:
                continue
            data = json.loads(chunk["bytes"].decode())
            text = _extract_stream_text(catalog_model, data)
            if text:
                yield text
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        error_msg = exc.response.get("Error", {}).get("Message", str(exc))
        logger.error("Bedrock stream ClientError [%s]: %s", error_code, error_msg)
        status = 403 if error_code in ("AccessDeniedException", "UnauthorizedException") else 502
        raise BedrockError(f"Bedrock error ({error_code}): {error_msg}", status_code=status) from exc
    except BotoCoreError as exc:
        logger.error("BotoCoreError: %s", exc)
        raise BedrockError(f"AWS connection error: {exc}", status_code=502) from exc
