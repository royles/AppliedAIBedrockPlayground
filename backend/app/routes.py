"""FastAPI routes for the Bedrock playground."""

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.bedrock_service import (
    BedrockError,
    _credential_source,
    is_aws_configured,
    invoke_chat as invoke_bedrock,
    stream_chat as stream_bedrock,
)
from app.local_llm_service import (
    LocalLLMError,
    is_local_configured,
    invoke_chat as invoke_local,
    stream_chat as stream_local,
)
from app.models_catalog import (
    CatalogError,
    allowed_model_ids,
    bedrock_catalog_status,
    get_bedrock_models,
    get_bedrock_regions,
    get_model_info,
    is_valid_region,
    normalize_bedrock_selection,
)
from app.schemas import (
    BedrockCatalog,
    ChatRequest,
    ChatResponse,
    ConfigUpdate,
    HealthResponse,
    ModelInfo,
    PublicConfig,
)
from app.state import runtime_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _bedrock_error() -> str | None:
    _, error = bedrock_catalog_status()
    return error


def _chat_ready() -> bool:
    provider = runtime_state.get_provider()
    if provider == "local":
        return is_local_configured()
    if not is_aws_configured():
        return False
    ready, _ = bedrock_catalog_status()
    return ready


def _public_config() -> PublicConfig:
    normalize_bedrock_selection()
    provider = runtime_state.get_provider()
    bedrock_error = _bedrock_error() if provider == "bedrock" else None
    return PublicConfig(
        provider=provider,
        model_id=(
            runtime_state.get_local_model_id()
            if provider == "local"
            else runtime_state.get_model_id()
        ),
        aws_region=runtime_state.get_region(),
        aws_configured=is_aws_configured(),
        credential_source=_credential_source(),
        local_endpoint_url=runtime_state.get_local_endpoint_url(),
        local_model_id=runtime_state.get_local_model_id(),
        local_configured=is_local_configured(),
        local_token_configured=runtime_state.has_local_token(),
        chat_ready=_chat_ready(),
        bedrock_error=bedrock_error,
    )


def _load_bedrock_catalog() -> BedrockCatalog:
    try:
        return BedrockCatalog(regions=get_bedrock_regions(), models=get_bedrock_models())
    except CatalogError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    provider = runtime_state.get_provider()
    bedrock_error = _bedrock_error() if provider == "bedrock" else None
    return HealthResponse(
        status="ok",
        provider=provider,
        aws_configured=is_aws_configured(),
        local_configured=is_local_configured(),
        chat_ready=_chat_ready(),
        bedrock_error=bedrock_error,
    )


@router.get("/bedrock/catalog", response_model=BedrockCatalog)
def bedrock_catalog() -> BedrockCatalog:
    return _load_bedrock_catalog()


@router.get("/regions", response_model=list[str])
def list_regions() -> list[str]:
    return _load_bedrock_catalog().regions


@router.get("/models", response_model=list[ModelInfo])
def list_models() -> list[ModelInfo]:
    if runtime_state.get_provider() == "local":
        model_id = runtime_state.get_local_model_id()
        if not model_id:
            raise HTTPException(status_code=503, detail="Local model is not configured.")
        return [
            ModelInfo(
                model_id=model_id,
                provider="Local",
                display_name=f"Local: {model_id}",
            )
        ]
    return _load_bedrock_catalog().models


@router.get("/config", response_model=PublicConfig)
def get_config() -> PublicConfig:
    return _public_config()


@router.put("/config", response_model=PublicConfig)
def update_config(payload: ConfigUpdate) -> PublicConfig:
    if payload.provider is not None:
        runtime_state.set_provider(payload.provider)

    if payload.local_endpoint_url is not None:
        runtime_state.set_local_endpoint_url(payload.local_endpoint_url)

    if payload.local_model_id is not None:
        model = payload.local_model_id.strip()
        if not model:
            raise HTTPException(status_code=400, detail="local_model_id cannot be empty.")
        runtime_state.set_local_model_id(model)

    if payload.clear_local_api_token:
        runtime_state.clear_local_api_token()
    elif payload.local_api_token is not None:
        runtime_state.set_local_api_token(payload.local_api_token)

    if payload.aws_region is not None:
        region = payload.aws_region.strip()
        if not region:
            raise HTTPException(status_code=400, detail="aws_region cannot be empty.")
        if runtime_state.get_provider() == "bedrock" and not is_valid_region(region):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown Bedrock region '{region}'. Choose from /api/bedrock/catalog.",
            )
        runtime_state.set_region(region)

    provider = runtime_state.get_provider()

    if payload.model_id is not None:
        if provider == "bedrock":
            if payload.model_id not in allowed_model_ids():
                raise HTTPException(
                    status_code=400,
                    detail="Unknown Bedrock model_id. Choose from /api/models.",
                )
            runtime_state.set_model_id(payload.model_id)
        else:
            runtime_state.set_local_model_id(payload.model_id)

    if provider == "local" and not is_local_configured():
        if payload.local_endpoint_url or payload.local_model_id:
            raise HTTPException(
                status_code=400,
                detail="Local provider requires both endpoint URL and model name.",
            )

    return _public_config()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    provider = runtime_state.get_provider()

    if provider == "local":
        if not is_local_configured():
            raise HTTPException(
                status_code=503,
                detail="Configure local endpoint URL and model name in settings.",
            )
        model_id = request.model_id or runtime_state.get_local_model_id()
        try:
            content, used_model, usage = invoke_local(
                messages=request.messages,
                model_id=model_id,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system_prompt=request.system_prompt,
            )
        except LocalLLMError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        logger.info("Chat completed provider=local model=%s", used_model)
        return ChatResponse(
            content=content,
            model_id=used_model,
            provider="local",
            usage=usage,
        )

    if not is_aws_configured():
        raise HTTPException(
            status_code=503,
            detail="AWS credentials not configured. Switch to Local LLM or set AWS credentials.",
        )

    ready, catalog_error = bedrock_catalog_status()
    if not ready:
        raise HTTPException(
            status_code=503,
            detail=catalog_error or "Bedrock catalog is not configured.",
        )

    model_id = request.model_id or runtime_state.get_model_id()
    if request.model_id and request.model_id not in allowed_model_ids():
        raise HTTPException(status_code=400, detail="Unknown Bedrock model_id.")

    try:
        content, used_model, usage = invoke_bedrock(
            messages=request.messages,
            model_id=model_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system_prompt=request.system_prompt,
        )
    except BedrockError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    model_info = get_model_info(used_model)
    logger.info(
        "Chat completed provider=bedrock model=%s vendor=%s",
        used_model,
        model_info.provider if model_info else "unknown",
    )

    return ChatResponse(
        content=content,
        model_id=used_model,
        provider="bedrock",
        usage=usage,
    )


def _sse_line(event_type: str, payload: dict) -> str:
    data = json.dumps({"type": event_type, **payload})
    return f"data: {data}\n\n"


def _stream_chat_events(request: ChatRequest) -> Iterator[str]:
    provider = runtime_state.get_provider()

    if provider == "local":
        if not is_local_configured():
            yield _sse_line("error", {"detail": "Configure local endpoint URL and model name in settings."})
            return
        model_id = request.model_id or runtime_state.get_local_model_id()
        stream_fn = stream_local
        used_provider = "local"
    else:
        if not is_aws_configured():
            yield _sse_line(
                "error",
                {"detail": "AWS credentials not configured. Switch to Local LLM or set AWS credentials."},
            )
            return
        ready, catalog_error = bedrock_catalog_status()
        if not ready:
            yield _sse_line(
                "error",
                {"detail": catalog_error or "Bedrock catalog is not configured."},
            )
            return
        model_id = request.model_id or runtime_state.get_model_id()
        if request.model_id and request.model_id not in allowed_model_ids():
            yield _sse_line("error", {"detail": "Unknown Bedrock model_id."})
            return
        stream_fn = stream_bedrock
        used_provider = "bedrock"

    yield _sse_line("start", {"model_id": model_id, "provider": used_provider})

    try:
        for token in stream_fn(
            messages=request.messages,
            model_id=model_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system_prompt=request.system_prompt,
        ):
            if token:
                yield _sse_line("token", {"text": token})
    except (BedrockError, LocalLLMError) as exc:
        yield _sse_line("error", {"detail": str(exc)})
        return

    logger.info("Chat stream completed provider=%s model=%s", used_provider, model_id)
    yield _sse_line("done", {"model_id": model_id, "provider": used_provider})


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
